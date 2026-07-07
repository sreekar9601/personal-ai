"""Web Push (slice P4): VAPID keys, subscriptions, pruning on send."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import auth, push
from api.server import build_api


@pytest.fixture
def client(sandbox):
    auth.init_db()
    push.init_db()
    c = TestClient(build_api())
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session())
    return c


def _sub(endpoint="https://push.example/ep1"):
    return {"endpoint": endpoint, "keys": {"p256dh": "pk", "auth": "at"}}


def test_push_endpoints_require_session(sandbox):
    auth.init_db()
    c = TestClient(build_api())
    assert c.get("/api/push/key").status_code == 401
    assert c.post("/api/push/subscribe", json={}).status_code == 401


def test_vapid_key_is_stable_and_b64u(client):
    k1 = client.get("/api/push/key").json()["key"]
    k2 = client.get("/api/push/key").json()["key"]
    assert k1 == k2  # generated once, then reused
    assert "=" not in k1 and "+" not in k1 and "/" not in k1
    # Uncompressed P-256 point = 65 bytes -> 87 base64url chars.
    assert len(k1) == 87


def test_subscribe_unsubscribe_round_trip(client):
    out = client.post("/api/push/subscribe", json={"subscription": _sub()}).json()
    assert out["subscriptions"] == 1
    # Re-subscribing the same endpoint replaces, not duplicates.
    out = client.post("/api/push/subscribe", json={"subscription": _sub()}).json()
    assert out["subscriptions"] == 1
    out = client.post(
        "/api/push/unsubscribe", json={"endpoint": _sub()["endpoint"]}
    ).json()
    assert out["subscriptions"] == 0


def test_subscribe_rejects_malformed(client):
    res = client.post("/api/push/subscribe", json={"subscription": {"endpoint": ""}})
    assert res.status_code == 400


def test_send_to_all_prunes_dead_subscriptions(sandbox, monkeypatch):
    push.init_db()
    push.ensure_vapid_keys()
    push.subscribe(_sub("https://push.example/alive"))
    push.subscribe(_sub("https://push.example/gone"))

    import pywebpush

    class FakeResponse:
        status_code = 410

    def fake_webpush(subscription_info, **kwargs):
        if subscription_info["endpoint"].endswith("/gone"):
            raise pywebpush.WebPushException("gone", response=FakeResponse())
        return None

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    sent = push.send_to_all("Test", "body")
    assert sent == 1
    assert push.subscription_count() == 1  # the dead one was pruned


def test_send_without_keys_is_noop(sandbox):
    push.init_db()
    push.subscribe(_sub())
    assert push.send_to_all("t", "b") == 0
