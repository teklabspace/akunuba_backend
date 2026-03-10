# Comprehensive Backend Analysis Report

Single document covering: third-party integrations, API routes vs frontend usage, migrations, security, error handling, deployment, scheduler, caching, frontend feature status, completion estimates, and top 10 launch issues.

---

# Part 1 — Third-Party Integrations

For each integration: real API usage, env vars, sandbox/production, webhooks, error/retry.

---

## Stripe

**Implementation level:** Full  
**Real API calls:** Yes — PaymentIntent, Customer, Subscription, Refund, PaymentMethod (attach/detach/list), Charge.  
**Environment variables required:** `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` (all required in config).  
**Sandbox/production:** Determined by key (test vs live key). No explicit env flag.  
**Webhook endpoints:** Yes — `POST /api/v1/payments/webhook`, `POST /api/v1/subscriptions/webhook`. Both verify signature via `StripeClient.verify_webhook_signature(payload, signature)` using `STRIPE_WEBHOOK_SECRET`.  
**Error/retry handlers:** Log and re-raise in client; no retry/backoff.  
**Used in:** payments, subscriptions, marketplace, admin.  
**Production readiness:** Ready. Webhook signature validation present; add retries for idempotent Stripe calls if desired.

---

## Plaid

**Implementation level:** Full  
**Real API calls:** Yes — link_token_create, item_public_token_exchange, accounts_get, transactions_get.  
**Environment variables required:** `PLAID_CLIENT_ID`, `PLAID_SECRET_KEY` (optional for dev); `PLAID_PUBLIC_KEY`, `PLAID_ENV`.  
**Sandbox/production:** `PLAID_ENV`: sandbox | development | production (maps to Plaid host).  
**Webhook endpoints:** None. Plaid webhooks (e.g. transactions updates) not implemented.  
**Error/retry handlers:** Log and raise; no retry. Graceful if SDK/creds missing (returns None or ValueError).  
**Used in:** banking.  
**Production readiness:** Partial. No webhooks for transaction updates; no scheduled banking sync.

---

## Alpaca

**Implementation level:** Full  
**Real API calls:** Yes — account, positions, orders (create/cancel/get), transactions (via SDK or HTTP).  
**Environment variables required:** API key: `ALPACA_API_KEY_ID`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL` (default paper). OAuth: `ALPACA_OAUTH_ENABLED`, `ALPACA_OAUTH_CLIENT_ID`, `ALPACA_OAUTH_CLIENT_SECRET`, `ALPACA_OAUTH_TOKEN_URL`, `ALPACA_OAUTH_BASE_URL`.  
**Sandbox/production:** Paper vs live via `ALPACA_BASE_URL` / `ALPACA_OAUTH_BASE_URL` (paper-api.alpaca.markets vs api.alpaca.markets).  
**Webhook endpoints:** None (Alpaca does not require backend webhooks for order flow).  
**Error/retry handlers:** Log and raise/return None; OAuth token cached with 5-min early refresh. No request retry.  
**Used in:** accounts, portfolio, investment, trading.  
**Production readiness:** Ready for paper/live depending on base URL.

---

## Polygon

**Implementation level:** Full  
**Real API calls:** Yes — ticker details, aggregates, last trade/quote, snapshot, daily open/close, search (httpx to api.polygon.io).  
**Environment variables required:** `POLYGON_API_KEY` (optional; missing key skips request and returns None).  
**Sandbox/production:** No env switch; same API key type.  
**Webhook endpoints:** None.  
**Error/retry handlers:** Log and return None; no retry.  
**Used in:** portfolio, investment, market.  
**Production readiness:** Ready. Optional key allows graceful degradation.

---

## Persona

**Implementation level:** Full  
**Real API calls:** Yes — create inquiry, get inquiry, submit inquiry, upload document, list documents, verification URL (httpx to withpersona.com).  
**Environment variables required:** `PERSONA_API_KEY`, `PERSONA_TEMPLATE_ID` (required for create_inquiry). Optional: `PERSONA_FILE_ACCESS_TOKEN_EXPIRY`, `PERSONA_REDIRECT_URI`.  
**Sandbox/production:** No explicit mode; depends on Persona dashboard config.  
**Webhook endpoints:** None in backend (Persona can send webhooks; no handler found).  
**Error/retry handlers:** HTTPStatusError re-raised; others logged and raised. No retry.  
**Used in:** kyc, kyb.  
**Production readiness:** Partial. Consider adding Persona webhook handler for status updates.

---

## Sendbird

**Implementation level:** Full  
**Real API calls:** Yes — create user, create channel, send message, get channels, get channel, get messages, update channel, delete channel (httpx to Sendbird API).  
**Environment variables required:** `SENDBIRD_APP_ID`, `SENDBIRD_API_TOKEN`.  
**Sandbox/production:** No env switch.  
**Webhook endpoints:** None.  
**Error/retry handlers:** Log and return None; no retry.  
**Used in:** chat (Sendbird-based chat module).  
**Production readiness:** Ready. Note: in-app chat (conversations + WebSocket) is separate and also implemented.

---

## PostHog

**Implementation level:** Full  
**Real API calls:** Yes — identify, capture (track), shutdown via SDK.  
**Environment variables required:** `POSTHOG_PROJECT_API_KEY` (primary), `POSTHOG_HOST` (optional). `POSTHOG_API_KEY` in config but client uses project key.  
**Sandbox/production:** No env switch.  
**Webhook endpoints:** N/A (analytics ingest).  
**Error/retry handlers:** Log and return False; no retry.  
**Used in:** analytics.  
**Production readiness:** Ready.

---

## Supabase

**Implementation level:** Full  
**Real API calls:** Yes — Auth (admin create_user), Storage (upload, download, delete, get public URL).  
**Environment variables required:** `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`.  
**Sandbox/production:** By project URL/keys.  
**Webhook endpoints:** N/A (storage/auth used as services).  
**Error/retry handlers:** Upload has overwrite-on-duplicate retry; otherwise log and raise.  
**Used in:** auth_new, assets, documents, files, kyc, kyb, support, entities, compliance, concierge.  
**Production readiness:** Ready.

---

# Part 2 — Backend API Routes and Frontend Usage

## All backend API routes defined

Prefix: `API_V1_PREFIX` = `/api/v1`. Plus WebSocket: `/ws/chat`.

| Module | Route count (approx) | Notes |
|--------|----------------------|--------|
| auth_new | 9 | register, login, refresh, request-otp, verify-otp, password reset, verify-email, resend-verification |
| users | 18 | me, list, get/update/delete user, role, stats, notifications, privacy, 2FA, change-password, deactivate, delete |
| accounts | 15 | CRUD, verify, joint-users, settings, stats, admin suspend/activate |
| kyc | 13 | start, status, documents, submit, verification URL, admin queue, etc. |
| kyb | 5 | start, status, documents, submit |
| banking | 8 | link-token, link, accounts, sync, refresh, disconnect, transactions |
| assets | 37 | CRUD, valuations, ownership, photos, documents, appraisals, sale-requests, transfers, share, reports, etc. |
| portfolio | 29 | summary, performance, history, allocation, risk, benchmark, crypto, cash-flow, trade-engine |
| investment | 14 | overview, performance, analytics, recommendations, goals, strategies, watchlist |
| market | 1 | benchmarks |
| trading | 3 | transactions, assets |
| payments | 13 | create-intent, webhook, history, invoices, payment-methods, refunds, stats |
| subscriptions | 10 | plans, create, get, cancel, renew, upgrade, history, webhook, permissions, limits |
| marketplace | 30 | listings, offers, escrow, search, market highlights/trends/summary, watchlist |
| documents | 9 | upload, list, download, delete, get, update, share, preview, stats |
| files | 1 | upload |
| support | 11 | tickets CRUD, replies, assign, documents, history, stats |
| chat | 8 | Sendbird: users, channels, messages |
| chat_conversations | 8 | conversations, messages, read, participants, create, update |
| notifications | 10 | list, read, read-all, unread-count, unread, settings, create, delete |
| tasks | 7 | CRUD, complete, remind |
| reminders | 5 | CRUD, snooze |
| referrals | 6 | stats, list, code, generate-code, rewards, leaderboard |
| reports | 8 | portfolio, performance, transactions, etc. |
| analytics | 8 | identify, track, track-batch, page-view, dashboard, portfolio, performance, risk |
| concierge | 11 | appraisals CRUD, assign, documents, comments, valuation, report, statistics |
| crm | 3 | users, dashboard/overview |
| entities | 27 | CRUD, types, hierarchy, compliance, people, audit-trail, documents |
| compliance | 24 | dashboard, tasks, audits, alerts, score, metrics, reports, policies |
| admin | 4 | dashboard, disputes list/get, resolve |

**Total backend endpoints:** ~331 HTTP route handlers + 1 WebSocket = **332**.

## Frontend usage

**Note:** The frontend codebase is not in this workspace (backend-only repo). The following is inferred from project docs and 404 notes.

- **Endpoints used by frontend:** Not verifiable without the frontend repo. Docs indicate auth, users, portfolio, investment, assets, marketplace (and others) are intended for use; 404 doc states backend APIs for portfolio, investment, assets, marketplace are “ready and working.”
- **Endpoints not used by frontend:** Cannot be computed without scanning the frontend. Likely unused or partially used: many of compliance, entities, concierge, crm, reports, analytics, referrals, tasks, reminders, Sendbird chat (if app uses in-app chat only), admin, KYC/KYB admin.
- **Grouped by module (candidates for “likely unused or low use” from doc context):**  
  Compliance (24), Entities (27), Concierge (11), CRM (3), Reports (8), Analytics (8), Referrals (6), Tasks (7), Reminders (5), Admin (4), Chat Sendbird (8 if in-app chat is primary), KYC/KYB admin endpoints.

**Recommendation:** Run a frontend codebase search for `/api/v1/` or `API_V1_PREFIX` to get exact counts of used vs unused endpoints.

---

# Part 3 — Database Migration Tools

**Migration system used:** Alembic (SQLAlchemy).  
**Config:** `alembic.ini` (script_location = alembic, placeholder `sqlalchemy.url`).  
**Migration files found:** 12 versioned migrations under `alembic/versions/`:
- 001_initial_migration.py  
- 002_enable_rls_on_all_tables.py  
- 003_enable_rls_alembic_version.py  
- 004_add_kyb_columns.py  
- 005_add_asset_category_fields_and_new_models.py  
- 006_enable_rls_asset_tables.py  
- 007_make_asset_id_nullable.py  
- 008_add_watchlist_table.py  
- 009_add_crm_tables.py  
- 010_add_entity_tables.py  
- 011_add_compliance_center_tables.py  
- 012_add_user_preferences_and_2fa.py  

**Schema versioning:** Yes — Alembic version table and revision chain.  
**Prisma / manual SQL:** No Prisma. No standalone manual SQL migration scripts found.  
**Risk if schema changes:** Low if migrations are run before deploy. Ensure `env.py` uses `DATABASE_URL` from environment (not hardcoded) and that production runs `alembic upgrade head`.

---

# Part 4 — Backend Security

| Control | Status | Notes |
|--------|--------|--------|
| **JWT authentication** | Implemented | `app.core.security`: create/decode access and refresh tokens (jose/jwt). `app.api.deps.get_current_user` validates Bearer token and loads user. |
| **Role-based permissions** | Implemented | `app.core.permissions`: Role (ADMIN, INVESTOR, ADVISOR), Permission enum, `has_permission()`. Used on users, accounts, marketplace, admin, notifications, etc. |
| **Input validation** | Implemented | Pydantic request bodies and query params; FastAPI RequestValidationError → 422. |
| **Rate limiting** | Missing | No rate_limit, throttle, or slowapi/similar middleware found. |
| **CORS configuration** | Implemented | main.py: CORSMiddleware with allow_origins (dev + prod list), credentials, methods, headers; OPTIONS handler. |
| **SQL injection protection** | Implemented | SQLAlchemy ORM and parameterized queries; no raw SQL concatenation. |
| **Secrets management** | Partial | Secrets in env vars (pydantic-settings); no vault/KMS. SECRET_KEY, DB and API keys in config. |
| **Webhook signature validation** | Implemented | Stripe: `StripeClient.verify_webhook_signature(payload, signature)` on payments and subscriptions webhooks. |

**Strengths:** JWT, RBAC, validation, CORS, ORM, Stripe webhook verification.  
**Missing:** Rate limiting (per-IP or per-user), optional secrets vault for production.

---

# Part 5 — Error Handling and Logging

**Global exception handlers (main.py):**  
- HTTPException / StarletteHTTPException → JSONResponse with `detail`, CORS headers.  
- RequestValidationError → 422, `detail`: validation errors.  
- Exception → 500, `detail`: generic or (if APP_DEBUG) exception string; CORS headers; `logger.error(..., exc_info=True)`.

**Logging:** `app.utils.logger`: standard logging, level from APP_DEBUG, format and StreamHandler to stdout. No file/rotation or structured JSON.  
**Error response format:** JSON `{"detail": ...}` (string or list for 422).  
**Retry for external APIs:** No tenacity/backoff. Isolated retries: Supabase upload overwrite, files upload duplicate.  
**Monitoring hooks:** None (no Sentry, DataDog, or health/metrics callbacks).

**Production readiness:** Partial. Add rate limiting, optional retries for idempotent external calls, and monitoring (e.g. Sentry).

---

# Part 6 — Deployment Configuration

**Dockerfile:** None found.  
**docker-compose:** None found.  
**CI/CD:** No `.github/workflows` or similar CI/CD in repo.  
**Environment configuration:** `.env` via pydantic-settings; `doc/RENDER_ENV_VARIABLES.md` (and similar) document env vars.  
**Production server config:** No Nginx, gunicorn, or uvicorn workers config in repo.  
**Scaling:** Redis used for WebSocket pub/sub (multi-instance); no Kubernetes/Docker or scale docs.

**Deployment readiness:** Low. Add Dockerfile, optional docker-compose, and CI/CD for tests and deploy; document production run (e.g. uvicorn workers, reverse proxy).

---

# Part 7 — Scheduler (app/core/scheduler.py)

**Library:** APScheduler 3.10.4 — `AsyncIOScheduler(timezone="UTC")`.  
**How jobs are triggered:** `IntervalTrigger` (expire_offers 1h, monitor_sla 6h) and `CronTrigger` (recalculate_portfolios 02:00, subscription_renewals 03:00, expire_listings 04:00). Registered in `setup_scheduled_tasks()`, started in main startup.  
**Persist after restart:** No. Jobs live in memory only; no job store (no database or Redis backend). Restart loses schedule; jobs re-register on next startup.  
**Distributed workers:** Not supported. Single process; no locking or coordination. Multiple instances would run the same jobs (duplication).  
**Risk of job duplication:** High if multiple app instances run (e.g. multiple pods). Same job can run on each instance.

**Reliability assessment:** Suitable for single-instance. For multi-instance: add a persistent job store and/or distributed lock (e.g. Redis) or move to a dedicated worker (e.g. Celery).

---

# Part 8 — Caching

| Mechanism | Status | Notes |
|-----------|--------|--------|
| **Redis** | Partial | Used for WebSocket pub/sub only (websocket_manager). Config: REDIS_URL. Not used for HTTP response cache or rate limiting. |
| **In-memory cache** | Yes | `app/api/v1/market.py`: `_BENCHMARK_CACHE` dict, 15-minute TTL for benchmark responses. |
| **API response caching** | No | No cache headers or server-side cache for generic API responses. |
| **Market data caching** | Yes | Market benchmarks only (in-memory, 15 min). |
| **Rate limit protection** | No | No Redis or in-memory rate limiter. |

**Performance optimization status:** Partial. Consider Redis cache for heavy read endpoints and rate limiting.

---

# Part 9 — Frontend Feature Status

**Scope:** Frontend codebase is not in this workspace. Status is inferred from `doc/CLIENT_DELIVERED_FEATURES.md` and `doc/FRONTEND_404_ERRORS_EXPLANATION.md`.

| Feature | Pages | API endpoints used | Status | Missing pieces |
|---------|--------|---------------------|--------|----------------|
| Auth | Yes | /auth/* | Functional | — |
| Dashboard | Yes | Mixed | Partial | 404s for marketplace, portfolio/Overview, investment, assets (missing or misconfigured routes). |
| Assets | Referenced | /assets/* | UI/API intended | Frontend route/page fixes. |
| Portfolio | Referenced | /portfolio/* | UI/API intended | Frontend route (e.g. Overview). |
| Investment | Referenced | /investment/* | UI/API intended | Frontend route. |
| Trading | — | /trading/* | Backend ready | Frontend integration. |
| Marketplace | Referenced | /marketplace/* | 404 on dashboard route | Frontend route. |
| Banking | — | /banking/* | Backend ready | Frontend integration. |
| Payments | — | /payments/* | Backend ready | Frontend integration. |
| Subscriptions | — | /subscriptions/* | Backend ready | Frontend integration. |
| Documents | — | /documents/* | Backend ready | Frontend integration. |
| Support | — | /support/* | Backend ready | Frontend integration. |
| Chat | — | /chat/*, /ws/chat | Backend ready | Sendbird vs in-app chat choice. |
| Notifications | — | /notifications/* | Backend ready | Frontend integration. |
| Admin | — | /admin/* | Backend ready | Frontend integration. |
| CRM | — | /crm/* | Backend ready | Frontend integration. |
| Compliance | — | /compliance/* | Backend ready | Frontend integration. |
| Reports | — | /reports/* | Backend ready | Frontend integration. |
| Analytics | — | /analytics/* | Backend ready | Frontend integration. |

**Conclusion:** Backend APIs exist for all listed features. Frontend has 404s for some dashboard routes (marketplace, portfolio/Overview, investment, assets); “used” counts need a frontend repo scan.

---

# Part 10 — Completion Estimates and Top 10 Launch Issues

## Estimates

- **Backend completion %:** ~85%. Most modules implemented; TODOs (e.g. default payment method, cancel_at_period_end, report generation async, invite email), optional webhooks (Plaid, Persona), and scheduled banking sync remain.
- **Production readiness %:** ~65%. Gaps: no rate limiting, no Docker/CI/CD, scheduler not multi-instance safe, no structured monitoring, secrets only in env.
- **Integration completeness %:** ~80%. Stripe/Supabase/Alpaca/Polygon/PostHog/Sendbird/Persona/Plaid all used; Plaid/Persona webhooks and banking sync missing.

## Top 10 issues to fix before launch

1. **Rate limiting** — Add per-IP or per-user rate limiting (e.g. Redis) to prevent abuse and DDoS.
2. **Scheduler in multi-instance** — Use a job store (DB/Redis) and/or distributed lock so only one instance runs each job when scaling.
3. **Deployment and CI/CD** — Add Dockerfile, document run command (e.g. uvicorn workers), and a CI pipeline (test + deploy).
4. **Secrets and env** — Ensure no secrets in code; use env/vault for all keys; document production env vars.
5. **Banking sync** — Add scheduled job (or Plaid webhooks) to refresh linked account balances/transactions.
6. **Error monitoring** — Integrate Sentry (or similar) for 500s and unhandled exceptions.
7. **Stripe cancel_at_period_end** — Persist and honor cancel_at_period_end in subscription flow and DB.
8. **Default payment method** — Implement tracking and “default” payment method logic (payments module TODO).
9. **Frontend 404s** — Fix dashboard routes (marketplace, portfolio/Overview, investment, assets) and ensure they call the correct backend endpoints.
10. **Plaid/Persona webhooks (optional)** — Add webhook handlers for transaction updates and verification status to keep data in sync and improve UX.

---

*Report generated from backend codebase scan. Frontend sections rely on project documentation; frontend repo not in workspace.*
