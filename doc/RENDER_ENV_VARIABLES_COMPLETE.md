# Render Environment Variables - Complete Setup

This document contains all environment variables formatted for Render Dashboard.

**How to use:**
1. Copy each variable and its value
2. Go to Render Dashboard → Your Service → Environment tab
3. Add each variable one by one
4. Click "Save Changes" when done

---

## 🔐 Authentication & Security

```
SECRET_KEY=your_app_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

---

## 📱 Application Configuration

```
APP_NAME=Akunuba
APP_ENV=production
APP_DEBUG=false
APP_VERSION=1.0.0
API_V1_PREFIX=/api/v1
HOST=0.0.0.0
PORT=8000
```

---

## 🌐 CORS Configuration

```
CORS_ORIGINS=https://akunuba.io/,https://www.akunuba.io/
```

---

## 🗄️ Database Configuration

```
DATABASE_URL=postgresql+asyncpg://postgres:your_db_password@your-db-host:5432/postgres
```

---

## ☁️ Supabase Configuration

```
SUPABASE_URL=https://your-supabase-project.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key_here
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here
SUPABASE_JWT_SECRET=your_supabase_jwt_secret_here
```

---

## 💳 Stripe Configuration

```
STRIPE_SECRET_KEY=sk_test_your_test_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_test_publishable_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_actual_webhook_secret_here
```

**⚠️ IMPORTANT:** Replace `STRIPE_WEBHOOK_SECRET` with your actual webhook secret from Stripe Dashboard:
1. Go to Stripe Dashboard → Developers → Webhooks
2. Create webhook endpoint: `https://your-render-url.onrender.com/api/v1/payments/webhook`
3. Copy the "Signing secret" (starts with `whsec_`)
4. Replace the value above

---

## 🏦 Plaid Configuration (Banking/Linked Accounts)

```
PLAID_CLIENT_ID=your_plaid_client_id_here
PLAID_ENV=sandbox
PLAID_SECRET_KEY=your_plaid_secret_key_here
PLAID_PUBLIC_KEY=your_plaid_public_key_here
```

**⚠️ IMPORTANT:** Replace with your actual Plaid keys:
1. Go to Plaid Dashboard → API Keys
2. Copy "Secret Key" → Set as `PLAID_SECRET_KEY`
3. Copy "Public Key" → Set as `PLAID_PUBLIC_KEY`

---

## 👤 Persona Configuration (KYC/KYB)

```
PERSONA_API_KEY=persona_sandbox_your_persona_api_key_here
PERSONA_TEMPLATE_ID=itmpl_your_persona_template_id_here
PERSONA_FILE_ACCESS_TOKEN_EXPIRY=21600
PERSONA_REDIRECT_URI=https://akunuba.io/kyc/complete
```

---

## 📧 Email Configuration (Resend)

```
RESEND_API_KEY=your_resend_api_key_here
EMAIL_FROM_ADDRESS=anaspirzadaiub@gmail.com
EMAIL_FROM_NAME=Akunuba
EMAIL_ENABLED=true
```

**⚠️ IMPORTANT:** 
- Get `RESEND_API_KEY` from Resend Dashboard → API Keys
- For production, verify your domain (`akunuba.io`) in Resend to send from `@akunuba.io` addresses

---

## 🔐 Google OAuth Configuration

```
GOOGLE_CLIENT_ID=your_google_client_id_here
GOOGLE_CLIENT_SECRET=your_google_client_secret_here
GOOGLE_REDIRECT_URI=https://akunuba.io/auth/google/callback
```

**Note:** Make sure to add the redirect URI in Google Cloud Console:
1. Go to Google Cloud Console → APIs & Services → Credentials
2. Edit your OAuth 2.0 Client ID
3. Add authorized redirect URI: `https://akunuba.io/auth/google/callback`

---

## 📊 Trading - Alpaca Configuration

```
ALPACA_OAUTH_ENABLED=true
ALPACA_OAUTH_CLIENT_ID=your_alpaca_oauth_client_id_here
ALPACA_OAUTH_CLIENT_SECRET=your_alpaca_oauth_client_secret_here
ALPACA_OAUTH_TOKEN_URL=https://authx.alpaca.markets/v1/oauth2/token
ALPACA_OAUTH_BASE_URL=https://paper-api.alpaca.markets
```

---

## 📈 Market Data - Polygon Configuration

```
POLYGON_API_KEY=your_polygon_api_key_here
```

---

## 📊 Analytics - PostHog Configuration

```
POSTHOG_API_KEY=your_posthog_api_key_here
POSTHOG_HOST=https://us.i.posthog.com
POSTHOG_PROJECT_API_KEY=your_posthog_project_api_key_here
```

**Optional:** Get `POSTHOG_PROJECT_API_KEY` from PostHog Dashboard → Project Settings → API Keys

---

## 💬 Chat - Sendbird Configuration

```
SENDBIRD_APP_ID=9EB0BB82-81BC-445A-BCC6-55C944ECDD3C
SENDBIRD_API_TOKEN=f080d9a3344aa83f33a847eeb7fece9b79ce7e24
```

---

## ☁️ Cloudflare Configuration (Optional - if using CDN/DNS)

```
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_ZONE_ID=
```

**Optional:** Only add if you're using Cloudflare for DNS/CDN

---

## 🐍 Python Version

```
PYTHON_VERSION=3.11.9
```

---

## 📋 Complete Checklist

### ✅ Already Set (from your current Render config)
- [x] APP_NAME
- [x] APP_ENV
- [x] APP_DEBUG
- [x] CORS_ORIGINS
- [x] DATABASE_URL
- [x] SUPABASE_URL
- [x] SUPABASE_ANON_KEY
- [x] SUPABASE_SERVICE_ROLE_KEY
- [x] SUPABASE_JWT_SECRET
- [x] STRIPE_SECRET_KEY
- [x] STRIPE_PUBLISHABLE_KEY
- [x] PLAID_CLIENT_ID
- [x] PLAID_ENV
- [x] PERSONA_API_KEY
- [x] PERSONA_TEMPLATE_ID
- [x] PERSONA_FILE_ACCESS_TOKEN_EXPIRY
- [x] POLYGON_API_KEY
- [x] POSTHOG_API_KEY
- [x] POSTHOG_HOST
- [x] SENDBIRD_APP_ID
- [x] SENDBIRD_API_TOKEN
- [x] SECRET_KEY
- [x] ALPACA_OAUTH_* (all 5 variables)
- [x] EMAIL_ENABLED
- [x] EMAIL_FROM_ADDRESS

### ⚠️ Need to Add/Update
- [ ] **STRIPE_WEBHOOK_SECRET** - Replace placeholder with actual webhook secret
- [ ] **PLAID_SECRET_KEY** - Get from Plaid Dashboard
- [ ] **PLAID_PUBLIC_KEY** - Get from Plaid Dashboard
- [ ] **RESEND_API_KEY** - Get from Resend Dashboard
- [ ] **EMAIL_FROM_NAME** - Set to "Akunuba"
- [ ] **GOOGLE_CLIENT_ID** - ✅ Provided above
- [ ] **GOOGLE_CLIENT_SECRET** - ✅ Provided above
- [ ] **GOOGLE_REDIRECT_URI** - Set to production URL
- [ ] **PERSONA_REDIRECT_URI** - Set to production URL (optional)
- [ ] **POSTHOG_PROJECT_API_KEY** - Optional, get from PostHog

---

## 🚀 Quick Setup Instructions

1. **Copy each variable above** (one at a time or in bulk)
2. **Go to Render Dashboard** → Your Service → **Environment** tab
3. **Click "Add Environment Variable"**
4. **Paste the variable name** in the "Key" field
5. **Paste the value** in the "Value" field
6. **Click "Save Changes"** when done
7. **Render will automatically redeploy** your service

---

## ⚠️ Security Notes

- ✅ Never commit these values to git (they're in `.gitignore`)
- ✅ All secrets are stored securely in Render's environment variables
- ✅ Use different keys for production vs development
- ✅ Rotate keys regularly for security
- ✅ Use Plaid production keys when going live (currently using sandbox)

---

## 📝 Notes

1. **Stripe Webhook**: You must create the webhook endpoint in Stripe Dashboard first, then copy the signing secret.

2. **Plaid Keys**: Currently using sandbox environment. When going to production:
   - Change `PLAID_ENV=production`
   - Use production keys from Plaid Dashboard

3. **Google OAuth**: Make sure the redirect URI is added in Google Cloud Console:
   - `https://akunuba.io/auth/google/callback`

4. **Email**: For production, verify your domain in Resend to send from `@akunuba.io` addresses.

5. **Python Version**: Render will use the version specified in `runtime.txt` or `PYTHON_VERSION` env var.

---

**Last Updated**: 2026-02-11  
**Status**: Ready for Render deployment
