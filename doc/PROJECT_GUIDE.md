# Fullego Backend — Project Guide

> A single reference to understand the codebase, locate things fast, and reason
> about bug fixes and changes. Read this first, then jump to the relevant module.
>
> **Stack:** FastAPI (async) · SQLAlchemy 2.0 (async/asyncpg) · Supabase Postgres
> · Alembic · Redis · Stripe · Plaid · Persona · Alpaca · Polygon · Sendbird ·
> Resend · PostHog · Sentry · APScheduler. Python 3.11+ (see `runtime.txt`).
>
> **Public name:** "Akunuba" (frontend at `akunuba.io` / `akunuba.vercel.app`).
> Internal/code name is "Fullego".

---

## 1. How to run it

| Action | Command |
|---|---|
| Dev server (auto-reload) | `python run.py` → uvicorn on `HOST:PORT` (default `0.0.0.0:8000`) |
| Prod entrypoint | `uvicorn app.main:app` (see `Dockerfile`, `render.yaml`) |
| DB migrations | `alembic upgrade head` (config in `alembic.ini`, scripts in `alembic/versions/`) |
| Health check | `GET /health` → status + version + DB/Redis checks + metrics |
| API docs | FastAPI auto Swagger at `/docs`, ReDoc at `/redoc` |

- Config is environment-driven via `app/config.py` (`pydantic-settings`, reads `.env`,
  **case-sensitive** env var names). Deployment env vars: `render.yaml`,
  `API_KEYS_AND_ENV_VARIABLES.md`, `ENV_VARIABLES_CHECK_REPORT.md`.
- All API routes are mounted under `API_V1_PREFIX` = `/api/v1`.

---

## 2. Architecture at a glance

```
app/
  main.py            ← FastAPI app: middleware, CORS, routers, exception handlers,
                        startup/shutdown (Redis, scheduler, DB ping, Sentry)
  config.py          ← Settings (all env vars live here)
  database.py        ← async engine + get_db() session dependency
  api/
    deps.py          ← shared dependencies: get_current_user, get_account,
                        subscription/feature gating
    v1/<domain>.py   ← one router file per domain (35 routers, see §4)
  models/            ← SQLAlchemy ORM models (one file per domain)
  schemas/           ← Pydantic request/response models
  services/          ← business logic reused across routers (email, notifications,
                        banking sync, SLA, ticket assignment, account restrictions)
  integrations/      ← third-party API clients (one per provider, see §6)
  core/              ← cross-cutting: security, permissions, features, rate_limit,
                        scheduler, websocket_manager, exceptions, metrics
  utils/             ← logger, validators, helpers, upload_helpers
```

**Request flow:** client → CORS/normalize/timing middleware → router (`api/v1/*`)
→ depends on `get_db` + `get_current_user`/`get_account` → uses `models` + `schemas`,
delegates heavier logic to `services` and external calls to `integrations` →
returns Pydantic response. Errors raise `core/exceptions` types, normalized to JSON
by the global handlers in `main.py`.

---

## 3. Key conventions (read before changing code)

- **Async everywhere.** Routers, DB calls, and integration clients are `async`.
  Use `await db.execute(select(...))` then `.scalar_one_or_none()` / `.scalars().all()`.
- **DB sessions:** inject `db: AsyncSession = Depends(get_db)`. `get_db` auto-commits
  on success and rolls back on exception — it is a **single-yield** generator on
  purpose (retry loops around `yield` cause "generator didn't stop" errors). Don't
  add retries there.
- **Auth:** Bearer JWT. `get_current_user` decodes the token (`core/security.py`),
  loads the `User`, and rejects inactive users. Most user-scoped routes depend on
  `get_account` (one `Account` per `User`).
- **JWTs** are HS256 signed with `SECRET_KEY`; access tokens carry `type: "access"`,
  refresh tokens `type: "refresh"`. Helpers: `create_access_token`,
  `decode_access_token`, etc. in `core/security.py`.
- **Passwords:** bcrypt. Hashing via passlib; **verification calls `bcrypt.checkpw`
  directly** to dodge passlib init bugs, with explicit handling of the 72-byte limit.
  Don't "simplify" this back to `pwd_context.verify`.
- **Exceptions:** raise the typed helpers in `core/exceptions.py`
  (`NotFoundException`, `BadRequestException`, `ForbiddenException`,
  `UnauthorizedException`, …) instead of bare `HTTPException` where possible.
  `main.py` has global handlers that always attach CORS headers (even on 500).
- **Plans & feature gating:** `core/features.py` maps `SubscriptionPlan` →
  `Feature` set and usage limits; `core/permissions.py` for role checks. Helpers
  `get_limit` / `check_usage_limit` enforce per-plan quotas. **Admins are exempt
  from usage limits** (see recent commits on assets/marketplace).
- **Enums in DB:** compliance and other models use a case-insensitive
  `EnumValueType` for enum columns — incoming values are matched case-insensitively.
- **File uploads:** go through `utils/upload_helpers.py`
  (`resolve_content_type`, `storage_bucket_for_file_type`,
  `validate_image_content_type`) and land in Supabase Storage buckets.
- **Logging:** use `from app.utils.logger import logger` (JSON logger). Avoid `print`.

---

## 4. API domains (`app/api/v1/`) and their mount prefix

All under `/api/v1`. Router → prefix (from `main.py`):

| Router file | Prefix | Purpose |
|---|---|---|
| `auth_new.py` (as `auth`) | `/auth` | signup/login, OTP, password reset, Google OAuth, 2FA |
| `users.py` | `/users` | profile, settings |
| `accounts.py` | `/accounts` | account record per user |
| `kyc.py` | `/kyc` | individual identity verification (Persona) |
| `kyb.py` | `/kyb` | business verification |
| `assets.py` | `/assets` | asset CRUD, photos, docs, appraisals, sale/transfer/share, reports |
| `portfolio.py` | `/portfolio` | portfolio aggregation & valuation |
| `trading.py` | `/trading` | order placement (Alpaca) |
| `marketplace.py` | `/marketplace` | listings, offers, escrow |
| `payments.py` | `/payments` | Stripe payments, refunds, invoices |
| `subscriptions.py` | `/subscriptions` | plan subscribe/renew/cancel |
| `banking.py` | `/banking` | Plaid linked accounts & transactions |
| `documents.py` | `/documents` | document storage & sharing |
| `files.py` | `/files` | generic file upload/serve |
| `support.py` | `/support` | tickets, replies, SLA |
| `notifications.py` | `/notifications` | in-app notifications |
| `reports.py` | `/reports` | generated reports |
| `chat.py` + `chat_conversations.py` | `/chat` | messaging (Sendbird) |
| `websocket_chat.py` | `ws://…/ws/chat` | realtime chat over WebSocket (Redis pub/sub) |
| `analytics.py` | `/analytics` | analytics dashboards |
| `admin.py` | `/admin` | admin-only operations |
| `investment.py` | `/investment` | investment products / watchlist |
| `market.py` | `/market` | market data (Polygon) |
| `tasks.py` | `/tasks` | task management |
| `reminders.py` | `/reminders` | reminders |
| `concierge.py` | `/concierge` | concierge requests |
| `crm.py` | `/crm` | CRM records |
| `entities.py` | `/entities` | legal entities, persons, compliance, audit trail |
| `compliance.py` | `/compliance` | compliance center: tasks, audits, alerts, scores, policies |
| `referrals.py` | `/referrals` | referral program & rewards |
| `webhooks.py` | `/webhooks` | inbound webhooks (Stripe, Plaid, Persona) |

---

## 5. Data model map (`app/models/`)

Models are registered in `app/models/__init__.py` (import side-effects register
them with `Base`). Domains: `user`, `account`, `asset` (+ many sub-tables),
`portfolio`, `order`, `marketplace`, `payment` (Payment/Refund/Invoice/Subscription),
`banking` (LinkedAccount/Transaction), `document` + `document_share`,
`support` + `ticket_reply`, `report`, `entity` (+ people/compliance/audit),
`notification`, `referral`, `chat` (Conversation/Message/…), `task` (Task/Reminder),
`watchlist`, `kyc`, `kyb`, `user_preferences` (incl. 2FA), `compliance` (tasks,
audits, alerts, scores, metrics, reports, policies), `joint_invitation`.

Schema changes go through **Alembic** (`alembic/versions/`, numbered `001`…`013`).
RLS (row-level security) is explicitly enabled on tables via dedicated migrations.

---

## 6. Third-party integrations (`app/integrations/`)

| Client | Provider | Used for |
|---|---|---|
| `supabase_client.py` | Supabase | Postgres + Storage (files); has HTTP fallback & hardened error handling |
| `stripe_client.py` | Stripe | payments, subscriptions, webhooks |
| `plaid_client.py` | Plaid | bank linking, transactions |
| `persona_client.py` | Persona | KYC/KYB identity verification |
| `alpaca_client.py` | Alpaca | brokerage/trading (API-key or OAuth2) |
| `polygon_client.py` | Polygon | market data |
| `sendbird_client.py` | Sendbird | chat/messaging |
| `posthog_client.py` | PostHog | product analytics (flushed on shutdown) |

Email is sent via **Resend** (`services/email_service.py`); OTP email failures can
optionally return the OTP in the API response when
`EMAIL_RETURN_OTP_ON_FAILURE=true` (used until the Resend domain is verified).

---

## 7. Background jobs (`app/core/scheduler.py`)

APScheduler (`AsyncIOScheduler`, UTC). Optional **Redis jobstore** for persistence
across restarts; every job runs behind a **distributed Redis lock**
(`scheduler_locks.py`) so only one instance executes it in a multi-instance deploy.

| Job id | Schedule | Action |
|---|---|---|
| `expire_offers` | every 1h | expire marketplace offers |
| `recalculate_portfolios` | daily 02:00 UTC | recompute portfolio values |
| `subscription_renewals` | daily 03:00 UTC | process renewals |
| `expire_listings` | daily 04:00 UTC | expire listings |
| `monitor_sla` | every 6h | support SLA breach monitoring |
| `banking_sync_all` | every 6h | sync all Plaid linked accounts |
| `subscription_retry_downgrade` | daily 04:30 UTC | retry failed payments / downgrade |

Scheduler starts in `startup_event` unless `APP_ENV == "test"`; failures don't block startup.

---

## 8. Cross-cutting infrastructure (`app/core/`)

- `security.py` — password hashing/verify, JWT create/decode, OTP & token generators.
- `permissions.py` — role/permission checks. `features.py` — plan → feature/limit maps.
- `rate_limit.py` — slowapi limiter (60/min default; auth routes 5/min);
  toggle with `RATE_LIMIT_ENABLED`.
- `websocket_manager.py` — WebSocket connection manager backed by Redis pub/sub
  (connected on startup, disconnected on shutdown).
- `scheduler.py` / `scheduler_locks.py` — background jobs + distributed locks.
- `metrics.py` — in-process request-timing/job-failure metrics exposed via `/health`.
- `exceptions.py` — typed HTTP exceptions.

**CORS** is configured in `main.py`: dev allows localhost:3000/5173/3001;
prod parses `CORS_ORIGINS` and always appends localhost + the `akunuba.*` origins.
A `NormalizePathMiddleware` collapses `//` in paths; a catch-all `OPTIONS` handler
and global exception handlers guarantee CORS headers on every response.

---

## 9. How to investigate a bug / make a change (playbook)

1. **Find the surface.** Identify the endpoint → open `app/api/v1/<domain>.py`.
   Routes are mounted in `main.py` (§4) so map URL prefix → file there.
2. **Trace the data.** Endpoint → `schemas/<domain>.py` (request/response shape) →
   `models/<domain>.py` (DB columns) → `services/*` (shared logic) →
   `integrations/*` (external calls).
3. **Auth/permission issues?** Check `api/deps.py` (`get_current_user`,
   `get_account`, subscription gating) and `core/{security,permissions,features}.py`.
4. **External-call failures?** The relevant `integrations/*` client + the env vars
   in `config.py`. Most clients have fallback/error handling already — read it
   before adding more.
5. **Data/enum/migration issues?** Check the model, then `alembic/versions/`.
   Enum case-mismatch → remember `EnumValueType` is case-insensitive.
6. **Background/scheduled behavior?** `core/scheduler.py` (§7).
7. **CORS / 500 with missing headers?** It's almost always the handlers in `main.py`.
8. **Reproduce**, then fix at the lowest correct layer (service over router when the
   logic is shared). Match surrounding async/SQLAlchemy style.
9. **Migrations:** if you touch a model's columns, add an Alembic revision — don't
   hand-edit the DB.
10. **Verify:** run the server (`python run.py`), hit the endpoint, check `/health`.

---

## 10. Change log of notable recent work (from git history)

> Keep this section updated when you land a meaningful change. Newest first.

- **Documents statistics:** added `GET /api/v1/documents/statistics` returning
  `{ total_documents, storage_used, storage_limit, last_uploaded }` (snake_case).
  Declared **before** `GET /{document_id}` to fix a 422 where "statistics" was
  parsed as a UUID by the dynamic route. Added per-plan `STORAGE_LIMITS` /
  `get_storage_limit()` in `core/features.py` so `storage_limit` is authoritative.
  Reminder: under `/documents`, any new static single-segment route must be
  declared above `/{document_id}`.
- **Assets/notifications:** better error management, share-link generation,
  case-insensitive enum support.
- **Compliance models:** switched enum columns to `EnumValueType`; added settings
  for compliance checks.
- **Assets/marketplace:** admin exemptions from usage limits.
- **Email/KYC:** moved email to **Resend**, OTP send error handling + fallback,
  improved KYC verification flow; added OTP/redirect-URI settings; stricter file
  upload content-type validation; Supabase client error handling + HTTP fallback.
- **Google OAuth:** callback redirect logic based on verification status;
  `FRONTEND_BASE_URL` for post-OAuth redirect; asyncpg exception support in DB ops.

---

## 11. Related docs in this repo

- `FEATURES.md` — full feature inventory (largest doc).
- `API_KEYS_AND_ENV_VARIABLES.md`, `ENV_VARIABLES_CHECK_REPORT.md`, `env.md` — env config.
- `BACKEND_API_CONTRACT_FOR_CURSOR.md`, `Fullego_Backend_API.postman_collection.json` — API contract.
- `doc/` — many integration & requirement guides (frontend integration, Plaid link,
  websockets, background jobs report, etc.).
- `QUICK_START.md`, `TROUBLESHOOTING_SERVER.md`, `RESTART_SERVER_INSTRUCTIONS.md` — ops.
- `mongodb.md` — note: the live datastore is **Supabase Postgres** (this file is reference only).

---

_Maintainer note: when you fix a bug or add a feature, update §10 and, if it changes
how a layer works, the relevant section above. This file is meant to stay accurate._
