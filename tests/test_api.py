"""The PWA API (slice P1): auth gating, enrollment flow, sessions, status."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.server import build_api


@pytest.fixture
def client(sandbox):
    auth.init_db()
    auth._challenges.clear()
    # Fresh rate-limit window per test.
    from api import server
    server._attempts.clear()
    return TestClient(build_api())


def _issue_enroll_token() -> str:
    """Mint an enrollment token the way ensure_enroll_token does, but return it."""
    import secrets
    token = secrets.token_urlsafe(24)
    auth._set_secret("enroll_token", auth._hash(token))
    return token


# --- Gating ------------------------------------------------------------------
def test_status_requires_session(client):
    assert client.get("/api/status").status_code == 401


def test_me_is_public_and_reports_state(client):
    body = client.get("/api/me").json()
    assert body == {"enrolled": False, "authenticated": False, "demo": False}


# --- Enrollment --------------------------------------------------------------
def test_register_options_rejects_bad_token(client):
    res = client.post("/api/webauthn/register/options", json={"token": "wrong"})
    assert res.status_code == 403


def test_register_options_with_valid_token(client):
    token = _issue_enroll_token()
    res = client.post("/api/webauthn/register/options", json={"token": token})
    assert res.status_code == 200
    body = json.loads(res.text)
    assert body["rp"]["name"] == auth.RP_NAME
    assert body["challenge"]
    assert body["authenticatorSelection"]["userVerification"] == "required"


def test_login_options_before_enrollment_fails(client):
    res = client.post("/api/webauthn/login/options")
    assert res.status_code == 400


# --- Sessions ------------------------------------------------------------------
def test_session_lifecycle(sandbox):
    auth.init_db()
    token = auth.create_session()
    assert auth.verify_session(token)
    assert not auth.verify_session("garbage")
    assert not auth.verify_session(None)
    auth.drop_session(token)
    assert not auth.verify_session(token)


def test_status_with_session_cookie(client, sandbox):
    from agent import spend
    spend.init_db()
    token = auth.create_session()
    client.cookies.set(auth.SESSION_COOKIE, token)
    res = client.get("/api/status")
    assert res.status_code == 200
    body = res.json()
    assert {"uptime_s", "spend_today_usd", "budget_usd", "inbox_count"} <= body.keys()


# --- Recovery -------------------------------------------------------------------
def test_recovery_round_trip(client):
    import secrets
    code = secrets.token_urlsafe(24)
    auth._set_secret("recovery_code", auth._hash(code))
    res = client.post("/api/webauthn/recover", json={"code": code})
    assert res.status_code == 200
    new_token = res.json()["enroll_token"]
    # The fresh token opens registration; the used code does not work twice.
    assert client.post(
        "/api/webauthn/register/options", json={"token": new_token}
    ).status_code == 200
    assert client.post("/api/webauthn/recover", json={"code": code}).status_code == 403


# --- Rate limiting ----------------------------------------------------------------
def test_auth_endpoints_rate_limited(client):
    from api import server
    for _ in range(server._RATE_MAX):
        client.post("/api/webauthn/register/options", json={"token": "x"})
    res = client.post("/api/webauthn/register/options", json={"token": "x"})
    assert res.status_code == 429
