# Plans & Dashboard APIs Requirements

**Purpose**: This document lists all APIs required for the subscription plans flow and the dashboard functionality after plan activation. This is for the backend team to implement.

**Base URL**: `/api/v1`  
**Authentication**: All endpoints require `Authorization: Bearer <token>` header (except where noted).

---

## Table of Contents
1. [Plans/Subscription APIs (Before Activation)](#1-planssubscription-apis-before-activation)
2. [Dashboard APIs (After Plan Activation)](#2-dashboard-apis-after-plan-activation)
3. [Payment APIs (Required for Plan Activation)](#3-payment-apis-required-for-plan-activation)
4. [Priority & Implementation Notes](#4-priority--implementation-notes)

---

## 1. Plans/Subscription APIs (Before Activation)

These APIs are needed for users to view available plans, select a plan, and activate their subscription.

### 1.1 Get Available Plans
**GET** `/subscriptions/plans` or `/billing/plans`

**Description**: Retrieves all available subscription plans with pricing, features, and limits.

**Headers**: `Authorization: Bearer <token>`

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
      "features": [
        "Basic portfolio dashboard",
        "Limited aggregation (1-2 accounts)",
        "Read-only market performance",
        "Marketplace browsing",
        "Standard email support"
      ],
      "limits": {
        "max_accounts": 2,
        "max_assets": 10
      },
      "popular": false
    },
    {
      "id": "plan_pro",
      "name": "Pro",
      "description": "For active investors & small business owners",
      "monthly_price": 199.00,
      "annual_price": 1999.00,
      "currency": "USD",
      "features": [
        "Full portfolio management",
        "Automated rebalancing",
        "Marketplace access",
        "Asset valuation tools",
        "Transaction tracking",
        "Priority support"
      ],
      "limits": {
        "max_accounts": 10,
        "max_assets": 100
      },
      "popular": true
    },
    {
      "id": "plan_premium",
      "name": "Premium",
      "description": "For advanced investors & entrepreneurs",
      "monthly_price": 699.00,
      "annual_price": 6999.00,
      "currency": "USD",
      "features": [
        "Everything in Pro",
        "AI-driven insights",
        "Automated asset valuation",
        "Document center",
        "Tax & investment advisory",
        "Premium support"
      ],
      "limits": {
        "max_accounts": -1,
        "max_assets": -1
      },
      "popular": false
    },
    {
      "id": "plan_concierge",
      "name": "Concierge",
      "description": "Custom enterprise solution",
      "monthly_price": null,
      "annual_price": null,
      "currency": "USD",
      "features": [
        "Everything in Premium",
        "Dedicated account manager",
        "Custom integrations",
        "White-glove onboarding",
        "24/7 concierge support"
      ],
      "limits": {
        "max_accounts": -1,
        "max_assets": -1
      },
      "is_custom": true,
      "popular": false
    }
  ]
}
```

**Use Case**: Display plans on `/plans` page and in settings/preferences

---

### 1.2 Get Current Subscription Status
**GET** `/subscriptions`

**Description**: Retrieves current subscription information for the authenticated user.

**Headers**: `Authorization: Bearer <token>`

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
  "features": [
    "full_portfolio_management",
    "marketplace_access",
    "priority_support"
  ],
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

**Use Case**: Check if user has active subscription before allowing dashboard access

---

### 1.3 Create/Activate Subscription
**POST** `/subscriptions`

**Description**: Creates a new subscription or activates a plan for the user.

**Headers**: `Authorization: Bearer <token>`

**Request Body**:
```json
{
  "plan_id": "plan_pro",
  "billing_cycle": "monthly",
  "payment_method_id": "pm_xxx",
  "coupon_code": "EARLYBIRD"
}
```

**Request Fields**:
- `plan_id` (string, required): One of `plan_starter`, `plan_pro`, `plan_premium`, `plan_concierge`
- `billing_cycle` (string, required): `"monthly"` or `"annual"`
- `payment_method_id` (string, optional): Stripe payment method ID if user has saved payment methods
- `coupon_code` (string, optional): Discount coupon code

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

**Use Case**: User selects a plan and activates subscription

---

### 1.4 Get Subscription Permissions
**GET** `/subscriptions/permissions`

**Description**: Returns feature permissions and access levels for the current user's subscription.

**Headers**: `Authorization: Bearer <token>`

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

**Use Case**: Check feature access before showing/hiding UI elements

---

### 1.5 Get Subscription Limits & Usage
**GET** `/subscriptions/limits`

**Description**: Returns current usage vs. plan limits.

**Headers**: `Authorization: Bearer <token>`

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

**Use Case**: Display usage bars and warnings when approaching limits

---

### 1.6 Get Subscription History
**GET** `/subscriptions/history`

**Description**: Returns subscription and payment history.

**Headers**: `Authorization: Bearer <token>`

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

**Use Case**: Display subscription history in settings/preferences

---

### 1.7 Cancel Subscription
**POST** `/subscriptions/cancel`

**Description**: Cancels the current active subscription. Access continues until end of billing period unless canceled immediately.

**Headers**: `Authorization: Bearer <token>`

**Request Body** (optional):
```json
{
  "cancel_immediately": false,
  "cancellation_reason": "Too expensive"
}
```

**Request Fields**:
- `cancel_immediately` (boolean, optional): If `true`, cancel immediately. Default: `false` (cancel at period end)
- `cancellation_reason` (string, optional): Reason for cancellation

**Response** (200):
```json
{
  "subscription": {
    "id": "sub_xxx",
    "status": "canceled",
    "cancel_at_period_end": true,
    "canceled_at": "2024-01-15T00:00:00Z",
    "current_period_end": "2024-02-15T00:00:00Z",
    "cancellation_reason": "Too expensive"
  },
  "message": "Subscription will remain active until 2024-02-15"
}
```

**Response** (400) - No Active Subscription:
```json
{
  "detail": "No active subscription to cancel"
}
```

**Use Case**: Allow users to cancel their subscription from settings/preferences page

---

### 1.8 Renew Subscription
**POST** `/subscriptions/renew`

**Description**: Renews an expired or canceled subscription.

**Headers**: `Authorization: Bearer <token>`

**Request Body**: None

**Response** (200):
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
    "renewed_at": "2024-01-15T00:00:00Z"
  },
  "message": "Subscription renewed successfully"
}
```

**Response** (400) - Already Active:
```json
{
  "detail": "Subscription is already active"
}
```

**Response** (402) - Payment Required:
```json
{
  "detail": "Payment method required for renewal",
  "payment_intent": {
    "id": "pi_xxx",
    "client_secret": "pi_xxx_secret_xxx"
  }
}
```

**Use Case**: Allow users to renew expired subscriptions

---

### 1.9 Upgrade/Downgrade Subscription
**PUT** `/subscriptions/upgrade`

**Description**: Changes the subscription plan (upgrade or downgrade) or billing cycle.

**Headers**: `Authorization: Bearer <token>`

**Request Body**:
```json
{
  "plan_id": "plan_premium",
  "billing_cycle": "annual"
}
```

**Request Fields**:
- `plan_id` (string, optional): New plan ID (`plan_starter`, `plan_pro`, `plan_premium`, `plan_concierge`)
- `billing_cycle` (string, optional): New billing cycle (`"monthly"` or `"annual"`)

**Note**: At least one field (`plan_id` or `billing_cycle`) must be provided.

**Response** (200):
```json
{
  "subscription": {
    "id": "sub_xxx",
    "plan_id": "plan_premium",
    "plan_name": "Premium",
    "status": "active",
    "amount": 699.00,
    "currency": "USD",
    "billing_cycle": "annual",
    "current_period_start": "2024-01-15T00:00:00Z",
    "current_period_end": "2025-01-15T00:00:00Z",
    "prorated_amount": 50.00,
    "updated_at": "2024-01-15T00:00:00Z"
  },
  "message": "Subscription updated successfully"
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
  "detail": "Payment required for plan upgrade",
  "payment_intent": {
    "id": "pi_xxx",
    "client_secret": "pi_xxx_secret_xxx",
    "amount": 50.00
  }
}
```

**Use Case**: Allow users to change their plan or billing cycle from settings

---

## 2. Dashboard APIs (After Plan Activation)

These APIs are called when the user accesses the dashboard after activating their plan. All endpoints require authentication.

### 2.1 User Profile
**GET** `/users/me`

**Description**: Get current user profile information.

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

**Use Case**: Display user name in dashboard header

---

### 2.2 Portfolio Summary
**GET** `/portfolio/summary`

**Description**: Get high-level portfolio overview.

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

**Use Case**: Display Net Worth, Assets, Debts cards on dashboard

---

### 2.3 Portfolio Performance
**GET** `/portfolio/performance`

**Description**: Get portfolio performance metrics and time-series data.

**Query Parameters**:
- `days` (integer, required): Number of days for performance calculation (1-365)

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
    },
    {
      "date": "2024-01-02",
      "value": 1405000.00,
      "return": 5000.00,
      "return_percentage": 0.36
    }
  ]
}
```

**Use Case**: Display performance charts and metrics

---

### 2.4 Portfolio History
**GET** `/portfolio/history`

**Description**: Get historical portfolio values for charts.

**Query Parameters**:
- `days` (integer, required): Number of days of history (1-365)

**Response** (200):
```json
{
  "data": [
    {
      "date": "2024-01-01",
      "value": 1400000.00
    },
    {
      "date": "2024-01-02",
      "value": 1405000.00
    }
  ]
}
```

**Use Case**: Historical performance graph on dashboard

---

### 2.5 Account Information
**GET** `/accounts/me`

**Description**: Get current account details.

**Response** (200):
```json
{
  "id": "uuid",
  "account_type": "individual",
  "status": "active",
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Use Case**: Account information display

---

### 2.6 Account Statistics
**GET** `/accounts/stats`

**Description**: Get account statistics and metrics.

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

**Use Case**: Display account stats on dashboard

**Note**: Must use timezone-aware datetime calculations to avoid 500 errors.

---

### 2.7 Bank Accounts
**GET** `/banking/accounts`

**Description**: Get all linked bank accounts.

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

**Use Case**: Calculate "Cash on Hand" card on dashboard

---

### 2.8 Portfolio Allocation
**GET** `/portfolio/allocation`

**Description**: Get asset allocation breakdown.

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

**Use Case**: Portfolio allocation charts (if used on dashboard)

---

### 2.9 Top Holdings
**GET** `/portfolio/holdings/top`

**Description**: Get top portfolio holdings.

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

**Use Case**: Top holdings display (if used on dashboard)

---

### 2.10 Recent Activity
**GET** `/portfolio/activity/recent`

**Description**: Get recent portfolio activity/transactions.

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

**Use Case**: Recent activity feed (if used on dashboard)

---

### 2.11 Market Summary
**GET** `/portfolio/market-summary`

**Description**: Get market summary and benchmarks.

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

**Use Case**: Market indicators on dashboard

---

### 2.12 Portfolio Alerts
**GET** `/portfolio/alerts`

**Description**: Get active portfolio alerts.

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

**Use Case**: Alerts display (if used on dashboard)

---

### 2.13 Portfolio Risk Metrics
**GET** `/portfolio/risk`

**Description**: Get portfolio risk metrics.

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

**Use Case**: Risk metrics display (if used on dashboard)

---

## 3. Payment APIs (Required for Plan Activation)

These APIs are needed to process payments when users activate a subscription plan.

### 3.1 Create Payment Intent
**POST** `/payments/create-intent`

**Description**: Creates a Stripe payment intent for subscription payment.

**Headers**: `Authorization: Bearer <token>`

**Request Body**:
```json
{
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

**Use Case**: Initialize payment when user activates subscription

---

### 3.2 Get Payment Methods
**GET** `/payments/payment-methods`

**Description**: Get saved payment methods for the user.

**Headers**: `Authorization: Bearer <token>`

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

**Use Case**: Show saved payment methods during subscription activation

---

### 3.3 Add Payment Method
**POST** `/payments/payment-methods`

**Description**: Add a new payment method.

**Headers**: `Authorization: Bearer <token>`

**Request Body**:
```json
{
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

**Use Case**: Save payment method during subscription activation

---

### 3.4 Delete Payment Method
**DELETE** `/payments/payment-methods/{method_id}`

**Description**: Removes a saved payment method.

**Headers**: `Authorization: Bearer <token>`

**Path Parameters**:
- `method_id` (string, required): Stripe payment method ID (e.g., `pm_xxx`)

**Response** (200):
```json
{
  "message": "Payment method removed successfully"
}
```

**Response** (404) - Not Found:
```json
{
  "detail": "Payment method not found"
}
```

**Response** (400) - Cannot Delete Default:
```json
{
  "detail": "Cannot delete default payment method. Set another as default first."
}
```

**Use Case**: Remove saved payment methods from settings/preferences

---

### 3.5 Get Payment History
**GET** `/payments/history`

**Description**: Get payment history.

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

**Use Case**: Display payment history in settings

---

### 3.6 Get Payment Statistics
**GET** `/payments/stats`

**Description**: Get payment statistics.

**Response** (200):
```json
{
  "total_paid": 199.00,
  "total_payments": 1,
  "last_payment_date": "2024-01-01T00:00:00Z",
  "payment_methods_count": 1
}
```

**Use Case**: Payment stats display (if used)

**Note**: Currently returns 405 Method Not Allowed - must be implemented.

---

### 3.7 Payment Webhook Handler
**POST** `/payments/webhook`

**Description**: Handles Stripe webhook events for payment status updates, subscription changes, and payment method updates.

**Headers**: 
- `Stripe-Signature` (string, required): Stripe webhook signature for verification

**Request Body**: (Stripe webhook payload)
```json
{
  "type": "payment_intent.succeeded",
  "data": {
    "object": {
      "id": "pi_xxx",
      "status": "succeeded",
      "amount": 19900,
      "currency": "usd",
      "metadata": {
        "subscription_id": "sub_xxx",
        "plan_name": "Pro"
      }
    }
  }
}
```

**Response** (200):
```json
{
  "received": true,
  "event_type": "payment_intent.succeeded",
  "processed_at": "2024-01-01T00:00:00Z"
}
```

**Response** (400) - Invalid Signature:
```json
{
  "detail": "Invalid webhook signature"
}
```

**Important Webhook Events to Handle**:
- `payment_intent.succeeded` - Payment completed successfully
- `payment_intent.payment_failed` - Payment failed
- `customer.subscription.created` - Subscription created
- `customer.subscription.updated` - Subscription updated (plan change, etc.)
- `customer.subscription.deleted` - Subscription canceled
- `invoice.payment_succeeded` - Invoice paid successfully
- `invoice.payment_failed` - Invoice payment failed

**Use Case**: 
- Update subscription status when payment succeeds/fails
- Sync payment status with Stripe
- Handle subscription lifecycle events

**Note**: This endpoint should verify Stripe webhook signatures for security.

---

## 4. Priority & Implementation Notes

### High Priority (Required for MVP)
1. **Plans APIs**:
   - `GET /subscriptions/plans` - Display plans page
   - `GET /subscriptions` - Check subscription status
   - `POST /subscriptions` - Activate subscription
   - `GET /subscriptions/permissions` - Check feature access

2. **Payment APIs**:
   - `POST /payments/create-intent` - Process subscription payment
   - `GET /payments/payment-methods` - Show saved payment methods
   - `POST /payments/payment-methods` - Save payment method
   - `POST /payments/webhook` - Handle Stripe webhooks (critical for payment status updates)

3. **Dashboard APIs** (Core):
   - `GET /users/me` - User profile
   - `GET /portfolio/summary` - Portfolio overview
   - `GET /portfolio/performance` - Performance metrics
   - `GET /portfolio/history` - Historical data
   - `GET /accounts/me` - Account info
   - `GET /accounts/stats` - Account statistics (fix timezone issue)
   - `GET /banking/accounts` - Bank accounts

### Medium Priority (Enhancements)
**Subscription Management**:
- `POST /subscriptions/cancel` - Cancel subscription
- `POST /subscriptions/renew` - Renew subscription
- `PUT /subscriptions/upgrade` - Upgrade/downgrade plan
- `GET /subscriptions/limits` - Usage limits
- `GET /subscriptions/history` - Subscription history

**Payment Management**:
- `DELETE /payments/payment-methods/{id}` - Remove payment method
- `GET /payments/history` - Payment history
- `GET /payments/stats` - Payment statistics (currently 405)

**Dashboard Enhancements**:
- `GET /portfolio/allocation` - Asset allocation
- `GET /portfolio/holdings/top` - Top holdings
- `GET /portfolio/activity/recent` - Recent activity
- `GET /portfolio/market-summary` - Market summary
- `GET /portfolio/alerts` - Portfolio alerts
- `GET /portfolio/risk` - Risk metrics

### Implementation Notes

1. **Error Handling**: All endpoints must return JSON errors (not HTML):
   ```json
   {
     "detail": "Error message here"
   }
   ```

2. **Authentication**: All endpoints require `Authorization: Bearer <token>` header.

3. **Date Formats**: Use ISO 8601 format: `"2024-01-01T00:00:00Z"`

4. **Currency**: All monetary values as decimals (e.g., `199.00`)

5. **Timezone**: Use timezone-aware datetime calculations (especially for `/accounts/stats`)

6. **Pagination**: Use `limit` and `offset` query parameters for list endpoints.

7. **Subscription Status Flow**:
   - User selects plan → `POST /subscriptions` → Returns `payment_intent`
   - Frontend processes payment with Stripe → Payment succeeds
   - Backend activates subscription → User can access dashboard

8. **Feature Gating**: Use `GET /subscriptions/permissions` to check feature access before allowing actions.

---

## Summary

**Total APIs Required**: 29 endpoints

**Breakdown**:
- **Plans/Subscription**: 9 endpoints (4 core MVP + 5 management)
- **Dashboard**: 13 endpoints (7 core MVP + 6 enhancements)
- **Payments**: 7 endpoints (4 core MVP + 3 management)

**Priority Summary**:
- **High Priority (MVP)**: 15 endpoints
  - Subscription: 4 endpoints
  - Payments: 4 endpoints (includes webhook)
  - Dashboard: 7 endpoints
- **Medium Priority**: 14 endpoints
  - Subscription Management: 5 endpoints
  - Payment Management: 3 endpoints
  - Dashboard Enhancements: 6 endpoints

**Critical Path for MVP**:
1. User views plans → `GET /subscriptions/plans`
2. User selects plan → `POST /subscriptions` → `POST /payments/create-intent`
3. Payment processed → Subscription activated
4. User accesses dashboard → All dashboard APIs called

All endpoints should follow the response formats specified above for frontend compatibility.
