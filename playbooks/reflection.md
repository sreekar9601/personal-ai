---
when_to_use: Periodic self-improvement — turning experience into reusable skills. Triggered by /reflect and a weekly job.
tier: strong
---
# Reflection playbook (self-improvement)

Goal: make exactly **one** durable improvement to how you work, grounded in what
actually happened — not a speculative rewrite.

## What a "skill" is
A skill is a short, self-authored procedure in `skills/<kebab-name>.md` that you
(or a future you) can read and follow, just like a playbook — but you wrote it
because you noticed a need. Use the same frontmatter as playbooks:

```
---
when_to_use: <the trigger situation, concretely>
tier: cheap | default | strong
---
```

## Process
0. **Empty-history short-circuit (check this first).** If the action log has no
   entries beyond its header AND there are no past sessions AND `skills/` is
   empty, there is nothing to reflect on. Do NOT investigate further, invent a
   recurring task, or edit procedure to feel productive — that is manufactured
   churn. Say "no operational history yet, nothing to improve" and stop. Only
   proceed to step 1 once real actions exist to learn from. (One legitimate
   exception: a gap you observe in the reflection loop *itself*, repeated across
   cycles, is real evidence and may be fixed here.)
1. **Read the recent action log** (provided) and skim the existing skills. Look
   for one of:
   - a task you did more than once and could standardise (→ new skill);
   - a step you got wrong or did clumsily (→ fix the relevant playbook/skill);
   - a gap a playbook doesn't cover (→ extend it).
2. **Pick the single highest-value improvement.** If nothing rises to that bar,
   it is correct to do nothing — say so and stop. Don't manufacture churn.
3. **Write it:**
   - New skill → create `skills/<name>.md` and add it to `skills/README.md`.
   - Playbook fix → edit the playbook in place, surgically.
4. **Log** one line to `vault/log.md` and reply with what you changed and the
   evidence from the log that motivated it.

## Hard boundary
You may write **only** under `skills/` and `playbooks/`. You must **not** modify
anything under `agent/` (your own source code) — that is changed by humans
through pull requests, never by you. A write there would be refused anyway; do
not attempt it.
