# Backend Team - API Implementation Request

**From**: Frontend Team  
**Date**: Implementation Request  
**Subject**: Subscription Plans & Dashboard APIs Implementation

---

## Overview

Hi Backend Team,

We've completed the frontend implementation for the subscription plans flow and dashboard functionality. To complete the integration, we need the following APIs implemented on the backend.

**Total APIs Required**: **29 endpoints**

---

## Documentation Provided

We've prepared comprehensive documentation for you:

1. **`PLANS_AND_DASHBOARD_APIS_REQUIREMENTS.md`** (Primary Document)
   - Complete API specifications with request/response formats
   - Detailed field descriptions
   - Error handling requirements
   - Implementation notes
   - **This is your main reference document**

2. **`ALL_REQUIRED_APIS_SUMMARY.md`** (Quick Reference)
   - Complete list of all 29 APIs
   - Priority breakdown
   - Quick reference flows
   - Summary of critical requirements

3. **`FRONTEND_API_REQUIREMENTS.md`** (Frontend Integration Guide)
   - When each API is called
   - Frontend usage examples
   - Integration flows
   - Error handling patterns

---

## Priority Breakdown

### 🚨 High Priority (MVP) - 15 Endpoints

**Must be implemented first for initial launch:**

#### Subscription APIs (4 endpoints)
- `GET /api/v1/subscriptions/plans` - Get available plans
- `GET /api/v1/subscriptions` - Get current subscription status
- `POST /api/v1/subscriptions` - Create/activate subscription
- `GET /api/v1/subscriptions/permissions` - Get feature permissions

#### Payment APIs (4 endpoints)
- `POST /api/v1/payments/create-intent` - Create Stripe payment intent
- `GET /api/v1/payments/payment-methods` - Get saved payment methods
- `POST /api/v1/payments/payment-methods` - Add payment method
- `POST /api/v1/payments/webhook` - **CRITICAL** - Handle Stripe webhooks

#### Dashboard APIs (7 endpoints)
- `GET /api/v1/users/me` - User profile
- `GET /api/v1/portfolio/summary` - Portfolio overview
- `GET /api/v1/portfolio/performance` - Performance metrics
- `GET /api/v1/portfolio/history` - Historical data
- `GET /api/v1/accounts/me` - Account information
- `GET /api/v1/accounts/stats` - Account statistics
- `GET /api/v1/banking/accounts` - Linked bank accounts

### 📋 Medium Priority (Enhancements) - 14 Endpoints

**Can be implemented after MVP:**

#### Subscription Management (5 endpoints)
- `POST /api/v1/subscriptions/cancel` - Cancel subscription
- `POST /api/v1/subscriptions/renew` - Renew expired subscription
- `PUT /api/v1/subscriptions/upgrade` - Upgrade/downgrade plan or billing cycle
- `GET /api/v1/subscriptions/limits` - Get usage limits & current usage
- `GET /api/v1/subscriptions/history` - Get subscription history

#### Payment Management (3 endpoints)
- `DELETE /api/v1/payments/payment-methods/{method_id}` - Delete payment method
- `GET /api/v1/payments/history` - Get payment history
- `GET /api/v1/payments/stats` - Get payment statistics

#### Dashboard Enhancements (6 endpoints)
- `GET /api/v1/portfolio/allocation` - Asset allocation breakdown
- `GET /api/v1/portfolio/holdings/top` - Top portfolio holdings
- `GET /api/v1/portfolio/activity/recent` - Recent portfolio activity
- `GET /api/v1/portfolio/market-summary` - Market summary and benchmarks
- `GET /api/v1/portfolio/alerts` - Portfolio alerts
- `GET /api/v1/portfolio/risk` - Portfolio risk metrics

---

## Critical Implementation Notes

### 1. Payment Webhook (CRITICAL) ⚠️
- **Endpoint**: `POST /api/v1/payments/webhook`
- **Must verify Stripe webhook signatures** for security
- Handles payment status updates and subscription lifecycle events
- **This is essential** for payment processing to work correctly
- **Webhook Events to Handle**:
  - `payment_intent.succeeded` - Payment completed successfully
  - `payment_intent.payment_failed` - Payment failed
  - `customer.subscription.created` - Subscription created
  - `customer.subscription.updated` - Subscription updated
  - `customer.subscription.deleted` - Subscription canceled
  - `invoice.payment_succeeded` - Invoice paid successfully
  - `invoice.payment_failed` - Invoice payment failed

### 2. Account Stats Timezone Issue ⚠️
- **Endpoint**: `GET /api/v1/accounts/stats`
- Currently returns 500 errors due to timezone-aware datetime calculations
- **Must use timezone-aware datetime math**:
  ```python
  from datetime import datetime, timezone
  
  # Correct approach
  now = datetime.now(timezone.utc)
  account_age_days = (now - account.created_at).days
  
  # Ensure account.created_at is timezone-aware
  if account.created_at.tzinfo is None:
      account.created_at = account.created_at.replace(tzinfo=timezone.utc)
  ```

### 3. Payment Stats Implementation ⚠️
- **Endpoint**: `GET /api/v1/payments/stats`
- Currently returns 405 Method Not Allowed
- Must be implemented according to spec in `PLANS_AND_DASHBOARD_APIS_REQUIREMENTS.md`

### 4. Error Handling
- **All endpoints must return JSON errors** (not HTML):
  ```json
  {
    "detail": "Error message here"
  }
  ```
- Use proper HTTP status codes:
  - `200` - Success
  - `201` - Created
  - `400` - Bad Request (invalid input)
  - `401` - Unauthorized (missing/invalid token)
  - `402` - Payment Required
  - `403` - Forbidden
  - `404` - Not Found
  - `422` - Unprocessable Entity
  - `500` - Internal Server Error

### 5. Authentication
- All endpoints require `Authorization: Bearer <token>` header
- Webhook endpoint uses `Stripe-Signature` header for verification (not Bearer token)

### 6. Date Formats
- Use ISO 8601 format: `"2024-01-01T00:00:00Z"`
- All timestamps must be timezone-aware (UTC)
- Never return naive datetime objects

### 7. Currency & Numbers
- All monetary values as decimals (e.g., `199.00`)
- Use proper decimal precision (2 decimal places for currency)
- Use `Decimal` type for financial calculations to avoid floating-point errors

### 8. Pagination
- Use `limit` and `offset` query parameters for list endpoints
- Default `limit`: 20
- Maximum `limit`: 100
- Default `offset`: 0
- Always return pagination metadata:
  ```json
  {
    "data": [...],
    "total": 100,
    "limit": 20,
    "offset": 0
  }
  ```

---

## Request/Response Format

All APIs follow these conventions:

- **Base URL**: `/api/v1`
- **Request**: JSON body with `Content-Type: application/json`
- **Response**: JSON with proper status codes
- **Field Naming**: Use `snake_case` in API responses (frontend will transform to `camelCase`)
- **Content-Type**: `application/json` for all responses

---

## Integration Flow

### Subscription Activation Flow
```
1. User views plans → GET /subscriptions/plans
2. User selects plan → POST /subscriptions
   - Request: { "plan_id": "plan_pro", "billing_cycle": "monthly" }
   - Response: { "subscription": {...}, "payment_intent": {...} }
3. Backend returns payment_intent with client_secret
4. Frontend processes payment via Stripe.js
5. Stripe sends webhook → POST /payments/webhook
   - Backend verifies signature
   - Backend updates subscription status
6. User accesses dashboard → Dashboard APIs
```

### Dashboard Load Flow
```
1. Check subscription → GET /subscriptions
   - If no active subscription → Redirect to plans page
2. Get permissions → GET /subscriptions/permissions
   - Used to show/hide features in UI
3. Load user data → GET /users/me
4. Load portfolio data (parallel requests):
   - GET /portfolio/summary?time_range=ALL
   - GET /portfolio/performance?days=365
   - GET /portfolio/history?days=365
5. Load account data (parallel requests):
   - GET /accounts/me
   - GET /accounts/stats
   - GET /banking/accounts
```

---

## Testing Requirements

Please ensure:

1. ✅ All endpoints return proper JSON responses (never HTML)
2. ✅ Error responses follow the `{ "detail": "message" }` format
3. ✅ Authentication is properly validated on all endpoints
4. ✅ Webhook signature verification works correctly
5. ✅ Timezone calculations are correct (no 500 errors on `/accounts/stats`)
6. ✅ All required fields are present in responses
7. ✅ Optional fields are handled gracefully (null or omitted)
8. ✅ Pagination works correctly with limit/offset
9. ✅ All monetary values use proper decimal precision
10. ✅ Date formats are ISO 8601 with timezone (UTC)

---

## Example Request/Response

### Example: Create Subscription
**Request**:
```http
POST /api/v1/subscriptions
Authorization: Bearer <token>
Content-Type: application/json

{
  "plan_id": "plan_pro",
  "billing_cycle": "monthly",
  "payment_method_id": "pm_xxx",
  "coupon_code": "EARLYBIRD"
}
```

**Response (201)**:
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

**Error Response (400)**:
```json
{
  "detail": "Invalid plan_id provided"
}
```

---

## Questions or Issues?

If you have any questions about:
- API specifications
- Request/response formats
- Integration flows
- Priority clarifications
- Implementation details

Please refer to:
- **Primary Spec**: `doc/PLANS_AND_DASHBOARD_APIS_REQUIREMENTS.md`
- **Quick Reference**: `doc/ALL_REQUIRED_APIS_SUMMARY.md`
- **Frontend Guide**: `doc/FRONTEND_API_REQUIREMENTS.md`
- **Analysis**: `doc/API_DOCUMENTS_ANALYSIS.md`

---

## Timeline Recommendation

### Phase 1 (MVP - Week 1-2)
**Focus**: Core functionality for subscription activation and dashboard access

**Week 1**:
- Implement subscription APIs (4 endpoints)
- Implement payment APIs (4 endpoints)
- **Critical**: Get webhook working correctly
- Test subscription activation flow end-to-end

**Week 2**:
- Implement dashboard APIs (7 endpoints)
- **Critical**: Fix account stats timezone issue
- Test dashboard load flow
- Integration testing with frontend

### Phase 2 (Enhancements - Week 3-4)
**Focus**: Additional features and management capabilities

**Week 3**:
- Subscription management (cancel, renew, upgrade, limits, history)
- Payment management (delete payment method, history, stats)

**Week 4**:
- Dashboard enhancements (allocation, holdings, activity, market summary, alerts, risk)
- End-to-end testing
- Performance optimization

---

## Summary

- **Total APIs**: 29 endpoints
- **High Priority (MVP)**: 15 endpoints
  - Subscription: 4 endpoints
  - Payments: 4 endpoints
  - Dashboard: 7 endpoints
- **Medium Priority**: 14 endpoints
  - Subscription Management: 5 endpoints
  - Payment Management: 3 endpoints
  - Dashboard Enhancements: 6 endpoints
- **Base URL**: `/api/v1`
- **Authentication**: Bearer token required (except webhook)

All detailed specifications, request/response examples, and implementation notes are in the documentation files provided.

---

## Critical Success Factors

1. **Payment Webhook** - Must work correctly for subscription activation
2. **Timezone Handling** - Fix account stats 500 errors
3. **Error Format** - Always return JSON, never HTML
4. **Authentication** - Properly validate all requests
5. **Response Format** - Match specifications exactly for frontend compatibility

---

**Thank you for your support!** Looking forward to completing the integration. 🚀

---

**Best regards,**  
Frontend Team

---

## Document References

- `doc/PLANS_AND_DASHBOARD_APIS_REQUIREMENTS.md` - Complete API specifications
- `doc/ALL_REQUIRED_APIS_SUMMARY.md` - Quick reference and priority breakdown
- `doc/FRONTEND_API_REQUIREMENTS.md` - Frontend integration guide
- `doc/API_DOCUMENTS_ANALYSIS.md` - Documentation analysis and verification
- `doc/PRIORITY_SYNCHRONIZATION_COMPLETE.md` - Priority synchronization status
