"""Single-user passkey auth for the PWA (docs/PWA-DESIGN.md §3).

Exactly one human may enroll. The trust bootstrap is an enrollment token
printed to the server log at startup (same spirit as the Telegram allowlist):
whoever holds the token registers the one passkey; from then on, login is
Face ID via WebAuthn and every /api route requires the session cookie.

Storage (same sqlite file as everything else):
  - webauthn_credentials : the registered passkey (replaced on re-enrollment)
  - api_sessions         : hashed bearer tokens with a sliding 30-day expiry
  - auth_secrets         : hashes of the enrollment token + recovery code

Recovery: a one-time code shown at enrollment. Presenting it re-opens
enrollment (a new passkey replaces the old), covering a lost/reset phone.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import time
from urllib.parse import urlparse

from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from agent import config

log = logging.getLogger("personal-ai.auth")

RP_NAME = "Personal AI"
_USER_ID = b"personal-ai-owner"
SESSION_COOKIE = "pai_session"
SESSION_TTL_S = 30 * 24 * 3600  # sliding 30 days
_CHALLENGE_TTL_S = 300

# Single-user, single-process: challenges can live in memory.
_challenges: dict[str, tuple[bytes, float]] = {}


class AuthError(Exception):
    """Invalid token/credential/session. Message is safe to show the user."""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.SESSION_DB)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS webauthn_credentials (
                   id         TEXT PRIMARY KEY,
                   public_key BLOB NOT NULL,
                   sign_count INTEGER NOT NULL,
                   created_at REAL NOT NULL
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS api_sessions (
                   token_hash TEXT PRIMARY KEY,
                   created_at REAL NOT NULL,
                   last_seen  REAL NOT NULL
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS auth_secrets (
                   name  TEXT PRIMARY KEY,
                   value TEXT NOT NULL
               )"""
        )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _get_secret(name: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM auth_secrets WHERE name = ?", (name,)
        ).fetchone()
    return row[0] if row else None


def _set_secret(name: str, value: str | None) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM auth_secrets WHERE name = ?", (name,))
        if value is not None:
            conn.execute(
                "INSERT INTO auth_secrets (name, value) VALUES (?, ?)", (name, value)
            )


# --- RP identity ---------------------------------------------------------------
def rp_id() -> str:
    return urlparse(config.PWA_ORIGIN).hostname or "localhost"


def expected_origin() -> str:
    return config.PWA_ORIGIN


# --- Enrollment gate -----------------------------------------------------------
def is_enrolled() -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM webauthn_credentials").fetchone()
    return bool(row and row[0])


def ensure_enroll_token() -> None:
    """At startup: if nobody is enrolled and no token is armed, mint one and
    print the enrollment URL to the log (the log is the trusted channel)."""
    if is_enrolled() or _get_secret("enroll_token"):
        if not is_enrolled():
            log.info("Passkey enrollment still open (token already issued).")
        return
    token = secrets.token_urlsafe(24)
    _set_secret("enroll_token", _hash(token))
    log.warning(
        "No passkey enrolled. Register yours at:  %s/?enroll=%s",
        config.PWA_ORIGIN, token,
    )


def _check_enroll_token(token: str) -> None:
    stored = _get_secret("enroll_token")
    if not stored or not secrets.compare_digest(stored, _hash(token or "")):
        raise AuthError("Invalid or expired enrollment token.")


# --- Challenges ------------------------------------------------------------------
def _store_challenge(kind: str, challenge: bytes) -> None:
    _challenges[kind] = (challenge, time.time() + _CHALLENGE_TTL_S)


def _take_challenge(kind: str) -> bytes:
    entry = _challenges.pop(kind, None)
    if not entry or entry[1] < time.time():
        raise AuthError("Challenge expired — try again.")
    return entry[0]


# --- Registration -----------------------------------------------------------------
def registration_options(enroll_token: str) -> str:
    _check_enroll_token(enroll_token)
    options = generate_registration_options(
        rp_id=rp_id(),
        rp_name=RP_NAME,
        user_name="owner",
        user_id=_USER_ID,
        user_display_name="Owner",
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,  # discoverable => Face ID
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _store_challenge("register", options.challenge)
    return options_to_json(options)


def registration_verify(enroll_token: str, credential: dict) -> tuple[str, str]:
    """Verify the new passkey. Returns (session_token, recovery_code) —
    the recovery code's plaintext exists only in this return value."""
    _check_enroll_token(enroll_token)
    verified = verify_registration_response(
        credential=credential,
        expected_challenge=_take_challenge("register"),
        expected_rp_id=rp_id(),
        expected_origin=expected_origin(),
        require_user_verification=True,
    )
    with _connect() as conn:
        conn.execute("DELETE FROM webauthn_credentials")  # single user: replace
        conn.execute(
            "INSERT INTO webauthn_credentials (id, public_key, sign_count, created_at)"
            " VALUES (?, ?, ?, ?)",
            (
                _b64url(verified.credential_id),
                verified.credential_public_key,
                verified.sign_count,
                time.time(),
            ),
        )
        conn.execute("DELETE FROM api_sessions")  # old phone's sessions die here
    _set_secret("enroll_token", None)
    recovery = secrets.token_urlsafe(24)
    _set_secret("recovery_code", _hash(recovery))
    log.info("Passkey enrolled; enrollment closed.")
    return create_session(), recovery


# --- Login -------------------------------------------------------------------------
def authentication_options() -> str:
    if not is_enrolled():
        raise AuthError("No passkey enrolled yet.")
    with _connect() as conn:
        rows = conn.execute("SELECT id FROM webauthn_credentials").fetchall()
    options = generate_authentication_options(
        rp_id=rp_id(),
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(r[0])) for r in rows
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _store_challenge("auth", options.challenge)
    return options_to_json(options)


def authentication_verify(credential: dict) -> str:
    cred_id = credential.get("id", "")
    with _connect() as conn:
        row = conn.execute(
            "SELECT public_key, sign_count FROM webauthn_credentials WHERE id = ?",
            (cred_id,),
        ).fetchone()
    if not row:
        raise AuthError("Unknown credential.")
    verified = verify_authentication_response(
        credential=credential,
        expected_challenge=_take_challenge("auth"),
        expected_rp_id=rp_id(),
        expected_origin=expected_origin(),
        credential_public_key=row[0],
        credential_current_sign_count=row[1],
        require_user_verification=True,
    )
    with _connect() as conn:
        conn.execute(
            "UPDATE webauthn_credentials SET sign_count = ? WHERE id = ?",
            (verified.new_sign_count, cred_id),
        )
    return create_session()


# --- Recovery ------------------------------------------------------------------------
def recover(code: str) -> str:
    """Trade the recovery code for a fresh enrollment token (lost phone path)."""
    stored = _get_secret("recovery_code")
    if not stored or not secrets.compare_digest(stored, _hash(code or "")):
        raise AuthError("Invalid recovery code.")
    _set_secret("recovery_code", None)  # single use
    token = secrets.token_urlsafe(24)
    _set_secret("enroll_token", _hash(token))
    log.warning("Recovery code used — enrollment re-opened.")
    return token


# --- Sessions ---------------------------------------------------------------------------
def create_session() -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO api_sessions (token_hash, created_at, last_seen) VALUES (?, ?, ?)",
            (_hash(token), now, now),
        )
        conn.execute(
            "DELETE FROM api_sessions WHERE last_seen < ?", (now - SESSION_TTL_S,)
        )
    return token


def verify_session(token: str | None) -> bool:
    if not token:
        return False
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT last_seen FROM api_sessions WHERE token_hash = ?", (_hash(token),)
        ).fetchone()
        if not row or row[0] < now - SESSION_TTL_S:
            return False
        conn.execute(
            "UPDATE api_sessions SET last_seen = ? WHERE token_hash = ?",
            (now, _hash(token)),
        )
    return True


def drop_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM api_sessions WHERE token_hash = ?", (_hash(token),))


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
