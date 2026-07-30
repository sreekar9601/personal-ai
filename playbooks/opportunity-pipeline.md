---
when_to_use: Tracking opportunities, organisations, and prep for upcoming conversations. Triggered by /track.
tier: strong
---
# Opportunity pipeline playbook

The vault is your CRM. Keep two things accurate: the **application tracker** and a
**page per company**. Never invent facts about a posting — record only what's in
the message or already in the vault.

## The application tracker — `vault/crm/pipeline.md`
A single markdown table, newest first. Columns and the allowed statuses:

```
# Job applications

| Company | Role | Status | Applied | Next action | Link |
|---|---|---|---|---|---|
```

Statuses (a simple pipeline): `lead` → `applied` → `screen` → `interview` →
`offer`, plus the terminal `rejected` / `withdrawn`. Always fill **Next action**
with something concrete and dated (e.g. "2026-07-03 follow up if no reply").

## Per-company pages — `vault/crm/<company-kebab>.md`
Create or update when there's substance worth keeping. `vault_search` first so you
extend an existing page instead of duplicating it. Frontmatter:

```
---
type: company
status: <pipeline status>
created: <today>
updated: <today>
---
```
Body: the role, why it fits (tie to USER.md), the posting link, key requirements,
contacts (name / title / how you know them), and a running log of touchpoints.

## Handling a request
1. **A posting** (pasted text or URL) → add/refresh the tracker row as a `lead`
   or `applied`, create/update the company page, set a next action.
2. **A status update** ("phone screen Thursday", "rejected") → move the row's
   status, update the next action, append a dated line to the company page.
3. **Interview prep** → read the company page + USER.md, produce a focused prep
   note (likely questions, your talking points, questions to ask) saved to the
   company page or `vault/01-projects/`.
4. **A pipeline question** ("what's outstanding?") → answer from the tracker; don't
   write anything.

Always finish: append one line to `vault/log.md`, and reply with what changed +
the single most important next action.
