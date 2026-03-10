# Frontend API Requirements

**Purpose**: This document lists all APIs that the frontend needs to integrate with the backend for the subscription plans flow and dashboard functionality.

**Base URL**: `/api/v1`  
**Authentication**: All endpoints require `Authorization: Bearer <token>` header.

---

## Table of Contents
1. [Subscription & Plans APIs](#1-subscription--plans-apis)
2. [Payment APIs](#2-payment-apis)
3. [Dashboard APIs](#3-dashboard-apis)
4. [API Integration Flow](#4-api-integration-flow)
5. [Error Handling](#5-error-handling)

---

## 1. Subscription & Plans APIs

### 1.1 Get Available Plans
**Endpoint**: `GET /subscriptions/plans` or `GET /billing/plans`

**When to Call**: 
- On `/plans` page load
- In settings/preferences page
- Before showing plan selection UI

**Request**:
```javascript
GET /api/v1/subscriptions/plans
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "plans": [
    {
      "id": "plan_starter",
      "name": "Starter",
      "description": "Perfect for new or casual investors",
      "monthly_price": 0.00,
      "annual_price": 0.00,
      "currency": "USD",
      "features": [...],
      "limits": {
        "max_accounts": 2,
        "max_assets": 10
      },
      "popular": false
    },
    {
      "id": "plan_pro",
      "name": "Pro",
      "monthly_price": 199.00,
      "annual_price": 1999.00,
      "popular": true
    },
    {
      "id": "plan_premium",
      "name": "Premium",
      "monthly_price": 699.00,
      "annual_price": 6999.00
    },
    {
      "id": "plan_concierge",
      "name": "Concierge",
      "monthly_price": null,
      "annual_price": null,
      "is_custom": true
    }
  ]
}
```

**Frontend Usage**: Display plan cards with pricing, features, and limits

---

### 1.2 Get Current Subscription Status
**Endpoint**: `GET /subscriptions`

**When to Call**:
- On app initialization (check if user has active subscription)
- Before allowing dashboard access
- In settings page to show current plan
- Route guards to protect dashboard routes

**Request**:
```javascript
GET /api/v1/subscriptions
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200) - Active Subscription:
```json
{
  "id": "uuid",
  "plan_id": "plan_pro",
  "plan_name": "Pro",
  "status": "active",
  "amount": 199.00,
  "currency": "USD",
  "billing_cycle": "monthly",
  "current_period_start": "2024-01-01T00:00:00Z",
  "current_period_end": "2024-02-01T00:00:00Z",
  "cancel_at_period_end": false,
  "canceled_at": null,
  "trial_end": null,
  "features": [...],
  "created_at": "2023-12-01T00:00:00Z"
}
```

**Response** (200) - No Subscription:
```json
null
```
or
```json
{
  "subscription": null,
  "message": "No active subscription"
}
```

**Status Values**: `"active" | "canceled" | "past_due" | "trialing" | "incomplete"`

**Frontend Usage**: 
- Show subscription status in UI
- Gate dashboard access (only allow if status === "active")
- Display plan name and billing cycle

---

### 1.3 Create/Activate Subscription
**Endpoint**: `POST /subscriptions`

**When to Call**:
- User clicks "Subscribe" or "Activate Plan" button
- After user selects a plan and billing cycle

**Request**:
```javascript
POST /api/v1/subscriptions
Headers: {
  Authorization: "Bearer <token>",
  "Content-Type": "application/json"
}
Body: {
  "plan_id": "plan_pro",
  "billing_cycle": "monthly",
  "payment_method_id": "pm_xxx",  // optional
  "coupon_code": "EARLYBIRD"       // optional
}
```

**Response** (201):
```json
{
  "subscription": {
    "id": "sub_xxx",
    "plan_id": "plan_pro",
    "plan_name": "Pro",
    "status": "active",
    "amount": 199.00,
    "currency": "USD",
    "billing_cycle": "monthly",
    "current_period_start": "2024-01-15T00:00:00Z",
    "current_period_end": "2024-02-15T00:00:00Z",
    "created_at": "2024-01-15T00:00:00Z"
  },
  "payment_intent": {
    "id": "pi_xxx",
    "client_secret": "pi_xxx_secret_xxx",
    "status": "requires_payment_method",
    "amount": 199.00,
    "currency": "USD"
  }
}
```

**Response** (400) - Invalid Plan:
```json
{
  "detail": "Invalid plan_id provided"
}
```

**Response** (402) - Payment Required:
```json
{
  "detail": "Payment method required",
  "payment_intent": {
    "id": "pi_xxx",
    "client_secret": "pi_xxx_secret_xxx"
  }
}
```

**Frontend Usage**:
- If payment_intent is returned, use `client_secret` with Stripe.js to process payment
- After successful payment, redirect to dashboard
- Show error messages if subscription creation fails

---

### 1.4 Get Subscription Permissions
**Endpoint**: `GET /subscriptions/permissions`

**When to Call**:
- On dashboard load (to show/hide features)
- Before rendering feature-specific UI components
- Before allowing feature actions (e.g., marketplace listing)

**Request**:
```javascript
GET /api/v1/subscriptions/permissions
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "features": {
    "portfolio_management": true,
    "marketplace_access": true,
    "marketplace_listing": true,
    "marketplace_purchase": true,
    "asset_valuation": true,
    "automated_rebalancing": true,
    "ai_insights": false,
    "document_center": false,
    "tax_advisory": false,
    "priority_support": true,
    "concierge_support": false
  },
  "limits": {
    "max_accounts": 10,
    "max_assets": 100,
    "max_marketplace_listings": 5
  }
}
```

**Frontend Usage**:
- Conditionally render UI elements based on `features` object
- Show upgrade prompts for disabled features
- Display plan limits to users

---

### 1.5 Get Subscription Limits & Usage
**Endpoint**: `GET /subscriptions/limits`

**When to Call**:
- On dashboard load
- In settings page
- Before allowing actions that might exceed limits

**Request**:
```javascript
GET /api/v1/subscriptions/limits
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "limits": {
    "max_accounts": 10,
    "max_assets": 100,
    "max_marketplace_listings": 5
  },
  "usage": {
    "accounts": 3,
    "assets": 25,
    "marketplace_listings": 2
  },
  "percentages": {
    "accounts": 30,
    "assets": 25,
    "marketplace_listings": 40
  }
}
```

**Frontend Usage**:
- Display usage progress bars
- Show warnings when approaching limits (e.g., 80% usage)
- Prevent actions that would exceed limits

---

### 1.6 Get Subscription History
**Endpoint**: `GET /subscriptions/history`

**When to Call**:
- In settings/preferences page
- User clicks "View Subscription History"

**Request**:
```javascript
GET /api/v1/subscriptions/history?limit=20&offset=0
Headers: {
  Authorization: "Bearer <token>"
}
```

**Query Parameters** (optional):
- `limit` (integer): Number of records (default: 20, max: 100)
- `offset` (integer): Pagination offset (default: 0)

**Response** (200):
```json
{
  "data": [
    {
      "id": "uuid",
      "plan_id": "plan_pro",
      "plan_name": "Pro",
      "status": "active",
      "amount": 199.00,
      "currency": "USD",
      "billing_cycle": "monthly",
      "period_start": "2024-01-01T00:00:00Z",
      "period_end": "2024-02-01T00:00:00Z",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

**Frontend Usage**: Display subscription history table with pagination

---

## 2. Payment APIs

### 2.1 Create Payment Intent
**Endpoint**: `POST /payments/create-intent`

**When to Call**:
- After user selects a plan and before showing payment form
- When user needs to process a payment

**Request**:
```javascript
POST /api/v1/payments/create-intent
Headers: {
  Authorization: "Bearer <token>",
  "Content-Type": "application/json"
}
Body: {
  "amount": 199.00,
  "currency": "USD",
  "payment_method": "card",
  "description": "Payment for Pro subscription",
  "metadata": {
    "subscription_id": "sub_xxx",
    "plan_name": "Pro"
  }
}
```

**Response** (201):
```json
{
  "payment_intent_id": "pi_xxx",
  "client_secret": "pi_xxx_secret_xxx",
  "amount": 199.00,
  "currency": "USD",
  "status": "requires_payment_method",
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Frontend Usage**:
- Use `client_secret` with Stripe.js `confirmCardPayment()` or `confirmPayment()`
- Handle payment status updates
- Show payment processing UI

---

### 2.2 Get Payment Methods
**Endpoint**: `GET /payments/payment-methods`

**When to Call**:
- On subscription activation page
- In payment settings page
- Before showing payment form (to show saved cards)

**Request**:
```javascript
GET /api/v1/payments/payment-methods
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "data": [
    {
      "id": "pm_xxx",
      "type": "card",
      "card": {
        "brand": "visa",
        "last4": "4242",
        "exp_month": 12,
        "exp_year": 2025
      },
      "is_default": true
    }
  ]
}
```

**Frontend Usage**:
- Display saved payment methods as selectable options
- Show card brand, last 4 digits, and expiration
- Allow user to select default payment method

---

### 2.3 Add Payment Method
**Endpoint**: `POST /payments/payment-methods`

**When to Call**:
- After user successfully adds a card via Stripe
- When user wants to save a payment method for future use

**Request**:
```javascript
POST /api/v1/payments/payment-methods
Headers: {
  Authorization: "Bearer <token>",
  "Content-Type": "application/json"
}
Body: {
  "payment_method_id": "pm_xxx",
  "is_default": true
}
```

**Response** (201):
```json
{
  "id": "pm_xxx",
  "type": "card",
  "card": {
    "brand": "visa",
    "last4": "4242"
  },
  "is_default": true
}
```

**Frontend Usage**:
- Save payment method after Stripe confirmation
- Update payment methods list
- Set as default if requested

---

### 2.4 Get Payment History
**Endpoint**: `GET /payments/history`

**When to Call**:
- In settings/billing page
- User clicks "View Payment History"

**Request**:
```javascript
GET /api/v1/payments/history?limit=20&offset=0&status=completed
Headers: {
  Authorization: "Bearer <token>"
}
```

**Query Parameters** (optional):
- `limit` (integer): Number of payments (default: 20, max: 100)
- `offset` (integer): Pagination offset (default: 0)
- `status` (string): Filter by status (`"completed" | "pending" | "failed" | "refunded"`)

**Response** (200):
```json
{
  "data": [
    {
      "id": "uuid",
      "amount": 199.00,
      "currency": "USD",
      "status": "completed",
      "payment_method": "card",
      "description": "Pro subscription payment",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

**Frontend Usage**: Display payment history table with filters and pagination

---

### 2.5 Get Payment Statistics
**Endpoint**: `GET /payments/stats`

**When to Call**:
- In billing/settings dashboard
- To show payment summary

**Request**:
```javascript
GET /api/v1/payments/stats
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "total_paid": 199.00,
  "total_payments": 1,
  "last_payment_date": "2024-01-01T00:00:00Z",
  "payment_methods_count": 1
}
```

**Frontend Usage**: Display payment statistics cards/summary

**Note**: Currently returns 405 Method Not Allowed - backend must implement this endpoint.

---

## 3. Dashboard APIs

### 3.1 User Profile
**Endpoint**: `GET /users/me`

**When to Call**:
- On dashboard load
- In user profile/settings page
- To display user name in header

**Request**:
```javascript
GET /api/v1/users/me
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "phone": "+1234567890",
  "email_verified": true,
  "kyc_status": "approved",
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Frontend Usage**: Display user name, email, and profile information

---

### 3.2 Portfolio Summary
**Endpoint**: `GET /portfolio/summary`

**When to Call**:
- On dashboard load
- When time range filter changes

**Request**:
```javascript
GET /api/v1/portfolio/summary?time_range=ALL
Headers: {
  Authorization: "Bearer <token>"
}
```

**Query Parameters** (optional):
- `time_range` (string): `"1D" | "1W" | "1M" | "3M" | "1Y" | "ALL"` (default: `"ALL"`)

**Response** (200):
```json
{
  "total_portfolio_value": 1500000.00,
  "total_assets": 1400000.00,
  "total_debts": 100000.00,
  "cash_available": 200000.00,
  "total_returns": 100000.00,
  "return_percentage": 7.14,
  "today_change": 5000.00,
  "today_change_percentage": 0.33
}
```

**Frontend Usage**: 
- Display Net Worth card
- Display Assets card
- Display Debts card
- Show returns and today's change

---

### 3.3 Portfolio Performance
**Endpoint**: `GET /portfolio/performance`

**When to Call**:
- On dashboard load
- When performance period changes

**Request**:
```javascript
GET /api/v1/portfolio/performance?days=365
Headers: {
  Authorization: "Bearer <token>"
}
```

**Query Parameters** (required):
- `days` (integer): Number of days for performance calculation (1-365)

**Response** (200):
```json
{
  "period_days": 365,
  "current_value": 1500000.00,
  "historical_value": 1400000.00,
  "total_return": 100000.00,
  "total_return_percentage": 7.14,
  "daily_returns": [
    {
      "date": "2024-01-01",
      "value": 1400000.00,
      "return": 0.0,
      "return_percentage": 0.0
    }
  ]
}
```

**Frontend Usage**: 
- Display performance metrics
- Render performance chart with `daily_returns` data

---

### 3.4 Portfolio History
**Endpoint**: `GET /portfolio/history`

**When to Call**:
- On dashboard load
- When historical period changes

**Request**:
```javascript
GET /api/v1/portfolio/history?days=365
Headers: {
  Authorization: "Bearer <token>"
}
```

**Query Parameters** (required):
- `days` (integer): Number of days of history (1-365)

**Response** (200):
```json
{
  "data": [
    {
      "date": "2024-01-01",
      "value": 1400000.00
    }
  ]
}
```

**Frontend Usage**: Render historical performance graph/chart

---

### 3.5 Account Information
**Endpoint**: `GET /accounts/me`

**When to Call**:
- On dashboard load
- In account settings page

**Request**:
```javascript
GET /api/v1/accounts/me
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "id": "uuid",
  "account_type": "individual",
  "status": "active",
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Frontend Usage**: Display account information

---

### 3.6 Account Statistics
**Endpoint**: `GET /accounts/stats`

**When to Call**:
- On dashboard load
- In account overview section

**Request**:
```javascript
GET /api/v1/accounts/stats
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "account_age_days": 30,
  "total_assets": 15,
  "total_accounts_linked": 3,
  "portfolio_value": 1500000.00,
  "last_activity": "2024-01-15T10:30:00Z"
}
```

**Frontend Usage**: Display account statistics cards

**Note**: Backend must use timezone-aware datetime calculations to avoid 500 errors.

---

### 3.7 Bank Accounts
**Endpoint**: `GET /banking/accounts`

**When to Call**:
- On dashboard load
- To calculate "Cash on Hand" card

**Request**:
```javascript
GET /api/v1/banking/accounts
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "data": [
    {
      "id": "uuid",
      "institution_name": "Chase Bank",
      "account_name": "Checking Account",
      "account_type": "checking",
      "balance": 50000.00,
      "currency": "USD",
      "last_synced": "2024-01-15T10:00:00Z"
    }
  ]
}
```

**Frontend Usage**: 
- Calculate total cash from all bank accounts
- Display "Cash on Hand" card on dashboard
- Show linked bank accounts list

---

### 3.8 Portfolio Allocation
**Endpoint**: `GET /portfolio/allocation`

**When to Call**:
- On dashboard load (if allocation chart is shown)
- When user views portfolio allocation page

**Request**:
```javascript
GET /api/v1/portfolio/allocation
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "asset_allocation": {
    "stocks": 66.67,
    "bonds": 20.0,
    "crypto": 10.0,
    "real_estate": 2.0,
    "other": 1.33
  },
  "sector_allocation": {
    "technology": 35.0,
    "healthcare": 20.0,
    "finance": 15.0
  }
}
```

**Frontend Usage**: Render pie charts for asset and sector allocation

---

### 3.9 Top Holdings
**Endpoint**: `GET /portfolio/holdings/top`

**When to Call**:
- On dashboard load (if top holdings widget is shown)
- When user views holdings page

**Request**:
```javascript
GET /api/v1/portfolio/holdings/top?limit=10
Headers: {
  Authorization: "Bearer <token>"
}
```

**Query Parameters** (optional):
- `limit` (integer): Number of holdings (default: 10)

**Response** (200):
```json
{
  "data": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "value": 50000.00,
      "percentage": 3.33,
      "shares": 250,
      "price": 200.00
    }
  ]
}
```

**Frontend Usage**: Display top holdings table or list

---

### 3.10 Recent Activity
**Endpoint**: `GET /portfolio/activity/recent`

**When to Call**:
- On dashboard load (if activity feed is shown)
- When user views activity page

**Request**:
```javascript
GET /api/v1/portfolio/activity/recent?limit=10
Headers: {
  Authorization: "Bearer <token>"
}
```

**Query Parameters** (optional):
- `limit` (integer): Number of activities (default: 10)

**Response** (200):
```json
{
  "data": [
    {
      "id": "uuid",
      "type": "trade",
      "description": "Bought 10 shares of AAPL",
      "amount": 2000.00,
      "date": "2024-01-15T10:00:00Z"
    }
  ]
}
```

**Frontend Usage**: Display recent activity feed/timeline

---

### 3.11 Market Summary
**Endpoint**: `GET /portfolio/market-summary`

**When to Call**:
- On dashboard load
- Periodically refresh (every 5-10 minutes) if market is open

**Request**:
```javascript
GET /api/v1/portfolio/market-summary
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "market_status": "open",
  "sp500_change": 0.5,
  "dow_change": 0.3,
  "nasdaq_change": 0.7,
  "last_updated": "2024-01-15T16:00:00Z"
}
```

**Frontend Usage**: Display market indicators (S&P 500, Dow, NASDAQ) with change percentages

---

### 3.12 Portfolio Alerts
**Endpoint**: `GET /portfolio/alerts`

**When to Call**:
- On dashboard load
- Periodically check for new alerts
- When user views alerts page

**Request**:
```javascript
GET /api/v1/portfolio/alerts?status=active&limit=10
Headers: {
  Authorization: "Bearer <token>"
}
```

**Query Parameters** (optional):
- `status` (string): Filter by status (`"active" | "resolved"`)
- `limit` (integer): Number of alerts (default: 10)

**Response** (200):
```json
{
  "data": [
    {
      "id": "uuid",
      "type": "price_alert",
      "message": "AAPL dropped below $200",
      "severity": "medium",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ]
}
```

**Frontend Usage**: 
- Display alerts banner/notification
- Show alerts list with severity indicators
- Filter by status

---

### 3.13 Portfolio Risk Metrics
**Endpoint**: `GET /portfolio/risk`

**When to Call**:
- On dashboard load (if risk metrics are shown)
- When user views risk analysis page

**Request**:
```javascript
GET /api/v1/portfolio/risk
Headers: {
  Authorization: "Bearer <token>"
}
```

**Response** (200):
```json
{
  "volatility": 2.5,
  "concentration_risk": 35.5,
  "diversification_score": 75.0,
  "asset_type_count": 4,
  "total_assets": 15
}
```

**Frontend Usage**: Display risk metrics cards with visual indicators

---

## 4. API Integration Flow

### Subscription Activation Flow
```
1. User visits /plans page
   → GET /subscriptions/plans (display plans)

2. User selects a plan
   → GET /subscriptions (check current subscription)
   → POST /subscriptions (create subscription)
   → Returns payment_intent with client_secret

3. Frontend processes payment
   → Use Stripe.js with client_secret
   → confirmCardPayment() or confirmPayment()

4. Payment succeeds
   → GET /subscriptions (verify subscription is active)
   → Redirect to dashboard
```

### Dashboard Load Flow
```
1. User accesses dashboard
   → GET /subscriptions (check if active)
   → GET /subscriptions/permissions (check features)
   → GET /users/me (get user profile)

2. Load portfolio data (parallel requests)
   → GET /portfolio/summary
   → GET /portfolio/performance?days=365
   → GET /portfolio/history?days=365
   → GET /accounts/me
   → GET /accounts/stats
   → GET /banking/accounts

3. Load additional data (if needed)
   → GET /portfolio/allocation
   → GET /portfolio/holdings/top
   → GET /portfolio/activity/recent
   → GET /portfolio/market-summary
   → GET /portfolio/alerts
   → GET /portfolio/risk
```

---

## 5. Error Handling

### Standard Error Response Format
All endpoints return errors in this format:
```json
{
  "detail": "Error message here"
}
```

### Common HTTP Status Codes
- **200**: Success
- **201**: Created (subscription/payment created)
- **400**: Bad Request (invalid input)
- **401**: Unauthorized (missing/invalid token)
- **402**: Payment Required (payment method needed)
- **404**: Not Found
- **405**: Method Not Allowed (endpoint not implemented)
- **500**: Internal Server Error

### Frontend Error Handling
```javascript
try {
  const response = await fetch('/api/v1/subscriptions', {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    }
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'An error occurred');
  }
  
  const data = await response.json();
  // Handle success
} catch (error) {
  // Display error message to user
  console.error('API Error:', error.message);
}
```

---

## Summary

### Total APIs Required: 24 endpoints

**Subscription & Plans (6 endpoints)**:
1. `GET /subscriptions/plans` - Get available plans
2. `GET /subscriptions` - Get current subscription
3. `POST /subscriptions` - Create/activate subscription
4. `GET /subscriptions/permissions` - Get feature permissions
5. `GET /subscriptions/limits` - Get usage limits
6. `GET /subscriptions/history` - Get subscription history

**Payment (5 endpoints)**:
1. `POST /payments/create-intent` - Create payment intent
2. `GET /payments/payment-methods` - Get saved payment methods
3. `POST /payments/payment-methods` - Add payment method
4. `GET /payments/history` - Get payment history
5. `GET /payments/stats` - Get payment statistics ⚠️ (currently 405)

**Dashboard (13 endpoints)**:
1. `GET /users/me` - User profile
2. `GET /portfolio/summary` - Portfolio summary
3. `GET /portfolio/performance` - Portfolio performance
4. `GET /portfolio/history` - Portfolio history
5. `GET /accounts/me` - Account information
6. `GET /accounts/stats` - Account statistics ⚠️ (timezone fix needed)
7. `GET /banking/accounts` - Bank accounts
8. `GET /portfolio/allocation` - Portfolio allocation
9. `GET /portfolio/holdings/top` - Top holdings
10. `GET /portfolio/activity/recent` - Recent activity
11. `GET /portfolio/market-summary` - Market summary
12. `GET /portfolio/alerts` - Portfolio alerts
13. `GET /portfolio/risk` - Risk metrics

### Priority for Frontend Implementation

**High Priority (MVP)**:
- All Subscription APIs (1.1-1.4)
- Payment APIs (2.1-2.3)
- Core Dashboard APIs (3.1-3.7)

**Medium Priority (Enhancements)**:
- Subscription history & limits (1.5-1.6)
- Payment history & stats (2.4-2.5)
- Additional Dashboard APIs (3.8-3.13)
