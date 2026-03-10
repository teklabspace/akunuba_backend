# Backend Team - API Implementation Request

**Date**: 2024-01-15  
**From**: Frontend Team  
**To**: Backend Development Team  
**Priority**: 🔴 High Priority Items Identified  
**Status**: ⚠️ Ready for Implementation Planning

---

## 📋 Executive Summary

After comprehensive analysis of the platform, we've identified **6 sections** that require backend API implementation to be fully functional. This document outlines all missing APIs with complete specifications, request/response formats, and implementation requirements.

**Total Missing APIs**: 15+ endpoints  
**Total Missing Features**: 8+ features  
**Estimated Total Implementation Time**: 4-6 weeks

---

## 🎯 Priority Breakdown

### 🔴 High Priority (Critical for MVP)

**1. Chat/Messaging System**
- **Status**: UI exists, but no backend APIs
- **Required**: 8 REST API endpoints + WebSocket server
- **Estimated Time**: 2-3 weeks
- **Impact**: Core feature for support team communication
- **Details**: See [Section 1: Chat/Messaging System](#1-chatmessaging-system)

### 🟡 Medium Priority (Important Features)

**2. Market Benchmarks API**
- **Status**: UI exists, but no backend API
- **Required**: 1 REST API endpoint
- **Estimated Time**: 3-5 days
- **Impact**: Enhances main dashboard with market comparison
- **Details**: See [Section 2: Market Benchmarks](#2-market-benchmarks-api)

**3. Task & Reminders System**
- **Status**: Placeholder UI only ("coming soon")
- **Required**: 7 Tasks API endpoints + 5 Reminders API endpoints
- **Estimated Time**: 1-2 weeks
- **Impact**: User productivity feature
- **Details**: See [Section 3: Task & Reminders](#3-task--reminders-system)

**4. Investment Watchlist**
- **Status**: Endpoints defined in config, but need verification
- **Required**: 3 REST API endpoints (if not already implemented)
- **Estimated Time**: 3-5 days
- **Impact**: Investment tracking feature
- **Details**: See [Section 6: Investment Watchlist](#6-investment-watchlist)

### ✅ Already Implemented (No Backend Work Needed)

- **Add Entity API**: ✅ Already exists, only frontend UI needed
- **Investment Features APIs**: ✅ Already exist, only frontend UI integration needed

---

## 📄 Complete API Specifications

### 1. Chat/Messaging System

**Priority**: 🔴 **High**  
**Estimated Time**: 2-3 weeks  
**Impact**: Core feature for support team communication

#### Overview
The support dashboard has a fully functional chat UI, but currently lacks backend APIs. We need a complete real-time messaging system with WebSocket support.

#### Required APIs

**1.1. Get Conversations**
```
GET /api/v1/chat/conversations
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Query Parameters:
  - status (string, optional): 'active' | 'archived' | 'all' (default: 'active')
  - limit (integer, optional): Number of results (1-100, default: 20)
  - offset (integer, optional): Pagination offset (default: 0)

Response (200):
{
  "conversations": [
    {
      "id": "uuid",
      "participants": [
        {
          "userId": "uuid",
          "userName": "John Doe",
          "userAvatar": "url",
          "isOnline": true,
          "lastSeen": "2024-01-15T10:00:00Z"
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
      "updatedAt": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 10,
  "limit": 20,
  "offset": 0
}

Error Responses:
  401 Unauthorized: {"detail": "Not authenticated"}
  403 Forbidden: {"detail": "Insufficient permissions"}
  500 Internal Server Error: {"detail": "Internal server error"}
```

**1.2. Get Conversation Messages**
```
GET /api/v1/chat/conversations/{conversation_id}/messages
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Path Parameters:
  - conversation_id (string, required): UUID of the conversation

Query Parameters:
  - limit (integer, optional): Number of messages (1-100, default: 50)
  - before (string, optional): ISO 8601 timestamp - get messages before this time
  - after (string, optional): ISO 8601 timestamp - get messages after this time

Response (200):
{
  "messages": [
    {
      "id": "uuid",
      "conversationId": "uuid",
      "senderId": "uuid",
      "senderName": "John Doe",
      "senderAvatar": "url",
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

Error Responses:
  401 Unauthorized: {"detail": "Not authenticated"}
  403 Forbidden: {"detail": "User not part of this conversation"}
  404 Not Found: {"detail": "Conversation not found"}
  500 Internal Server Error: {"detail": "Internal server error"}
```

**1.3. Send Message**
```
POST /api/v1/chat/conversations/{conversation_id}/messages
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Path Parameters:
  - conversation_id (string, required): UUID of the conversation

Request Body:
{
  "content": "Message text",  // Required, max 5000 characters
  "attachments": ["file_id_1", "file_id_2"]  // Optional, array of file IDs
}

Response (201):
{
  "message": {
    "id": "uuid",
    "conversationId": "uuid",
    "senderId": "uuid",
    "senderName": "John Doe",
    "senderAvatar": "url",
    "content": "Message text",
    "timestamp": "2024-01-15T10:00:00Z",
    "isRead": false,
    "attachments": []
  }
}

Error Responses:
  400 Bad Request: {"detail": "Invalid request body, content too long, or invalid file IDs"}
  401 Unauthorized: {"detail": "Not authenticated"}
  403 Forbidden: {"detail": "User not part of this conversation"}
  404 Not Found: {"detail": "Conversation not found"}
  500 Internal Server Error: {"detail": "Internal server error"}
```

**1.4. Mark Messages as Read**
```
PUT /api/v1/chat/conversations/{conversation_id}/read
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Path Parameters:
  - conversation_id (string, required): UUID of the conversation

Request Body:
{
  "messageIds": ["uuid1", "uuid2"]  // Optional, array of message UUIDs. If not provided, mark all as read
}

Response (200):
{
  "updated": 5,
  "message": "Messages marked as read"
}

Error Responses:
  400 Bad Request: {"detail": "Invalid message IDs"}
  401 Unauthorized: {"detail": "Not authenticated"}
  403 Forbidden: {"detail": "User not part of this conversation"}
  404 Not Found: {"detail": "Conversation not found"}
  500 Internal Server Error: {"detail": "Internal server error"}
```

**1.5. Delete Message**
```
DELETE /api/v1/chat/messages/{message_id}
Headers:
  Authorization: Bearer <token>

Path Parameters:
  - message_id (string, required): UUID of the message

Response (204 No Content):
(No body)

Error Responses:
  401 Unauthorized: {"detail": "Not authenticated"}
  403 Forbidden: {"detail": "User not authorized to delete this message"}
  404 Not Found: {"detail": "Message not found"}
  500 Internal Server Error: {"detail": "Internal server error"}
```

**1.6. Get Conversation Participants**
```
GET /api/v1/chat/conversations/{conversation_id}/participants
Headers:
  Authorization: Bearer <token>

Path Parameters:
  - conversation_id (string, required): UUID of the conversation

Response (200):
{
  "participants": [
    {
      "userId": "uuid",
      "userName": "John Doe",
      "userAvatar": "url",
      "isOnline": true,
      "lastSeen": "2024-01-15T10:00:00Z",
      "role": "participant"  // "participant" | "admin" | "moderator"
    }
  ]
}

Error Responses:
  401 Unauthorized: {"detail": "Not authenticated"}
  403 Forbidden: {"detail": "User not part of this conversation"}
  404 Not Found: {"detail": "Conversation not found"}
```

**1.7. Create Conversation**
```
POST /api/v1/chat/conversations
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Request Body:
{
  "participantIds": ["user_uuid_1", "user_uuid_2"],  // Required, array of user UUIDs (min 1, max 10)
  "subject": "Support Request",  // Optional, max 200 characters
  "initialMessage": "Hello, I need help..."  // Optional, max 5000 characters
}

Response (201):
{
  "conversation": {
    "id": "uuid",
    "participants": [
      {
        "userId": "uuid",
        "userName": "John Doe",
        "userAvatar": "url",
        "isOnline": false,
        "lastSeen": null
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
  }  // Only included if initialMessage was provided
}

Error Responses:
  400 Bad Request: {"detail": "Invalid participant IDs, duplicate participants, or invalid subject/message"}
  401 Unauthorized: {"detail": "Not authenticated"}
  404 Not Found: {"detail": "One or more participant IDs not found"}
  500 Internal Server Error: {"detail": "Internal server error"}
```

**1.8. Update Conversation**
```
PUT /api/v1/chat/conversations/{conversation_id}
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Path Parameters:
  - conversation_id (string, required): UUID of the conversation

Request Body:
{
  "subject": "Updated Subject",  // Optional
  "muted": true,  // Optional, mute notifications for this conversation
  "archived": true  // Optional, archive the conversation
}

Response (200):
{
  "conversation": {
    "id": "uuid",
    "subject": "Updated Subject",
    "muted": true,
    "archived": true,
    "updatedAt": "2024-01-15T10:00:00Z"
  }
}

Error Responses:
  400 Bad Request: {"detail": "Invalid request body"}
  401 Unauthorized: {"detail": "Not authenticated"}
  403 Forbidden: {"detail": "User not part of this conversation"}
  404 Not Found: {"detail": "Conversation not found"}
```

#### WebSocket Support (Recommended)

**WebSocket Connection**:
- **URL**: `wss://api.example.com/ws/chat`
- **Authentication**: Bearer token in connection query parameter or header
- **Connection**: Persistent connection for real-time updates

**WebSocket Events**:

**Client → Server**:
- `message:send` - Send a message
- `typing:start` - User started typing
- `typing:stop` - User stopped typing
- `read:mark` - Mark messages as read

**Server → Client**:
- `message:new` - New message received
  ```json
  {
    "event": "message:new",
    "data": {
      "message": { /* message object */ }
    }
  }
  ```
- `message:read` - Message read by recipient
  ```json
  {
    "event": "message:read",
    "data": {
      "messageId": "uuid",
      "readBy": "uuid",
      "readAt": "2024-01-15T10:00:00Z"
    }
  }
  ```
- `typing:start` - User started typing
  ```json
  {
    "event": "typing:start",
    "data": {
      "conversationId": "uuid",
      "userId": "uuid",
      "userName": "John Doe"
    }
  }
  ```
- `typing:stop` - User stopped typing
- `user:online` - User came online
- `user:offline` - User went offline

#### Database Schema Considerations

**Tables Needed**:
1. `conversations` - Store conversation metadata
2. `conversation_participants` - Many-to-many relationship
3. `messages` - Store messages
4. `message_attachments` - Store file attachments
5. `message_reads` - Track read receipts

**Key Fields**:
- `conversations`: id, subject, created_at, updated_at, archived_at
- `messages`: id, conversation_id, sender_id, content, timestamp, is_read
- `conversation_participants`: conversation_id, user_id, role, joined_at

#### Implementation Checklist

- [ ] Design database schema
- [ ] Implement REST API endpoints (8 endpoints)
- [ ] Implement WebSocket server
- [ ] Add message persistence and pagination
- [ ] Add file attachment support
- [ ] Implement typing indicators
- [ ] Implement online/offline status tracking
- [ ] Add message read receipts
- [ ] Add rate limiting for message sending
- [ ] Add spam detection
- [ ] Add conversation archiving
- [ ] Add conversation search functionality

---

### 2. Market Benchmarks API

**Priority**: 🟡 **Medium**  
**Estimated Time**: 3-5 days  
**Impact**: Enhances main dashboard with market comparison

#### Overview
The main dashboard displays benchmark comparison (S&P 500, DOW JONES, TSLA), but currently shows "No benchmark data available". We need an API to fetch real-time and historical benchmark data.

#### Required API

**2.1. Get Market Benchmarks**
```
GET /api/v1/market/benchmarks
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Query Parameters:
  - benchmarks (string[], optional): Array of benchmark symbols (e.g., ['SPY', 'DIA', 'TSLA'])
    Default: ['SPY', 'DIA', 'TSLA'] if not provided
    Max: 10 symbols per request
  - timeRange (string, optional): '1D' | '1W' | '1M' | '3M' | '6M' | '1Y' | 'ALL'
    Default: '1Y'

Response (200):
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
    },
    {
      "symbol": "TSLA",
      "name": "Tesla Inc.",
      "currentValue": 250.75,
      "change": 5.25,
      "changePercentage": 2.14,
      "currency": "USD",
      "historicalData": []
    }
  ],
  "timeRange": "1Y",
  "updatedAt": "2024-01-15T10:00:00Z"
}

Error Responses:
  400 Bad Request: {"detail": "Invalid benchmark symbols or timeRange value"}
  401 Unauthorized: {"detail": "Not authenticated"}
  500 Internal Server Error: {"detail": "Internal server error or data provider unavailable"}
```

#### Data Source Requirements

**Recommended Providers**:
- Alpha Vantage API
- Yahoo Finance API
- Polygon.io
- IEX Cloud

**Caching Strategy**:
- Cache benchmark data for 15 minutes
- Update cache asynchronously
- Return cached data if provider is unavailable

#### Implementation Checklist

- [ ] Choose financial data provider
- [ ] Set up API credentials
- [ ] Implement benchmarks API endpoint
- [ ] Add caching mechanism (15-minute TTL)
- [ ] Add support for multiple benchmark types (indices, stocks, ETFs)
- [ ] Add historical data retrieval
- [ ] Add error handling for data provider failures
- [ ] Add rate limiting
- [ ] Add fallback mechanism if provider fails

---

### 3. Task & Reminders System

**Priority**: 🟡 **Medium**  
**Estimated Time**: 1-2 weeks  
**Impact**: User productivity feature

#### Overview
The settings page has a "Task & Reminders" tab with placeholder text. We need complete APIs for task and reminder management.

#### Required APIs

**3.1. Tasks API**

**3.1.1. Get Tasks**
```
GET /api/v1/tasks
Headers:
  Authorization: Bearer <token>

Query Parameters:
  - status (string, optional): 'pending' | 'in_progress' | 'completed' | 'cancelled'
  - priority (string, optional): 'low' | 'medium' | 'high' | 'urgent'
  - category (string, optional): Filter by category
  - due_date_from (string, optional): ISO 8601 date
  - due_date_to (string, optional): ISO 8601 date
  - limit (integer, optional): Number of tasks (default: 20, max: 100)
  - offset (integer, optional): Pagination offset (default: 0)

Response (200):
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

**3.1.2. Create Task**
```
POST /api/v1/tasks
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Request Body:
{
  "title": "Review investment portfolio",  // Required, max 200 characters
  "description": "Review and rebalance portfolio",  // Optional, max 5000 characters
  "priority": "high",  // Optional: "low" | "medium" | "high" | "urgent" (default: "medium")
  "category": "investment",  // Optional
  "dueDate": "2024-01-20T00:00:00Z",  // Optional, ISO 8601 datetime
  "reminderDate": "2024-01-19T09:00:00Z"  // Optional, ISO 8601 datetime
}

Response (201):
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
    "createdAt": "2024-01-15T10:00:00Z",
    "updatedAt": "2024-01-15T10:00:00Z"
  }
}
```

**3.1.3. Get Task Details**
```
GET /api/v1/tasks/{task_id}
Headers:
  Authorization: Bearer <token>

Response (200):
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

**3.1.4. Update Task**
```
PUT /api/v1/tasks/{task_id}
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Request Body:
{
  "title": "Updated title",  // Optional
  "description": "Updated description",  // Optional
  "priority": "medium",  // Optional
  "category": "investment",  // Optional
  "dueDate": "2024-01-25T00:00:00Z",  // Optional
  "reminderDate": "2024-01-24T09:00:00Z"  // Optional
}

Response (200):
{
  "task": {
    "id": "uuid",
    "title": "Updated title",
    // ... updated fields
    "updatedAt": "2024-01-15T11:00:00Z"
  }
}
```

**3.1.5. Delete Task**
```
DELETE /api/v1/tasks/{task_id}
Headers:
  Authorization: Bearer <token>

Response (204 No Content):
(No body)
```

**3.1.6. Mark Task as Complete**
```
PUT /api/v1/tasks/{task_id}/complete
Headers:
  Authorization: Bearer <token>

Response (200):
{
  "task": {
    "id": "uuid",
    "status": "completed",
    "completedAt": "2024-01-15T11:00:00Z",
    "updatedAt": "2024-01-15T11:00:00Z"
  }
}
```

**3.1.7. Set Task Reminder**
```
PUT /api/v1/tasks/{task_id}/remind
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Request Body:
{
  "reminderDate": "2024-01-19T09:00:00Z"  // Required, ISO 8601 datetime
}

Response (200):
{
  "task": {
    "id": "uuid",
    "reminderDate": "2024-01-19T09:00:00Z",
    "updatedAt": "2024-01-15T11:00:00Z"
  }
}
```

**3.2. Reminders API**

**3.2.1. Get Reminders**
```
GET /api/v1/reminders
Headers:
  Authorization: Bearer <token>

Query Parameters:
  - status (string, optional): 'pending' | 'snoozed' | 'completed' | 'cancelled'
  - due_date_from (string, optional): ISO 8601 date
  - due_date_to (string, optional): ISO 8601 date
  - limit (integer, optional): Number of reminders (default: 20, max: 100)
  - offset (integer, optional): Pagination offset (default: 0)

Response (200):
{
  "data": [
    {
      "id": "uuid",
      "title": "Portfolio review reminder",
      "description": "Time to review your portfolio",
      "reminderDate": "2024-01-19T09:00:00Z",
      "status": "pending",
      "taskId": "uuid",  // Optional, if reminder is linked to a task
      "createdAt": "2024-01-15T10:00:00Z",
      "updatedAt": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 5,
  "limit": 20,
  "offset": 0
}
```

**3.2.2. Create Reminder**
```
POST /api/v1/reminders
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Request Body:
{
  "title": "Portfolio review reminder",  // Required, max 200 characters
  "description": "Time to review your portfolio",  // Optional, max 5000 characters
  "reminderDate": "2024-01-19T09:00:00Z",  // Required, ISO 8601 datetime
  "taskId": "uuid",  // Optional, link to a task
  "notificationChannels": ["email", "push"]  // Optional: ["email", "push", "sms"]
}

Response (201):
{
  "reminder": {
    "id": "uuid",
    "title": "Portfolio review reminder",
    "description": "Time to review your portfolio",
    "reminderDate": "2024-01-19T09:00:00Z",
    "status": "pending",
    "taskId": "uuid",
    "notificationChannels": ["email", "push"],
    "createdAt": "2024-01-15T10:00:00Z",
    "updatedAt": "2024-01-15T10:00:00Z"
  }
}
```

**3.2.3. Update Reminder**
```
PUT /api/v1/reminders/{reminder_id}
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Request Body:
{
  "title": "Updated title",  // Optional
  "description": "Updated description",  // Optional
  "reminderDate": "2024-01-20T09:00:00Z",  // Optional
  "notificationChannels": ["email"]  // Optional
}

Response (200):
{
  "reminder": {
    "id": "uuid",
    // ... updated fields
    "updatedAt": "2024-01-15T11:00:00Z"
  }
}
```

**3.2.4. Delete Reminder**
```
DELETE /api/v1/reminders/{reminder_id}
Headers:
  Authorization: Bearer <token>

Response (204 No Content):
(No body)
```

**3.2.5. Snooze Reminder**
```
PUT /api/v1/reminders/{reminder_id}/snooze
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Request Body:
{
  "snoozeUntil": "2024-01-20T09:00:00Z"  // Required, ISO 8601 datetime
}

Response (200):
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

#### Background Job Requirements

**Reminder Notification System**:
- Background job to check for due reminders
- Send notifications via configured channels (email, push, SMS)
- Update reminder status after notification sent
- Support for recurring reminders (optional)

#### Implementation Checklist

- [ ] Design database schema (tasks, reminders)
- [ ] Implement Tasks API (7 endpoints)
- [ ] Implement Reminders API (5 endpoints)
- [ ] Add reminder notification system (background job)
- [ ] Add email notification support
- [ ] Add push notification support
- [ ] Add SMS notification support (optional)
- [ ] Add task categories and tags
- [ ] Add task priorities
- [ ] Add task dependencies (optional)
- [ ] Add recurring tasks support (optional)
- [ ] Add task sharing/collaboration (optional)

---

### 4. Investment Watchlist

**Priority**: 🟡 **Medium**  
**Estimated Time**: 3-5 days  
**Impact**: Investment tracking feature

#### Overview
Endpoints are defined in frontend config, but need verification if they exist in backend. This is separate from the marketplace watchlist.

#### Required APIs (Need Verification)

**4.1. Get Investment Watchlist**
```
GET /api/v1/investment/watchlist
Headers:
  Authorization: Bearer <token>

Response (200):
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

**4.2. Add to Investment Watchlist**
```
POST /api/v1/investment/watchlist
Headers:
  Authorization: Bearer <token>
  Content-Type: application/json

Request Body:
{
  "symbol": "AAPL",  // Required
  "assetType": "stock",  // Required: "stock" | "crypto" | "etf" | "bond"
  "name": "Apple Inc."  // Optional
}

Response (201):
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

**4.3. Remove from Investment Watchlist**
```
DELETE /api/v1/investment/watchlist/{item_id}
Headers:
  Authorization: Bearer <token>

Response (204 No Content):
(No body)
```

#### Implementation Checklist

- [ ] Verify if endpoints exist in backend
- [ ] If not, implement Investment Watchlist API (3 endpoints)
- [ ] Add watchlist item management
- [ ] Add watchlist alerts/notifications (optional)

---

## 🔐 Authentication & Security Requirements

All endpoints require:
- **Authentication**: Bearer token in `Authorization` header
- **Content-Type**: `application/json` for request bodies
- **Rate Limiting**: Implement appropriate rate limits per endpoint
- **Input Validation**: Validate all request parameters and body fields
- **Authorization**: Verify user has permission to access requested resources
- **Error Handling**: Return appropriate HTTP status codes and error messages

---

## 📝 API Standards

### Request/Response Format
- **Date Format**: ISO 8601 (e.g., `2024-01-15T10:00:00Z`)
- **UUID Format**: Standard UUID v4
- **Currency**: Decimal format (e.g., `150000.00`)
- **Pagination**: Use `limit` and `offset` query parameters

### Error Response Format
```json
{
  "detail": "Error message description",
  "code": "ERROR_CODE",  // Optional
  "field": "field_name"  // Optional, for validation errors
}
```

### Success Response Format
- **200 OK**: For GET, PUT requests
- **201 Created**: For POST requests
- Include relevant data in response body

---

## 🚀 Deployment Considerations

### Chat/Messaging System
- **WebSocket Server**: Requires WebSocket support in production
- **Redis**: Consider using Redis for pub/sub if multiple server instances
- **Connection Management**: Implement connection management and reconnection logic
- **Message Storage**: Design indexes for frequently queried fields
- **Scalability**: Consider partitioning for large tables (messages)

### Market Benchmarks
- **Data Provider**: Set up API keys and credentials
- **Fallback**: Implement fallback mechanisms if primary provider fails
- **Caching**: Consider caching strategy for cost optimization
- **Rate Limits**: Respect data provider rate limits

### Task & Reminders
- **Email Service**: Set up email service (SendGrid, AWS SES, etc.)
- **Push Notifications**: Set up push notification service (Firebase, OneSignal, etc.)
- **SMS Service**: Set up SMS service (Twilio, etc.) if needed
- **Background Jobs**: Implement background job queue (Celery, Bull, etc.)
- **Database**: Design indexes for frequently queried fields

---

## 📋 Implementation Priority

### Phase 1 - Critical (High Priority)
1. **Chat/Messaging System** - Essential for support team
   - Backend: Real-time chat APIs + WebSocket
   - Frontend: Chat UI integration
   - **Timeline**: 2-3 weeks

### Phase 2 - Important (Medium Priority)
2. **Market Benchmarks** - Enhances main dashboard
   - Backend: Benchmarks API
   - Frontend: Dashboard integration
   - **Timeline**: 3-5 days

3. **Add Entity Functionality** - Quick win (backend exists)
   - Frontend: UI implementation only
   - **Timeline**: 2-3 days

### Phase 3 - Enhancements (Medium Priority)
4. **Task & Reminders** - Useful but not critical
   - Backend: Tasks + Reminders APIs
   - Frontend: UI implementation
   - **Timeline**: 1-2 weeks

5. **Investment Watchlist** - Nice to have feature
   - Backend: Verify/implement endpoints
   - Frontend: UI implementation
   - **Timeline**: 3-5 days

---

## ❓ Questions to Clarify

Before starting implementation, please confirm:

### Chat System
1. Should chat be separate from support tickets?
2. Do we need group chats or only 1-on-1?
3. Should chat history be persistent?
4. What is the maximum message length?
5. What file types should attachments support?

### Market Benchmarks
1. Which financial data provider should we use? (Alpha Vantage, Yahoo Finance, Polygon.io, IEX Cloud)
2. How often should data be updated? (Recommended: 15 minutes)
3. Do we need historical comparison data?
4. What is the budget for data provider API calls?

### Task & Reminders
1. Should tasks be personal or shared?
2. Do we need task collaboration features?
3. Which notification channels should reminders support? (Email, Push, SMS)
4. Should reminders support recurring schedules?
5. What is the maximum number of reminders per user?

### Investment Watchlist
1. Are the endpoints already implemented? (Need verification)
2. What types of items can be watched? (Stocks, Crypto, ETFs, Bonds)
3. Should watchlist support alerts/notifications?
4. What is the maximum number of items per user?

---

## 📞 Contact & Next Steps

### Next Steps
1. **Review this Document**: Please review all API specifications
2. **Prioritize**: Based on business needs, confirm implementation priority
3. **Timeline**: Provide estimated timeline for each feature
4. **Questions**: Answer clarification questions above
5. **Kickoff**: Schedule kickoff meeting to discuss implementation details

### Contact
For questions or clarifications:
- **Frontend Team**: Available for API design discussions
- **Product Team**: For business requirements clarification
- **Technical Lead**: For architecture and technical decisions

---

## 📎 Attachments

- `UNIMPLEMENTED_SECTIONS_REQUIREMENTS.md` - Complete detailed requirements document
- `REMAINING_SECTIONS_FRONTEND_INTEGRATION_GUIDE.md` - Frontend integration guide for already implemented APIs

---

## 🙏 Thank You

Thank you for your continued support in building this platform. I'm confident that with these APIs implemented, we'll have a fully functional and feature-rich application.

Please let me know if you need any additional information or have any questions.

---

**Document Version**: 1.0  
**Date**: 2024-01-15  
**Status**: ✅ Ready for Backend Team Review  
**Priority**: 🔴 High Priority Items Identified
