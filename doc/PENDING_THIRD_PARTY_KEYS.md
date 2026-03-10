## Pending Third‑Party API & WebSocket Keys

This document lists **third‑party API/WebSocket related keys that are still pending or incomplete** based on the current `dotenv.md`, plus **how to obtain them** so you can update your environment.

This is focused only on **external providers** (Stripe, Plaid, chat, analytics, OAuth, etc.), not on internal config like `SECRET_KEY` or `DATABASE_URL`.

---

### 1. Stripe – Webhook Secret

- **Env vars**
  - `STRIPE_WEBHOOK_SECRET`
- **Current status**
  - In `dotenv.md` this is still a **placeholder**, not a real webhook signing secret.
- **Impact**
  - Stripe events (payment succeeded, subscription updated, etc.) **won’t be trusted** and webhook handling can fail or be insecure.
- **How to obtain**
  1. Log in to the **Stripe Dashboard**.
  2. Go to **Developers → Webhooks**.
  3. Either:
     - Select your existing webhook endpoint that points to this backend, or
     - Create a new webhook endpoint that targets your backend URL (e.g. `/api/v1/webhooks/stripe`).
  4. Once the webhook endpoint exists, open it and copy the **“Signing secret”** (`whsec_...`).
  5. Set `STRIPE_WEBHOOK_SECRET` to that value in:
     - Your local `.env`, and
     - Your production environment (Render or other).

---

### 2. PostHog – Project API Key (Frontend/Client)

- **Env vars**
  - `POSTHOG_API_KEY`
  - `POSTHOG_PROJECT_API_KEY` (**missing**)
- **Current status**
  - `POSTHOG_API_KEY` and `POSTHOG_HOST` are set in `dotenv.md`.
  - `POSTHOG_PROJECT_API_KEY` is **not present** but is referenced in the env docs.
- **Impact**
  - Analytics may be **partially configured**; some client‑side or environment‑specific tracking may not behave as expected.
- **How to obtain**
  1. Log in to **PostHog**.
  2. Go to your **Project → Settings → Project API Keys**.
  3. Copy the relevant **Project API key** (often also starts with `phc_...`).
  4. Add it as:
     - `POSTHOG_PROJECT_API_KEY` in your local `.env`.
     - The same key in your production environment.

---

### 3. Google OAuth – Login (If Google Login Is Required)

- **Env vars**
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_CLIENT_SECRET`
  - `GOOGLE_REDIRECT_URI`
- **Current status**
  - These variables are **not present** in `dotenv.md`, but are documented in `API_KEYS_AND_ENV_VARIABLES.md` as required for Google login.
- **Impact**
  - **Google OAuth login won’t work** until these are configured.
- **How to obtain**
  1. Go to **Google Cloud Console** (`console.cloud.google.com`).
  2. Create or select a project for Fullego.
  3. Enable **“Google Identity Services / OAuth 2.0”** (or the relevant OAuth consent screen).
  4. Under **APIs & Services → Credentials**, create an **OAuth 2.0 Client ID** (usually type “Web application”).
  5. Configure **Authorized redirect URIs**, for example:
     - `https://your-production-domain.com/auth/google/callback`
     - `http://localhost:8000/auth/google/callback` (for local testing, if used).
  6. After creation, copy:
     - `GOOGLE_CLIENT_ID` → the **Client ID** string.
     - `GOOGLE_CLIENT_SECRET` → the **Client secret** string.
  7. Set `GOOGLE_REDIRECT_URI` to the exact redirect URI your backend expects.
  8. Add all three vars to:
     - Local `.env`.
     - Production environment variables.

---

### 4. Cloudflare – CDN/DNS (Only If Using Cloudflare)

- **Env vars**
  - `CLOUDFLARE_API_TOKEN`
  - `CLOUDFLARE_ACCOUNT_ID`
  - `CLOUDFLARE_ZONE_ID`
- **Current status**
  - These are **optional** and not defined in `dotenv.md`. They are only needed if the project uses Cloudflare automation (DNS updates, cache purge, etc.).
- **Impact**
  - If any backend features rely on Cloudflare APIs (e.g. automated DNS or cache) they will **not work** without these values. If no such features are in use, you can ignore them.
- **How to obtain**
  1. Log in to the **Cloudflare Dashboard**.
  2. Go to your **account** page to find:
     - `CLOUDFLARE_ACCOUNT_ID`.
  3. Select the **zone** (your domain) to find:
     - `CLOUDFLARE_ZONE_ID`.
  4. Go to **My Profile → API Tokens** and create a token with the minimum required permissions (e.g. DNS edit, cache purge).
  5. Copy that token as `CLOUDFLARE_API_TOKEN`.
  6. Add these to your `.env` and production environment if Cloudflare‑based automation is actually used.

---

### 5. WebSocket / Realtime‑Related Keys

#### a. SendBird Chat (WebSocket‑based Chat)

- **Env vars**
  - `SENDBIRD_APP_ID`
  - `SENDBIRD_API_TOKEN`
- **Current status**
  - Both are **already present** in `dotenv.md`.
- **Action**
  - No additional keys are pending for SendBird; just ensure they match the correct SendBird application in production.

#### b. Redis (WebSocket Pub/Sub)

- **Env vars**
  - `REDIS_URL`
- **Current status**
  - Set to `redis://localhost:6379/0` in `dotenv.md` for local development.
- **Impact**
  - For production WebSocket scaling (pub/sub between processes), you will likely need a **hosted Redis instance** and production `REDIS_URL`, but this is infrastructure, not a third‑party API key.
- **Action**
  - When deploying at scale, provision Redis (Render, Upstash, AWS, etc.) and update `REDIS_URL` accordingly.

---

## Quick Checklist – What You Still Need to Provide

- **Stripe**
  - [ ] Real `STRIPE_WEBHOOK_SECRET` from Stripe Webhooks.
- **PostHog**
  - [ ] `POSTHOG_PROJECT_API_KEY` from PostHog Project settings (if required by your analytics setup).
- **Google OAuth (if using Google login)**
  - [ ] `GOOGLE_CLIENT_ID`
  - [ ] `GOOGLE_CLIENT_SECRET`
  - [ ] `GOOGLE_REDIRECT_URI`
- **Cloudflare (only if you use Cloudflare automation)**
  - [ ] `CLOUDFLARE_API_TOKEN`
  - [ ] `CLOUDFLARE_ACCOUNT_ID`
  - [ ] `CLOUDFLARE_ZONE_ID`

Once you have these values, add them to your **local `.env`** and your **production environment** so all third‑party integrations and WebSocket‑related features work correctly.

