"""Path safety, the auto-approve allowlist, and the Phase 6 content guards."""
from __future__ import annotations

import pytest

from agent import hooks
from agent.hooks import MAX_WRITE_BYTES, PathNotAllowed


def test_resolve_in_repo_allows_inside(sandbox):
    p = hooks.resolve_in_repo("vault/00-inbox/note.md")
    assert str(p).startswith(str(sandbox))


@pytest.mark.parametrize("escape", ["../../etc/passwd", "/etc/passwd", "vault/../../x"])
def test_resolve_in_repo_refuses_escape(sandbox, escape):
    with pytest.raises(PathNotAllowed):
        hooks.resolve_in_repo(escape)


def test_is_auto_approved(sandbox):
    assert hooks.is_auto_approved(sandbox / "vault" / "x.md")
    assert hooks.is_auto_approved(sandbox / "memory" / "MEMORY.md")
    # agent source is never auto-approved
    assert not hooks.is_auto_approved(sandbox / "agent" / "loop.py")
    assert not hooks.is_auto_approved(sandbox / "finance" / "imports" / "raw.csv")


def test_assess_content_allows_normal():
    assert hooks.assess_content("# A normal note\nsome text") is None


def test_assess_content_rejects_oversize():
    big = "x" * (MAX_WRITE_BYTES + 1)
    reason = hooks.assess_content(big)
    assert reason and "cap" in reason


def test_assess_content_rejects_private_key():
    body = "here is a key\n-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n"
    reason = hooks.assess_content(body)
    assert reason and "private-key" in reason
