# Fullego Backend

FastAPI backend for the Fullego / Akunuba wealth‑management platform. It powers
asset tracking, AI and concierge (human) appraisals, portfolios, a private
marketplace, payments/subscriptions, KYC/KYB compliance, and real‑time
notifications.

- **Framework:** FastAPI (ASGI, async SQLAlchemy 2.x)
- **Runtime:** Python 3.11
- **Database:** PostgreSQL (Supabase) with Alembic migrations
- **Auth:** JWT access/refresh tokens + optional TOTP 2FA
- **Realtime:** WebSockets (chat + notifications) with optional Redis pub/sub fan‑out

---

## Features

- **Assets** — CRUD with categories, photos, documents, valuations, ownership,
  and human‑readable codes (`AK‑01`, `AK‑02`, …). Investors see only their own
  assets; admins see all and can search by code.
- **Appraisals** — instant **AI** valuations (Anthropic) and **concierge**
  (human) appraisals with a comment/document thread, document requests, and a
  one‑open‑human‑appraisal‑per‑asset rule.
- **Notifications** — persisted bell notifications + live WebSocket push for
  appraisal events (creation and messages), user‑addressable across roles.
- **Portfolios & Trading** — holdings, watchlists, market data, brokerage
  integration (Alpaca).
- **Marketplace** — listings, offers, and escrow transactions.
- **Payments & Subscriptions** — Stripe billing, plans, and usage limits.
- **Banking** — account linking via Plaid.
- **Compliance** — KYC (individuals) and KYB (businesses), admin review flows.
- **Platform** — accounts, users/roles (investor / advisor / admin), CRM,
  entities, support tickets, reports, documents/files (Supabase Storage),
  analytics (PostHog), and an admin console.

## Tech stack

| Area | Tool |
|------|------|
| Web framework | FastAPI + Uvicorn |
| ORM / migrations | SQLAlchemy 2 (async, asyncpg) + Alembic |
| Database / storage / auth infra | Supabase (Postgres + Storage) |
| Auth | python‑jose (JWT), passlib/bcrypt, pyotp (2FA) |
| Payments / banking | Stripe, Plaid |
| Brokerage / market data | Alpaca |
| AI | Anthropic (Claude) |
| Realtime / caching | Redis (pub/sub, rate limiting) |
| Email | Jinja2 templates + SMTP |
| Observability | Sentry, PostHog, JSON logging |

---

## Getting started

### Prerequisites
- Python 3.11
- A PostgreSQL database (Supabase project recommended)
- (Optional) Redis for multi‑worker WebSocket fan‑out and rate limiting

### Setup
```bash
# 1. Create a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env            # then fill in the values (see below)

# 4. Run database migrations
alembic upgrade head

# 5. Start the dev server
python run.py                   # http://localhost:8000
```

API docs are served at `http://localhost:8000/docs` (Swagger) and `/redoc`.

### Environment variables
Configuration is loaded from `.env` via `app/config.py`. Common values:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Postgres connection string (asyncpg) |
| `SECRET_KEY` | JWT signing secret |
| `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY` | Supabase project + storage |
| `REDIS_URL` | Redis connection (enables cross‑worker WS fan‑out) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Stripe billing |
| `PLAID_CLIENT_ID`, `PLAID_SECRET` | Plaid banking |
| `ANTHROPIC_API_KEY` | AI appraisals/reviews |
| `SENTRY_DSN`, `POSTHOG_API_KEY` | Observability (optional) |

> Never commit `.env`. It is git‑ignored.

---

## Project structure

```
app/
  main.py            # FastAPI app, router registration, lifespan, WS routes
  config.py          # Settings (env-driven)
  database.py        # Async engine + session
  api/
    deps.py          # Shared dependencies (auth, account, plan)
    v1/              # Route modules (assets, concierge, notifications, …)
  core/              # Security, permissions, websocket manager, exceptions
  models/            # SQLAlchemy models
  schemas/           # Pydantic request/response models
  services/          # Business logic (AI appraisal, notifications, email, …)
  integrations/      # Stripe, Supabase, etc.
alembic/             # Migration environment + versions/
```

## Database migrations

```bash
alembic upgrade head                      # apply all migrations
alembic revision -m "describe change"     # create a new migration
alembic downgrade -1                       # roll back one
```

## Realtime / WebSockets

- **Notifications:** `wss://<host>/api/v1/ws/notifications?token=<JWT>` — pushes
  `appraisal_created` and `appraisal_message` events; auth via the `token` query
  param (closed with code `4401` if invalid).
- **Chat:** `wss://<host>/ws/chat?token=<JWT>`.

Delivery is per‑user. With `REDIS_URL` configured, events fan out across all
workers/replicas; without Redis it runs in single‑worker mode.

## Deployment

The service ships with a `Dockerfile` and `docker-compose.yml`, plus
`render.yaml` for Render. It also runs on Railway (WebSockets supported on the
same host/port — no extra config). Run `alembic upgrade head` against the target
database on deploy.

```bash
docker compose up --build
```

## API reference

- Interactive: `/docs` (Swagger UI) and `/redoc`.
- A Postman collection is included: `Fullego_Backend_API.postman_collection.json`.
