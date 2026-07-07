"""The PWA's HTTP face: auth endpoints, /api/status, and the static app shell.

Runs in the same asyncio process as the Telegram bot (see agent/main.py), so
both transports share one brain, one sqlite, one approval store. Every /api
route except the auth handshake requires the passkey session cookie; the
static shell is public (it is just HTML — all data sits behind /api).
"""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agent import config, finance, gitsync, providers, retrieval, spend
from agent.hooks import PathNotAllowed, resolve_in_repo

from . import auth

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_CATEGORY_RE = re.compile(r"^[\w &/-]{1,40}$")

log = logging.getLogger("personal-ai.api")

_STARTED = time.monotonic()

# Tiny fixed-window rate limit for the unauthenticated auth endpoints.
_RATE_WINDOW_S = 60
_RATE_MAX = 20
_attempts: deque[float] = deque()


def _rate_limit() -> None:
    now = time.time()
    while _attempts and _attempts[0] < now - _RATE_WINDOW_S:
        _attempts.popleft()
    if len(_attempts) >= _RATE_MAX:
        raise HTTPException(429, "Too many attempts — wait a minute.")
    _attempts.append(now)


def _session_ok(request: Request) -> None:
    if not auth.verify_session(request.cookies.get(auth.SESSION_COOKIE)):
        raise HTTPException(401, "Not signed in.")


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_TTL_S,
        httponly=True,
        secure=config.PWA_ORIGIN.startswith("https://"),
        samesite="strict",
        path="/",
    )


def status_payload() -> dict:
    """The /status health check as JSON (mirrors the Telegram /status text)."""
    usage = spend.today()
    inbox = config.VAULT_DIR / "00-inbox"
    return {
        "uptime_s": int(time.monotonic() - _STARTED),
        "deployed": config.DEPLOYED,
        "provider": providers.provider_name(),
        "models": {t: providers.model_for(t) for t in ("cheap", "default", "strong")},
        "spend_today_usd": round(usage["cost_usd"], 4),
        "budget_usd": config.DAILY_BUDGET_USD,
        "tokens_in": usage["input_tokens"],
        "tokens_out": usage["output_tokens"],
        "inbox_count": len(list(inbox.glob("*.md"))) if inbox.is_dir() else 0,
        "last_commit": gitsync.last_commit(),
        "kill_switch": config.KILL_SWITCH,
    }


def build_api() -> FastAPI:
    app = FastAPI(title="personal-ai", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self';"
            " script-src 'self'; connect-src 'self'"
        )
        if config.PWA_ORIGIN.startswith("https://"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response

    # --- Auth handshake (unauthenticated, rate-limited) -----------------------
    @app.get("/api/me")
    async def me(request: Request):
        return {
            "enrolled": auth.is_enrolled(),
            "authenticated": auth.verify_session(
                request.cookies.get(auth.SESSION_COOKIE)
            ),
        }

    @app.post("/api/webauthn/register/options")
    async def register_options(body: dict):
        _rate_limit()
        try:
            options = auth.registration_options(body.get("token", ""))
        except auth.AuthError as e:
            raise HTTPException(403, str(e))
        return Response(options, media_type="application/json")

    @app.post("/api/webauthn/register/verify")
    async def register_verify(body: dict):
        _rate_limit()
        try:
            session, recovery = auth.registration_verify(
                body.get("token", ""), body.get("credential") or {}
            )
        except auth.AuthError as e:
            raise HTTPException(403, str(e))
        except Exception as e:  # webauthn library rejections
            log.warning("registration rejected: %s", e)
            raise HTTPException(400, "Passkey registration failed.")
        response = JSONResponse({"ok": True, "recovery_code": recovery})
        _set_session_cookie(response, session)
        return response

    @app.post("/api/webauthn/login/options")
    async def login_options():
        _rate_limit()
        try:
            options = auth.authentication_options()
        except auth.AuthError as e:
            raise HTTPException(400, str(e))
        return Response(options, media_type="application/json")

    @app.post("/api/webauthn/login/verify")
    async def login_verify(body: dict):
        _rate_limit()
        try:
            session = auth.authentication_verify(body.get("credential") or {})
        except auth.AuthError as e:
            raise HTTPException(403, str(e))
        except Exception as e:
            log.warning("login rejected: %s", e)
            raise HTTPException(400, "Passkey sign-in failed.")
        response = JSONResponse({"ok": True})
        _set_session_cookie(response, session)
        return response

    @app.post("/api/webauthn/recover")
    async def recover(body: dict):
        _rate_limit()
        try:
            token = auth.recover(body.get("code", ""))
        except auth.AuthError as e:
            raise HTTPException(403, str(e))
        return {"enroll_token": token}

    @app.post("/api/logout")
    async def logout(request: Request):
        auth.drop_session(request.cookies.get(auth.SESSION_COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    # --- Authenticated API ------------------------------------------------------
    @app.get("/api/status", dependencies=[Depends(_session_ok)])
    async def status():
        return status_payload()

    @app.get("/api/bootstrap", dependencies=[Depends(_session_ok)])
    async def bootstrap_data():
        """One call on app open: everything the tabs need to first-paint."""
        month = date.today().strftime("%Y-%m")
        try:
            summary = finance.summary(month)
        except Exception:  # empty/absent ledger must not blank the app
            summary = {"period": month, "by_category": [], "totals": {}}
        return {"status": status_payload(), "finance": summary, "month": month}

    @app.get("/api/finance/summary", dependencies=[Depends(_session_ok)])
    async def finance_summary(month: str | None = None):
        if month and not _MONTH_RE.match(month):
            raise HTTPException(400, "month must be YYYY-MM")
        try:
            return finance.summary(month)
        except finance.FinanceError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/finance/ledger", dependencies=[Depends(_session_ok)])
    async def finance_ledger(
        month: str | None = None, category: str | None = None, limit: int = 50
    ):
        # Inputs are validated to a safe shape, then inlined (the ledger view is
        # read-only and single-statement-guarded in finance.query).
        if month and not _MONTH_RE.match(month):
            raise HTTPException(400, "month must be YYYY-MM")
        if category and not _CATEGORY_RE.match(category):
            raise HTTPException(400, "invalid category")
        where = []
        if month:
            where.append(f"strftime(date, '%Y-%m') = '{month}'")
        if category:
            where.append("category = '" + category.replace("'", "''") + "'")
        sql = (
            "SELECT id, date, description, amount, category, account FROM ledger"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY date DESC, id"
        )
        try:
            rows = finance.query(sql, limit=max(1, min(int(limit), 500)))
        except finance.FinanceError as e:
            raise HTTPException(400, str(e))
        return {"rows": rows}

    @app.get("/api/notes", dependencies=[Depends(_session_ok)])
    async def notes(path: str = "vault"):
        """Read-only vault browser: directories list, files return content."""
        norm = path.replace("\\", "/").strip("/")
        try:
            abs_path = resolve_in_repo(norm)
        except PathNotAllowed:
            raise HTTPException(403, "path escapes the vault")
        # Containment is checked on the RESOLVED path, so `vault/../x` can't
        # sneak past a string-prefix test.
        vault_root = config.VAULT_DIR.resolve()
        if abs_path != vault_root and vault_root not in abs_path.parents:
            raise HTTPException(403, "only vault/ is browsable")
        if not abs_path.exists():
            raise HTTPException(404, "not found")
        if abs_path.is_dir():
            entries = [
                {"name": p.name, "dir": p.is_dir()}
                for p in sorted(abs_path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
                if not p.name.startswith(".")
            ]
            return {"type": "dir", "path": norm, "entries": entries}
        return {"type": "file", "path": norm, "content": abs_path.read_text()}

    @app.get("/api/notes/search", dependencies=[Depends(_session_ok)])
    async def notes_search(q: str = ""):
        return {"hits": retrieval.search_vault(q) if q.strip() else []}

    # --- Static app shell ---------------------------------------------------------
    if config.WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")

    return app
