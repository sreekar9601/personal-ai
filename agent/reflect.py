"""Self-improvement (Phase 5) — the reflection loop ("Channel-1").

The agent gets better the same way a careful employee does: by noticing a task it
keeps doing the long way, or a mistake it made, and writing down a better
procedure for next time. Those self-authored procedures live in skills/ — which
is inside the auto-approve allowlist, while agent/ source is NOT. So reflection
can improve *how the agent works* (its skills and playbooks) without being able
to silently rewrite its own code; code changes stay PR-gated ("Channel-2").

Entry point:
  reflect(session_id) -> TurnResult   (the /reflect command + weekly cron)
"""
from __future__ import annotations

from . import config, loop

REFLECTION_DIRECTIVE = (
    "You are running the REFLECTION loop (self-improvement). Read and follow"
    " playbooks/reflection.md (use vault_read). Review the recent action log and"
    " the existing skills, find ONE concrete, durable improvement — a recurring"
    " task worth a reusable skill, or a playbook that needs sharpening — and make"
    " it. You may ONLY write under skills/ or playbooks/ (your procedures); never"
    " edit agent/ code — that is out of bounds and would be refused. Be"
    " conservative: one good improvement, not a rewrite. Update skills/README.md"
    " if you add a skill, log what you changed, and reply with the skill/playbook"
    " touched and why."
)


def recent_log(limit: int = 60) -> str:
    """The tail of vault/log.md — the agent's recent actions to reflect on."""
    path = config.VAULT_DIR / "log.md"
    if not path.exists():
        return ""
    lines = path.read_text().splitlines()
    return "\n".join(lines[-limit:])


def _skills_inventory() -> str:
    if not config.SKILLS_DIR.is_dir():
        return "(no skills yet)"
    skills = sorted(p.name for p in config.SKILLS_DIR.glob("*.md"))
    return "\n".join(f"- {s}" for s in skills) or "(no skills yet)"


async def reflect(session_id: str) -> "loop.TurnResult":
    """Run one reflection pass."""
    context = (
        f"# Recent action log (vault/log.md tail)\n{recent_log() or '(empty)'}\n\n"
        f"# Existing skills (skills/)\n{_skills_inventory()}\n\n"
        "Reflect now and make one improvement."
    )
    return await loop.run_turn(
        session_id, context, tier="strong", directive=REFLECTION_DIRECTIVE
    )
