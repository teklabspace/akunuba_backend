# All Required APIs Summary

**Purpose**: Complete list of all APIs required for plans, subscription management, payments, and dashboard functionality.

**Base URL**: `/api/v1`  
**Authentication**: All endpoints require `Authorization: Bearer <token>` header (except webhook).

**Total APIs**: **29 endpoints**

---

## 📋 Complete API List

### 1. Subscription & Plans APIs (9 endpoints)

#### Core Subscription APIs (6 endpoints)
1. **GET** `/subscriptions/plans` - Get available subscription plans
2. **GET** `/subscriptions` - Get current subscription status
3. **POST** `/subscriptions` - Create/activate subscription
4. **GET** `/subscriptions/permissions` - Get feature permissions
5. **GET** `/subscriptions/limits` - Get usage limits & current usage
6. **GET** `/subscriptions/history` - Get subscription history

#### Subscription Management APIs (3 endpoints)
7. **POST** `/subscriptions/cancel` - Cancel subscription
8. **POST** `/subscriptions/renew` - Renew expired subscription
9. **PUT** `/subscriptions/upgrade` - Upgrade/downgrade plan or billing cycle

---

### 2. Payment APIs (7 endpoints)

#### Core Payment APIs (5 endpoints)
1. **POST** `/payments/create-intent` - Create Stripe payment intent
2. **GET** `/payments/payment-methods` - Get saved payment methods
3. **POST** `/payments/payment-methods` - Add/save payment method
4. **GET** `/payments/history` - Get payment history
5. **GET** `/payments/stats` - Get payment statistics

#### Payment Management APIs (2 endpoints)
6. **DELETE** `/payments/payment-methods/{method_id}` - Delete payment method
7. **POST** `/payments/webhook` - Handle Stripe webhook events

---

### 3. Dashboard APIs (13 endpoints)

#### User & Account APIs (3 endpoints)
1. **GET** `/users/me` - Get user profile
2. **GET** `/accounts/me` - Get account information
3. **GET** `/accounts/stats` - Get account statistics

#### Portfolio APIs (7 endpoints)
4. **GET** `/portfolio/summary` - Get portfolio summary
5. **GET** `/portfolio/performance` - Get portfolio performance metrics
6. **GET** `/portfolio/history` - Get portfolio historical data
7. **GET** `/portfolio/allocation` - Get asset allocation breakdown
8. **GET** `/portfolio/holdings/top` - Get top holdings
9. **GET** `/portfolio/activity/recent` - Get recent activity
10. **GET** `/portfolio/risk` - Get risk metrics

#### Market & Alerts APIs (2 endpoints)
11. **GET** `/portfolio/market-summary` - Get market summary
12. **GET** `/portfolio/alerts` - Get portfolio alerts

#### Banking APIs (1 endpoint)
13. **GET** `/banking/accounts` - Get linked bank accounts

---

## 🎯 Priority Breakdown

### High Priority (MVP - 15 endpoints)

**Must have for initial launch:**

#### Subscription (4 endpoints)
- ✅ `GET /subscriptions/plans`
- ✅ `GET /subscriptions`
- ✅ `POST /subscriptions`
- ✅ `GET /subscriptions/permissions`

#### Payments (4 endpoints)
- ✅ `POST /payments/create-intent`
- ✅ `GET /payments/payment-methods`
- ✅ `POST /payments/payment-methods`
- ✅ `POST /payments/webhook` (critical for payment status)

#### Dashboard (7 endpoints)
- ✅ `GET /users/me`
- ✅ `GET /portfolio/summary`
- ✅ `GET /portfolio/performance`
- ✅ `GET /portfolio/history`
- ✅ `GET /accounts/me`
- ✅ `GET /accounts/stats`
- ✅ `GET /banking/accounts`

---

### Medium Priority (Enhancements - 14 endpoints)

**Can be added after MVP:**

#### Subscription Management (5 endpoints)
- `POST /subscriptions/cancel`
- `POST /subscriptions/renew`
- `PUT /subscriptions/upgrade`
- `GET /subscriptions/limits`
- `GET /subscriptions/history`

#### Payment Management (3 endpoints)
- `DELETE /payments/payment-methods/{id}`
- `GET /payments/history`
- `GET /payments/stats`

#### Dashboard Enhancements (6 endpoints)
- `GET /portfolio/allocation`
- `GET /portfolio/holdings/top`
- `GET /portfolio/activity/recent`
- `GET /portfolio/market-summary`
- `GET /portfolio/alerts`
- `GET /portfolio/risk`

---

## 📝 Quick Reference by Category

### Plans & Subscription Flow
```
1. User views plans → GET /subscriptions/plans
2. Check current status → GET /subscriptions
3. Select plan → POST /subscriptions
4. Process payment → POST /payments/create-intent
5. Webhook confirms → POST /payments/webhook
6. Check permissions → GET /subscriptions/permissions
7. Access dashboard → Dashboard APIs
```

### Dashboard Load Flow
```
1. Check subscription → GET /subscriptions
2. Get permissions → GET /subscriptions/permissions
3. Load user data → GET /users/me
4. Load portfolio (parallel):
   - GET /portfolio/summary
   - GET /portfolio/performance?days=365
   - GET /portfolio/history?days=365
5. Load account data:
   - GET /accounts/me
   - GET /accounts/stats
   - GET /banking/accounts
6. Load market data:
   - GET /portfolio/market-summary
   - GET /portfolio/alerts
```

### Subscription Management Flow
```
1. View current plan → GET /subscriptions
2. Cancel → POST /subscriptions/cancel
3. Renew → POST /subscriptions/renew
4. Upgrade/Downgrade → PUT /subscriptions/upgrade
5. View history → GET /subscriptions/history
6. Check limits → GET /subscriptions/limits
```

---

## ⚠️ Important Notes

### Critical Implementation Requirements

1. **Payment Webhook** (`POST /payments/webhook`)
   - Must verify Stripe webhook signatures
   - Handle all payment and subscription events
   - Update subscription status automatically

2. **Account Stats** (`GET /accounts/stats`)
   - Must use timezone-aware datetime calculations
   - Currently returns 500 errors - needs fix

3. **Payment Stats** (`GET /payments/stats`)
   - Currently returns 405 Method Not Allowed
   - Must be implemented

4. **Error Handling**
   - All endpoints must return JSON errors (not HTML)
   - Format: `{ "detail": "Error message" }`

5. **Authentication**
   - All endpoints require `Authorization: Bearer <token>`
   - Webhook endpoint uses `Stripe-Signature` header

---

## 📚 Detailed Documentation

For complete API specifications with request/response formats, see:
- **Backend Team**: `doc/PLANS_AND_DASHBOARD_APIS_REQUIREMENTS.md`
- **Frontend Team**: `doc/FRONTEND_API_REQUIREMENTS.md`

---

## Summary

- **Total Endpoints**: 29
- **High Priority (MVP)**: 15 endpoints
  - Subscription: 4 endpoints
  - Payments: 4 endpoints
  - Dashboard: 7 endpoints
- **Medium Priority**: 14 endpoints
  - Subscription Management: 5 endpoints
  - Payment Management: 3 endpoints
  - Dashboard Enhancements: 6 endpoints
- **Subscription APIs**: 9 endpoints
- **Payment APIs**: 7 endpoints
- **Dashboard APIs**: 13 endpoints

All endpoints are documented with complete request/response specifications in the detailed documentation files.
