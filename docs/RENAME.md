# Renaming the repo to `agentic-command-center`

The in-repo work is done (see the C8 commit). What's left needs your GitHub and
Fly accounts. Read the "don't touch" list first — two identifiers look
renameable but aren't.

## 1. Rename on GitHub (1 minute)

Repo → **Settings → General → Repository name** → `agentic-command-center` →
**Rename**.

GitHub keeps redirects from the old URL, so existing clones and links keep
working. Then update your local remote:

```bash
git remote set-url origin git@github.com:sreekar9601/agentic-command-center.git
```

## 2. Point the running app at the new URL (important)

The deployed app clones your knowledge repo from `GIT_REMOTE_URL`. Redirects
cover it for a while, but set it properly:

```bash
fly secrets set GIT_REMOTE_URL=git@github.com:sreekar9601/agentic-command-center.git
```

The deploy key is attached to the repo (not its name), so it keeps working.

## 3. Polish the repo page (2 minutes)

- **Description**: *Self-hosted agentic AI command center — iPhone PWA +
  desktop dashboard, passkey-secured, over a git-backed data plane.*
- **Topics**: `ai-agent` `llm` `pydantic-ai` `fastapi` `pwa` `webauthn`
  `personal-finance` `self-hosted` `anthropic` `python`
- **Social preview** (Settings → General → Social preview): upload
  `docs/media/desktop-overview.png` — it becomes the link card on LinkedIn and
  in messages.
- **Pin the repo** on your profile.
- Update the README's CI badge URL and the `<you>/<repo>` placeholder in the
  deploy snippet to the new slug.

## 4. Do NOT rename these

| Identifier | Why it must stay |
|---|---|
| `app = "personal-ai"` in `fly.toml` | The live Fly app name **and hostname**. Renaming points deploys at a non-existent app, and changing the hostname breaks `PWA_ORIGIN` — which your passkey is cryptographically bound to. Repo name and app name are independent; leave it. |
| `_USER_ID = b"personal-ai-owner"` in `api/auth.py` | The WebAuthn user handle baked into your already-registered passkey. Changing it invalidates the enrolled device and forces a recovery-code re-enrollment. It's an opaque id, not a label. |

Both now carry comments in the source saying so.

*If you ever do want a nicer hostname* (e.g. `command-center.fly.dev`), that's a
deliberate migration: create the new Fly app, move the volume/secrets, set
`PWA_ORIGIN` to the new URL, deploy — then **re-enroll your passkey** with the
recovery code, because passkeys are bound to the origin.

## 5. Summary lines (for a portfolio or profile)

Tune the numbers when you use them; these are all defensible from the code:

- Built and operate a **self-hosted agentic AI system** ("Personal Agentic
  Command Center"): a tool-using LLM agent with human-in-the-loop approvals,
  serving an installed iOS PWA and a desktop dashboard from one FastAPI/Python
  process — in production 24/7 on Fly.io.
- Designed the security model: **WebAuthn passkey** (Face ID) single-user auth,
  strict-CSP frontend, path-traversal-guarded file APIs, secret-pattern write
  refusal, and a persisted human approval gate for irreversible actions.
- Engineered **agent cost control**: 3-tier model routing with prompt caching,
  bounded conversation history, per-model token accounting, and a daily budget
  guard — keeping a daily-driver agent at roughly $10–30/month.
- Built a **git-backed data plane** where every agent action is a commit (audit
  trail, backup, and desktop sync in one), plus an autonomous **self-improvement
  loop** that rewrites its own skills inside a write-approval sandbox.
- 112 automated tests and merge-to-deploy CI/CD (GitHub Actions → Fly).
