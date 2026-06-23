# Fullego Backend - Environment Variables

# Application Settings
APP_NAME=Fullego Backend
APP_ENV=development
APP_DEBUG=True

# CORS - Allow localhost for development
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000

# Database (Supabase/PostgreSQL) - EXAMPLE VALUES ONLY (REPLACE IN RENDER)
SUPABASE_URL=https://your-supabase-project.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key_here
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here
SUPABASE_JWT_SECRET=your_supabase_jwt_secret_here
DATABASE_URL=postgresql+asyncpg://postgres:your_db_password@your-db-host:5432/postgres




# Authentication - EXAMPLE VALUE ONLY
SECRET_KEY=your_app_secret_key_here

# Stripe - EXAMPLE TEST KEYS ONLY (REPLACE WITH YOUR OWN IN RENDER)
STRIPE_SECRET_KEY=sk_test_your_test_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_test_publishable_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here

# Plaid - EXAMPLE VALUES ONLY
PLAID_CLIENT_ID=your_plaid_client_id_here
PLAID_SECRET_KEY=your_plaid_secret_key_here
PLAID_PUBLIC_KEY=your_plaid_public_key_here
PLAID_ENV=sandbox

# Persona (KYC Verification) - EXAMPLE VALUES ONLY
PERSONA_API_KEY=persona_sandbox_your_persona_api_key_here
PERSONA_TEMPLATE_ID=itmpl_your_persona_template_id_here
PERSONA_FILE_ACCESS_TOKEN_EXPIRY=21600

# SendBird Chat (for messaging/chat features) - EXAMPLE VALUES ONLY
SENDBIRD_APP_ID=your_sendbird_app_id_here
SENDBIRD_API_TOKEN=your_sendbird_api_token_here

# Email Service (Resend) - EXAMPLE VALUES ONLY
RESEND_API_KEY=re_your_resend_api_key_here
EMAIL_FROM_ADDRESS=onboarding@example.com
EMAIL_FROM_NAME=Fullego
EMAIL_ENABLED=true


# Others - EXAMPLE VALUES ONLY
POLYGON_API_KEY=your_polygon_api_key_here
ALPACA_OAUTH_ENABLED=true
ALPACA_OAUTH_CLIENT_ID=your_alpaca_oauth_client_id_here
ALPACA_OAUTH_CLIENT_SECRET=your_alpaca_oauth_client_secret_here
ALPACA_OAUTH_TOKEN_URL=https://authx.alpaca.markets/v1/oauth2/token
ALPACA_OAUTH_BASE_URL=https://paper-api.alpaca.markets


POSTHOG_API_KEY=your_posthog_api_key_here
POSTHOG_HOST=https://us.i.posthog.com
