# Newly Implemented APIs - Frontend Integration Guide

**Date**: 2024-01-15  
**Status**: ✅ All APIs Implemented and Ready for Frontend Integration  
**Priority**: 🔴 High Priority - Ready for Testing

---

## 📋 Executive Summary

This document provides a comprehensive guide for frontend developers to integrate the newly implemented backend APIs. All APIs listed in `BACKEND_TEAM_IMPLEMENTATION_REQUEST.md` have been successfully implemented and are ready for frontend integration.

**Total APIs Implemented**: 24 endpoints
- **Chat/Messaging**: 8 endpoints
- **Market Benchmarks**: 1 endpoint
- **Tasks**: 7 endpoints
- **Reminders**: 5 endpoints
- **Investment Watchlist**: 3 endpoints

---

## 🔐 Authentication

All endpoints require authentication via Bearer token:

```javascript
headers: {
  'Authorization': `Bearer ${accessToken}`,
  'Content-Type': 'application/json'
}
```

---

## 📡 API Base URL

```
Development: http://localhost:8000/api/v1
Production: https://api.yourapp.com/api/v1
```

---

## 1. Chat/Messaging System

**Base Path**: `/api/v1/chat`

### 1.1. Get Conversations

**Endpoint**: `GET /api/v1/chat/conversations`

**Query Parameters**:
- `status` (optional): `'active'` | `'archived'` | `'all'` (default: `'active'`)
- `limit` (optional): Number of results (1-100, default: 20)
- `offset` (optional): Pagination offset (default: 0)

**Response**:
```json
{
  "conversations": [
    {
      "id": "uuid",
      "participants": [
        {
          "userId": "uuid",
          "userName": "John Doe",
          "userAvatar": null,
          "isOnline": false,
          "lastSeen": null,
          "role": "participant"
        }
      ],
      "lastMessage": {
        "id": "uuid",
        "content": "Hello, I need help...",
        "senderId": "uuid",
        "timestamp": "2024-01-15T10:00:00Z",
        "isRead": false
      },
      "unreadCount": 2,
      "updatedAt": "2024-01-15T10:00:00Z",
      "subject": "Support Request"
    }
  ],
  "total": 10,
  "limit": 20,
  "offset": 0
}
```

**Frontend Example**:
```javascript
const getConversations = async (status = 'active', limit = 20, offset = 0) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/chat/conversations?status=${status}&limit=${limit}&offset=${offset}`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to fetch conversations');
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching conversations:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Conversations loaded successfully"
- Error: "Unable to load conversations. Please try again."

---

### 1.2. Get Conversation Messages

**Endpoint**: `GET /api/v1/chat/conversations/{conversation_id}/messages`

**Path Parameters**:
- `conversation_id` (required): UUID of the conversation

**Query Parameters**:
- `limit` (optional): Number of messages (1-100, default: 50)
- `before` (optional): ISO 8601 timestamp - get messages before this time
- `after` (optional): ISO 8601 timestamp - get messages after this time

**Response**:
```json
{
  "messages": [
    {
      "id": "uuid",
      "conversationId": "uuid",
      "senderId": "uuid",
      "senderName": "John Doe",
      "senderAvatar": null,
      "content": "Message content",
      "timestamp": "2024-01-15T10:00:00Z",
      "isRead": false,
      "attachments": [
        {
          "id": "uuid",
          "fileName": "document.pdf",
          "fileUrl": "https://...",
          "fileSize": 1024000,
          "mimeType": "application/pdf"
        }
      ]
    }
  ],
  "hasMore": false,
  "total": 150
}
```

**Frontend Example**:
```javascript
const getMessages = async (conversationId, limit = 50, before = null) => {
  try {
    let url = `${API_BASE_URL}/chat/conversations/${conversationId}/messages?limit=${limit}`;
    if (before) {
      url += `&before=${before}`;
    }
    
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    });
    
    if (!response.ok) {
      throw new Error('Failed to fetch messages');
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching messages:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Messages loaded"
- Error: "Unable to load messages. Please refresh and try again."

---

### 1.3. Send Message

**Endpoint**: `POST /api/v1/chat/conversations/{conversation_id}/messages`

**Path Parameters**:
- `conversation_id` (required): UUID of the conversation

**Request Body**:
```json
{
  "content": "Message text",  // Required, max 5000 characters
  "attachments": ["file_id_1", "file_id_2"]  // Optional, array of file IDs
}
```

**Response** (201 Created):
```json
{
  "message": {
    "id": "uuid",
    "conversationId": "uuid",
    "senderId": "uuid",
    "senderName": "John Doe",
    "senderAvatar": null,
    "content": "Message text",
    "timestamp": "2024-01-15T10:00:00Z",
    "isRead": false,
    "attachments": []
  }
}
```

**Frontend Example**:
```javascript
const sendMessage = async (conversationId, content, attachments = []) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/chat/conversations/${conversationId}/messages`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          content,
          attachments
        })
      }
    );
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to send message');
    }
    
    const data = await response.json();
    return data.message;
  } catch (error) {
    console.error('Error sending message:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Message sent successfully"
- Error: "Failed to send message. Please check your connection and try again."
- Validation Error: "Message is too long. Maximum 5000 characters allowed."

---

### 1.4. Mark Messages as Read

**Endpoint**: `PUT /api/v1/chat/conversations/{conversation_id}/read`

**Path Parameters**:
- `conversation_id` (required): UUID of the conversation

**Request Body**:
```json
{
  "messageIds": ["uuid1", "uuid2"]  // Optional, if not provided, marks all as read
}
```

**Response**:
```json
{
  "updated": 5,
  "message": "Messages marked as read"
}
```

**Frontend Example**:
```javascript
const markAsRead = async (conversationId, messageIds = null) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/chat/conversations/${conversationId}/read`,
      {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          messageIds: messageIds || undefined
        })
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to mark messages as read');
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error marking messages as read:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Messages marked as read"
- Error: "Unable to update read status. Please try again."

---

### 1.5. Delete Message

**Endpoint**: `DELETE /api/v1/chat/messages/{message_id}`

**Path Parameters**:
- `message_id` (required): UUID of the message

**Response**: 204 No Content

**Frontend Example**:
```javascript
const deleteMessage = async (messageId) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/chat/messages/${messageId}`,
      {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to delete message');
    }
    
    return true;
  } catch (error) {
    console.error('Error deleting message:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Message deleted"
- Error: "Unable to delete message. Please try again."
- Forbidden: "You can only delete your own messages."

---

### 1.6. Get Conversation Participants

**Endpoint**: `GET /api/v1/chat/conversations/{conversation_id}/participants`

**Path Parameters**:
- `conversation_id` (required): UUID of the conversation

**Response**:
```json
{
  "participants": [
    {
      "userId": "uuid",
      "userName": "John Doe",
      "userAvatar": null,
      "isOnline": false,
      "lastSeen": "2024-01-15T10:00:00Z",
      "role": "participant"
    }
  ]
}
```

**Frontend Example**:
```javascript
const getParticipants = async (conversationId) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/chat/conversations/${conversationId}/participants`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to fetch participants');
    }
    
    const data = await response.json();
    return data.participants;
  } catch (error) {
    console.error('Error fetching participants:', error);
    throw error;
  }
};
```

---

### 1.7. Create Conversation

**Endpoint**: `POST /api/v1/chat/conversations`

**Request Body**:
```json
{
  "participantIds": ["user_uuid_1", "user_uuid_2"],  // Required, min 1, max 10
  "subject": "Support Request",  // Optional, max 200 characters
  "initialMessage": "Hello, I need help..."  // Optional, max 5000 characters
}
```

**Response** (201 Created):
```json
{
  "conversation": {
    "id": "uuid",
    "participants": [
      {
        "userId": "uuid",
        "userName": "John Doe",
        "userAvatar": null,
        "isOnline": false,
        "lastSeen": null,
        "role": "admin"
      }
    ],
    "subject": "Support Request",
    "createdAt": "2024-01-15T10:00:00Z",
    "lastMessage": null,
    "unreadCount": 0
  },
  "initialMessage": {
    "id": "uuid",
    "content": "Hello, I need help...",
    "timestamp": "2024-01-15T10:00:00Z"
  }
}
```

**Frontend Example**:
```javascript
const createConversation = async (participantIds, subject = null, initialMessage = null) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/chat/conversations`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          participantIds,
          subject,
          initialMessage
        })
      }
    );
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to create conversation');
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error creating conversation:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Conversation created successfully"
- Error: "Failed to create conversation. Please try again."
- Validation Error: "Please select at least one participant."

---

### 1.8. Update Conversation

**Endpoint**: `PUT /api/v1/chat/conversations/{conversation_id}`

**Path Parameters**:
- `conversation_id` (required): UUID of the conversation

**Request Body**:
```json
{
  "subject": "Updated Subject",  // Optional
  "muted": true,  // Optional
  "archived": true  // Optional
}
```

**Response**:
```json
{
  "conversation": {
    "id": "uuid",
    "subject": "Updated Subject",
    "muted": true,
    "archived": true,
    "updatedAt": "2024-01-15T10:00:00Z"
  }
}
```

**Frontend Example**:
```javascript
const updateConversation = async (conversationId, updates) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/chat/conversations/${conversationId}`,
      {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(updates)
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to update conversation');
    }
    
    const data = await response.json();
    return data.conversation;
  } catch (error) {
    console.error('Error updating conversation:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Conversation updated"
- Error: "Unable to update conversation. Please try again."

---

## 2. Market Benchmarks API

**Base Path**: `/api/v1/market`

### 2.1. Get Market Benchmarks

**Endpoint**: `GET /api/v1/market/benchmarks`

**Query Parameters**:
- `benchmarks` (optional): Comma-separated list of symbols (e.g., `'SPY,DIA,TSLA'`)
  - Default: `['SPY', 'DIA', 'TSLA']` if not provided
  - Max: 10 symbols per request
- `timeRange` (optional): `'1D'` | `'1W'` | `'1M'` | `'3M'` | `'6M'` | `'1Y'` | `'ALL'`
  - Default: `'1Y'`

**Response**:
```json
{
  "benchmarks": [
    {
      "symbol": "SPY",
      "name": "S&P 500",
      "currentValue": 4500.25,
      "change": 25.50,
      "changePercentage": 0.57,
      "currency": "USD",
      "historicalData": [
        {
          "date": "2024-01-01",
          "value": 4474.75
        },
        {
          "date": "2024-01-02",
          "value": 4480.00
        }
      ]
    },
    {
      "symbol": "DIA",
      "name": "DOW JONES",
      "currentValue": 35000.00,
      "change": -150.00,
      "changePercentage": -0.43,
      "currency": "USD",
      "historicalData": []
    }
  ],
  "timeRange": "1Y",
  "updatedAt": "2024-01-15T10:00:00Z"
}
```

**Frontend Example**:
```javascript
const getBenchmarks = async (benchmarks = ['SPY', 'DIA', 'TSLA'], timeRange = '1Y') => {
  try {
    const benchmarksParam = Array.isArray(benchmarks) 
      ? benchmarks.join(',') 
      : benchmarks;
    
    const response = await fetch(
      `${API_BASE_URL}/market/benchmarks?benchmarks=${benchmarksParam}&timeRange=${timeRange}`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to fetch benchmarks');
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching benchmarks:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Market benchmarks loaded"
- Error: "Unable to load market data. Please try again later."
- No Data: "No benchmark data available at this time."

---

## 3. Tasks API

**Base Path**: `/api/v1/tasks`

### 3.1. Get Tasks

**Endpoint**: `GET /api/v1/tasks`

**Query Parameters**:
- `status` (optional): `'pending'` | `'in_progress'` | `'completed'` | `'cancelled'`
- `priority` (optional): `'low'` | `'medium'` | `'high'` | `'urgent'`
- `category` (optional): Filter by category
- `due_date_from` (optional): ISO 8601 date
- `due_date_to` (optional): ISO 8601 date
- `limit` (optional): Number of tasks (default: 20, max: 100)
- `offset` (optional): Pagination offset (default: 0)

**Response**:
```json
{
  "data": [
    {
      "id": "uuid",
      "title": "Review investment portfolio",
      "description": "Review and rebalance portfolio",
      "status": "pending",
      "priority": "high",
      "category": "investment",
      "dueDate": "2024-01-20T00:00:00Z",
      "reminderDate": "2024-01-19T09:00:00Z",
      "completedAt": null,
      "createdAt": "2024-01-15T10:00:00Z",
      "updatedAt": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 10,
  "limit": 20,
  "offset": 0
}
```

**Frontend Example**:
```javascript
const getTasks = async (filters = {}, limit = 20, offset = 0) => {
  try {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
      ...filters
    });
    
    const response = await fetch(
      `${API_BASE_URL}/tasks?${params}`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to fetch tasks');
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching tasks:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Tasks loaded successfully"
- Error: "Unable to load tasks. Please try again."
- Empty: "No tasks found. Create your first task to get started!"

---

### 3.2. Create Task

**Endpoint**: `POST /api/v1/tasks`

**Request Body**:
```json
{
  "title": "Review investment portfolio",  // Required, max 200 characters
  "description": "Review and rebalance portfolio",  // Optional, max 5000 characters
  "priority": "high",  // Optional: "low" | "medium" | "high" | "urgent" (default: "medium")
  "category": "investment",  // Optional
  "dueDate": "2024-01-20T00:00:00Z",  // Optional, ISO 8601 datetime
  "reminderDate": "2024-01-19T09:00:00Z"  // Optional, ISO 8601 datetime
}
```

**Response** (201 Created):
```json
{
  "task": {
    "id": "uuid",
    "title": "Review investment portfolio",
    "description": "Review and rebalance portfolio",
    "status": "pending",
    "priority": "high",
    "category": "investment",
    "dueDate": "2024-01-20T00:00:00Z",
    "reminderDate": "2024-01-19T09:00:00Z",
    "completedAt": null,
    "createdAt": "2024-01-15T10:00:00Z",
    "updatedAt": "2024-01-15T10:00:00Z"
  }
}
```

**Frontend Example**:
```javascript
const createTask = async (taskData) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/tasks`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(taskData)
      }
    );
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to create task');
    }
    
    const data = await response.json();
    return data.task;
  } catch (error) {
    console.error('Error creating task:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Task created successfully"
- Error: "Failed to create task. Please try again."
- Validation Error: "Please provide a task title."

---

### 3.3. Get Task Details

**Endpoint**: `GET /api/v1/tasks/{task_id}`

**Response**:
```json
{
  "task": {
    "id": "uuid",
    "title": "Review investment portfolio",
    "description": "Review and rebalance portfolio",
    "status": "pending",
    "priority": "high",
    "category": "investment",
    "dueDate": "2024-01-20T00:00:00Z",
    "reminderDate": "2024-01-19T09:00:00Z",
    "completedAt": null,
    "createdAt": "2024-01-15T10:00:00Z",
    "updatedAt": "2024-01-15T10:00:00Z"
  }
}
```

---

### 3.4. Update Task

**Endpoint**: `PUT /api/v1/tasks/{task_id}`

**Request Body** (all fields optional):
```json
{
  "title": "Updated title",
  "description": "Updated description",
  "priority": "medium",
  "category": "investment",
  "dueDate": "2024-01-25T00:00:00Z",
  "reminderDate": "2024-01-24T09:00:00Z"
}
```

**Response**: Same as Get Task Details

---

### 3.5. Delete Task

**Endpoint**: `DELETE /api/v1/tasks/{task_id}`

**Response**: 204 No Content

**User-Friendly Messages**:
- Success: "Task deleted successfully"
- Error: "Unable to delete task. Please try again."

---

### 3.6. Mark Task as Complete

**Endpoint**: `PUT /api/v1/tasks/{task_id}/complete`

**Response**:
```json
{
  "task": {
    "id": "uuid",
    "status": "completed",
    "completedAt": "2024-01-15T11:00:00Z",
    "updatedAt": "2024-01-15T11:00:00Z"
  }
}
```

**User-Friendly Messages**:
- Success: "Task marked as complete! 🎉"
- Error: "Unable to complete task. Please try again."

---

### 3.7. Set Task Reminder

**Endpoint**: `PUT /api/v1/tasks/{task_id}/remind`

**Request Body**:
```json
{
  "reminderDate": "2024-01-19T09:00:00Z"  // Required, ISO 8601 datetime
}
```

**Response**: Same as Get Task Details

**User-Friendly Messages**:
- Success: "Reminder set successfully"
- Error: "Failed to set reminder. Please try again."

---

## 4. Reminders API

**Base Path**: `/api/v1/reminders`

### 4.1. Get Reminders

**Endpoint**: `GET /api/v1/reminders`

**Query Parameters**:
- `status` (optional): `'pending'` | `'snoozed'` | `'completed'` | `'cancelled'`
- `due_date_from` (optional): ISO 8601 date
- `due_date_to` (optional): ISO 8601 date
- `limit` (optional): Number of reminders (default: 20, max: 100)
- `offset` (optional): Pagination offset (default: 0)

**Response**:
```json
{
  "data": [
    {
      "id": "uuid",
      "title": "Portfolio review reminder",
      "description": "Time to review your portfolio",
      "reminderDate": "2024-01-19T09:00:00Z",
      "status": "pending",
      "taskId": "uuid",
      "notificationChannels": ["email", "push"],
      "snoozedUntil": null,
      "createdAt": "2024-01-15T10:00:00Z",
      "updatedAt": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 5,
  "limit": 20,
  "offset": 0
}
```

---

### 4.2. Create Reminder

**Endpoint**: `POST /api/v1/reminders`

**Request Body**:
```json
{
  "title": "Portfolio review reminder",  // Required, max 200 characters
  "description": "Time to review your portfolio",  // Optional, max 5000 characters
  "reminderDate": "2024-01-19T09:00:00Z",  // Required, ISO 8601 datetime
  "taskId": "uuid",  // Optional, link to a task
  "notificationChannels": ["email", "push"]  // Optional: ["email", "push", "sms"]
}
```

**Response** (201 Created):
```json
{
  "reminder": {
    "id": "uuid",
    "title": "Portfolio review reminder",
    "description": "Time to review your portfolio",
    "reminderDate": "2024-01-19T09:00:00Z",
    "status": "pending",
    "taskId": "uuid",
    "notificationChannels": ["email", "push"],
    "snoozedUntil": null,
    "createdAt": "2024-01-15T10:00:00Z",
    "updatedAt": "2024-01-15T10:00:00Z"
  }
}
```

**User-Friendly Messages**:
- Success: "Reminder created successfully"
- Error: "Failed to create reminder. Please try again."

---

### 4.3. Update Reminder

**Endpoint**: `PUT /api/v1/reminders/{reminder_id}`

**Request Body** (all fields optional):
```json
{
  "title": "Updated title",
  "description": "Updated description",
  "reminderDate": "2024-01-20T09:00:00Z",
  "notificationChannels": ["email"]
}
```

---

### 4.4. Delete Reminder

**Endpoint**: `DELETE /api/v1/reminders/{reminder_id}`

**Response**: 204 No Content

**User-Friendly Messages**:
- Success: "Reminder deleted"
- Error: "Unable to delete reminder. Please try again."

---

### 4.5. Snooze Reminder

**Endpoint**: `PUT /api/v1/reminders/{reminder_id}/snooze`

**Request Body**:
```json
{
  "snoozeUntil": "2024-01-20T09:00:00Z"  // Required, ISO 8601 datetime
}
```

**Response**:
```json
{
  "reminder": {
    "id": "uuid",
    "status": "snoozed",
    "reminderDate": "2024-01-20T09:00:00Z",
    "snoozedUntil": "2024-01-20T09:00:00Z",
    "updatedAt": "2024-01-15T11:00:00Z"
  }
}
```

**User-Friendly Messages**:
- Success: "Reminder snoozed until [date]"
- Error: "Failed to snooze reminder. Please try again."

---

## 5. Investment Watchlist API

**Base Path**: `/api/v1/investment`

### 5.1. Get Investment Watchlist

**Endpoint**: `GET /api/v1/investment/watchlist`

**Response**:
```json
{
  "data": [
    {
      "id": "uuid",
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "assetType": "stock",
      "currentPrice": 200.00,
      "change": 2.50,
      "changePercentage": 1.25,
      "addedAt": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 5
}
```

**Frontend Example**:
```javascript
const getWatchlist = async () => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/investment/watchlist`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to fetch watchlist');
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching watchlist:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Watchlist loaded"
- Error: "Unable to load watchlist. Please try again."
- Empty: "Your watchlist is empty. Add assets to track their performance."

---

### 5.2. Add to Investment Watchlist

**Endpoint**: `POST /api/v1/investment/watchlist`

**Request Body**:
```json
{
  "symbol": "AAPL",  // Required
  "assetType": "stock",  // Required: "stock" | "crypto" | "etf" | "bond"
  "name": "Apple Inc."  // Optional
}
```

**Response** (201 Created):
```json
{
  "watchlistItem": {
    "id": "uuid",
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "assetType": "stock",
    "addedAt": "2024-01-15T10:00:00Z"
  }
}
```

**Frontend Example**:
```javascript
const addToWatchlist = async (symbol, assetType, name = null) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/investment/watchlist`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          symbol,
          assetType,
          name
        })
      }
    );
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to add to watchlist');
    }
    
    const data = await response.json();
    return data.watchlistItem;
  } catch (error) {
    console.error('Error adding to watchlist:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "[Symbol] added to watchlist"
- Error: "Failed to add to watchlist. Please try again."
- Duplicate: "This asset is already in your watchlist."

---

### 5.3. Remove from Investment Watchlist

**Endpoint**: `DELETE /api/v1/investment/watchlist/{item_id}`

**Path Parameters**:
- `item_id` (required): UUID of the watchlist item

**Response**: 204 No Content

**Frontend Example**:
```javascript
const removeFromWatchlist = async (itemId) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/investment/watchlist/${itemId}`,
      {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      }
    );
    
    if (!response.ok) {
      throw new Error('Failed to remove from watchlist');
    }
    
    return true;
  } catch (error) {
    console.error('Error removing from watchlist:', error);
    throw error;
  }
};
```

**User-Friendly Messages**:
- Success: "Removed from watchlist"
- Error: "Unable to remove item. Please try again."

---

## 🔄 Error Handling

All endpoints follow consistent error response format:

```json
{
  "detail": "Error message description",
  "code": "ERROR_CODE",  // Optional
  "field": "field_name"  // Optional, for validation errors
}
```

**Common HTTP Status Codes**:
- `200 OK`: Success
- `201 Created`: Resource created successfully
- `204 No Content`: Success with no response body
- `400 Bad Request`: Invalid request data
- `401 Unauthorized`: Authentication required
- `403 Forbidden`: Insufficient permissions
- `404 Not Found`: Resource not found
- `422 Unprocessable Entity`: Validation error
- `500 Internal Server Error`: Server error

**Frontend Error Handling Example**:
```javascript
const handleApiError = async (response) => {
  if (!response.ok) {
    const error = await response.json().catch(() => ({
      detail: 'An unexpected error occurred'
    }));
    
    switch (response.status) {
      case 400:
        throw new Error(error.detail || 'Invalid request');
      case 401:
        throw new Error('Please log in to continue');
      case 403:
        throw new Error('You do not have permission to perform this action');
      case 404:
        throw new Error('Resource not found');
      case 422:
        throw new Error(error.detail || 'Validation error');
      case 500:
        throw new Error('Server error. Please try again later');
      default:
        throw new Error(error.detail || 'An error occurred');
    }
  }
  return response;
};
```

---

## 💡 Integration Tips

### 1. **Pagination**
- Always use `limit` and `offset` for list endpoints
- Implement "Load More" or infinite scroll for better UX
- Check `hasMore` field (where available) to determine if more data exists

### 2. **Real-time Updates** (Future Enhancement)
- WebSocket support for chat is recommended but not yet implemented
- Consider polling for real-time updates in the meantime
- Poll interval: 5-10 seconds for active conversations

### 3. **Caching**
- Cache benchmark data for 15 minutes (matches backend cache)
- Cache watchlist data and refresh on user action
- Cache conversation list and refresh on navigation

### 4. **Optimistic Updates**
- For chat messages, show message immediately before API confirmation
- For task completion, update UI immediately
- Rollback on error

### 5. **Date Handling**
- All dates are in ISO 8601 format with timezone
- Use UTC for consistency
- Format dates for display using user's locale

### 6. **File Attachments** (Chat)
- File attachments require file upload first (use `/api/v1/files/upload`)
- Store file IDs and pass them in `attachments` array
- Display file size and type before upload

---

## 📝 Testing Checklist

Before deploying to production, test:

- [ ] All endpoints return expected response formats
- [ ] Authentication works correctly
- [ ] Error handling displays user-friendly messages
- [ ] Pagination works for all list endpoints
- [ ] Date/time formatting is correct
- [ ] File uploads work for chat attachments
- [ ] Real-time updates (if implemented) work correctly
- [ ] Mobile responsiveness for all features

---

## 📞 Support

For questions or issues:
- **Backend Team**: Available for API clarifications
- **Frontend Team**: For integration support
- **Technical Lead**: For architecture questions

---

**Document Version**: 1.0  
**Last Updated**: 2024-01-15  
**Status**: ✅ Ready for Frontend Integration
