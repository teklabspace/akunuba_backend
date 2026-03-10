# Remaining Sections - Frontend Integration Guide

Complete API documentation for frontend developers to integrate the remaining sections that currently use mock data.

**Base URL**: `/api/v1`  
**Authentication**: All endpoints require Bearer token in `Authorization` header  
**Content-Type**: `application/json`

---

## Table of Contents

1. [Notifications Page Integration](#notifications-page-integration)
2. [Referrals Page Integration](#referrals-page-integration)
3. [Transactions Page Integration](#transactions-page-integration)
4. [Support Dashboard Integration](#support-dashboard-integration)
5. [Error Handling](#error-handling)
6. [User-Friendly Messages](#user-friendly-messages)
7. [Integration Checklist](#integration-checklist)

---

## Notifications Page Integration

**Page Location**: `src/app/dashboard/notifications/page.js`  
**Current Status**: ❌ Uses hardcoded mock data  
**Priority**: 🔴 **High**

### Available APIs

All notification APIs are fully implemented and ready to use.

---

### 1. Get All Notifications

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
  },
  {
    "id": "uuid",
    "notification_type": "payment_received",
    "title": "Payment Received",
    "message": "You received $100.00",
    "is_read": true,
    "created_at": "2024-01-14T09:15:00Z"
  }
]
```

**Frontend Code Example**:
```javascript
import { getNotifications } from '@/utils/notificationsApi';

const fetchNotifications = async (unreadOnly = false) => {
  try {
    const notifications = await getNotifications({ unread_only: unreadOnly });
    setNotifications(notifications);
    return notifications;
  } catch (error) {
    console.error('Failed to fetch notifications:', error);
    toast.error('Failed to load notifications');
    return [];
  }
};
```

---

### 2. Get Unread Notifications

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

**Frontend Code Example**:
```javascript
import { getUnreadNotifications } from '@/utils/notificationsApi';

const fetchUnreadNotifications = async () => {
  try {
    const unread = await getUnreadNotifications();
    setUnreadNotifications(unread);
    return unread;
  } catch (error) {
    console.error('Failed to fetch unread notifications:', error);
    return [];
  }
};
```

---

### 3. Get Unread Count

**GET** `/notifications/unread-count`

**Description**: Get count of unread notifications (for badge).

**Response** (200 OK):
```json
{
  "count": 5
}
```

**Frontend Code Example**:
```javascript
import { getUnreadCount } from '@/utils/notificationsApi';

const fetchUnreadCount = async () => {
  try {
    const response = await getUnreadCount();
    setUnreadCount(response.count);
    return response.count;
  } catch (error) {
    console.error('Failed to fetch unread count:', error);
    return 0;
  }
};

// Use in useEffect for badge
useEffect(() => {
  fetchUnreadCount();
  // Poll every 30 seconds for new notifications
  const interval = setInterval(fetchUnreadCount, 30000);
  return () => clearInterval(interval);
}, []);
```

---

### 4. Mark Notification as Read

**PUT** `/notifications/{notification_id}/read`

**Description**: Mark a specific notification as read.

**Response** (200 OK):
```json
{
  "message": "Notification marked as read"
}
```

**Frontend Code Example**:
```javascript
import { markAsRead } from '@/utils/notificationsApi';

const handleMarkAsRead = async (notificationId) => {
  try {
    await markAsRead(notificationId);
    
    // Update local state
    setNotifications(prev => 
      prev.map(n => 
        n.id === notificationId ? { ...n, is_read: true } : n
      )
    );
    
    // Update unread count
    await fetchUnreadCount();
  } catch (error) {
    toast.error('Failed to mark notification as read');
  }
};
```

---

### 5. Mark All as Read

**POST** `/notifications/read-all`

**Description**: Mark all notifications as read.

**Response** (200 OK):
```json
{
  "message": "5 notifications marked as read"
}
```

**Frontend Code Example**:
```javascript
import { markAllAsRead } from '@/utils/notificationsApi';

const handleMarkAllAsRead = async () => {
  try {
    const response = await markAllAsRead();
    toast.success(response.message);
    
    // Update all notifications to read
    setNotifications(prev => 
      prev.map(n => ({ ...n, is_read: true }))
    );
    
    // Reset unread count
    setUnreadCount(0);
  } catch (error) {
    toast.error('Failed to mark all as read');
  }
};
```

---

### 6. Delete Notification

**DELETE** `/notifications/{notification_id}`

**Description**: Delete a specific notification.

**Response** (204 No Content):
```
(No body)
```

**Frontend Code Example**:
```javascript
import { deleteNotification } from '@/utils/notificationsApi';

const handleDeleteNotification = async (notificationId) => {
  try {
    await deleteNotification(notificationId);
    
    // Remove from local state
    setNotifications(prev => prev.filter(n => n.id !== notificationId));
    
    // Update unread count if needed
    await fetchUnreadCount();
    
    toast.success('Notification deleted');
  } catch (error) {
    toast.error('Failed to delete notification');
  }
};
```

---

### 7. Get Notification Settings

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

**Frontend Code Example**:
```javascript
import { getNotificationSettings } from '@/utils/notificationsApi';

const fetchNotificationSettings = async () => {
  try {
    const settings = await getNotificationSettings();
    setNotificationSettings(settings);
    return settings;
  } catch (error) {
    console.error('Failed to fetch notification settings:', error);
    return null;
  }
};
```

---

### 8. Update Notification Settings

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

**Frontend Code Example**:
```javascript
import { updateNotificationSettings } from '@/utils/notificationsApi';

const handleUpdateSettings = async (updatedSettings) => {
  try {
    const response = await updateNotificationSettings(updatedSettings);
    setNotificationSettings(response);
    toast.success('Notification preferences updated');
  } catch (error) {
    toast.error('Failed to update notification preferences');
  }
};
```

---

### Complete Notifications Page Integration

**Full Implementation Example**:
```javascript
'use client';

import { useState, useEffect } from 'react';
import { 
  getNotifications, 
  getUnreadCount, 
  markAsRead, 
  markAllAsRead, 
  deleteNotification,
  getNotificationSettings,
  updateNotificationSettings
} from '@/utils/notificationsApi';
import { toast } from 'react-hot-toast';

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all'); // 'all' | 'unread'
  const [settings, setSettings] = useState(null);

  // Fetch notifications
  useEffect(() => {
    fetchNotifications();
    fetchUnreadCount();
    fetchSettings();
    
    // Poll for new notifications every 30 seconds
    const interval = setInterval(() => {
      fetchUnreadCount();
      if (filter === 'all') {
        fetchNotifications();
      }
    }, 30000);
    
    return () => clearInterval(interval);
  }, [filter]);

  const fetchNotifications = async () => {
    try {
      setLoading(true);
      const data = await getNotifications({ 
        unread_only: filter === 'unread' 
      });
      setNotifications(data);
    } catch (error) {
      toast.error('Failed to load notifications');
    } finally {
      setLoading(false);
    }
  };

  const fetchUnreadCount = async () => {
    try {
      const response = await getUnreadCount();
      setUnreadCount(response.count);
    } catch (error) {
      console.error('Failed to fetch unread count:', error);
    }
  };

  const fetchSettings = async () => {
    try {
      const data = await getNotificationSettings();
      setSettings(data);
    } catch (error) {
      console.error('Failed to fetch settings:', error);
    }
  };

  const handleMarkAsRead = async (id) => {
    try {
      await markAsRead(id);
      setNotifications(prev => 
        prev.map(n => n.id === id ? { ...n, is_read: true } : n)
      );
      setUnreadCount(prev => Math.max(0, prev - 1));
    } catch (error) {
      toast.error('Failed to mark as read');
    }
  };

  const handleMarkAllAsRead = async () => {
    try {
      await markAllAsRead();
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
      setUnreadCount(0);
      toast.success('All notifications marked as read');
    } catch (error) {
      toast.error('Failed to mark all as read');
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteNotification(id);
      const notification = notifications.find(n => n.id === id);
      setNotifications(prev => prev.filter(n => n.id !== id));
      if (notification && !notification.is_read) {
        setUnreadCount(prev => Math.max(0, prev - 1));
      }
      toast.success('Notification deleted');
    } catch (error) {
      toast.error('Failed to delete notification');
    }
  };

  // Render notifications list...
}
```

---

## Referrals Page Integration

**Page Location**: `src/app/dashboard/referral/page.js`  
**Current Status**: ❌ Uses hardcoded mock data  
**Priority**: 🔴 **High**

### Available APIs

All referral APIs are fully implemented and ready to use.

---

### 1. Get Referral Statistics

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

**Frontend Code Example**:
```javascript
import { getReferralStats } from '@/utils/referralsApi';

const fetchReferralStats = async () => {
  try {
    const stats = await getReferralStats();
    setReferralStats(stats);
    return stats;
  } catch (error) {
    console.error('Failed to fetch referral stats:', error);
    toast.error('Failed to load referral statistics');
    return null;
  }
};
```

---

### 2. Get Referral List

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

**Frontend Code Example**:
```javascript
import { getReferralList } from '@/utils/referralsApi';

const fetchReferralList = async (page = 1, statusFilter = null) => {
  try {
    const response = await getReferralList({
      page,
      limit: 20,
      status_filter: statusFilter
    });
    setReferrals(response.data);
    setPagination({
      total: response.total,
      page: response.page,
      limit: response.limit,
      totalPages: Math.ceil(response.total / response.limit)
    });
    return response;
  } catch (error) {
    console.error('Failed to fetch referral list:', error);
    toast.error('Failed to load referrals');
    return null;
  }
};
```

---

### 3. Get Referral Code

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

**Frontend Code Example**:
```javascript
import { getReferralCode } from '@/utils/referralsApi';

const fetchReferralCode = async () => {
  try {
    const codeData = await getReferralCode();
    const fullLink = `${window.location.origin}${codeData.referral_link}`;
    
    setReferralCode(codeData.referral_code);
    setReferralLink(fullLink);
    setReferralStats(codeData);
    
    return codeData;
  } catch (error) {
    console.error('Failed to fetch referral code:', error);
    toast.error('Failed to load referral code');
    return null;
  }
};

const copyReferralLink = async () => {
  try {
    const codeData = await getReferralCode();
    const fullLink = `${window.location.origin}${codeData.referral_link}`;
    await navigator.clipboard.writeText(fullLink);
    toast.success('Referral link copied to clipboard!');
  } catch (error) {
    toast.error('Failed to copy referral link');
  }
};
```

---

### 4. Generate Referral Code

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

**Frontend Code Example**:
```javascript
import { generateReferralCode } from '@/utils/referralsApi';

const handleGenerateCode = async () => {
  try {
    const response = await generateReferralCode();
    const fullLink = `${window.location.origin}${response.referral_link}`;
    
    setReferralCode(response.referral_code);
    setReferralLink(fullLink);
    
    toast.success(`New referral code generated: ${response.referral_code}`);
  } catch (error) {
    toast.error('Failed to generate referral code');
  }
};
```

---

### 5. Get Referral Rewards

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

**Frontend Code Example**:
```javascript
import { getReferralRewards } from '@/utils/referralsApi';

const fetchReferralRewards = async () => {
  try {
    const rewards = await getReferralRewards();
    setReferralRewards(rewards);
    return rewards;
  } catch (error) {
    console.error('Failed to fetch referral rewards:', error);
    return [];
  }
};
```

---

### 6. Get Referral Leaderboard

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

**Frontend Code Example**:
```javascript
import { getReferralLeaderboard } from '@/utils/referralsApi';

const fetchLeaderboard = async () => {
  try {
    const leaderboard = await getReferralLeaderboard(10);
    setLeaderboard(leaderboard);
    return leaderboard;
  } catch (error) {
    console.error('Failed to fetch leaderboard:', error);
    return [];
  }
};
```

---

### Complete Referrals Page Integration

**Full Implementation Example**:
```javascript
'use client';

import { useState, useEffect } from 'react';
import { 
  getReferralStats,
  getReferralList,
  getReferralCode,
  generateReferralCode,
  getReferralRewards,
  getReferralLeaderboard
} from '@/utils/referralsApi';
import { toast } from 'react-hot-toast';

export default function ReferralPage() {
  const [stats, setStats] = useState(null);
  const [referralCode, setReferralCode] = useState('');
  const [referralLink, setReferralLink] = useState('');
  const [referrals, setReferrals] = useState([]);
  const [rewards, setRewards] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState(null);

  useEffect(() => {
    fetchAllData();
  }, [page, statusFilter]);

  const fetchAllData = async () => {
    setLoading(true);
    try {
      await Promise.all([
        fetchReferralStats(),
        fetchReferralCode(),
        fetchReferralList(),
        fetchReferralRewards(),
        fetchLeaderboard()
      ]);
    } finally {
      setLoading(false);
    }
  };

  const fetchReferralStats = async () => {
    try {
      const data = await getReferralStats();
      setStats(data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  const fetchReferralCode = async () => {
    try {
      const data = await getReferralCode();
      setReferralCode(data.referral_code);
      setReferralLink(`${window.location.origin}${data.referral_link}`);
    } catch (error) {
      console.error('Failed to fetch referral code:', error);
    }
  };

  const fetchReferralList = async () => {
    try {
      const response = await getReferralList({
        page,
        limit: 20,
        status_filter: statusFilter
      });
      setReferrals(response.data);
    } catch (error) {
      console.error('Failed to fetch referral list:', error);
    }
  };

  const fetchReferralRewards = async () => {
    try {
      const data = await getReferralRewards();
      setRewards(data);
    } catch (error) {
      console.error('Failed to fetch rewards:', error);
    }
  };

  const fetchLeaderboard = async () => {
    try {
      const data = await getReferralLeaderboard(10);
      setLeaderboard(data);
    } catch (error) {
      console.error('Failed to fetch leaderboard:', error);
    }
  };

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(referralLink);
      toast.success('Referral link copied!');
    } catch (error) {
      toast.error('Failed to copy link');
    }
  };

  const handleGenerateCode = async () => {
    try {
      await generateReferralCode();
      await fetchReferralCode();
      toast.success('New referral code generated!');
    } catch (error) {
      toast.error('Failed to generate code');
    }
  };

  // Render UI...
}
```

---

## Transactions Page Integration

**Page Location**: `src/app/dashboard/transactions/page.js`  
**Current Status**: ❌ Uses hardcoded mock data  
**Priority**: 🟡 **Medium**

### Available APIs

Transactions can be fetched from multiple sources. You can combine them or use separately:

---

### 1. Get Trading Transactions

**GET** `/trading/transactions?start_date=2024-01-01&end_date=2024-01-31&limit=100`

**Description**: Get trading transactions from Alpaca.

**Query Parameters**:
- `start_date` (string, optional): Start date (YYYY-MM-DD), defaults to 30 days ago
- `end_date` (string, optional): End date (YYYY-MM-DD), defaults to today
- `limit` (integer, optional): Number of transactions (default: 100, max: 500)

**Response** (200 OK):
```json
{
  "transactions": [
    {
      "id": "tx_xxx",
      "activity_type": "FILL",
      "symbol": "AAPL",
      "quantity": 10,
      "price": 200.00,
      "amount": 2000.00,
      "date": "2024-01-15T10:30:00Z",
      "description": "Buy 10 shares of AAPL"
    }
  ],
  "count": 1,
  "period": {
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
  }
}
```

**Frontend Code Example**:
```javascript
import { getTradingTransactions } from '@/utils/tradingApi';

const fetchTradingTransactions = async (startDate, endDate) => {
  try {
    const response = await getTradingTransactions({
      start_date: startDate,
      end_date: endDate,
      limit: 100
    });
    return response.transactions.map(tx => ({
      ...tx,
      type: 'trading',
      category: 'trade'
    }));
  } catch (error) {
    console.error('Failed to fetch trading transactions:', error);
    return [];
  }
};
```

---

### 2. Get Payment History

**GET** `/payments/history?status=completed&limit=20&offset=0`

**Description**: Get payment transaction history.

**Query Parameters**:
- `status` (string, optional): Filter by status (`pending`, `completed`, `failed`, `refunded`)
- `limit` (integer, optional): Number of payments (default: 20, max: 100)
- `offset` (integer, optional): Pagination offset (default: 0)

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "uuid",
      "amount": 99.00,
      "currency": "USD",
      "status": "completed",
      "payment_method": "card",
      "description": "Premium subscription",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

**Frontend Code Example**:
```javascript
import { getPaymentHistory } from '@/utils/paymentsApi';

const fetchPaymentTransactions = async (page = 1) => {
  try {
    const response = await getPaymentHistory({
      status: 'completed',
      limit: 20,
      offset: (page - 1) * 20
    });
    return response.data.map(payment => ({
      id: payment.id,
      type: 'payment',
      category: 'subscription',
      amount: payment.amount,
      currency: payment.currency,
      status: payment.status,
      description: payment.description || 'Payment',
      date: payment.created_at,
      name: payment.description || 'Payment'
    }));
  } catch (error) {
    console.error('Failed to fetch payment transactions:', error);
    return [];
  }
};
```

---

### 3. Get Recent Trades

**GET** `/portfolio/trade-engine/recent-trades?symbol=AAPL&limit=10`

**Description**: Get recent trades from trade engine.

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

**Frontend Code Example**:
```javascript
import { getRecentTrades } from '@/utils/portfolioApi';

const fetchRecentTrades = async () => {
  try {
    const response = await getRecentTrades({ limit: 50 });
    return response.data.map(trade => ({
      id: trade.id,
      type: 'trade',
      category: trade.type, // 'buy' or 'sell'
      symbol: trade.symbol,
      name: trade.symbol,
      amount: trade.type === 'buy' ? `-$${trade.total}` : `+$${trade.total}`,
      price: trade.price,
      quantity: trade.quantity,
      status: trade.status,
      date: trade.executed_at
    }));
  } catch (error) {
    console.error('Failed to fetch recent trades:', error);
    return [];
  }
};
```

---

### 4. Get Banking Transactions

**GET** `/banking/accounts/{linked_account_id}/transactions?start_date=2024-01-01&end_date=2024-01-31&limit=50`

**Description**: Get transactions for a specific linked bank account.

**Query Parameters**:
- `start_date` (string, optional): Start date (YYYY-MM-DD)
- `end_date` (string, optional): End date (YYYY-MM-DD)
- `limit` (integer, optional): Number of transactions (default: 50, max: 500)

**Response** (200 OK):
```json
{
  "transactions": [
    {
      "id": "uuid",
      "amount": -100.00,
      "currency": "USD",
      "description": "Grocery Store",
      "category": "food",
      "transaction_date": "2024-01-15T10:30:00Z",
      "account_name": "Chase Checking"
    }
  ],
  "count": 1
}
```

**Frontend Code Example**:
```javascript
import { getAccountTransactions } from '@/utils/bankingApi';

const fetchBankingTransactions = async (accountId, startDate, endDate) => {
  try {
    const response = await getAccountTransactions(accountId, {
      start_date: startDate,
      end_date: endDate,
      limit: 100
    });
    return response.transactions.map(tx => ({
      id: tx.id,
      type: 'banking',
      category: tx.category || 'other',
      amount: tx.amount,
      currency: tx.currency,
      description: tx.description,
      date: tx.transaction_date,
      name: tx.description,
      account: tx.account_name
    }));
  } catch (error) {
    console.error('Failed to fetch banking transactions:', error);
    return [];
  }
};
```

---

### Complete Transactions Page Integration

**Combined Transactions Approach**:
```javascript
'use client';

import { useState, useEffect } from 'react';
import { getTradingTransactions } from '@/utils/tradingApi';
import { getPaymentHistory } from '@/utils/paymentsApi';
import { getRecentTrades } from '@/utils/portfolioApi';
import { getAccountTransactions, listBankingAccounts } from '@/utils/bankingApi';
import { toast } from 'react-hot-toast';

export default function TransactionsPage() {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all'); // 'all' | 'trading' | 'payment' | 'banking'
  const [dateRange, setDateRange] = useState({
    start: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    end: new Date().toISOString().split('T')[0]
  });

  useEffect(() => {
    fetchAllTransactions();
  }, [filter, dateRange]);

  const fetchAllTransactions = async () => {
    setLoading(true);
    try {
      const allTransactions = [];

      // Fetch trading transactions
      if (filter === 'all' || filter === 'trading') {
        const tradingTxs = await fetchTradingTransactions();
        allTransactions.push(...tradingTxs);
      }

      // Fetch payment transactions
      if (filter === 'all' || filter === 'payment') {
        const paymentTxs = await fetchPaymentTransactions();
        allTransactions.push(...paymentTxs);
      }

      // Fetch recent trades
      if (filter === 'all' || filter === 'trading') {
        const recentTrades = await fetchRecentTrades();
        allTransactions.push(...recentTrades);
      }

      // Fetch banking transactions
      if (filter === 'all' || filter === 'banking') {
        const bankingTxs = await fetchBankingTransactions();
        allTransactions.push(...bankingTxs);
      }

      // Sort by date (newest first)
      allTransactions.sort((a, b) => 
        new Date(b.date) - new Date(a.date)
      );

      setTransactions(allTransactions);
    } catch (error) {
      toast.error('Failed to load transactions');
    } finally {
      setLoading(false);
    }
  };

  const fetchTradingTransactions = async () => {
    try {
      const response = await getTradingTransactions({
        start_date: dateRange.start,
        end_date: dateRange.end,
        limit: 100
      });
      return response.transactions.map(tx => ({
        ...tx,
        type: 'trading',
        category: 'trade',
        date: tx.date
      }));
    } catch (error) {
      return [];
    }
  };

  const fetchPaymentTransactions = async () => {
    try {
      const response = await getPaymentHistory({
        limit: 100,
        offset: 0
      });
      return response.data.map(payment => ({
        id: payment.id,
        type: 'payment',
        category: 'subscription',
        amount: payment.amount,
        currency: payment.currency,
        status: payment.status,
        description: payment.description || 'Payment',
        date: payment.created_at,
        name: payment.description || 'Payment'
      }));
    } catch (error) {
      return [];
    }
  };

  const fetchRecentTrades = async () => {
    try {
      const response = await getRecentTrades({ limit: 50 });
      return response.data.map(trade => ({
        id: trade.id,
        type: 'trade',
        category: trade.type,
        symbol: trade.symbol,
        name: trade.symbol,
        amount: trade.type === 'buy' ? `-$${trade.total}` : `+$${trade.total}`,
        price: trade.price,
        quantity: trade.quantity,
        status: trade.status,
        date: trade.executed_at
      }));
    } catch (error) {
      return [];
    }
  };

  const fetchBankingTransactions = async () => {
    try {
      // First get all linked accounts
      const accountsResponse = await listBankingAccounts();
      const accounts = accountsResponse.data || [];

      // Fetch transactions from each account
      const allBankingTxs = [];
      for (const account of accounts) {
        try {
          const response = await getAccountTransactions(account.id, {
            start_date: dateRange.start,
            end_date: dateRange.end,
            limit: 100
          });
          allBankingTxs.push(...response.transactions.map(tx => ({
            ...tx,
            type: 'banking',
            date: tx.transaction_date
          })));
        } catch (error) {
          console.error(`Failed to fetch transactions for account ${account.id}:`, error);
        }
      }

      return allBankingTxs;
    } catch (error) {
      return [];
    }
  };

  // Render transactions list with filtering...
}
```

---

## Support Dashboard Integration

**Page Location**: `src/app/dashboard/support-dashboard/page.js`  
**Current Status**: ❌ Uses hardcoded mock data  
**Priority**: 🟡 **Medium**

### Available APIs

Support ticket APIs are available. Chat functionality may need separate implementation.

---

### 1. List Support Tickets

**GET** `/support/tickets?status=open&priority=high&page=1&limit=20`

**Description**: Get list of support tickets.

**Query Parameters**:
- `status` (string, optional): Filter by status (`open`, `in_progress`, `resolved`, `closed`)
- `priority` (string, optional): Filter by priority (`low`, `medium`, `high`, `urgent`)
- `page` (integer, optional): Page number (default: 1)
- `limit` (integer, optional): Items per page (default: 20, max: 100)

**Response** (200 OK):
```json
{
  "data": [
    {
      "id": "uuid",
      "subject": "Account Issue",
      "description": "I cannot access my account",
      "status": "open",
      "priority": "high",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T11:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

**Frontend Code Example**:
```javascript
import { listTickets } from '@/utils/supportTicketsApi';

const fetchSupportTickets = async (filters = {}) => {
  try {
    const response = await listTickets({
      status: filters.status,
      priority: filters.priority,
      page: filters.page || 1,
      limit: 20
    });
    return response;
  } catch (error) {
    console.error('Failed to fetch support tickets:', error);
    toast.error('Failed to load support tickets');
    return { data: [], total: 0 };
  }
};
```

---

### Complete Support Dashboard Integration

**Full Implementation Example**:
```javascript
'use client';

import { useState, useEffect } from 'react';
import { listTickets } from '@/utils/supportTicketsApi';
import { toast } from 'react-hot-toast';

export default function SupportDashboardPage() {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    status: null,
    priority: null,
    page: 1
  });

  useEffect(() => {
    fetchTickets();
  }, [filters]);

  const fetchTickets = async () => {
    setLoading(true);
    try {
      const response = await listTickets({
        status: filters.status,
        priority: filters.priority,
        page: filters.page,
        limit: 20
      });
      setTickets(response.data);
    } catch (error) {
      toast.error('Failed to load support tickets');
    } finally {
      setLoading(false);
    }
  };

  // Render tickets list...
}
```

**Note**: For chat functionality, you may need to implement WebSocket connections or use a separate chat API if available.

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

**Error Handling Pattern**:
```javascript
try {
  const response = await apiCall();
  // Handle success
} catch (error) {
  if (error.response) {
    // API returned error
    const message = error.response.data?.detail || 'An error occurred';
    toast.error(message);
  } else {
    // Network or other error
    toast.error('Failed to connect to server');
  }
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

### Transaction Types

**Labels**:
- `trading` → "Trading"
- `payment` → "Payment"
- `banking` → "Banking"
- `trade` → "Trade"

---

## Integration Checklist

### Notifications Page ✅

- [ ] Replace mock data with `getNotifications()`
- [ ] Add `getUnreadCount()` for badge in header
- [ ] Implement `markAsRead()` on notification click
- [ ] Implement `markAllAsRead()` button
- [ ] Implement `deleteNotification()` with confirmation
- [ ] Add notification settings UI
- [ ] Add loading states
- [ ] Add error handling
- [ ] Add real-time polling (every 30 seconds)
- [ ] Add filter for "All" vs "Unread"

### Referrals Page ✅

- [ ] Replace mock data with `getReferralStats()`
- [ ] Replace mock code with `getReferralCode()`
- [ ] Replace mock list with `getReferralList()` with pagination
- [ ] Add `getReferralRewards()` display
- [ ] Add `getReferralLeaderboard()` display (optional)
- [ ] Implement `generateReferralCode()` if needed
- [ ] Implement copy referral link functionality
- [ ] Add loading states
- [ ] Add error handling
- [ ] Add filter by status (pending/completed)

### Transactions Page ⚠️

- [ ] Decide on API approach (combined vs separate)
- [ ] Integrate `getTradingTransactions()`
- [ ] Integrate `getPaymentHistory()`
- [ ] Integrate `getRecentTrades()`
- [ ] Integrate `getAccountTransactions()` for banking
- [ ] Combine all transactions and sort by date
- [ ] Add filtering by type (trading/payment/banking)
- [ ] Add date range picker
- [ ] Add loading states
- [ ] Add error handling

### Support Dashboard ⚠️

- [ ] Integrate `listTickets()` API
- [ ] Add filtering by status and priority
- [ ] Add pagination
- [ ] Replace mock data
- [ ] Add loading states
- [ ] Add error handling
- [ ] (Optional) Add chat functionality if needed

---

## Quick Reference

| Section | Endpoints | Base Path | Priority |
|---------|-----------|-----------|----------|
| Notifications | 8 | `/notifications` | 🔴 High |
| Referrals | 6 | `/referrals` | 🔴 High |
| Transactions | 4+ | `/trading`, `/payments`, `/portfolio`, `/banking` | 🟡 Medium |
| Support | 1+ | `/support` | 🟡 Medium |

---

## Implementation Priority

### Immediate (High Priority)
1. **Notifications Page** - Core feature, all APIs ready
2. **Referrals Page** - Core feature, all APIs ready

### Short Term (Medium Priority)
3. **Transactions Page** - Combine multiple APIs
4. **Support Dashboard** - Use ticket APIs

---

**Last Updated**: 2024-01-15  
**Status**: ✅ All APIs Ready for Integration  
**Total Endpoints**: 19+
