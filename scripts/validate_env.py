#!/usr/bin/env python3
"""
Validate required environment variables for deployment.
Exit 0 if all required vars are set (or optional missing is acceptable), else 1.
"""
import os
import sys

REQUIRED = [
    "DATABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "PERSONA_API_KEY",
    "SENDBIRD_APP_ID",
    "SENDBIRD_API_TOKEN",
    "SECRET_KEY",
]

OPTIONAL_BUT_RECOMMENDED = [
    "REDIS_URL",
    "SENTRY_DSN",
    "PERSONA_WEBHOOK_SECRET",
]

def main():
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        print("Missing required environment variables:", file=sys.stderr)
        for k in missing:
            print(f"  - {k}", file=sys.stderr)
        sys.exit(1)
    missing_opt = [k for k in OPTIONAL_BUT_RECOMMENDED if not os.getenv(k)]
    if missing_opt:
        print("Optional (recommended) variables not set:", file=sys.stderr)
        for k in missing_opt:
            print(f"  - {k}", file=sys.stderr)
    print("Required environment variables are set.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
