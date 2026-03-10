# Frontend API Integration Guide

Complete API documentation for frontend developers with request/response examples and user-friendly messages.

**Base URL**: `/api/v1`  
**Authentication**: All endpoints require Bearer token in `Authorization` header  
**Content-Type**: `application/json`

---

## Table of Contents

1. [Subscription APIs](#subscription-apis)
2. [Payment APIs](#payment-apis)
3. [Dashboard APIs](#dashboard-apis)
4. [Error Handling](#error-handling)
5. [User-Friendly Messages](#user-friendly-messages)

---

## Subscription APIs

### 1. Get Available Plans

**GET** `/subscriptions/plans`

**Description**: Retrieves all available subscription plans with pricing, features, and limits.

**Headers**:
```
Authorization: Bearer <token>
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
      "popular": false,
      "is_custom": false
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
      "popular": true,
      "is_custom": false
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
      "popular": false,
      "is_custom": false
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
      "popular": false,
      "is_custom": true
    }
  ]
}
```

**User-Friendly Messages**:
- **Success**: "Plans loaded successfully"
- **Error (401)**: "Please log in to view subscription plans"
- **Error (500)**: "Unable to load plans. Please try again later"

**Frontend Usage**:
```javascript
// Display plans on pricing page
const response = await fetch('/api/v1/subscriptions/plans', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const { plans } = await response.json();
// Highlight popular plan, show features, pricing
```

---

### 2. Get Current Subscription

**GET** `/subscriptions`

**Description**: Retrieves current subscription information for the authenticated user.

**Headers**:
```
Authorization: Bearer <token>
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
  "features": [
    "Full portfolio management",
    "Automated rebalancing",
    "Marketplace access"
  ],
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Response** (200) - No Subscription:
```json
null
```

**User-Friendly Messages**:
- **Active Subscription**: "Your {plan_name} subscription is active until {current_period_end}"
- **Expired Subscription**: "Your subscription has expired. Renew now to continue using premium features."
- **Cancelled Subscription**: "Your subscription will end on {current_period_end}. You'll lose access to premium features after this date."
- **No Subscription**: "You're currently on the free plan. Upgrade to unlock premium features."

**Frontend Usage**:
```javascript
// Check subscription status on app load
const response = await fetch('/api/v1/subscriptions', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const subscription = await response.json();

if (!subscription) {
  // Show upgrade prompt
} else if (subscription.status === 'active') {
  // Show subscription details
} else if (subscription.status === 'expired') {
  // Show renewal prompt
}
```

---

### 3. Create/Activate Subscription

**POST** `/subscriptions`

**Description**: Creates or activates a subscription. Returns payment intent if payment is required.

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "plan_id": "plan_pro",
  "billing_cycle": "monthly",
  "payment_method_id": "pm_xxx",
  "coupon_code": "EARLYBIRD"
}
```

**Response** (201):
```json
{
  "subscription": {
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
    "created_at": "2024-01-01T00:00:00Z"
  },
  "payment_intent": {
    "id": "pi_xxx",
    "client_secret": "pi_xxx_secret_xxx",
    "amount": 199.00,
    "currency": "USD",
    "status": "requires_payment_method",
    "created_at": "2024-01-01T00:00:00Z"
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
  "detail": "Payment method required"
}
```

**User-Friendly Messages**:
- **Success**: "🎉 Your {plan_name} subscription is now active! You can access all premium features."
- **Payment Required**: "Please complete payment to activate your subscription"
- **Invalid Plan**: "The selected plan is not available. Please choose another plan."
- **Custom Plan**: "This plan requires custom pricing. Our team will contact you shortly."

**Frontend Usage**:
```javascript
// Activate subscription
const response = await fetch('/api/v1/subscriptions', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    plan_id: 'plan_pro',
    billing_cycle: 'monthly',
    coupon_code: 'EARLYBIRD'
  })
});

if (response.status === 402) {
  // Show payment form using payment_intent.client_secret
  const { payment_intent } = await response.json();
  // Use Stripe.js to confirm payment
} else if (response.ok) {
  // Show success message
  showSuccess('Your subscription is now active!');
}
```

---

### 4. Get Subscription Permissions

**GET** `/subscriptions/permissions`

**Description**: Get feature permissions and access levels for the current user's subscription.

**Headers**:
```
Authorization: Bearer <token>
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
    "automated_rebalancing": false,
    "ai_insights": false,
    "document_center": false,
    "tax_advisory": false,
    "priority_support": false,
    "concierge_support": false
  },
  "limits": {
    "max_accounts": 10,
    "max_assets": 100,
    "max_marketplace_listings": 10
  }
}
```

**User-Friendly Messages**:
- **Feature Available**: Show feature as enabled/available
- **Feature Unavailable**: "Upgrade to {plan_name} to unlock this feature"
- **Limit Reached**: "You've reached your plan limit. Upgrade to add more {resource}."

**Frontend Usage**:
```javascript
// Check permissions before showing features
const response = await fetch('/api/v1/subscriptions/permissions', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const { features, limits } = await response.json();

if (features.marketplace_listing) {
  // Show "List Asset" button
} else {
  // Show "Upgrade to unlock" button
}
```

---

### 5. Get Usage Limits

**GET** `/subscriptions/limits`

**Description**: Get current usage vs. plan limits.

**Headers**:
```
Authorization: Bearer <token>
```

**Response** (200):
```json
{
  "limits": {
    "max_accounts": 10,
    "max_assets": 100,
    "max_marketplace_listings": 10
  },
  "usage": {
    "accounts": 3,
    "assets": 25,
    "marketplace_listings": 2
  },
  "percentages": {
    "accounts": 30,
    "assets": 25,
    "marketplace_listings": 20
  }
}
```

**User-Friendly Messages**:
- **Under Limit**: "You're using {usage} of {limit} {resource}"
- **Near Limit (80%+)**: "⚠️ You're running low on {resource}. Consider upgrading."
- **At Limit**: "You've reached your {resource} limit. Upgrade to add more."
- **Unlimited**: "Unlimited {resource}"

**Frontend Usage**:
```javascript
// Show usage progress bars
const { limits, usage, percentages } = await response.json();

// Display progress: "25 of 100 assets (25%)"
// Show warning if percentage > 80%
// Disable "Add" button if at limit
```

---

### 6. Get Subscription History

**GET** `/subscriptions/history?limit=20&offset=0`

**Description**: Returns subscription and payment history.

**Query Parameters**:
- `limit` (integer, optional): Number of records (default: 20, max: 100)
- `offset` (integer, optional): Pagination offset (default: 0)

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

**User-Friendly Messages**:
- **Empty History**: "No subscription history found"
- **Loading**: "Loading subscription history..."

**Frontend Usage**:
```javascript
// Display subscription history table
const response = await fetch('/api/v1/subscriptions/history?limit=20&offset=0', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const { data, total, limit, offset } = await response.json();
// Render table with pagination
```

---

### 7. Cancel Subscription

**POST** `/subscriptions/cancel`

**Description**: Cancels the current active subscription.

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body** (optional):
```json
{
  "cancel_immediately": false,
  "cancellation_reason": "Too expensive"
}
```

**Response** (200):
```json
{
  "subscription": {
    "id": "uuid",
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

**User-Friendly Messages**:
- **Cancel at Period End**: "Your subscription will remain active until {date}. You'll lose access to premium features after this date."
- **Cancel Immediately**: "Your subscription has been cancelled. You no longer have access to premium features."
- **Confirmation**: "Are you sure you want to cancel your subscription? You'll lose access to premium features."
- **Success**: "Subscription cancelled successfully. You'll continue to have access until {date}."

**Frontend Usage**:
```javascript
// Show confirmation dialog first
if (confirm('Are you sure you want to cancel your subscription?')) {
  const response = await fetch('/api/v1/subscriptions/cancel', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      cancel_immediately: false,
      cancellation_reason: 'Too expensive'
    })
  });
  
  const { message } = await response.json();
  showSuccess(message);
}
```

---

### 8. Renew Subscription

**POST** `/subscriptions/renew`

**Description**: Renews an expired or canceled subscription.

**Headers**:
```
Authorization: Bearer <token>
```

**Response** (200):
```json
{
  "subscription": {
    "id": "uuid",
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

**User-Friendly Messages**:
- **Success**: "Your subscription has been renewed! Welcome back to {plan_name}."
- **Payment Required**: "Please complete payment to renew your subscription"
- **Already Active**: "Your subscription is already active"
- **Expired**: "Your subscription has expired. Renew now to continue using premium features."

**Frontend Usage**:
```javascript
// Renew expired subscription
const response = await fetch('/api/v1/subscriptions/renew', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}` }
});

if (response.status === 402) {
  // Show payment form
} else if (response.ok) {
  showSuccess('Subscription renewed successfully!');
}
```

---

### 9. Upgrade/Downgrade Subscription

**PUT** `/subscriptions/upgrade`

**Description**: Changes the subscription plan or billing cycle.

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "plan_id": "plan_premium",
  "billing_cycle": "annual"
}
```

**Response** (200):
```json
{
  "subscription": {
    "id": "uuid",
    "plan_id": "plan_premium",
    "plan_name": "Premium",
    "status": "active",
    "amount": 6999.00,
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

**User-Friendly Messages**:
- **Upgrade Success**: "🎉 You've successfully upgraded to {plan_name}! New features are now available."
- **Downgrade Success**: "Your plan has been changed to {plan_name}. Changes will take effect at the end of your current billing period."
- **Payment Required**: "Please complete payment of ${amount} to upgrade your plan"
- **Prorated Amount**: "You'll be charged a prorated amount of ${amount} for the remaining days in your billing period."

**Frontend Usage**:
```javascript
// Upgrade subscription
const response = await fetch('/api/v1/subscriptions/upgrade', {
  method: 'PUT',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    plan_id: 'plan_premium',
    billing_cycle: 'annual'
  })
});

if (response.status === 402) {
  const { payment_intent } = await response.json();
  // Show payment form for prorated amount
} else if (response.ok) {
  showSuccess('Plan upgraded successfully!');
}
```

---

## Payment APIs

### 10. Create Payment Intent

**POST** `/payments/create-intent`

**Description**: Creates a Stripe payment intent for subscription payment.

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

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

**User-Friendly Messages**:
- **Success**: "Payment form ready. Please enter your payment details."
- **Error**: "Unable to initialize payment. Please try again."

**Frontend Usage**:
```javascript
// Create payment intent
const response = await fetch('/api/v1/payments/create-intent', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    amount: 199.00,
    currency: 'USD',
    description: 'Payment for Pro subscription'
  })
});

const { client_secret } = await response.json();
// Use Stripe.js to confirm payment with client_secret
```

---

### 11. Get Payment Methods

**GET** `/payments/payment-methods`

**Description**: Get saved payment methods for the user.

**Headers**:
```
Authorization: Bearer <token>
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

**User-Friendly Messages**:
- **No Payment Methods**: "No saved payment methods. Add one to make checkout faster."
- **Loading**: "Loading payment methods..."

**Frontend Usage**:
```javascript
// Display saved payment methods
const response = await fetch('/api/v1/payments/payment-methods', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const { data } = await response.json();

// Display: "Visa •••• 4242 (Expires 12/2025)"
data.forEach(method => {
  if (method.type === 'card') {
    const { brand, last4, exp_month, exp_year } = method.card;
    // Show card info
  }
});
```

---

### 12. Add Payment Method

**POST** `/payments/payment-methods`

**Description**: Add a new payment method.

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

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

**User-Friendly Messages**:
- **Success**: "Payment method added successfully"
- **Error**: "Unable to add payment method. Please check your details and try again."

**Frontend Usage**:
```javascript
// Add payment method from Stripe Elements
const { paymentMethod } = await stripe.createPaymentMethod({
  type: 'card',
  card: cardElement
});

const response = await fetch('/api/v1/payments/payment-methods', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    payment_method_id: paymentMethod.id,
    is_default: true
  })
});

showSuccess('Payment method added successfully');
```

---

### 13. Delete Payment Method

**DELETE** `/payments/payment-methods/{method_id}`

**Description**: Removes a saved payment method.

**Path Parameters**:
- `method_id` (string, required): Stripe payment method ID

**Response** (200):
```json
{
  "message": "Payment method removed successfully"
}
```

**Response** (404):
```json
{
  "detail": "Payment method not found"
}
```

**User-Friendly Messages**:
- **Success**: "Payment method removed successfully"
- **Not Found**: "Payment method not found"
- **Confirmation**: "Are you sure you want to remove this payment method?"

**Frontend Usage**:
```javascript
// Remove payment method
if (confirm('Are you sure you want to remove this payment method?')) {
  const response = await fetch(`/api/v1/payments/payment-methods/${methodId}`, {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${token}` }
  });
  
  if (response.ok) {
    showSuccess('Payment method removed');
    // Refresh payment methods list
  }
}
```

---

### 14. Get Payment History

**GET** `/payments/history?limit=20&offset=0&status=completed`

**Description**: Get payment history.

**Query Parameters**:
- `limit` (integer, optional): Number of payments (default: 20, max: 100)
- `offset` (integer, optional): Pagination offset (default: 0)
- `status` (string, optional): Filter by status (`completed`, `pending`, `failed`, `refunded`)

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
      "description": "Payment for Pro subscription",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

**User-Friendly Messages**:
- **Empty History**: "No payment history found"
- **Status Labels**:
  - `completed`: "Paid"
  - `pending`: "Processing"
  - `failed`: "Failed"
  - `refunded`: "Refunded"

**Frontend Usage**:
```javascript
// Display payment history
const response = await fetch('/api/v1/payments/history?limit=20&offset=0', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const { data, total, limit, offset } = await response.json();

// Render table with status badges
data.forEach(payment => {
  const statusLabels = {
    completed: 'Paid',
    pending: 'Processing',
    failed: 'Failed',
    refunded: 'Refunded'
  };
  // Display payment with status label
});
```

---

### 15. Get Payment Statistics

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

**User-Friendly Messages**:
- **Display**: "Total Paid: ${total_paid} | Payments: {total_payments} | Last Payment: {last_payment_date}"

**Frontend Usage**:
```javascript
// Show payment stats
const response = await fetch('/api/v1/payments/stats', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const stats = await response.json();

// Display: "Total Paid: $199.00 | 1 payment(s) | Last payment: Jan 1, 2024"
```

---

## Dashboard APIs

### 16. Get Portfolio Summary

**GET** `/portfolio/summary?time_range=ALL`

**Description**: Get high-level portfolio overview.

**Query Parameters**:
- `time_range` (string, optional): `1D`, `1W`, `1M`, `3M`, `1Y`, `ALL` (default: `ALL`)

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

**User-Friendly Messages**:
- **Positive Change**: "📈 Your portfolio is up ${today_change} ({today_change_percentage}%) today"
- **Negative Change**: "📉 Your portfolio is down ${today_change} ({today_change_percentage}%) today"
- **No Change**: "Your portfolio value is unchanged today"
- **Display Format**: 
  - "Net Worth: ${total_portfolio_value}"
  - "Assets: ${total_assets}"
  - "Debts: ${total_debts}"
  - "Cash: ${cash_available}"
  - "Total Returns: ${total_returns} ({return_percentage}%)"

**Frontend Usage**:
```javascript
// Display portfolio summary cards
const response = await fetch('/api/v1/portfolio/summary?time_range=ALL', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const summary = await response.json();

// Format numbers with currency
const formatCurrency = (amount) => new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD'
}).format(amount);

// Display cards:
// - Net Worth: $1,500,000.00
// - Assets: $1,400,000.00
// - Cash: $200,000.00
// - Returns: +$100,000.00 (+7.14%)
```

---

### 17. Get Portfolio Performance

**GET** `/portfolio/performance?days=365`

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

**User-Friendly Messages**:
- **Positive Returns**: "Your portfolio has gained ${total_return} ({total_return_percentage}%) over the past {period_days} days"
- **Negative Returns**: "Your portfolio has lost ${total_return} ({total_return_percentage}%) over the past {period_days} days"
- **No Returns**: "Your portfolio value is unchanged over the past {period_days} days"

**Frontend Usage**:
```javascript
// Display performance chart
const response = await fetch('/api/v1/portfolio/performance?days=365', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const performance = await response.json();

// Use charting library (Chart.js, Recharts, etc.)
const chartData = performance.daily_returns.map(item => ({
  date: item.date,
  value: item.value,
  return: item.return
}));

// Display metrics:
// "Total Return: +$100,000.00 (+7.14%)"
// "Current Value: $1,500,000.00"
// "Starting Value: $1,400,000.00"
```

---

### 18. Get Portfolio History

**GET** `/portfolio/history?days=30`

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

**User-Friendly Messages**:
- **Empty History**: "No historical data available"
- **Loading**: "Loading portfolio history..."

**Frontend Usage**:
```javascript
// Display historical chart
const response = await fetch('/api/v1/portfolio/history?days=30', {
  headers: { 'Authorization': `Bearer ${token}` }
});
const { data } = await response.json();

// Plot line chart with dates on x-axis and values on y-axis
// Use charting library to visualize trend
```

---

## Error Handling

### Standard Error Responses

All endpoints return errors in the following format:

**400 Bad Request**:
```json
{
  "detail": "Error message describing what went wrong"
}
```

**401 Unauthorized**:
```json
{
  "detail": "Not authenticated"
}
```

**403 Forbidden**:
```json
{
  "detail": "Not enough permissions"
}
```

**404 Not Found**:
```json
{
  "detail": "Resource not found"
}
```

**402 Payment Required**:
```json
{
  "detail": "Payment method required",
  "payment_intent": {
    "id": "pi_xxx",
    "client_secret": "pi_xxx_secret_xxx"
  }
}
```

**500 Internal Server Error**:
```json
{
  "detail": "Internal server error"
}
```

### User-Friendly Error Messages

**401 Unauthorized**:
- "Your session has expired. Please log in again."
- "Please log in to continue"

**403 Forbidden**:
- "You don't have permission to perform this action"
- "This feature requires a premium subscription"

**404 Not Found**:
- "The requested resource was not found"
- "Subscription not found"

**400 Bad Request**:
- Show the specific error message from `detail` field
- Common messages:
  - "Invalid plan_id provided" → "Please select a valid subscription plan"
  - "billing_cycle must be 'monthly' or 'annual'" → "Please select a valid billing cycle"
  - "No active subscription to cancel" → "You don't have an active subscription to cancel"

**402 Payment Required**:
- "Payment required to continue"
- "Please add a payment method to activate your subscription"

**500 Internal Server Error**:
- "Something went wrong. Please try again later."
- "We're experiencing technical difficulties. Please try again in a few moments."

### Error Handling Example

```javascript
async function handleApiCall(url, options) {
  try {
    const response = await fetch(url, options);
    
    if (!response.ok) {
      const error = await response.json();
      
      switch (response.status) {
        case 401:
          // Redirect to login
          window.location.href = '/login';
          break;
        case 403:
          showError('You don\'t have permission to perform this action');
          break;
        case 404:
          showError('Resource not found');
          break;
        case 400:
          showError(error.detail || 'Invalid request');
          break;
        case 402:
          // Handle payment required
          const { payment_intent } = error;
          showPaymentForm(payment_intent);
          break;
        case 500:
          showError('Something went wrong. Please try again later.');
          break;
        default:
          showError(error.detail || 'An error occurred');
      }
      
      return null;
    }
    
    return await response.json();
  } catch (error) {
    showError('Network error. Please check your connection and try again.');
    return null;
  }
}
```

---

## User-Friendly Messages Summary

### Success Messages

- **Subscription Activated**: "🎉 Your {plan_name} subscription is now active! You can access all premium features."
- **Payment Successful**: "Payment processed successfully"
- **Payment Method Added**: "Payment method added successfully"
- **Subscription Cancelled**: "Subscription cancelled successfully. You'll continue to have access until {date}."
- **Subscription Renewed**: "Your subscription has been renewed! Welcome back to {plan_name}."
- **Plan Upgraded**: "🎉 You've successfully upgraded to {plan_name}! New features are now available."

### Warning Messages

- **Limit Reached**: "⚠️ You've reached your {resource} limit. Upgrade to add more."
- **Near Limit**: "⚠️ You're running low on {resource}. Consider upgrading."
- **Subscription Expiring**: "Your subscription expires on {date}. Renew now to continue using premium features."
- **Cancelled Subscription**: "Your subscription will end on {date}. You'll lose access to premium features after this date."

### Info Messages

- **No Subscription**: "You're currently on the free plan. Upgrade to unlock premium features."
- **Feature Unavailable**: "Upgrade to {plan_name} to unlock this feature"
- **Payment Required**: "Please complete payment to activate your subscription"
- **Loading**: "Loading..." (with spinner)

### Error Messages

- **Network Error**: "Network error. Please check your connection and try again."
- **Session Expired**: "Your session has expired. Please log in again."
- **Invalid Request**: Show specific error message from API
- **Server Error**: "Something went wrong. Please try again later."

---

## Integration Tips

1. **Always check authentication**: Include `Authorization: Bearer <token>` header
2. **Handle 401 errors**: Redirect to login page
3. **Handle 402 errors**: Show payment form using `payment_intent.client_secret`
4. **Format currency**: Use `Intl.NumberFormat` for currency display
5. **Format dates**: Use `Intl.DateTimeFormat` for date display
6. **Show loading states**: Display spinners while API calls are in progress
7. **Handle empty states**: Show friendly messages when no data is available
8. **Validate inputs**: Validate on frontend before making API calls
9. **Use pagination**: Implement pagination for list endpoints
10. **Error boundaries**: Wrap API calls in try-catch blocks

---

## Example Integration

```javascript
// Example: Complete subscription activation flow
async function activateSubscription(planId, billingCycle, couponCode) {
  try {
    // Show loading
    showLoading('Activating subscription...');
    
    // Create subscription
    const response = await fetch('/api/v1/subscriptions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        plan_id: planId,
        billing_cycle: billingCycle,
        coupon_code: couponCode
      })
    });
    
    if (response.status === 402) {
      // Payment required
      const { payment_intent } = await response.json();
      hideLoading();
      showPaymentForm(payment_intent);
      return;
    }
    
    if (!response.ok) {
      const error = await response.json();
      hideLoading();
      showError(error.detail || 'Failed to activate subscription');
      return;
    }
    
    const { subscription, payment_intent } = await response.json();
    
    if (payment_intent) {
      // Confirm payment with Stripe
      const { error } = await stripe.confirmCardPayment(
        payment_intent.client_secret,
        {
          payment_method: {
            card: cardElement
          }
        }
      );
      
      if (error) {
        hideLoading();
        showError(error.message);
        return;
      }
    }
    
    hideLoading();
    showSuccess(`🎉 Your ${subscription.plan_name} subscription is now active!`);
    
    // Refresh subscription status
    await refreshSubscriptionStatus();
    
  } catch (error) {
    hideLoading();
    showError('Network error. Please check your connection and try again.');
  }
}
```

---

**Last Updated**: 2024-01-15  
**API Version**: v1
