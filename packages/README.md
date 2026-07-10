# Shared Packages

Planned shared workspaces:

- `ui` — reusable components and design tokens
- `sdk` — typed client generated from the FastAPI OpenAPI specification
- `types` — shared TypeScript contracts
- `config` — shared linting, formatting and TypeScript configuration

Packages should remain independently testable and must not contain application-specific secrets or deployment configuration.
