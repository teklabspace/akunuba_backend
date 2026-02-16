# Missing Environment Variables in Render

Comparison between your current Render environment and required variables from `app/config.py`.

---

## ❌ CRITICAL - Missing Required Variables

These are **required** and will cause errors if not set:

### 1. **PLAID_SECRET_KEY**
```
PLAID_SECRET_KEY=your_plaid_secret_key_here
```
- **Status**: ❌ Missing
- **Impact**: Banking/linked accounts feature won't work
- **Where to get**: Plaid Dashboard → API Keys → Secret Key

### 2. **PLAID_PUBLIC_KEY**
```
PLAID_PUBLIC_KEY=your_plaid_public_key_here
```
- **Status**: ❌ Missing
- **Impact**: Plaid Link initialization will fail
- **Where to get**: Plaid Dashboard → API Keys → Public Key

### 3. **STRIPE_WEBHOOK_SECRET** (Currently has placeholder)
```
STRIPE_WEBHOOK_SECRET=whsec_your_actual_webhook_secret
```
- **Status**: ⚠️ Has placeholder value `your-stripe-webhook-secret-here`
- **Impact**: Stripe webhook verification will fail
- **Action**: Replace with actual webhook secret from Stripe Dashboard

---

## ⚠️ IMPORTANT - Recommended Variables

These are recommended for full functionality:

### 4. **RESEND_API_KEY**
```
RESEND_API_KEY=re_your_resend_api_key_here
```
- **Status**: ❌ Missing
- **Impact**: Email sending (verification, notifications) won't work
- **Where to get**: Resend Dashboard → API Keys

### 5. **EMAIL_FROM_NAME**
```
EMAIL_FROM_NAME=Akunuba
```
- **Status**: ❌ Missing
- **Impact**: Email sender name will default to "Fullego" instead of "Akunuba"
- **Action**: Simple addition

### 6. **GOOGLE_CLIENT_ID**
```
GOOGLE_CLIENT_ID=your_google_client_id_here
```
- **Status**: ❌ Missing (but you have the value)
- **Impact**: Google OAuth login won't work
- **Action**: Add this value

### 7. **GOOGLE_CLIENT_SECRET**
```
GOOGLE_CLIENT_SECRET=your_google_client_secret_here
```
- **Status**: ❌ Missing (but you have the value)
- **Impact**: Google OAuth login won't work
- **Action**: Add this value

### 8. **GOOGLE_REDIRECT_URI**
```
GOOGLE_REDIRECT_URI=https://akunuba.io/auth/google/callback
```
- **Status**: ❌ Missing
- **Impact**: Google OAuth redirect won't work correctly
- **Action**: Set to your production domain
- **Note**: Also add this URI in Google Cloud Console → OAuth 2.0 Client → Authorized redirect URIs

---

## 📋 OPTIONAL - Nice to Have

These have defaults but can be customized:

### 9. **PERSONA_REDIRECT_URI**
```
PERSONA_REDIRECT_URI=https://akunuba.io/kyc/complete
```
- **Status**: ❌ Missing (optional)
- **Impact**: After Persona KYC verification, users won't be redirected to custom URL
- **Action**: Optional, only if you want custom redirect

### 10. **POSTHOG_PROJECT_API_KEY**
```
POSTHOG_PROJECT_API_KEY=phc_your_project_api_key_here
```
- **Status**: ❌ Missing (optional)
- **Impact**: Some PostHog analytics features may not work fully
- **Where to get**: PostHog Dashboard → Project Settings → API Keys
- **Note**: Different from `POSTHOG_API_KEY` (which you already have)

### 11. **ALGORITHM**
```
ALGORITHM=HS256
```
- **Status**: ❌ Missing (has default)
- **Impact**: None (defaults to "HS256")
- **Action**: Optional, but good to set explicitly

### 12. **ACCESS_TOKEN_EXPIRE_MINUTES**
```
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```
- **Status**: ❌ Missing (has default)
- **Impact**: None (defaults to 1440 minutes = 24 hours)
- **Action**: Optional, but good to set explicitly

### 13. **APP_VERSION**
```
APP_VERSION=1.0.0
```
- **Status**: ❌ Missing (has default)
- **Impact**: None (defaults to "1.0.0")
- **Action**: Optional, but good for tracking

### 14. **API_V1_PREFIX**
```
API_V1_PREFIX=/api/v1
```
- **Status**: ❌ Missing (has default)
- **Impact**: None (defaults to "/api/v1")
- **Action**: Optional, only change if you want different API prefix

---

## ✅ Already Set in Render (Good!)

These are correctly configured:
- ✅ ALPACA_OAUTH_BASE_URL
- ✅ ALPACA_OAUTH_CLIENT_ID
- ✅ ALPACA_OAUTH_CLIENT_SECRET
- ✅ ALPACA_OAUTH_ENABLED
- ✅ ALPACA_OAUTH_TOKEN_URL
- ✅ APP_DEBUG
- ✅ APP_ENV
- ✅ APP_NAME
- ✅ CORS_ORIGINS
- ✅ DATABASE_URL
- ✅ EMAIL_ENABLED
- ✅ EMAIL_FROM_ADDRESS
- ✅ PERSONA_API_KEY
- ✅ PERSONA_FILE_ACCESS_TOKEN_EXPIRY
- ✅ PERSONA_TEMPLATE_ID
- ✅ PLAID_CLIENT_ID
- ✅ PLAID_ENV
- ✅ POLYGON_API_KEY
- ✅ POSTHOG_API_KEY
- ✅ POSTHOG_HOST
- ✅ PYTHON_VERSION
- ✅ SECRET_KEY
- ✅ SENDBIRD_API_TOKEN
- ✅ SENDBIRD_APP_ID
- ✅ STRIPE_PUBLISHABLE_KEY
- ✅ STRIPE_SECRET_KEY
- ✅ SUPABASE_ANON_KEY
- ✅ SUPABASE_JWT_SECRET
- ✅ SUPABASE_SERVICE_ROLE_KEY
- ✅ SUPABASE_URL

---

## 🚀 Quick Add List for Render

Copy and paste these into Render Dashboard → Environment tab:

### Critical (Must Add):
```
PLAID_SECRET_KEY=your_plaid_secret_key_here
PLAID_PUBLIC_KEY=your_plaid_public_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_actual_webhook_secret
```

### Important (Should Add):
```
RESEND_API_KEY=re_your_resend_api_key_here
EMAIL_FROM_NAME=Akunuba
GOOGLE_CLIENT_ID=your_google_client_id_here
GOOGLE_CLIENT_SECRET=your_google_client_secret_here
GOOGLE_REDIRECT_URI=https://akunuba.io/auth/google/callback
```

### Optional (Nice to Have):
```
PERSONA_REDIRECT_URI=https://akunuba.io/kyc/complete
POSTHOG_PROJECT_API_KEY=phc_your_project_api_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
APP_VERSION=1.0.0
```

---

## 📊 Summary

**Total Missing:**
- **Critical**: 3 variables (2 missing + 1 placeholder)
- **Important**: 5 variables
- **Optional**: 5 variables

**Priority Order:**
1. 🔴 **Fix STRIPE_WEBHOOK_SECRET** (replace placeholder)
2. 🔴 **Add PLAID_SECRET_KEY** (for banking feature)
3. 🔴 **Add PLAID_PUBLIC_KEY** (for banking feature)
4. 🟡 **Add RESEND_API_KEY** (for email functionality)
5. 🟡 **Add Google OAuth variables** (3 variables)
6. 🟡 **Add EMAIL_FROM_NAME**
7. 🟢 **Add optional variables** (if needed)

---

**Last Updated**: 2026-02-11
