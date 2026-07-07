# PWA Design — the personal app

*Design for the iPhone-first companion app (PLAN.md Phase 10). The goal is not
"a chat client": it is a **personal platform** — one authenticated surface that
today shows the assistant, money, and tasks, and later absorbs whatever domain
comes next. Telegram remains the capture channel during the transition and is
demoted once the PWA earns it.*

---

## 1. Why a PWA (and iPhone specifics)

An installable web app served by the existing Fly machine, added to the home
screen from Safari. Full-screen, app icon, push notifications — no App Store,
no $99/yr Apple developer account, no TestFlight expiries, one codebase.

iPhone constraints that shape the design (iOS 16.4+):

| iOS reality | Design consequence |
|---|---|
| Web Push works **only when installed** to the home screen | Onboarding step 1 is "Add to Home Screen"; the app detects browser mode and shows the instruction banner |
| Push payloads are E2E-encrypted (RFC 8291) | Proactive briefings/approvals can carry real content — Apple relays but cannot read |
| No background sync / background fetch for PWAs | All state lives server-side; the app is a *view*, it never owns data. Reopening = one `GET /api/bootstrap` |
| Service-worker cache can be evicted under storage pressure | Cache is a convenience (app shell only), never a store of record |
| `MediaRecorder` works in Safari (voice), `<input capture>` works (camera) | Voice notes and receipt photos are standard web APIs, no native code needed |

## 2. Architecture

One Fly machine, one Python process, two transports over the same brain:

```
iPhone (installed PWA)                    Telegram (legacy channel)
   │  HTTPS + passkey session                │  long-polling
   ▼                                         ▼
FastAPI (api/)  ──────────────┬────────  python-telegram-bot (agent/main.py)
   │  SSE stream, REST, push  │
   └──────────────► agent/loop.run_turn / resume_turn  ◄──────────┘
                        │
        vault/ · finance/ · memory/ · sqlite  (the /data volume, unchanged)
```

- **`api/` package** (new): FastAPI app started in the same asyncio loop as the
  bot (uvicorn served as a task; PTB run via `initialize()/start()` instead of
  `run_polling()`). One process keeps sqlite access simple and the machine at
  512MB.
- **The brain is shared.** Both transports call `loop.run_turn()`; approval
  gates, budget guard, kill switch, git commits, audit log all apply
  identically. A turn started on Telegram can even be approved in the PWA —
  pending approvals already live in sqlite.
- **`fly.toml` gains `[http_service]`** with `force_https`, `min_machines_running=1`.
  This is the moment the machine gets a public port — auth below is the wall.

## 3. Auth (single user, passkey-first)

- **WebAuthn/passkey** as the only login: Face ID on the phone, synced via
  iCloud Keychain. Single-user server: exactly one registered credential set,
  bound at enrollment.
- **Enrollment** is a one-time URL printed to the server log at first boot
  (`/enroll?token=<random>`), consumed on use — same trust bootstrap as the
  Telegram allowlist.
- **Sessions**: httpOnly, Secure, SameSite=Strict cookie; 30-day sliding
  expiry; `/api/*` rejects anything without it (401, no redirect leak).
- **Recovery**: a long random recovery code shown once at enrollment (stored
  by the user, hash on server) that can re-open enrollment.
- **Hard rules**: no CORS beyond own origin, security headers (CSP, HSTS),
  rate-limit auth endpoints, all other endpoints session-gated. The Telegram
  path keeps working regardless — it is the recovery transport of last resort.

## 4. API surface (v1)

| Endpoint | What |
|---|---|
| `POST /api/chat` → SSE | Send a message; stream status + final reply; approval requests arrive as a typed event |
| `POST /api/approvals/{token}` | Approve/deny (same store the Telegram buttons use) |
| `GET /api/bootstrap` | One call on open: pending approvals, today's spend, inbox count, task list, month summary |
| `GET /api/finance/summary?month=` · `GET /api/finance/ledger` | Money tab data (wraps `finance.summary/query`) |
| `GET/POST/PATCH /api/tasks` | Task list (backed by `vault/tasks.md` when that slice lands) |
| `POST /api/capture/photo` · `POST /api/capture/voice` | Receipt/photo → vision extraction; voice → transcription → normal turn |
| `GET /api/status` | The `/status` payload as JSON |
| `POST /api/push/subscribe` | Store the Web Push subscription (VAPID) |

Server-side generation of dashboards drops away: the PWA renders live JSON.

## 5. Frontend

- **Stack**: Vite + React + TypeScript + Tailwind. Built to static files,
  served by FastAPI (`/` → app shell, `/api/*` → JSON). No SSR, no Node in
  production — the Fly image stays Python-only; CI builds the frontend and
  bakes `dist/` into the Docker image.
- **Tabs** (the expansion pattern — each future domain is one new tab + one
  new API router, nothing else changes):
  1. **Chat** — capture + conversation; approval cards inline with real
     Approve/Deny buttons; streaming replies.
  2. **Money** — month-to-date by category, vs-last-month, ledger list,
     tap-to-recategorise; add-expense sheet (amount/category/merchant) for
     when typing beats chatting.
  3. **Tasks** — checkboxes, due dates, add/complete; agenda view.
  4. **Notes** — browse/search the wiki (read-only v1), render wikilinks.
  5. **Status** — uptime, spend vs budget, kill switch view, push toggle.
- **PWA shell**: manifest (icons, `display: standalone`), service worker
  caching the shell only; a visible "install me" banner when running in
  Safari-tab mode.
- **Live updates**: SSE while the app is open; Web Push (briefing, approval
  needed, weekly reflection) when it is not.

## 6. Security posture change

| | Today (Telegram) | With PWA |
|---|---|---|
| Open ports | none | 443 (Fly TLS) |
| Who can read messages | you + Telegram | you only (TLS to your server; push E2E-encrypted) |
| Auth | Telegram account + allowlist | passkey (Face ID) on your own server |
| Weakest link | your Telegram account, bot token | your auth code + dependency patching |

Mitigations for the new surface: passkeys only (no passwords to stuff),
femto-attack-surface API (a dozen routes, all session-gated), fail-closed
enrollment, Dependabot on the repo, and the existing kill switch also
disables the API's write paths.

## 7. Build slices (each independently shippable)

| Slice | Contents | Size |
|---|---|---|
| **P1 — Skeleton + auth** | FastAPI in-process, `[http_service]`, passkey enroll/login, `/api/status`, app shell installable on iPhone | ~2–3 days |
| **P2 — Read-only dashboard** | bootstrap endpoint, Money + Status tabs, Notes browse | ~2 days |
| **P3 — Chat + approvals** | SSE chat, approval cards, unified approval store | ~2–3 days |
| **P4 — Push** | VAPID Web Push: morning briefing, approval-needed, budget-hit | ~1–2 days |
| **P5 — Capture upgrades** | receipt photos (vision → `log_expense` → ledger); voice via the iOS keyboard's dictation key (native on-device STT into the chat input — better latency and zero server/provider cost than a MediaRecorder→transcription pipeline, which would need an audio-capable second provider; revisit only if dictation proves insufficient) | ~2 days |
| **P6 — Demote Telegram** | make PWA primary, Telegram fallback; revisit whether to keep it | ~½ day |

P1+P2 give a private, Face-ID-locked dashboard on the phone with zero risk to
the working Telegram flow. Chat (P3) only cuts over when it is demonstrably
nicer than Telegram.

## 8. Explicitly out of scope (v1)

- Native Swift app (revisit only if a PWA constraint actually bites).
- Multi-user anything — one human, one credential set, by design.
- Offline mutation queue (server-authoritative; iOS PWA background limits make
  offline writes more complexity than value for a personal tool).
- E2E encryption of the vault at rest beyond Fly volume encryption (the
  threat model is remote attackers, not the hosting provider).
