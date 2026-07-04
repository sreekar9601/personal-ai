# Skills

Self-authored procedures the agent writes for itself during reflection
(`/reflect`, Phase 5). A skill is a small markdown file — same shape as a
playbook — that codifies something the agent learned it does repeatedly or got
wrong, so next time it has a procedure to follow.

- Playbooks (`playbooks/`) are the human-authored core procedures.
- Skills (`skills/`) are agent-authored, growing over time. Both are inside the
  auto-approve write zone; the agent's own code under `agent/` is not, and is
  only changed by humans via pull request.

## Catalog
_(empty — the reflection loop adds entries here as it writes skills.)_
