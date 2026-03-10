# Missing APIs - Frontend Integration Guide

Complete API documentation for frontend developers with request/response examples and user-friendly messages.

**Base URL**: `/api/v1`  
**Authentication**: All endpoints require Bearer token in `Authorization` header  
**Content-Type**: `application/json`

---

## Table of Contents

1. [Investment Management APIs](#investment-management-apis)
2. [Notifications APIs](#notifications-apis)
3. [Referrals APIs](#referrals-apis)
4. [Error Handling](#error-handling)
5. [User-Friendly Messages](#user-friendly-messages)

---

## Investment Management APIs

### 1. Adjust Investment Goal

**POST** `/investment/goals/{goal_id}/adjust`

**Description**: Adjust investment goal parameters (target amount, target date, monthly contribution, risk tolerance).

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "target_amount": 50000.00,  // Optional: new target amount
  "target_date": "2025-12-31",  // Optional: new target date (YYYY-MM-DD)
  "monthly_contribution": 1000.00,  // Optional: new monthly contribution
  "risk_tolerance": "moderate",  // Optional: "conservative" | "moderate" | "aggressive"
  "notes": "Updated goal to save for house down payment"  // Optional
}
```

**Response** (200 OK):
```json
{
  "goal_id": "uuid",
  "message": "Goal adjusted successfully",
  "updated_parameters": {
    "target_amount": 50000.00,
    "target_date": "2025-12-31",
    "monthly_contribution": 1000.00,
    "risk_tolerance": "moderate",
    "notes": "Updated goal to save for house down payment"
  }
}
```

**Error Responses**:
- **400 Bad Request**: `{"detail": "Failed to adjust goal: {error_message}"}`
- **404 Not Found**: `{"detail": "Goal not found"}`

**User-Friendly Messages**:
- **Success**: "Goal updated successfully. Your target of $50,000.00 by December 31, 2025 is now active."
- **Error**: "Unable to update goal. {error_message}"

**Frontend Code Example**:
```javascript
import { adjustGoal } from '@/utils/investmentApi';

const handleAdjustGoal = async (goalId, adjustmentData) => {
  try {
    const response = await adjustGoal(goalId, adjustmentData);
    
    if (response.message) {
      toast.success('Goal updated successfully');
      // Refresh goal details
      await fetchGoalDetails(goalId);
    }
  } catch (error) {
    toast.error(error.detail || 'Failed to update goal');
  }
};
```

---

### 2. Backtest Strategy

**POST** `/investment/strategies/{strategy_id}/backtest`

**Description**: Backtest an investment strategy using historical data.

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "start_date": "2023-01-01",  // Required: backtest start date (YYYY-MM-DD)
  "end_date": "2023-12-31",  // Required: backtest end date (YYYY-MM-DD)
  "initial_capital": 10000.00  // Required: initial investment amount
}
```

**Response** (200 OK):
```json
{
  "strategy_id": "uuid",
  "backtest_id": "uuid",
  "start_date": "2023-01-01",
  "end_date": "2023-12-31",
  "initial_capital": 10000.00,
  "final_value": 11250.50,
  "total_return": 1250.50,
  "total_return_percentage": 12.5,
  "annualized_return": 12.5,
  "max_drawdown": -5.5,
  "sharpe_ratio": 1.2,
  "volatility": 8.3,
  "win_rate": 64.3,
  "total_trades": 42,
  "winning_trades": 27,
  "losing_trades": 15
}
```

**User-Friendly Messages**:
- **Success**: "Backtest completed. Strategy returned 12.5% over the period."
- **Loading**: "Running backtest simulation..."
- **Error**: "Backtest failed. {error_message}"

**Frontend Code Example**:
```javascript
import { backtestStrategy } from '@/utils/investmentApi';

const handleBacktest = async (strategyId, backtestParams) => {
  try {
    setLoading(true);
    const response = await backtestStrategy(strategyId, backtestParams);
    
    if (response.total_return_percentage) {
      toast.success(
        `Backtest completed: ${response.total_return_percentage.toFixed(2)}% return`
      );
      // Display backtest results
      setBacktestResults(response);
    }
  } catch (error) {
    toast.error(error.detail || 'Backtest failed');
  } finally {
    setLoading(false);
  }
};
```

---

### 3. Get Strategy Performance

**GET** `/investment/strategies/{strategy_id}/performance?days=30`

**Description**: Get performance metrics for a specific investment strategy.

**Query Parameters**:
- `days` (integer, optional): Number of days for performance calculation (default: 30, max: 365)

**Response** (200 OK):
```json
{
  "strategy_id": "uuid",
  "period": {
    "start": "2024-01-01T00:00:00Z",
    "end": "2024-01-31T00:00:00Z",
    "days": 30
  },
  "performance": {
    "total_return": 1250.50,
    "total_return_percentage": 12.5,
    "annualized_return": 15.2,
    "sharpe_ratio": 1.2,
    "max_drawdown": -5.5,
    "volatility": 8.3,
    "beta": 0.95,
    "alpha": 2.1
  },
  "trades": {
    "total": 42,
    "winning": 27,
    "losing": 15,
    "win_rate": 64.3
  },
  "current_value": 11250.50,
  "initial_value": 10000.00
}
```

**User-Friendly Messages**:
- **Display**: "Strategy Performance: +12.5% return | Win Rate: 64.3% | Sharpe Ratio: 1.2"
- **No Data**: "No performance data available for this strategy"

**Frontend Code Example**:
```javascript
import { getStrategyPerformance } from '@/utils/investmentApi';

const fetchStrategyPerformance = async (strategyId, days = 30) => {
  const response = await getStrategyPerformance(strategyId, days);
  
  // Display performance metrics
  const metrics = {
    return: response.performance.total_return_percentage,
    winRate: response.trades.win_rate,
    sharpeRatio: response.performance.sharpe_ratio
  };
  
  return metrics;
};
```

---

### 4. Clone Strategy

**POST** `/investment/strategies/{strategy_id}/clone`

**Description**: Clone an existing investment strategy with optional parameter adjustments.

**Headers**:
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**:
```json
{
  "new_name": "My Cloned Strategy",  // Required: name for the cloned strategy
  "adjust_parameters": {  // Optional: adjust strategy parameters
    "risk_level": "moderate",
    "rebalance_frequency": "monthly"
  }
}
```

**Response** (200 OK):
```json
{
  "original_strategy_id": "uuid",
  "new_strategy_id": "uuid",
  "name": "My Cloned Strategy",
  "status": "active",
  "cloned_at": "2024-01-15T10:30:00Z",
  "message": "Strategy cloned successfully"
}
```

**User-Friendly Messages**:
- **Success**: "Strategy cloned successfully! New strategy ID: {new_strategy_id}"
- **Error**: "Failed to clone strategy. {error_message}"

**Frontend Code Example**:
```javascript
import { cloneStrategy } from '@/utils/investmentApi';

const handleCloneStrategy = async (strategyId, newName, adjustParams = {}) => {
  try {
    const response = await cloneStrategy(strategyId, {
      new_name: newName,
      adjust_parameters: adjustParams
    });
    
    if (response.new_strategy_id) {
      toast.success('Strategy cloned successfully');
      // Navigate to new strategy
      router.push(`/dashboard/investment/strategies/${response.new_strategy_id}`);
    }
  } catch (error) {
    toast.error(error.detail || 'Failed to clone strategy');
  }
};
```

---

## Notifications APIs

### 5. Get Notifications

**GET** `/notifications?unread_only=false`

**Description**: Get all notifications for the authenticated user.

**Query Parameters**:
- `unread_only` (boolean, optional): Filter to show only unread notifications (default: false)

**Response** (200 OK):
```json
[
  {
    "id": "uuid",
    "notification_type": "order_filled",
    "title": "Order Filled",
    "message": "Your order for AAPL has been filled",
    "is_read": false,
    "created_at": "2024-01-15T10:30:00Z"
  }
]
```

**User-Friendly Messages**:
- **No Notifications**: "No notifications"
- **Unread Count**: "You have {count} unread notifications"

---

### 6. Get Unread Notifications

**GET** `/notifications/unread`

**Description**: Get only unread notifications.

**Response** (200 OK):
```json
[
  {
    "id": "uuid",
    "notification_type": "order_filled",
    "title": "Order Filled",
    "message": "Your order for AAPL has been filled",
    "is_read": false,
    "created_at": "2024-01-15T10:30:00Z"
  }
]
```

**User-Friendly Messages**:
- **No Unread**: "All caught up! No unread notifications"
- **Unread Count**: "{count} unread notifications"

---

### 7. Mark Notification as Read

**PUT** `/notifications/{notification_id}/read`

**Description**: Mark a specific notification as read.

**Response** (200 OK):
```json
{
  "message": "Notification marked as read"
}
```

**User-Friendly Messages**:
- **Success**: "Notification marked as read"

---

### 8. Mark All as Read

**POST** `/notifications/read-all`

**Description**: Mark all notifications as read.

**Response** (200 OK):
```json
{
  "message": "5 notifications marked as read"
}
```

**User-Friendly Messages**:
- **Success**: "All notifications marked as read"
- **No Unread**: "No unread notifications to mark"

**Frontend Code Example**:
```javascript
import { markAllAsRead } from '@/utils/notificationsApi';

const handleMarkAllRead = async () => {
  try {
    const response = await markAllAsRead();
    toast.success(response.message);
    // Refresh notifications list
    await fetchNotifications();
  } catch (error) {
    toast.error('Failed to mark all as read');
  }
};
```

---

### 9. Delete Notification

**DELETE** `/notifications/{notification_id}`

**Description**: Delete a specific notification.

**Response** (204 No Content):
```
(No body)
```

**User-Friendly Messages**:
- **Success**: "Notification deleted"
- **Error**: "Failed to delete notification"

---

### 10. Get Notification Settings

**GET** `/notifications/settings`

**Description**: Get user's notification preferences.

**Response** (200 OK):
```json
{
  "email_enabled": true,
  "push_enabled": true,
  "sms_enabled": false,
  "order_notifications": true,
  "offer_notifications": true,
  "payment_notifications": true,
  "kyc_notifications": true,
  "support_notifications": true,
  "general_notifications": true
}
```

**User-Friendly Messages**:
- **Display**: Show toggle switches for each notification type

---

### 11. Update Notification Settings

**PUT** `/notifications/settings`

**Description**: Update user's notification preferences.

**Request Body**:
```json
{
  "email_enabled": true,  // Optional
  "push_enabled": true,  // Optional
  "sms_enabled": false,  // Optional
  "order_notifications": true,  // Optional
  "offer_notifications": true,  // Optional
  "payment_notifications": true,  // Optional
  "kyc_notifications": true,  // Optional
  "support_notifications": true,  // Optional
  "general_notifications": true  // Optional
}
```

**Response** (200 OK):
```json
{
  "email_enabled": true,
  "push_enabled": true,
  "sms_enabled": false,
  "order_notifications": true,
  "offer_notifications": true,
  "payment_notifications": true,
  "kyc_notifications": true,
  "support_notifications": true,
  "general_notifications": true
}
```

**User-Friendly Messages**:
- **Success**: "Notification preferences updated"
- **Error**: "Failed to update preferences"

**Frontend Code Example**:
```javascript
import { updateNotificationSettings } from '@/utils/notificationsApi';

const handleUpdateSettings = async (settings) => {
  try {
    const response = await updateNotificationSettings(settings);
    toast.success('Notification preferences updated');
    setSettings(response);
  } catch (error) {
    toast.error('Failed to update preferences');
  }
};
```

---

## Referrals APIs

### 12. Get Referral Statistics

**GET** `/referrals`

**Description**: Get referral statistics for the current user.

**Response** (200 OK):
```json
{
  "total_referrals": 15,
  "completed_referrals": 10,
  "pending_referrals": 5,
  "total_rewards_earned": 500.00,
  "total_rewards_paid": 300.00,
  "pending_rewards": 200.00,
  "currency": "USD"
}
```

**User-Friendly Messages**:
- **Display**: "You've referred {total_referrals} people and earned ${total_rewards_earned}"
- **No Referrals**: "Start referring friends to earn rewards!"

**Frontend Code Example**:
```javascript
import { getReferralStats } from '@/utils/referralsApi';

const fetchReferralStats = async () => {
  const stats = await getReferralStats();
  
  // Display stats
  console.log(`Total referrals: ${stats.total_referrals}`);
  console.log(`Rewards earned: $${stats.total_rewards_earned}`);
  
  return stats;
};
```

---

### 13. Get Referral List

**GET** `/referrals/list?status_filter=completed&page=1&limit=20`

**Description**: Get list of referrals with pagination.

**Query Parameters**:
- `status_filter` (string, optional): Filter by status (`pending`, `completed`, `cancelled`)
- `page` (integer, optional): Page number (default: 1)
- `limit` (integer, optional): Items per page (default: 20, max: 100)

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "uuid",
      "referral_code": "REF-ABC123",
      "referred_email": "friend@example.com",
      "status": "completed",
      "reward_amount": 50.00,
      "reward_currency": "USD",
      "reward_paid": true,
      "created_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-20T10:30:00Z"
    }
  ],
  "total": 15,
  "page": 1,
  "limit": 20
}
```

**User-Friendly Messages**:
- **No Referrals**: "No referrals found"
- **Status Labels**:
  - `pending`: "Pending"
  - `completed`: "Completed"
  - `cancelled`: "Cancelled"

---

### 14. Get Referral Code

**GET** `/referrals/code`

**Description**: Get user's referral code and statistics.

**Response** (200 OK):
```json
{
  "referral_code": "REF-ABC123",
  "referral_link": "/signup?ref=REF-ABC123",
  "created_at": "2024-01-15T10:30:00Z",
  "total_uses": 10,
  "total_rewards": 500.00
}
```

**User-Friendly Messages**:
- **Display**: "Your referral code: REF-ABC123 | Used {total_uses} times | Earned ${total_rewards}"
- **Copy Link**: "Referral link copied to clipboard!"

**Frontend Code Example**:
```javascript
import { getReferralCode } from '@/utils/referralsApi';

const fetchReferralCode = async () => {
  const codeData = await getReferralCode();
  
  // Display referral code
  setReferralCode(codeData.referral_code);
  setReferralLink(`${window.location.origin}${codeData.referral_link}`);
  
  return codeData;
};

const copyReferralLink = async () => {
  const codeData = await getReferralCode();
  await navigator.clipboard.writeText(`${window.location.origin}${codeData.referral_link}`);
  toast.success('Referral link copied!');
};
```

---

### 15. Generate Referral Code

**POST** `/referrals/generate-code`

**Description**: Generate a new referral code.

**Response** (201 Created):
```json
{
  "referral_code": "REF-XYZ789",
  "referral_link": "/signup?ref=REF-XYZ789",
  "created_at": "2024-01-15T10:30:00Z",
  "total_uses": 0,
  "total_rewards": 0.00
}
```

**User-Friendly Messages**:
- **Success**: "New referral code generated: REF-XYZ789"
- **Error**: "Failed to generate referral code"

**Frontend Code Example**:
```javascript
import { generateReferralCode } from '@/utils/referralsApi';

const handleGenerateCode = async () => {
  try {
    const response = await generateReferralCode();
    toast.success(`New referral code: ${response.referral_code}`);
    setReferralCode(response.referral_code);
  } catch (error) {
    toast.error('Failed to generate referral code');
  }
};
```

---

### 16. Get Referral Rewards

**GET** `/referrals/rewards`

**Description**: Get referral rewards for the current user.

**Response** (200 OK):
```json
[
  {
    "id": "uuid",
    "referral_id": "uuid",
    "amount": 50.00,
    "currency": "USD",
    "reward_type": "signup",
    "paid": true,
    "paid_at": "2024-01-20T10:30:00Z",
    "created_at": "2024-01-15T10:30:00Z"
  }
]
```

**User-Friendly Messages**:
- **No Rewards**: "No rewards yet. Start referring to earn!"
- **Display**: "Reward: $50.00 for {reward_type} - {paid_status}"

---

### 17. Get Referral Leaderboard

**GET** `/referrals/leaderboard?limit=10`

**Description**: Get referral leaderboard (top referrers).

**Query Parameters**:
- `limit` (integer, optional): Number of top referrers to return (default: 10, max: 100)

**Response** (200 OK):
```json
[
  {
    "account_id": "uuid",
    "referral_code": "REF-ABC123",
    "total_referrals": 50,
    "completed_referrals": 40,
    "total_rewards": 2000.00,
    "rank": 1
  }
]
```

**User-Friendly Messages**:
- **Display**: "Rank #{rank}: {total_referrals} referrals | ${total_rewards} earned"
- **Your Rank**: "You're ranked #{rank} with {total_referrals} referrals"

**Frontend Code Example**:
```javascript
import { getReferralLeaderboard } from '@/utils/referralsApi';

const fetchLeaderboard = async () => {
  const leaderboard = await getReferralLeaderboard(10);
  
  // Display leaderboard
  leaderboard.forEach(item => {
    console.log(`#${item.rank}: ${item.total_referrals} referrals - $${item.total_rewards}`);
  });
  
  return leaderboard;
};
```

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

### Notification Types

**Labels**:
- `order_filled` → "Order Filled"
- `order_cancelled` → "Order Cancelled"
- `offer_received` → "New Offer"
- `offer_accepted` → "Offer Accepted"
- `listing_approved` → "Listing Approved"
- `payment_received` → "Payment Received"
- `kyc_approved` → "KYC Approved"
- `support_reply` → "Support Reply"
- `general` → "General Notification"

### Referral Status

**Labels**:
- `pending` → "Pending"
- `completed` → "Completed"
- `cancelled` → "Cancelled"

### Reward Types

**Labels**:
- `signup` → "Signup Bonus"
- `first_payment` → "First Payment"
- `subscription` → "Subscription"

---

## Integration Tips

1. **Authentication**: Always include `Authorization: Bearer <token>` header
2. **Error Handling**: Check for `error.detail` in catch blocks
3. **Loading States**: Show loading indicators for async operations
4. **Date Formatting**: Use ISO 8601 format for dates
5. **Currency Formatting**: Format amounts with 2 decimal places
6. **Pagination**: Use `page` and `limit` for list endpoints
7. **Real-time Updates**: Poll notification endpoints for new notifications

---

## Quick Reference

| Category | Endpoints | Base Path |
|----------|-----------|-----------|
| Investment Management | 4 | `/investment/goals/{goal_id}` or `/investment/strategies/{strategy_id}` |
| Notifications | 7 | `/notifications` |
| Referrals | 6 | `/referrals` |

---

**Last Updated**: 2024-01-15  
**Status**: ✅ All APIs Implemented and Ready  
**Total Endpoints**: 17
