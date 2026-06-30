---
when_to_use: Tailoring a resume or cover letter to a specific role. Triggered from /job when asked to tailor.
tier: strong
---
# Resume / cover-letter tailoring playbook

Goal: produce a tailored resume or cover letter grounded in the user's *real*
experience — never invent roles, dates, or achievements.

## Inputs
- **Master resume:** look in `vault/02-areas/` (e.g. `vault/02-areas/resume.md`).
  Use `vault_search` for "resume". If there is no master resume, stop and ask the
  user to add one — do not fabricate a work history.
- **Target role:** the company page in `vault/crm/` and/or the posting in the
  request.
- **Voice & facts:** `memory/USER.md` for focus and register.

## Process
1. Pull the job's key requirements from the company page / posting.
2. Map each requirement to a *real* bullet from the master resume. Reorder and
   re-word for relevance; tighten language. Drop irrelevant material.
3. **Cover letter** (if asked): three short paragraphs — why them, why you (two
   or three mapped proof points), and a clear close. Match the user's plain,
   concise register.
4. **Save** to `vault/01-projects/<company>-<role>-resume.md` (or `-cover.md`)
   with frontmatter `type: application-doc`, and link it from the company page.
5. **Log** a line and reply with the path + a one-line note on what you
   emphasised.

## Guardrails
- Every claim must trace to the master resume. If a requirement has no matching
  experience, say so plainly in your reply rather than inventing one.
- Tailoring means selection and emphasis, not exaggeration.
