---
when_to_use: Default handling for an inbound message that is a thought, link, or note to keep.
tier: default
---
# Capture playbook

When a message is something to *remember* rather than a question to answer:

1. **Write it to** `vault/00-inbox/` as `YYYY-MM-DD-<short-kebab-slug>.md`.
2. **Frontmatter:**
   ```
   ---
   type: capture
   created: <today>
   source: telegram
   ---
   ```
3. **Body:** the raw text, lightly cleaned. Do not editorialize or expand —
   capture is for the user's words, synthesis happens later (Phase 1).
4. **Confirm** in one line: what you filed and where.

Heuristics:
- A URL alone → capture with the URL and any context the user gave.
- A question ("what did I spend on…", "when is X") → answer it, don't file it.
- Ambiguous → capture, and note in your reply that you filed it.
