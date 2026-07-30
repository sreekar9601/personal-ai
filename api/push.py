"""Web Push (slice P4): proactive messages to the installed PWA's lock screen.

Payloads are end-to-end encrypted (RFC 8291) — Apple/Google relay them but
cannot read them — so the morning briefing can carry real content.

VAPID keys are generated once at first boot and kept in the data dir (they
identify this server to the push services; losing them just means
re-enabling notifications in the app). Subscriptions live in sqlite; dead
ones (404/410 from the push service) are pruned on send.

send_to_all() is synchronous (pywebpush uses requests) — call it from async
code via asyncio.to_thread. It is best-effort by design: a push failure must
never break a scheduled job.
"""
from __future__ import annotations

import base64
import json
import logging
import sqlite3
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from agent import config

log = logging.getLogger("personal-ai.push")

# Contact address in the VAPID claims. Subscriptions bind to the VAPID
# *public key*, not this value, so it is safe to change.
VAPID_SUB = "mailto:owner@command-center.local"
_KEY_FILE = "vapid_private.pem"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.SESSION_DB)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS push_subscriptions (
                   endpoint     TEXT PRIMARY KEY,
                   subscription TEXT NOT NULL,
                   created_at   REAL NOT NULL
               )"""
        )


# --- VAPID keys -----------------------------------------------------------------
def _key_path():
    return config.DATA_DIR / _KEY_FILE


def ensure_vapid_keys() -> str:
    """Create the VAPID keypair if missing; return the public key (base64url,
    uncompressed point) for the browser's applicationServerKey."""
    path = _key_path()
    if not path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pem)
        path.chmod(0o600)
        log.info("Generated VAPID keypair at %s", path)
    return public_key_b64u()


def _private_key():
    return serialization.load_pem_private_key(_key_path().read_bytes(), password=None)


def public_key_b64u() -> str:
    pub = _private_key().public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(pub).rstrip(b"=").decode()


# --- Subscriptions -----------------------------------------------------------------
def subscribe(subscription: dict) -> None:
    endpoint = subscription.get("endpoint", "")
    if not endpoint or "keys" not in subscription:
        raise ValueError("malformed push subscription")
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO push_subscriptions
               (endpoint, subscription, created_at) VALUES (?, ?, ?)""",
            (endpoint, json.dumps(subscription), time.time()),
        )


def unsubscribe(endpoint: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
        )


def subscription_count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]


# --- Sending ------------------------------------------------------------------------
def send_to_all(title: str, body: str, tag: str = "command-center") -> int:
    """Push a notification to every subscription. Returns how many succeeded.
    Never raises; dead subscriptions are pruned."""
    try:
        from pywebpush import WebPushException, webpush
    except Exception:  # pragma: no cover - import guard
        return 0
    if not _key_path().exists():
        return 0
    with _connect() as conn:
        rows = conn.execute(
            "SELECT endpoint, subscription FROM push_subscriptions"
        ).fetchall()
    payload = json.dumps({"title": title, "body": body[:500], "tag": tag})
    sent = 0
    for endpoint, sub_json in rows:
        try:
            webpush(
                subscription_info=json.loads(sub_json),
                data=payload,
                vapid_private_key=str(_key_path()),
                vapid_claims={"sub": VAPID_SUB},
                ttl=3600,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):  # subscription is gone; prune it
                unsubscribe(endpoint)
                log.info("pruned dead push subscription (%s)", status)
            else:
                log.warning("push failed (%s): %s", status, e)
        except Exception:  # pragma: no cover - never break the caller
            log.exception("push failed")
    return sent
