# Render Environment Variables Checklist

## ✅ Currently Set (Good!)

These are already configured in your Render environment:

- `ALPACA_OAUTH_BASE_URL`
- `ALPACA_OAUTH_CLIENT_ID`
- `ALPACA_OAUTH_CLIENT_SECRET`
- `ALPACA_OAUTH_ENABLED`
- `ALPACA_OAUTH_TOKEN_URL`
- `APP_DEBUG`
- `APP_ENV`
- `APP_NAME`
- `CORS_ORIGINS`
- `DATABASE_URL`
- `EMAIL_ENABLED`
- `EMAIL_FROM_ADDRESS`
- `PERSONA_API_KEY`
- `PERSONA_FILE_ACCESS_TOKEN_EXPIRY`
- `PERSONA_TEMPLATE_ID`
- `PLAID_CLIENT_ID`
- `PLAID_ENV`
- `POLYGON_API_KEY`
- `POSTHOG_API_KEY`
- `POSTHOG_HOST`
- `PYTHON_VERSION`
- `SECRET_KEY`
- `SENDBIRD_API_TOKEN`
- `SENDBIRD_APP_ID`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_SECRET_KEY`
- `SUPABASE_ANON_KEY`
- `SUPABASE_JWT_SECRET`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_URL`

---

## ⚠️ CRITICAL - Missing Required Variables

These are **required** and will cause errors if not set:

### 1. **PLAID_SECRET_KEY** (Required for Banking/Linked Accounts)
```
PLAID_SECRET_KEY=your_plaid_secret_key_here
```
- **Where to get it**: Plaid Dashboard → API Keys → Secret Key
- **Impact**: Banking/linked accounts feature won't work without this

### 2. **PLAID_PUBLIC_KEY** (Required for Banking/Linked Accounts)
```
PLAID_PUBLIC_KEY=your_plaid_public_key_here
```
- **Where to get it**: Plaid Dashboard → API Keys → Public Key
- **Impact**: Plaid Link initialization will fail without this

### 3. **STRIPE_WEBHOOK_SECRET** (Required for Stripe Webhooks)
```
STRIPE_WEBHOOK_SECRET=whsec_your_actual_webhook_secret_here
```
- **Current value**: `your-stripe-webhook-secret-here` (placeholder - needs real value)
- **Where to get it**: Stripe Dashboard → Developers → Webhooks → Your webhook → Signing secret
- **Impact**: Stripe webhook verification will fail, payment events won't be processed

---

## 📧 RECOMMENDED - Email Service

### **RESEND_API_KEY** (Recommended for Email Functionality)
```
RESEND_API_KEY=re_your_resend_api_key_here
```
- **Where to get it**: Resend Dashboard → API Keys
- **Impact**: Email sending (verification, notifications, etc.) won't work
- **Note**: You're using `EMAIL_FROM_ADDRESS=anaspirzadaiub@gmail.com`, but Resend requires verified domains for production

### **EMAIL_FROM_NAME** (Optional but Recommended)
```
EMAIL_FROM_NAME=Akunuba
```
- **Default**: "Fullego" (but should match your app name)
- **Impact**: Email sender name in user's inbox

---

## 🔍 OPTIONAL - Analytics & Monitoring

### **POSTHOG_PROJECT_API_KEY** (Optional - for PostHog Analytics)
```
POSTHOG_PROJECT_API_KEY=phc_your_project_api_key_here
```
- **Where to get it**: PostHog Dashboard → Project Settings → API Keys
- **Impact**: Some PostHog features may not work fully
- **Note**: You already have `POSTHOG_API_KEY`, but `POSTHOG_PROJECT_API_KEY` is separate

---

## 🔐 OPTIONAL - OAuth & Authentication

### **GOOGLE_CLIENT_ID** (Optional - for Google OAuth)
```
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
```

### **GOOGLE_CLIENT_SECRET** (Optional - for Google OAuth)
```
GOOGLE_CLIENT_SECRET=your_google_client_secret
```

### **GOOGLE_REDIRECT_URI** (Optional - for Google OAuth)
```
GOOGLE_REDIRECT_URI=https://akunuba.io/auth/google/callback
```
- **Note**: Update from `localhost:3000` to your production domain
- **Where to get it**: Google Cloud Console → APIs & Services → Credentials

---

## ☁️ OPTIONAL - Cloudflare (if using CDN/DNS)

### **CLOUDFLARE_API_TOKEN** (Optional)
```
CLOUDFLARE_API_TOKEN=your_cloudflare_api_token
```

### **CLOUDFLARE_ACCOUNT_ID** (Optional)
```
CLOUDFLARE_ACCOUNT_ID=your_cloudflare_account_id
```

### **CLOUDFLARE_ZONE_ID** (Optional)
```
CLOUDFLARE_ZONE_ID=your_cloudflare_zone_id
```

---

## 🔄 OPTIONAL - Legacy Alpaca (if not using OAuth)

If you're using Alpaca OAuth (which you are), these are not needed:

- `ALPACA_API_KEY_ID` (not needed - using OAuth)
- `ALPACA_SECRET_KEY` (not needed - using OAuth)
- `ALPACA_BASE_URL` (not needed - using OAuth)

---

## 📝 OPTIONAL - Persona Redirect URI

### **PERSONA_REDIRECT_URI** (Optional - for KYC completion redirect)
```
PERSONA_REDIRECT_URI=https://akunuba.io/kyc/complete
```
- **Impact**: After Persona KYC verification, users will be redirected here
- **Note**: Only needed if you want custom redirect after KYC completion

---

## 📋 Summary: What to Add to Render

### **MUST ADD (Critical):**
1. `PLAID_SECRET_KEY` - Get from Plaid Dashboard
2. `PLAID_PUBLIC_KEY` - Get from Plaid Dashboard  
3. `STRIPE_WEBHOOK_SECRET` - Get from Stripe Dashboard (replace placeholder)

### **SHOULD ADD (Recommended):**
4. `RESEND_API_KEY` - Get from Resend Dashboard (for email functionality)
5. `EMAIL_FROM_NAME=Akunuba` - Set to match your app name

### **OPTIONAL (Nice to have):**
6. `POSTHOG_PROJECT_API_KEY` - If using PostHog analytics
7. `GOOGLE_CLIENT_ID` - If using Google OAuth
8. `GOOGLE_CLIENT_SECRET` - If using Google OAuth
9. `GOOGLE_REDIRECT_URI` - Update to production domain if using Google OAuth
10. `PERSONA_REDIRECT_URI` - If you want custom KYC redirect

---

## 🚀 How to Add Variables in Render

1. Go to your Render Dashboard
2. Select your service (Fullego Backend / Akunuba Backend)
3. Go to **Environment** tab
4. Click **Add Environment Variable**
5. Add each variable with its value
6. Click **Save Changes**
7. Render will automatically redeploy

---

## ⚠️ Important Notes

1. **STRIPE_WEBHOOK_SECRET**: You need to:
   - Create a webhook endpoint in Stripe Dashboard pointing to: `https://your-render-url.onrender.com/api/v1/payments/webhook`
   - Copy the webhook signing secret and set it as `STRIPE_WEBHOOK_SECRET`

2. **PLAID Keys**: Make sure you're using the correct environment keys:
   - Sandbox keys for testing
   - Production keys for live environment

3. **Email**: If using Resend, you may need to verify your domain (`akunuba.io`) before sending from `@akunuba.io` addresses. For now, `anaspirzadaiub@gmail.com` should work for testing.

4. **Security**: Never commit these values to git. They're already set in Render's environment variables, which is the correct approach.

---

**Last Updated**: 2026-02-11
