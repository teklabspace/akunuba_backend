# 🔑 API Keys & Environment Variables - Complete Guide

This document lists **all API keys and environment variables** that can affect your application's results and functionality.

---

## 🚨 CRITICAL - Required (Will Cause Errors if Missing)

These variables **MUST** be set or the application will fail to start or certain features will break:

### 1. **Database & Supabase** (Required)
```env
DATABASE_URL=postgresql+asyncpg://postgres:password@host:5432/postgres
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_JWT_SECRET=your_jwt_secret
```
- **Impact**: ❌ App won't start without these
- **Where to get**: Supabase Dashboard → Project Settings → API

### 2. **Authentication** (Required)
```env
SECRET_KEY=your_secret_key_here
```
- **Impact**: ❌ JWT token generation will fail
- **Generate**: Use a secure random string (32+ characters)

### 3. **Stripe Payment Processing** (Required)
```env
STRIPE_SECRET_KEY=sk_test_... or sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_test_... or pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```
- **Impact**: ❌ Payment processing will fail
- **Where to get**: Stripe Dashboard → Developers → API Keys / Webhooks
- **⚠️ Note**: `STRIPE_WEBHOOK_SECRET` must be the actual webhook secret, not a placeholder

### 4. **Persona KYC Verification** (Required)
```env
PERSONA_API_KEY=persona_sandbox_... or persona_live_...
PERSONA_TEMPLATE_ID=itmpl_...
```
- **Impact**: ❌ KYC/identity verification features won't work
- **Where to get**: Persona Dashboard → API Keys / Templates

### 5. **SendBird Chat** (Required)
```env
SENDBIRD_APP_ID=your_app_id
SENDBIRD_API_TOKEN=your_api_token
```
- **Impact**: ❌ Chat/messaging features won't work
- **Where to get**: SendBird Dashboard → Settings → Application

---

## ⚠️ IMPORTANT - Feature-Specific (Will Break Features if Missing)

These won't crash the app, but specific features won't work:

### 6. **Plaid Banking Integration** (For Banking Features)
```env
PLAID_CLIENT_ID=692b0eb3111b5200219bd3b4  # Your Plaid Client ID
PLAID_SECRET_KEY=49f680c66cc54b7aa43c2ab53a8c83  # Your Plaid Secret Key (sandbox)
PLAID_ENV=sandbox  # or 'production'
PLAID_PUBLIC_KEY=  # Optional - not used in backend code
```
- **Required for Backend**: `PLAID_CLIENT_ID` and `PLAID_SECRET_KEY` are required
- **Optional**: `PLAID_PUBLIC_KEY` is not used in backend code (only needed if frontend initializes Plaid Link directly)
- **Impact**: ⚠️ Banking/linked accounts feature won't work without `PLAID_SECRET_KEY`
- **Where to get**: Plaid Dashboard → Team Settings → Keys
- **How it works**: Backend creates link tokens server-side via `/api/v1/banking/link-token` endpoint, so frontend doesn't need public key
- **Status**: `PLAID_CLIENT_ID` is set, but `PLAID_SECRET_KEY` needs to be updated with your sandbox secret

### 7. **Email Service (Resend)** (For Email Functionality)
```env
RESEND_API_KEY=re_...
EMAIL_FROM_ADDRESS=onboarding@yourdomain.com
EMAIL_FROM_NAME=Your App Name
EMAIL_ENABLED=true
```
- **Impact**: ⚠️ Email sending (verification, notifications) won't work
- **Where to get**: Resend Dashboard → API Keys
- **Status**: Currently missing in your setup

### 8. **Google OAuth** (For Google Login)
```env
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=https://yourdomain.com/auth/google/callback
```
- **Impact**: ⚠️ Google OAuth login won't work
- **Where to get**: Google Cloud Console → APIs & Services → Credentials
- **Status**: Currently missing in your setup

### 9. **Polygon Market Data** (For Market Data Features)
```env
POLYGON_API_KEY=your_polygon_api_key
```
- **Impact**: ⚠️ Market data/stock quotes won't work
- **Where to get**: Polygon.io Dashboard → API Keys
- **Status**: ✅ Already set

### 10. **Alpaca Trading** (For Trading Features)
```env
ALPACA_OAUTH_ENABLED=true
ALPACA_OAUTH_CLIENT_ID=your_client_id
ALPACA_OAUTH_CLIENT_SECRET=your_client_secret
ALPACA_OAUTH_TOKEN_URL=https://authx.alpaca.markets/v1/oauth2/token
ALPACA_OAUTH_BASE_URL=https://paper-api.alpaca.markets  # or https://api.alpaca.markets
```
- **Impact**: ⚠️ Trading features won't work
- **Where to get**: Alpaca Dashboard → OAuth Apps
- **Status**: ✅ Already set

### 11. **PostHog Analytics** (For Analytics)
```env
POSTHOG_API_KEY=phc_...
POSTHOG_PROJECT_API_KEY=phc_...
POSTHOG_HOST=https://us.i.posthog.com
```
- **Impact**: ⚠️ Analytics tracking may be incomplete
- **Where to get**: PostHog Dashboard → Project Settings → API Keys
- **Status**: ✅ Partially set (missing `POSTHOG_PROJECT_API_KEY`)

---

## 📋 OPTIONAL - Nice to Have

These have defaults and won't break anything:

```env
# JWT Settings (has defaults)
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# App Settings (has defaults)
APP_VERSION=1.0.0
API_V1_PREFIX=/api/v1
HOST=0.0.0.0
PORT=8000

# Persona Settings (has defaults)
PERSONA_FILE_ACCESS_TOKEN_EXPIRY=21600
PERSONA_REDIRECT_URI=https://yourdomain.com/kyc/complete

# Cloudflare (only if using CDN/DNS)
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_ZONE_ID=
```

---

## 🔍 How to Check What's Missing

### For Local Development (.env file):
1. Check if `.env` file exists in `D:\Fiver\Fullego_Backend\`
2. Compare with `env.md` (template file)
3. Make sure all required variables are set

### For Production (Render):
1. Check `doc/RENDER_MISSING_VARIABLES.md` for missing variables
2. Go to Render Dashboard → Your Service → Environment tab
3. Compare with the list above

---

## 🎯 Quick Checklist

### ✅ Must Have (App Won't Start Without):
- [ ] `DATABASE_URL`
- [ ] `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`
- [ ] `SECRET_KEY`
- [ ] `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`
- [ ] `PERSONA_API_KEY`, `PERSONA_TEMPLATE_ID`
- [ ] `SENDBIRD_APP_ID`, `SENDBIRD_API_TOKEN`

### ⚠️ Should Have (Features Won't Work Without):
- [ ] `PLAID_CLIENT_ID`, `PLAID_SECRET_KEY` (for banking - both required)
- [ ] `PLAID_PUBLIC_KEY` (optional - only if frontend initializes Plaid Link directly)
- [ ] `RESEND_API_KEY` (for emails)
- [ ] `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (for Google login)
- [ ] `POLYGON_API_KEY` (for market data)
- [ ] `ALPACA_OAUTH_*` (for trading)

---

## 🚨 Common Issues & Solutions

### Issue: "Field required" or "ValidationError"
**Cause**: Missing required environment variable
**Solution**: Check `.env` file and ensure all required variables are set

### Issue: Feature not working (e.g., banking, email)
**Cause**: Missing feature-specific API key
**Solution**: Check the feature-specific section above and add the missing keys

### Issue: Stripe webhooks failing
**Cause**: `STRIPE_WEBHOOK_SECRET` has placeholder value
**Solution**: Get actual webhook secret from Stripe Dashboard → Webhooks → Signing secret

### Issue: Plaid Link not initializing
**Cause**: Missing `PLAID_SECRET_KEY` (required) or `PLAID_CLIENT_ID` (required)
**Solution**: 
- Add `PLAID_CLIENT_ID` and `PLAID_SECRET_KEY` from Plaid Dashboard
- `PLAID_PUBLIC_KEY` is optional - only needed if frontend initializes Plaid Link directly (backend creates link tokens server-side)
- Your keys: `PLAID_CLIENT_ID=692b0eb3111b5200219bd3b4`, `PLAID_SECRET_KEY=49f680c66cc54b7aa43c2ab53a8c83`

---

## 📚 Related Documentation

- `env.md` - Template for local `.env` file
- `doc/RENDER_ENV_VARIABLES.md` - Render-specific checklist
- `doc/RENDER_ENV_VARIABLES_COMPLETE.md` - Complete Render setup
- `doc/RENDER_MISSING_VARIABLES.md` - Missing variables analysis
- `app/config.py` - Source of truth for all configuration

---

**Last Updated**: 2026-02-11
