# Deploying Akunuba from One Monorepo

Akunuba uses one Git repository but three independently managed runtime platforms:

- `apps/web` -> Cloudflare Pages/Workers
- `apps/api` -> Render
- PostgreSQL and Storage -> Supabase

The Git repository is shared. The deployments are intentionally separate.

## Required repository layout

```text
akunuba-platform/
├── apps/
│   ├── web/                 # Next.js frontend
│   └── api/                 # FastAPI backend
├── packages/
├── infrastructure/
├── package.json
├── pnpm-workspace.yaml
├── turbo.json
└── render.yaml
```

## 1. Import the existing applications

Move the current frontend repository into `apps/web/` while preserving its Git history where practical.

Move the current backend into `apps/api/`:

- `app/`
- `alembic/`
- `alembic.ini`
- `requirements.txt`
- `run.py`
- backend Docker and deployment files

Do not delete the existing Cloudflare or Render services until both monorepo deployments pass production smoke tests.

## 2. Cloudflare configuration

Connect the monorepo repository to the existing Cloudflare project and use:

| Setting | Value |
|---|---|
| Production branch | `main` |
| Root directory | `apps/web` |
| Build command | `npm ci && npm run pages:build` |
| Build output directory | `out` |
| Node version | `20` or the version declared by the frontend |

If the frontend switches to pnpm after migration, use:

```bash
corepack enable && pnpm install --frozen-lockfile && pnpm --filter @akunuba/web pages:build
```

Configure build watch paths so backend-only changes do not rebuild Cloudflare:

```text
apps/web/**
packages/ui/**
packages/sdk/**
packages/types/**
packages/config/**
pnpm-lock.yaml
package.json
pnpm-workspace.yaml
turbo.json
```

Required frontend environment variables should include the public API base URL and public Supabase values only:

```text
NEXT_PUBLIC_API_BASE_URL=https://api.akunuba.com
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=...
NEXT_PUBLIC_PERSONA_TEMPLATE_ID=...
```

Never expose the Supabase service-role key, database password, Stripe secret key, Persona API key or backend JWT secret to Cloudflare frontend variables.

## 3. Render configuration

The Render service should use `apps/api` as its root directory. Build and start commands then run relative to that directory.

Recommended Blueprint service:

```yaml
services:
  - type: web
    name: akunuba-api
    runtime: python
    rootDir: apps/api
    region: oregon
    plan: starter
    buildCommand: pip install --upgrade pip && pip install -r requirements.txt
    preDeployCommand: alembic upgrade head
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    autoDeploy: true
    buildFilter:
      paths:
        - apps/api/**
        - packages/python/**
        - render.yaml
```

Set secrets in Render, not in Git:

```text
DATABASE_URL
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_JWT_SECRET
SECRET_KEY
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
PLAID_CLIENT_ID
PLAID_SECRET_KEY
PERSONA_API_KEY
ANTHROPIC_API_KEY
REDIS_URL
SENTRY_DSN
```

Set CORS explicitly:

```text
CORS_ORIGINS=https://akunuba.com,https://www.akunuba.com,https://<cloudflare-project>.pages.dev
```

## 4. Supabase configuration

Supabase is not deployed from the monorepo in the same way as the web and API applications. It remains a managed platform referenced by environment variables.

Use the pooled connection string for normal application traffic when appropriate and a direct database connection for migrations if the migration tooling requires it. Keep schema migrations in `apps/api/alembic/` and run them from Render's pre-deploy command.

Recommended separation:

```text
DATABASE_URL=<runtime pooled connection>
MIGRATION_DATABASE_URL=<direct migration connection, when needed>
```

The application must never place the database password or service-role key in frontend code.

## 5. DNS and request flow

```text
User
  -> akunuba.com / app.akunuba.com (Cloudflare frontend)
  -> api.akunuba.com (Render FastAPI service)
  -> Supabase Postgres and Storage
```

Recommended domains:

- `akunuba.com` or `app.akunuba.com` -> Cloudflare
- `api.akunuba.com` -> Render

Configure the frontend API base URL as `https://api.akunuba.com` and add the Cloudflare production and preview origins to the backend CORS allowlist.

## 6. Safe cutover

1. Merge the frontend and backend into their final `apps/` directories.
2. Validate local builds from the monorepo root.
3. Create preview deployments on Cloudflare and Render.
4. Run database migrations against a staging Supabase project first.
5. Test login, KYC, asset uploads, appraisals, payments, WebSockets and webhook callbacks.
6. Connect production domains only after the smoke tests pass.
7. Keep the old services available for rollback until production is stable.

## Deployment ownership

A GitHub commit can prepare all configuration, but deployment activation requires authenticated access to the Cloudflare, Render and Supabase projects. Account secrets must be entered directly into those platforms and must not be committed to GitHub.
