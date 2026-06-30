---
when_to_use: Turning a rough idea into a detailed, buildable spec. Triggered by /spec.
tier: strong
---
# Spec-writing playbook

Goal: take a one-line idea and produce a spec someone could actually build from.

## Process
1. **Restate the idea** in one sentence so the user can catch a misread.
2. **Interrogate it** — but don't block: make reasonable assumptions and mark
   them explicitly rather than asking a wall of questions. List open questions
   at the end instead.
3. **Write the spec** with these sections:
   - **Problem** — what hurts today, who feels it.
   - **Goal / non-goals** — what success is, and what's explicitly out of scope.
   - **Users & key flows** — the 2–4 core journeys, step by step.
   - **Functional requirements** — numbered, testable.
   - **Data & interfaces** — entities, important fields, external APIs.
   - **Constraints & risks** — security, cost, performance, unknowns.
   - **Milestones** — a thin first slice, then increments.
   - **Open questions** — the assumptions you made and what to confirm.
4. **Save** to `vault/01-projects/<kebab-title>.md` with frontmatter:
   ```
   ---
   type: spec
   status: draft
   created: <today>
   ---
   ```
5. **Log** a line to `vault/log.md` and reply with a 2-3 line summary + the path.

## Style
Concrete over abstract. Prefer numbered requirements to prose. A good spec is
skimmable: headings, lists, and tables beat paragraphs.
