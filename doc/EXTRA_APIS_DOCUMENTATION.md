# Extra APIs Documentation - Flow, Request/Response, and Messages

**Date**: Complete Documentation  
**Status**: ✅ These APIs ARE Important and Part of Design

---

## Summary

**YES, these APIs are important and part of the design!** They are actively used in the frontend:

- ✅ **Crypto Portfolio APIs** - Used in `/dashboard/portfolio/crypto` page
- ✅ **Trade Engine APIs** - Used in `/dashboard/portfolio/trade-engine` page  
- ✅ **Cash Flow APIs** - Used in `/dashboard/portfolio/cash-flow` page
- ✅ **Refund/Invoice APIs** - Used in settings/payments management
- ⚠️ **Portfolio Benchmark** - May be used in analytics

These are **NOT** part of the initial 29 MVP APIs, but they are **essential for the full application functionality**.

---

## 1. Payment Refunds APIs

### 1.1 Create Refund

**Endpoint**: `POST /api/v1/payments/payments/{payment_id}/refund`

**Description**: Creates a refund for a completed payment (full or partial).

**Flow**:
```
1. User views payment history
2. User selects a payment to refund
3. User clicks "Request Refund"
4. Frontend calls: POST /payments/payments/{payment_id}/refund
5. Backend processes refund via Stripe
6. Frontend shows refund status
```

**Request Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "amount": 50.00,  // Optional: partial refund amount. Omit for full refund
  "reason": "customer_request",  // "customer_request" | "duplicate" | "fraudulent"
  "metadata": {
    "refund_reason": "Customer requested refund",
    "notes": "Product not as described"
  }
}
```

**Request Fields**:
- `amount` (decimal, optional): Partial refund amount. If omitted, full refund is processed
- `reason` (string, required): Refund reason - `"customer_request"`, `"duplicate"`, or `"fraudulent"`
- `metadata` (object, optional): Additional metadata about the refund

**Response** (201 Created):
```json
{
  "refund": {
    "id": "re_xxx",
    "payment_id": "uuid",
    "amount": 50.00,
    "currency": "USD",
    "status": "pending",  // "pending" | "succeeded" | "failed"
    "reason": "customer_request",
    "created_at": "2024-01-15T10:30:00Z",
    "estimated_completion": "2024-01-17T10:30:00Z"
  },
  "message": "Refund request submitted successfully"
}
```

**Response** (400 Bad Request):
```json
{
  "detail": "Payment cannot be refunded. Reason: Payment is not completed"
}
```

**Response** (404 Not Found):
```json
{
  "detail": "Payment not found"
}
```

**User-Friendly Messages**:
- **Success**: "Refund request submitted successfully. Your refund of ${amount} will be processed within 5-10 business days."
- **Pending**: "Refund is being processed. You'll receive an email when it's completed."
- **Failed**: "Refund failed. Please contact support for assistance."
- **Error**: "Unable to process refund. {error_message}"

**Frontend Usage**:
```javascript
import { createRefund } from '@/utils/paymentsApi';

const handleRefund = async (paymentId, refundAmount, reason) => {
  try {
    const response = await createRefund(paymentId, {
      amount: refundAmount,  // Optional - omit for full refund
      reason: reason,
      metadata: {
        refund_reason: "Customer requested refund"
      }
    });
    
    if (response.refund) {
      toast.success(`Refund of $${refundAmount} requested successfully`);
    }
  } catch (error) {
    toast.error(error.detail || 'Failed to process refund');
  }
};
```

---

### 1.2 Get Refunds

**Endpoint**: `GET /api/v1/payments/payments/{payment_id}/refunds`

**Description**: Retrieves all refunds for a specific payment.

**Flow**:
```
1. User views payment details
2. Frontend calls: GET /payments/payments/{payment_id}/refunds
3. Display refund history for that payment
```

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "re_xxx",
      "payment_id": "uuid",
      "amount": 50.00,
      "currency": "USD",
      "status": "succeeded",
      "reason": "customer_request",
      "created_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-17T10:30:00Z"
    }
  ],
  "total": 1,
  "total_refunded": 50.00
}
```

**User-Friendly Messages**:
- **No Refunds**: "No refunds for this payment"
- **Display**: "Refunded: ${total_refunded} on {formatted_date}"
- **Status Labels**:
  - `pending`: "Processing"
  - `succeeded`: "Completed"
  - `failed`: "Failed"

**Frontend Usage**:
```javascript
import { getRefunds } from '@/utils/paymentsApi';

const fetchRefunds = async (paymentId) => {
  const response = await getRefunds(paymentId);
  if (response.data) {
    // Display refunds list
    response.data.forEach(refund => {
      // Show refund details
    });
  }
};
```

---

## 2. Invoice Management APIs

### 2.1 Create Invoice

**Endpoint**: `POST /api/v1/payments/invoices`

**Description**: Creates a new invoice for billing (for custom billing scenarios).

**Flow**:
```
1. Admin/user needs to create custom invoice
2. Fill invoice form (amount, description, due date)
3. Frontend calls: POST /payments/invoices
4. Invoice created and sent to customer
```

**Request Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "amount": 99.00,
  "currency": "USD",
  "description": "Premium subscription - January 2024",
  "due_date": "2024-02-01",
  "customer_email": "customer@example.com",
  "line_items": [
    {
      "description": "Premium Plan",
      "amount": 99.00,
      "quantity": 1
    }
  ],
  "metadata": {
    "subscription_id": "uuid",
    "plan_name": "Premium"
  }
}
```

**Request Fields**:
- `amount` (decimal, required): Total invoice amount
- `currency` (string, required): Currency code (default: "USD")
- `description` (string, required): Invoice description
- `due_date` (string, required): Due date in YYYY-MM-DD format
- `customer_email` (string, required): Customer email
- `line_items` (array, optional): Line items breakdown
- `metadata` (object, optional): Additional metadata

**Response** (201 Created):
```json
{
  "invoice": {
    "id": "inv_xxx",
    "amount": 99.00,
    "currency": "USD",
    "status": "draft",  // "draft" | "open" | "paid" | "void" | "uncollectible"
    "description": "Premium subscription - January 2024",
    "due_date": "2024-02-01",
    "invoice_url": "https://invoice.example.com/inv_xxx",
    "created_at": "2024-01-15T10:30:00Z"
  },
  "message": "Invoice created successfully"
}
```

**User-Friendly Messages**:
- **Success**: "Invoice created successfully. Invoice ID: {invoice_id}"
- **Error**: "Failed to create invoice. {error_message}"

---

### 2.2 List Invoices

**Endpoint**: `GET /api/v1/payments/invoices`

**Description**: Retrieves all invoices for the authenticated user.

**Query Parameters**:
- `status_filter` (string, optional): Filter by status (`draft`, `open`, `paid`, `void`, `uncollectible`)
- `limit` (integer, optional): Number of invoices (default: 20, max: 100)
- `offset` (integer, optional): Pagination offset (default: 0)

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "inv_xxx",
      "amount": 99.00,
      "currency": "USD",
      "status": "open",
      "description": "Premium subscription - January 2024",
      "due_date": "2024-02-01",
      "paid_at": null,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

**User-Friendly Messages**:
- **No Invoices**: "No invoices found"
- **Status Labels**:
  - `draft`: "Draft"
  - `open`: "Unpaid"
  - `paid`: "Paid"
  - `void`: "Void"
  - `uncollectible`: "Uncollectible"

---

### 2.3 Get Invoice Details

**Endpoint**: `GET /api/v1/payments/invoices/{invoice_id}`

**Description**: Retrieves detailed information about a specific invoice.

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "invoice": {
    "id": "inv_xxx",
    "amount": 99.00,
    "currency": "USD",
    "status": "open",
    "description": "Premium subscription - January 2024",
    "due_date": "2024-02-01",
    "invoice_url": "https://invoice.example.com/inv_xxx",
    "line_items": [
      {
        "description": "Premium Plan",
        "amount": 99.00,
        "quantity": 1
      }
    ],
    "paid_at": null,
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

---

### 2.4 Pay Invoice

**Endpoint**: `POST /api/v1/payments/invoices/{invoice_id}/pay`

**Description**: Processes payment for an open invoice.

**Request Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "payment_method_id": "pm_xxx"  // Optional: use saved payment method
}
```

**Response** (200 OK):
```json
{
  "invoice": {
    "id": "inv_xxx",
    "status": "paid",
    "paid_at": "2024-01-15T11:00:00Z"
  },
  "payment_intent": {
    "id": "pi_xxx",
    "client_secret": "pi_xxx_secret_xxx"
  },
  "message": "Invoice paid successfully"
}
```

**User-Friendly Messages**:
- **Success**: "Invoice paid successfully"
- **Payment Required**: "Please complete payment to pay this invoice"
- **Already Paid**: "This invoice has already been paid"

---

## 3. Portfolio Benchmark API

### 3.1 Get Portfolio Benchmark

**Endpoint**: `GET /api/v1/portfolio/benchmark`

**Description**: Compares portfolio performance with a benchmark (e.g., S&P 500).

**Flow**:
```
1. User views portfolio performance
2. User selects benchmark (S&P 500, Dow, etc.)
3. Frontend calls: GET /portfolio/benchmark?benchmark_value={value}
4. Display comparison chart
```

**Query Parameters**:
- `benchmark_value` (decimal, required): Benchmark value to compare against

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "portfolio_value": 1500000.00,
  "benchmark_value": 1400000.00,
  "difference": 100000.00,
  "difference_percentage": 7.14,
  "outperformance": true,
  "comparison_data": [
    {
      "date": "2024-01-01",
      "portfolio": 1400000.00,
      "benchmark": 1350000.00
    }
  ]
}
```

**User-Friendly Messages**:
- **Outperforming**: "Your portfolio is outperforming the benchmark by {difference_percentage}%"
- **Underperforming**: "Your portfolio is underperforming the benchmark by {difference_percentage}%"
- **Equal**: "Your portfolio matches the benchmark performance"

**Frontend Usage**:
```javascript
import { getPortfolioBenchmark } from '@/utils/portfolioApi';

const compareWithBenchmark = async (benchmarkValue) => {
  const response = await getPortfolioBenchmark(benchmarkValue);
  // Display comparison chart
};
```

---

## 4. Crypto Portfolio APIs

### 4.1 Get Crypto Portfolio Summary

**Endpoint**: `GET /api/v1/portfolio/crypto/summary`

**Description**: Get high-level crypto portfolio overview.

**Used In**: `/dashboard/portfolio/crypto` page

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "total_value": 50000.00,
  "total_cost": 45000.00,
  "total_return": 5000.00,
  "return_percentage": 11.11,
  "holdings_count": 5,
  "top_holding": {
    "symbol": "BTC",
    "value": 30000.00,
    "percentage": 60.0
  }
}
```

**User-Friendly Messages**:
- **Display**: "Total Crypto Value: ${total_value} | Return: ${total_return} ({return_percentage}%)"

---

### 4.2 Get Crypto Performance

**Endpoint**: `GET /api/v1/portfolio/crypto/performance`

**Description**: Get crypto performance metrics over time.

**Query Parameters**:
- `time_range` (string, required): `24h`, `7d`, `30d`, `90d`, `1y`, `all`
- `metric` (string, required): `value-over-time`, `return-rate`, `risk-exposure`

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "data": [
    {
      "date": "2024-01-15",
      "value": 50000.00,
      "return": 5.0,
      "risk": 2.5
    }
  ]
}
```

**Used In**: Crypto portfolio page performance charts

---

### 4.3 Get Crypto Breakdown

**Endpoint**: `GET /api/v1/portfolio/crypto/breakdown`

**Description**: Get crypto portfolio breakdown by category.

**Query Parameters**:
- `group_by` (string, required): `value`, `return`, `risk`

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "data": [
    {
      "category": "Bitcoin",
      "value": 30000.00,
      "percentage": 60.0
    }
  ]
}
```

---

### 4.4 Get Crypto Holdings

**Endpoint**: `GET /api/v1/portfolio/crypto/holdings`

**Description**: Get detailed crypto holdings list.

**Query Parameters**:
- `sort_by` (string, optional): `value`, `return`, `name`
- `order` (string, optional): `asc`, `desc`

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "data": [
    {
      "symbol": "BTC",
      "name": "Bitcoin",
      "quantity": 0.5,
      "value": 30000.00,
      "cost_basis": 28000.00,
      "return": 2000.00,
      "return_percentage": 7.14
    }
  ]
}
```

---

## 5. Cash Flow APIs

### 5.1 Get Cash Flow Summary

**Endpoint**: `GET /api/v1/portfolio/cash-flow/summary`

**Description**: Get cash flow summary for a period.

**Used In**: `/dashboard/portfolio/cash-flow` page

**Query Parameters**:
- `period` (string, required): `month`, `quarter`, `year`, `custom`
- `start_date` (string, optional): Start date (YYYY-MM-DD) for custom period
- `end_date` (string, optional): End date (YYYY-MM-DD) for custom period

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "total_income": 10000.00,
  "total_expenses": 5000.00,
  "net_cash_flow": 5000.00,
  "period": "month",
  "start_date": "2024-01-01",
  "end_date": "2024-01-31"
}
```

**User-Friendly Messages**:
- **Positive Flow**: "Net Cash Flow: +${net_cash_flow} this {period}"
- **Negative Flow**: "Net Cash Flow: -${net_cash_flow} this {period}"

---

### 5.2 Get Cash Flow Trends

**Endpoint**: `GET /api/v1/portfolio/cash-flow/trends`

**Description**: Get cash flow trends over time.

**Query Parameters**:
- `period` (string, required): `month`, `quarter`, `year`, `custom`
- `start_date` (string, optional): Start date
- `end_date` (string, optional): End date
- `granularity` (string, optional): `daily`, `weekly`, `monthly`

**Response** (200 OK):
```json
{
  "data": [
    {
      "date": "2024-01-01",
      "income": 1000.00,
      "expenses": 500.00,
      "net": 500.00
    }
  ]
}
```

---

### 5.3 Get Cash Flow Transactions

**Endpoint**: `GET /api/v1/portfolio/cash-flow/transactions`

**Description**: Get cash flow transactions with filtering.

**Query Parameters**:
- `period` (string, required): `month`, `quarter`, `year`, `custom`
- `start_date` (string, optional): Start date
- `end_date` (string, optional): End date
- `type` (string, optional): `income`, `expense`, `all`
- `category` (string, optional): Category filter
- `min_amount` (decimal, optional): Minimum amount
- `max_amount` (decimal, optional): Maximum amount
- `page` (integer, optional): Page number
- `limit` (integer, optional): Items per page

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "uuid",
      "type": "income",
      "category": "salary",
      "amount": 5000.00,
      "description": "Monthly salary",
      "date": "2024-01-15",
      "account": "Chase Checking"
    }
  ],
  "pagination": {
    "total": 10,
    "page": 1,
    "limit": 20,
    "total_pages": 1
  }
}
```

---

### 5.4 Get Cash Flow Accounts

**Endpoint**: `GET /api/v1/portfolio/cash-flow/accounts`

**Description**: Get accounts used for cash flow tracking.

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Chase Checking",
      "type": "checking",
      "balance": 5000.00
    }
  ]
}
```

---

### 5.5 Create Transfer

**Endpoint**: `POST /api/v1/portfolio/cash-flow/transfers`

**Description**: Create a transfer between accounts.

**Request Body**:
```json
{
  "from_account_id": "uuid",
  "to_account_id": "uuid",
  "amount": 1000.00,
  "description": "Transfer to savings",
  "date": "2024-01-15"
}
```

**Response** (201 Created):
```json
{
  "transfer": {
    "id": "uuid",
    "status": "pending",
    "amount": 1000.00,
    "created_at": "2024-01-15T10:30:00Z"
  },
  "message": "Transfer initiated successfully"
}
```

---

### 5.6 Get Transfer Status

**Endpoint**: `GET /api/v1/portfolio/cash-flow/transfers/{transfer_id}`

**Description**: Get transfer status.

**Response** (200 OK):
```json
{
  "transfer": {
    "id": "uuid",
    "status": "completed",
    "amount": 1000.00,
    "completed_at": "2024-01-15T11:00:00Z"
  }
}
```

---

## 6. Trade Engine APIs

### 6.1 Search Assets

**Endpoint**: `GET /api/v1/portfolio/trade-engine/search`

**Description**: Search for assets to trade.

**Used In**: `/dashboard/portfolio/trade-engine` page

**Query Parameters**:
- `query` (string, required): Search query (symbol or name)
- `asset_class` (string, optional): `stock`, `crypto`, `bond`, etc.
- `limit` (integer, optional): Number of results (default: 10)

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "data": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "asset_class": "stock",
      "current_price": 200.00,
      "exchange": "NASDAQ"
    }
  ]
}
```

**User-Friendly Messages**:
- **No Results**: "No assets found matching '{query}'"
- **Loading**: "Searching assets..."

---

### 6.2 Get Asset Details

**Endpoint**: `GET /api/v1/portfolio/trade-engine/assets/{symbol}`

**Description**: Get detailed asset information for trading.

**Request Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "asset": {
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "current_price": 200.00,
    "change": 2.50,
    "change_percentage": 1.25,
    "volume": 50000000,
    "market_cap": 3000000000000,
    "exchange": "NASDAQ"
  }
}
```

---

### 6.3 Get Recent Trades

**Endpoint**: `GET /api/v1/portfolio/trade-engine/recent-trades`

**Description**: Get recent trades.

**Query Parameters**:
- `symbol` (string, optional): Filter by symbol
- `limit` (integer, optional): Number of trades (default: 10)

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "uuid",
      "symbol": "AAPL",
      "type": "buy",
      "quantity": 10,
      "price": 200.00,
      "total": 2000.00,
      "status": "completed",
      "executed_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

---

### 6.4 Get Trading History

**Endpoint**: `GET /api/v1/portfolio/trade-engine/assets/{symbol}/history`

**Description**: Get trading history for a specific asset.

**Response** (200 OK):
```json
{
  "data": [
    {
      "date": "2024-01-15",
      "price": 200.00,
      "volume": 1000
    }
  ]
}
```

---

### 6.5 Get Brokerage Accounts

**Endpoint**: `GET /api/v1/portfolio/trade-engine/accounts`

**Description**: Get linked brokerage accounts.

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Fidelity Account",
      "account_number": "****4321",
      "balance": 50000.00,
      "type": "brokerage"
    }
  ]
}
```

---

### 6.6 Place Order

**Endpoint**: `POST /api/v1/portfolio/trade-engine/orders`

**Description**: Place a trading order.

**Used In**: Trade engine page - order placement

**Request Body**:
```json
{
  "symbol": "AAPL",
  "order_type": "buy",  // "buy" | "sell"
  "order_mode": "market",  // "market" | "limit"
  "quantity": 10,
  "limit_price": 185.92,  // Required if order_mode is "limit"
  "brokerage_account": "****4321",
  "duration": "day-only",  // "day-only" | "good-till-canceled"
  "notes": "Investment in tech sector"
}
```

**Response** (201 Created):
```json
{
  "order": {
    "id": "uuid",
    "symbol": "AAPL",
    "status": "pending",
    "quantity": 10,
    "estimated_total": 2000.00,
    "created_at": "2024-01-15T10:30:00Z"
  },
  "message": "Order placed successfully"
}
```

**User-Friendly Messages**:
- **Success**: "Order placed successfully! Order ID: {order_id}"
- **Pending**: "Order is being processed..."
- **Failed**: "Order failed. {error_message}"

---

### 6.7 Get Order Status

**Endpoint**: `GET /api/v1/portfolio/trade-engine/orders/{order_id}`

**Description**: Get order status.

**Response** (200 OK):
```json
{
  "order": {
    "id": "uuid",
    "symbol": "AAPL",
    "status": "completed",
    "quantity": 10,
    "executed_price": 200.00,
    "total": 2000.00,
    "executed_at": "2024-01-15T10:35:00Z"
  }
}
```

---

### 6.8 Cancel Order

**Endpoint**: `DELETE /api/v1/portfolio/trade-engine/orders/{order_id}`

**Description**: Cancel a pending order.

**Response** (200 OK):
```json
{
  "message": "Order cancelled successfully"
}
```

**User-Friendly Messages**:
- **Success**: "Order cancelled successfully"
- **Error**: "Cannot cancel order. Order is already {status}"

---

## Summary

### APIs by Importance

**✅ Critical (Used in Active Pages)**:
- Crypto Portfolio APIs (4) - `/dashboard/portfolio/crypto`
- Trade Engine APIs (8) - `/dashboard/portfolio/trade-engine`
- Cash Flow APIs (6) - `/dashboard/portfolio/cash-flow`

**✅ Important (Used in Settings)**:
- Refund APIs (2) - Payment management
- Invoice APIs (4) - Billing management

**⚠️ Optional**:
- Portfolio Benchmark (1) - Analytics enhancement

### Total Extra APIs: 25 endpoints

These APIs are **essential for the full application** but are **not part of the initial 29 MVP APIs** that the backend team needs to implement first.

---

**Status**: ✅ Documentation Complete  
**All APIs Documented**: 25 endpoints  
**Used in Production**: Yes
