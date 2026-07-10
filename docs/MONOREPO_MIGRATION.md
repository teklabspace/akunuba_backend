# Akunuba Monorepo Migration

## Target structure

```text
akunuba-platform/
├── apps/
│   ├── web/                 # Next.js customer and admin application
│   ├── api/                 # Existing FastAPI backend
│   └── mobile/              # Future mobile application
├── packages/
│   ├── ui/                  # Shared UI components and design tokens
│   ├── config/              # Shared linting, TypeScript and formatting config
│   ├── sdk/                 # Generated/typed API client
│   └── types/               # Shared TypeScript contracts
├── infrastructure/
│   ├── docker/
│   ├── terraform/
│   └── cloudflare/
├── docs/
├── .github/workflows/
├── package.json
├── pnpm-workspace.yaml
└── turbo.json
```

## Migration strategy

### Phase 1 — Foundation

- Add pnpm workspaces and Turborepo configuration.
- Add the target directories and ownership boundaries.
- Keep the existing FastAPI backend at the repository root so current Render deployments continue to work.

### Phase 2 — Move the backend

Move the current backend files into `apps/api/`:

- `app/`
- `alembic/`
- `alembic.ini`
- `requirements.txt`
- `run.py`
- `Dockerfile`
- `docker-compose.yml`
- `render.yaml`
- backend Postman collections and backend-specific scripts

Update deployment commands, Docker build context, Alembic paths, CI paths and documentation in the same pull request. Preserve environment-variable names to avoid breaking existing deployments.

### Phase 3 — Add the web application

Add the Akunuba Next.js frontend under `apps/web/`. The frontend should consume the backend through `packages/sdk`, rather than duplicating API request logic in pages and components.

### Phase 4 — Shared packages and platform automation

- Extract UI components and design tokens into `packages/ui`.
- Add an OpenAPI-generated client under `packages/sdk`.
- Add shared TypeScript, ESLint and formatting configuration.
- Add path-aware CI so frontend-only changes do not rebuild the Python backend.
- Add dependency, secret, SAST and container scanning.

## Deployment model

- `apps/web`: Cloudflare Pages/Workers.
- `apps/api`: Render or Railway.
- PostgreSQL and object storage: Supabase.
- Redis: managed Redis service.

Each deployable application must have its own environment configuration, health check and release process. Root-level commands should orchestrate local development and CI but should not couple production deployments.

## Compatibility rule

The repository should not move the production backend until Render and Docker configuration have been tested from `apps/api`. Phase 1 therefore introduces the monorepo control plane without changing the current backend runtime path.
