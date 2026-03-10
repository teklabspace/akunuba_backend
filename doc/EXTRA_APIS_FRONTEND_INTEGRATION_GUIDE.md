# Extra APIs - Frontend Integration Guide

Complete API documentation for frontend developers with request/response examples and user-friendly messages.

**Base URL**: `/api/v1`  
**Authentication**: All endpoints require Bearer token in `Authorization` header  
**Content-Type**: `application/json`

---

## Table of Contents

1. [Payment Refunds APIs](#payment-refunds-apis)
2. [Invoice Management APIs](#invoice-management-apis)
3. [Portfolio Benchmark API](#portfolio-benchmark-api)
4. [Crypto Portfolio APIs](#crypto-portfolio-apis)
5. [Cash Flow APIs](#cash-flow-apis)
6. [Trade Engine APIs](#trade-engine-apis)
7. [Error Handling](#error-handling)
8. [User-Friendly Messages](#user-friendly-messages)

---

## Payment Refunds APIs

### 1. Create Refund

**POST** `/payments/payments/{payment_id}/refund`

**Description**: Creates a refund for a completed payment (full or partial).

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "amount": 50.00,  // Optional: partial refund amount. Omit for full refund
  "reason": "customer_request"  // "customer_request" | "duplicate" | "fraudulent"
}
```

**Response** (201 Created):
```json
{
  "refund": {
    "id": "uuid",
    "payment_id": "uuid",
    "amount": 50.00,
    "currency": "USD",
    "status": "pending",
    "reason": "customer_request",
    "created_at": "2024-01-15T10:30:00Z",
    "estimated_completion": "2024-01-22T10:30:00Z"
  },
  "message": "Refund request submitted successfully"
}
```

**Error Responses**:
- **400 Bad Request**: `{"detail": "Payment cannot be refunded. Reason: Payment is not completed"}`
- **404 Not Found**: `{"detail": "Payment not found"}`

**User-Friendly Messages**:
- **Success**: "Refund request submitted successfully. Your refund of $50.00 will be processed within 5-10 business days."
- **Pending**: "Refund is being processed. You'll receive an email when it's completed."
- **Failed**: "Refund failed. Please contact support for assistance."
- **Error**: "Unable to process refund. {error_message}"

**Frontend Code Example**:
```javascript
import { createRefund } from '@/utils/paymentsApi';

const handleRefund = async (paymentId, refundAmount, reason) => {
  try {
    const response = await createRefund(paymentId, {
      amount: refundAmount,  // Optional - omit for full refund
      reason: reason || "customer_request"
    });
    
    if (response.refund) {
      toast.success(
        `Refund of $${refundAmount || 'full amount'} requested successfully. ` +
        `Expected completion: ${formatDate(response.refund.estimated_completion)}`
      );
    }
  } catch (error) {
    toast.error(error.detail || 'Failed to process refund');
  }
};
```

---

### 2. Get Refunds

**GET** `/payments/payments/{payment_id}/refunds`

**Description**: Retrieves all refunds for a specific payment.

**Headers**:
```
Authorization: Bearer <token>
```

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "uuid",
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
- **Display**: "Refunded: $50.00 on January 17, 2024"
- **Status Labels**:
  - `pending`: "Processing"
  - `succeeded`: "Completed"
  - `failed`: "Failed"

**Frontend Code Example**:
```javascript
import { getRefunds } from '@/utils/paymentsApi';

const fetchRefunds = async (paymentId) => {
  const response = await getRefunds(paymentId);
  if (response.data && response.data.length > 0) {
    // Display refunds list
    response.data.forEach(refund => {
      const statusLabel = {
        'pending': 'Processing',
        'succeeded': 'Completed',
        'failed': 'Failed'
      }[refund.status] || refund.status;
      
      console.log(`Refund: $${refund.amount} - ${statusLabel}`);
    });
  } else {
    console.log('No refunds for this payment');
  }
};
```

---

## Invoice Management APIs

### 3. Create Invoice

**POST** `/payments/invoices`

**Description**: Creates a new invoice for billing.

**Headers**:
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
  "due_date": "2024-02-01"
}
```

**Response** (201 Created):
```json
{
  "id": "uuid",
  "invoice_number": "INV-2024-001",
  "amount": 99.00,
  "currency": "USD",
  "description": "Premium subscription - January 2024",
  "due_date": "2024-02-01T00:00:00Z",
  "paid_at": null,
  "payment_id": null,
  "created_at": "2024-01-15T10:30:00Z"
}
```

**User-Friendly Messages**:
- **Success**: "Invoice created successfully. Invoice ID: INV-2024-001"
- **Error**: "Failed to create invoice. {error_message}"

---

### 4. List Invoices

**GET** `/payments/invoices?status_filter=open&limit=20&offset=0`

**Description**: Retrieves all invoices for the authenticated user.

**Query Parameters**:
- `status_filter` (string, optional): Filter by status (`paid`, `unpaid`, `overdue`)
- `limit` (integer, optional): Number of invoices (default: 20, max: 100)
- `offset` (integer, optional): Pagination offset (default: 0)

**Response** (200 OK):
```json
[
  {
    "id": "uuid",
    "invoice_number": "INV-2024-001",
    "amount": 99.00,
    "currency": "USD",
    "description": "Premium subscription - January 2024",
    "due_date": "2024-02-01T00:00:00Z",
    "paid_at": null,
    "payment_id": null,
    "created_at": "2024-01-15T10:30:00Z"
  }
]
```

**User-Friendly Messages**:
- **No Invoices**: "No invoices found"
- **Status Labels**:
  - `paid`: "Paid"
  - `unpaid`: "Unpaid"
  - `overdue`: "Overdue"

---

### 5. Get Invoice Details

**GET** `/payments/invoices/{invoice_id}`

**Description**: Retrieves detailed information about a specific invoice.

**Response** (200 OK):
```json
{
  "id": "uuid",
  "invoice_number": "INV-2024-001",
  "amount": 99.00,
  "currency": "USD",
  "description": "Premium subscription - January 2024",
  "due_date": "2024-02-01T00:00:00Z",
  "paid_at": null,
  "payment_id": null,
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

### 6. Pay Invoice

**POST** `/payments/invoices/{invoice_id}/pay`

**Description**: Processes payment for an open invoice.

**Request Body**:
```json
{
  "payment_method_id": "pm_xxx"  // Optional: use saved payment method
}
```

**Response** (200 OK):
```json
{
  "id": "uuid",
  "amount": 99.00,
  "currency": "USD",
  "status": "completed",
  "payment_method": "card",
  "stripe_payment_intent_id": "pi_xxx",
  "created_at": "2024-01-15T11:00:00Z"
}
```

**User-Friendly Messages**:
- **Success**: "Invoice paid successfully"
- **Payment Required**: "Please complete payment to pay this invoice"
- **Already Paid**: "This invoice has already been paid"

---

## Portfolio Benchmark API

### 7. Compare with Benchmark

**GET** `/portfolio/benchmark?benchmark_value=1400000.00`

**Description**: Compares portfolio performance with a benchmark (e.g., S&P 500).

**Query Parameters**:
- `benchmark_value` (decimal, required): Benchmark value to compare against

**Response** (200 OK):
```json
{
  "portfolio_value": 1500000.00,
  "benchmark_value": 1400000.00,
  "difference": 100000.00,
  "difference_percentage": 7.14,
  "outperforming": true
}
```

**User-Friendly Messages**:
- **Outperforming**: "Your portfolio is outperforming the benchmark by 7.14%"
- **Underperforming**: "Your portfolio is underperforming the benchmark by 7.14%"
- **Equal**: "Your portfolio matches the benchmark performance"

**Frontend Code Example**:
```javascript
import { getPortfolioBenchmark } from '@/utils/portfolioApi';

const compareWithBenchmark = async (benchmarkValue) => {
  const response = await getPortfolioBenchmark(benchmarkValue);
  
  if (response.outperforming) {
    toast.success(
      `Your portfolio is outperforming by ${response.difference_percentage.toFixed(2)}%`
    );
  } else if (response.difference_percentage < 0) {
    toast.warning(
      `Your portfolio is underperforming by ${Math.abs(response.difference_percentage).toFixed(2)}%`
    );
  }
  
  // Display comparison chart
  return response;
};
```

---

## Crypto Portfolio APIs

### 8. Get Crypto Summary

**GET** `/portfolio/crypto/summary`

**Description**: Get high-level crypto portfolio overview.

**Response** (200 OK):
```json
{
  "summary": {
    "total_value": 50000.00,
    "total_cost": 45000.00,
    "total_return": 5000.00,
    "return_percentage": 11.11,
    "holdings_count": 5,
    "volatility": 2.5,
    "risk_level": "medium"
  }
}
```

**User-Friendly Messages**:
- **Display**: "Total Crypto Value: $50,000.00 | Return: $5,000.00 (11.11%)"

---

### 9. Get Crypto Performance

**GET** `/portfolio/crypto/performance?time_range=30d&metric=value-over-time`

**Description**: Get crypto performance metrics over time.

**Query Parameters**:
- `time_range` (string, required): `1h`, `6h`, `12h`, `24h`, `7d`, `30d`, `1y`
- `metric` (string, required): `value-over-time`, `return-rate`, `risk-exposure`

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

**User-Friendly Messages**:
- **Loading**: "Loading crypto performance data..."
- **No Data**: "No performance data available for the selected period"

---

### 10. Get Crypto Breakdown

**GET** `/portfolio/crypto/breakdown?group_by=value`

**Description**: Get crypto portfolio breakdown by category.

**Query Parameters**:
- `group_by` (string, required): `value`, `return-rate`

**Response** (200 OK):
```json
{
  "data": [
    {
      "symbol": "BTC",
      "name": "Bitcoin",
      "value": 30000.00,
      "percentage": 60.0,
      "return_rate": 7.14
    }
  ]
}
```

---

### 11. Get Crypto Holdings

**GET** `/portfolio/crypto/holdings?sort_by=value&order=desc`

**Description**: Get detailed crypto holdings list.

**Query Parameters**:
- `sort_by` (string, optional): `value`, `change_24h`, `change_7d`, `portfolio_weight`
- `order` (string, optional): `asc`, `desc`

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
      "return_percentage": 7.14,
      "change_24h": 2.5,
      "change_7d": 5.0
    }
  ]
}
```

---

## Cash Flow APIs

### 12. Get Cash Flow Summary

**GET** `/portfolio/cash-flow/summary?period=last30&start_date=2024-01-01&end_date=2024-01-31`

**Description**: Get cash flow summary for a period.

**Query Parameters**:
- `period` (string, required): `last30`, `thisMonth`, `custom`
- `start_date` (string, optional): Start date (YYYY-MM-DD) for custom period
- `end_date` (string, optional): End date (YYYY-MM-DD) for custom period

**Response** (200 OK):
```json
{
  "summary": {
    "total_inflow": 10000.00,
    "total_outflow": 5000.00,
    "net_cash_flow": 5000.00,
    "forecast": {
      "next_month": 4500.00,
      "next_quarter": 13500.00
    }
  }
}
```

**User-Friendly Messages**:
- **Positive Flow**: "Net Cash Flow: +$5,000.00 this month"
- **Negative Flow**: "Net Cash Flow: -$5,000.00 this month"

---

### 13. Get Cash Flow Trends

**GET** `/portfolio/cash-flow/trends?period=last30&granularity=monthly`

**Description**: Get cash flow trends over time.

**Query Parameters**:
- `period` (string, required): `last30`, `thisMonth`, `custom`
- `start_date` (string, optional): Start date
- `end_date` (string, optional): End date
- `granularity` (string, optional): `daily`, `weekly`, `monthly`

**Response** (200 OK):
```json
{
  "data": [
    {
      "date": "2024-01-01",
      "inflow": 1000.00,
      "outflow": 500.00,
      "net": 500.00
    }
  ]
}
```

---

### 14. Get Cash Flow Transactions

**GET** `/portfolio/cash-flow/transactions?period=last30&type=all&page=1&limit=20`

**Description**: Get cash flow transactions with filtering.

**Query Parameters**:
- `period` (string, required): `last30`, `thisMonth`, `custom`
- `start_date` (string, optional): Start date
- `end_date` (string, optional): End date
- `type` (string, optional): `inflow`, `outflow`, `all`
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
      "type": "inflow",
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

### 15. Get Cash Flow Accounts

**GET** `/portfolio/cash-flow/accounts`

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

### 16. Create Transfer

**POST** `/portfolio/cash-flow/transfers`

**Description**: Create a transfer between accounts.

**Request Body**:
```json
{
  "transfer_type": "internal",
  "from_account_id": "uuid",
  "to_account_id": "uuid",
  "amount": 1000.00,
  "transfer_date": "2024-01-15",
  "frequency": "one-time",
  "description": "Transfer to savings"
}
```

**Response** (201 Created):
```json
{
  "transfer": {
    "id": "uuid",
    "status": "pending",
    "amount": 1000.00,
    "confirmation_number": "TRF-2024-001",
    "created_at": "2024-01-15T10:30:00Z"
  },
  "message": "Transfer initiated successfully"
}
```

**User-Friendly Messages**:
- **Success**: "Transfer of $1,000.00 initiated successfully. Confirmation: TRF-2024-001"
- **Error**: "Transfer failed. {error_message}"

---

### 17. Get Transfer Status

**GET** `/portfolio/cash-flow/transfers/{transfer_id}`

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

## Trade Engine APIs

### 18. Search Assets

**GET** `/portfolio/trade-engine/search?query=AAPL&asset_class=stocks&limit=20`

**Description**: Search for assets to trade.

**Query Parameters**:
- `query` (string, required): Search query (symbol or name)
- `asset_class` (string, optional): `stocks`, `crypto`, `bonds`, `etf`, `all`
- `limit` (integer, optional): Number of results (default: 20)

**Response** (200 OK):
```json
{
  "data": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "asset_class": "stock",
      "current_price": 200.00,
      "change": 2.50,
      "change_percentage": 1.25,
      "exchange": "NASDAQ"
    }
  ]
}
```

**User-Friendly Messages**:
- **No Results**: "No assets found matching 'AAPL'"
- **Loading**: "Searching assets..."

---

### 19. Get Asset Details

**GET** `/portfolio/trade-engine/assets/{symbol}`

**Description**: Get detailed asset information for trading.

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
    "exchange": "NASDAQ",
    "52_week_high": 220.00,
    "52_week_low": 150.00
  }
}
```

---

### 20. Get Recent Trades

**GET** `/portfolio/trade-engine/recent-trades?symbol=AAPL&limit=10`

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

### 21. Get Trading History

**GET** `/portfolio/trade-engine/assets/{symbol}/history`

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

### 22. Get Brokerage Accounts

**GET** `/portfolio/trade-engine/accounts`

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

### 23. Place Order

**POST** `/portfolio/trade-engine/orders`

**Description**: Place a trading order.

**Request Body**:
```json
{
  "symbol": "AAPL",
  "order_type": "buy",  // "buy" | "sell"
  "order_mode": "market",  // "market" | "limit"
  "quantity": 10,
  "limit_price": 185.92,  // Required if order_mode is "limit"
  "brokerage_account_id": "broker_xxx",
  "order_duration": "day-only",  // "day-only" | "good-till-canceled"
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
    "confirmation_number": "ORD-2024-001",
    "created_at": "2024-01-15T10:30:00Z"
  },
  "message": "Order placed successfully"
}
```

**User-Friendly Messages**:
- **Success**: "Order placed successfully! Order ID: ORD-2024-001"
- **Pending**: "Order is being processed..."
- **Failed**: "Order failed. {error_message}"

**Frontend Code Example**:
```javascript
import { placeOrder } from '@/utils/portfolioApi';

const handlePlaceOrder = async (orderData) => {
  try {
    const response = await placeOrder(orderData);
    
    if (response.order) {
      toast.success(
        `Order placed successfully! Confirmation: ${response.order.confirmation_number}`
      );
      
      // Redirect to order status page
      router.push(`/dashboard/portfolio/trade-engine/orders/${response.order.id}`);
    }
  } catch (error) {
    toast.error(error.detail || 'Failed to place order');
  }
};
```

---

### 24. Get Order Status

**GET** `/portfolio/trade-engine/orders/{order_id}`

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
    "fees": 1.00,
    "executed_at": "2024-01-15T10:35:00Z"
  }
}
```

**User-Friendly Messages**:
- **Status Labels**:
  - `pending`: "Pending"
  - `filled`: "Filled"
  - `partially_filled`: "Partially Filled"
  - `cancelled`: "Cancelled"
  - `rejected`: "Rejected"

---

### 25. Cancel Order

**DELETE** `/portfolio/trade-engine/orders/{order_id}`

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

## Error Handling

All endpoints may return the following error responses:

### 400 Bad Request
```json
{
  "detail": "Invalid request parameters"
}
```

### 401 Unauthorized
```json
{
  "detail": "Not authenticated"
}
```

### 403 Forbidden
```json
{
  "detail": "Insufficient permissions"
}
```

### 404 Not Found
```json
{
  "detail": "Resource not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

---

## User-Friendly Messages

### Status Labels

**Refund Status**:
- `pending` → "Processing"
- `succeeded` → "Completed"
- `failed` → "Failed"

**Invoice Status**:
- `paid` → "Paid"
- `unpaid` → "Unpaid"
- `overdue` → "Overdue"

**Order Status**:
- `pending` → "Pending"
- `filled` → "Filled"
- `partially_filled` → "Partially Filled"
- `cancelled` → "Cancelled"
- `rejected` → "Rejected"

**Transfer Status**:
- `pending` → "Processing"
- `completed` → "Completed"
- `failed` → "Failed"

---

## Integration Tips

1. **Authentication**: Always include `Authorization: Bearer <token>` header
2. **Error Handling**: Check for `error.detail` in catch blocks
3. **Loading States**: Show loading indicators for async operations
4. **Date Formatting**: Use ISO 8601 format for dates
5. **Currency Formatting**: Format amounts with 2 decimal places
6. **Pagination**: Use `limit` and `offset` for list endpoints
7. **Status Updates**: Poll order/transfer status endpoints for real-time updates

---

## Quick Reference

| Category | Endpoints | Base Path |
|----------|-----------|-----------|
| Payment Refunds | 2 | `/payments/payments/{payment_id}/refund` |
| Invoice Management | 4 | `/payments/invoices` |
| Portfolio Benchmark | 1 | `/portfolio/benchmark` |
| Crypto Portfolio | 4 | `/portfolio/crypto` |
| Cash Flow | 6 | `/portfolio/cash-flow` |
| Trade Engine | 8 | `/portfolio/trade-engine` |

---

**Last Updated**: 2024-01-15  
**Status**: ✅ All APIs Ready for Integration  
**Total Endpoints**: 25
