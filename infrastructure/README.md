# Infrastructure

Infrastructure code should be organized by platform and kept separate from application source:

- `docker/` — local development and reusable container assets
- `terraform/` — infrastructure as code
- `cloudflare/` — Pages, Workers, DNS and edge configuration
- `render/` — backend service and worker deployment configuration

Production credentials must be stored in the target platform's secret manager and never committed to the repository.
