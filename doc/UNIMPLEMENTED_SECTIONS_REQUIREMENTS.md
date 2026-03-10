# Unimplemented Sections & Requirements

**Date**: 2024-01-15  
**Status**: ⚠️ **Sections Requiring Implementation**

---

## Executive Summary

This document lists all sections that are **NOT fully implemented** and details what is required for each section to be complete.

**Total Unimplemented Sections**: 6  
**Total Missing APIs**: 15+  
**Total Missing Features**: 8+

### 📋 Quick Summary for Backend Team

**What's Needed from Backend**:

1. **Chat/Messaging System** (🔴 High Priority)
   - 8 REST API endpoints
   - WebSocket server for real-time messaging
   - Message persistence and file attachments
   - Estimated: 2-3 weeks

2. **Market Benchmarks API** (🟡 Medium Priority)
   - 1 REST API endpoint
   - Integration with financial data provider
   - Estimated: 3-5 days

3. **Task & Reminders System** (🟡 Medium Priority)
   - 7 Tasks API endpoints
   - 5 Reminders API endpoints
   - Background job for notifications
   - Estimated: 1-2 weeks

4. **Investment Watchlist** (🟡 Medium Priority)
   - 3 REST API endpoints (needs verification if they exist)
   - Estimated: 3-5 days

**Already Implemented** (No Backend Work Needed):
- ✅ Add Entity API - Already exists, only frontend UI needed
- ✅ Investment Features APIs - Already exist, only frontend UI integration needed

**Document Status**: ✅ **Ready to Send to Backend Team**

---

## 🔴 High Priority - Not Implemented

### 1. Chat/Messaging System

**Location**: `src/app/dashboard/support-dashboard/page.js`  
**Status**: ❌ **UI Exists, No API Implementation**

**Current State**:
- Support Dashboard has chat UI components
- Chat items are displayed in the sidebar
- Messages can be typed and sent
- **NO chat/messaging API exists**
- Currently using ticket comments as a workaround

**What's Required**:

#### Backend APIs Needed:
1. **Real-time Chat API** (WebSocket or REST)
   - `GET /api/v1/chat/conversations` - Get all chat conversations
   - `GET /api/v1/chat/conversations/{id}/messages` - Get messages for a conversation
   - `POST /api/v1/chat/conversations/{id}/messages` - Send a message
   - `PUT /api/v1/chat/messages/{id}/read` - Mark message as read
   - `DELETE /api/v1/chat/messages/{id}` - Delete a message
   - `GET /api/v1/chat/conversations/{id}/participants` - Get conversation participants
   - `POST /api/v1/chat/conversations` - Create new conversation
   - `PUT /api/v1/chat/conversations/{id}` - Update conversation (mute, archive, etc.)

2. **WebSocket Support** (Recommended)
   - Real-time message delivery
   - Typing indicators
   - Online/offline status
   - Message read receipts

#### Frontend Implementation Required:
- Create `src/utils/chatApi.js` service file
- Add chat endpoints to `src/config/api.js`
- Implement WebSocket connection (if using WebSocket)
- Update Support Dashboard to use chat APIs instead of ticket comments
- Add real-time message updates
- Add typing indicators
- Add online/offline status

**Priority**: 🔴 **High** - Core feature for support team communication

**Estimated Effort**: 
- Backend: 2-3 weeks
- Frontend: 1 week

---

### 2. Market Benchmarks API

**Location**: `src/app/dashboard/page.js` (Main Dashboard)  
**Status**: ❌ **UI Exists, No API Implementation**

**Current State**:
- Dashboard displays benchmark comparison section
- Shows S&P 500, DOW JONES, TSLA
- Currently uses empty array (no data)
- Shows "No benchmark data available" when empty

**What's Required**:

#### Backend API Needed:
1. **Market Benchmarks API**
   - `GET /api/v1/market/benchmarks` - Get market benchmark data
   - Query Parameters:
     - `benchmarks` (array): List of benchmark symbols (e.g., ['SPY', 'DIA', 'TSLA'])
     - `timeRange` (string): '1D', '1W', '1M', '3M', '6M', '1Y', 'ALL'
   - Response should include:
     - Benchmark name
     - Current value
     - Change percentage
     - Historical data for comparison

#### Frontend Implementation Required:
- Add endpoint to `src/config/api.js`:
  ```javascript
  MARKET: {
    BENCHMARKS: '/market/benchmarks',
  }
  ```
- Create `src/utils/marketApi.js` service file (or add to existing)
- Implement `getMarketBenchmarks(benchmarks, timeRange)` function
- Update main dashboard to fetch and display benchmark data
- Add loading states and error handling

**Priority**: 🟡 **Medium** - Enhances dashboard but not critical

**Estimated Effort**:
- Backend: 3-5 days
- Frontend: 1-2 days

---

### 3. Task & Reminders System

**Location**: `src/app/settings/page.js`  
**Status**: ❌ **UI Placeholder Only - "Coming Soon"**

**Current State**:
- Settings page has "Task & Reminders" tab
- Shows placeholder text: "Task & Reminders content coming soon..."
- No functionality implemented

**What's Required**:

#### Backend APIs Needed:
1. **Tasks API**
   - `GET /api/v1/tasks` - Get user tasks
   - `POST /api/v1/tasks` - Create a task
   - `GET /api/v1/tasks/{id}` - Get task details
   - `PUT /api/v1/tasks/{id}` - Update task
   - `DELETE /api/v1/tasks/{id}` - Delete task
   - `PUT /api/v1/tasks/{id}/complete` - Mark task as complete
   - `PUT /api/v1/tasks/{id}/remind` - Set reminder for task

2. **Reminders API**
   - `GET /api/v1/reminders` - Get user reminders
   - `POST /api/v1/reminders` - Create a reminder
   - `PUT /api/v1/reminders/{id}` - Update reminder
   - `DELETE /api/v1/reminders/{id}` - Delete reminder
   - `PUT /api/v1/reminders/{id}/snooze` - Snooze reminder

#### Frontend Implementation Required:
- Add endpoints to `src/config/api.js`
- Create `src/utils/tasksApi.js` service file
- Create `src/utils/remindersApi.js` service file
- Build Task & Reminders UI component
- Add task creation form
- Add reminder creation form
- Add task/reminder list with filters
- Add calendar view (optional)
- Add notification integration for reminders

**Priority**: 🟡 **Medium** - Useful feature but not critical for MVP

**Estimated Effort**:
- Backend: 1-2 weeks
- Frontend: 1 week

---

### 4. Add Entity Functionality

**Location**: `src/app/dashboard/entity-structure/page.js`  
**Status**: ❌ **Button Exists, Shows "Coming Soon" Toast**

**Current State**:
- Entity Structure page has "Add Entity" button
- Clicking shows toast: "Add entity functionality coming soon"
- Entity listing and management works via API
- Only the "Add" functionality is missing

**What's Required**:

#### Backend API Status:
- ✅ `POST /api/v1/entities` - Already exists and implemented
- ✅ Entity creation API is fully functional

#### Frontend Implementation Required:
- Create "Add Entity" modal/form component
- Add form fields:
  - Entity name
  - Entity type
  - Legal structure
  - Registration details
  - Initial compliance settings
- Connect form to `createEntity()` API call
- Add validation
- Add success/error handling
- Refresh entity list after creation

**Priority**: 🟡 **Medium** - Feature exists in backend, just needs UI

**Estimated Effort**:
- Frontend: 2-3 days

---

## 🟡 Medium Priority - Partially Implemented

### 5. Investment Management - Extra Features

**Location**: `src/app/dashboard/investment/`  
**Status**: ⚠️ **APIs Implemented, UI Integration Incomplete**

**Current State**:
- Investment APIs are implemented in `src/utils/investmentApi.js`
- Some features are marked as "Structure only - not integrated in UI"
- Functions exist but may not be used in UI components

**What's Required**:

#### Already Implemented (Functions Exist):
1. ✅ `adjustGoal(goalId, adjustmentData)` - Implemented
2. ✅ `backtestStrategy(strategyId, backtestParams)` - Implemented
3. ✅ `getStrategyPerformance(strategyId, days)` - Implemented
4. ✅ `cloneStrategy(strategyId, cloneData)` - Implemented
5. ✅ `getInvestmentPerformance()` - Implemented
6. ✅ `getInvestmentAnalytics()` - Implemented
7. ✅ `getInvestmentRecommendations()` - Implemented

#### Missing UI Integration:
1. **Adjust Goal Feature**
   - Add UI form in Goals Tracker page
   - Allow users to adjust goal parameters (target amount, deadline, etc.)
   - Connect to `adjustGoal()` API

2. **Strategy Backtest Feature**
   - Add "Backtest" button to Strategy detail page
   - Create backtest configuration modal
   - Display backtest results (charts, metrics)
   - Connect to `backtestStrategy()` API

3. **Strategy Performance Feature**
   - Add performance metrics section to Strategy detail page
   - Display performance charts and statistics
   - Connect to `getStrategyPerformance()` API

4. **Clone Strategy Feature**
   - Add "Clone" button to Strategy cards/list
   - Add clone confirmation dialog
   - Handle clone success/error
   - Connect to `cloneStrategy()` API

5. **Investment Performance Analytics**
   - Create analytics dashboard component
   - Display performance metrics
   - Add filtering and time range selection
   - Connect to `getInvestmentPerformance()` API

6. **Investment Analytics**
   - Create analytics page/component
   - Display detailed analytics
   - Add filtering options
   - Connect to `getInvestmentAnalytics()` API

7. **Investment Recommendations**
   - Create recommendations section/component
   - Display personalized recommendations
   - Add "Apply Recommendation" functionality
   - Connect to `getInvestmentRecommendations()` API

**Priority**: 🟡 **Medium** - Features exist, need UI integration

**Estimated Effort**:
- Frontend: 2-3 weeks

---

### 6. Investment Watchlist

**Location**: `src/config/api.js` (lines 166-168)  
**Status**: ❌ **Endpoints Defined, No Implementation**

**Current State**:
- Endpoints defined in config:
  - `GET /api/v1/investment/watchlist`
  - `POST /api/v1/investment/watchlist`
  - `DELETE /api/v1/investment/watchlist/{id}`
- **NO service functions implemented**
- **NO UI implementation**
- Note: Marketplace watchlist is separate and already implemented

**What's Required**:

#### Backend API Status:
- ⚠️ Endpoints may or may not exist (needs verification)

#### Frontend Implementation Required:
1. **Service Functions** (`src/utils/investmentApi.js`):
   - `getInvestmentWatchlist()` - Get watchlist items
   - `addToInvestmentWatchlist(itemData)` - Add item to watchlist
   - `removeFromInvestmentWatchlist(itemId)` - Remove item from watchlist

2. **UI Components**:
   - Watchlist section in Investment Overview page
   - "Add to Watchlist" buttons on investment opportunities
   - Watchlist management page/component
   - Watchlist item cards with remove functionality

**Priority**: 🟡 **Medium** - Separate from marketplace watchlist

**Estimated Effort**:
- Backend (if needed): 3-5 days
- Frontend: 1 week

---

## 🟢 Low Priority - Enhancement Features

### 7. Plaid Link UI Integration

**Location**: `src/app/dashboard/settings/page.js` (line 1645)  
**Status**: ⚠️ **TODO Comment Found**

**Current State**:
- TODO comment: `// TODO: Integrate Plaid Link UI here`
- Plaid API endpoints exist
- Plaid integration APIs are implemented
- UI integration may be incomplete

**What's Required**:
- Verify Plaid Link UI is fully integrated
- If not, implement Plaid Link component
- Add bank account connection flow
- Add account verification UI

**Priority**: 🟢 **Low** - May already be implemented elsewhere

**Estimated Effort**: 2-3 days (if needed)

---

## 📊 Summary Table

| Section | Status | Priority | Backend APIs | Frontend Work | Estimated Time |
|---------|--------|----------|--------------|---------------|----------------|
| **Chat/Messaging** | ❌ Not Implemented | 🔴 High | 8 APIs needed | Service + UI | 3-4 weeks |
| **Market Benchmarks** | ❌ Not Implemented | 🟡 Medium | 1 API needed | Service + UI | 1 week |
| **Task & Reminders** | ❌ Not Implemented | 🟡 Medium | 12 APIs needed | Service + UI | 2-3 weeks |
| **Add Entity** | ⚠️ Partial | 🟡 Medium | ✅ Exists | UI only | 2-3 days |
| **Investment Features** | ⚠️ Partial | 🟡 Medium | ✅ Exists | UI integration | 2-3 weeks |
| **Investment Watchlist** | ❌ Not Implemented | 🟡 Medium | ⚠️ Verify | Service + UI | 1-2 weeks |
| **Plaid Link UI** | ⚠️ Verify | 🟢 Low | ✅ Exists | UI verify | 2-3 days |

---

## 🎯 Implementation Priority

### Phase 1 - Critical (High Priority)
1. **Chat/Messaging System** - Essential for support team
   - Backend: Real-time chat APIs + WebSocket
   - Frontend: Chat UI integration

### Phase 2 - Important (Medium Priority)
2. **Add Entity Functionality** - Quick win (backend exists)
3. **Market Benchmarks** - Enhances main dashboard
4. **Investment Features UI** - Complete existing features

### Phase 3 - Enhancements (Medium-Low Priority)
5. **Task & Reminders** - Useful but not critical
6. **Investment Watchlist** - Nice to have feature

### Phase 4 - Verification (Low Priority)
7. **Plaid Link UI** - Verify if already implemented

---

## 📝 Detailed Requirements by Section

### 1. Chat/Messaging System - Detailed Requirements

#### Backend APIs Required:

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
  401 Unauthorized: Missing or invalid token
  403 Forbidden: Insufficient permissions
  500 Internal Server Error: Server error
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
  401 Unauthorized: Missing or invalid token
  403 Forbidden: User not part of this conversation
  404 Not Found: Conversation not found
  500 Internal Server Error: Server error
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
  400 Bad Request: Invalid request body, content too long, or invalid file IDs
  401 Unauthorized: Missing or invalid token
  403 Forbidden: User not part of this conversation
  404 Not Found: Conversation not found
  500 Internal Server Error: Server error
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
  400 Bad Request: Invalid message IDs
  401 Unauthorized: Missing or invalid token
  403 Forbidden: User not part of this conversation
  404 Not Found: Conversation not found
  500 Internal Server Error: Server error
```

**1.5. Create Conversation**
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
  400 Bad Request: Invalid participant IDs, duplicate participants, or invalid subject/message
  401 Unauthorized: Missing or invalid token
  404 Not Found: One or more participant IDs not found
  500 Internal Server Error: Server error
```

**1.6. WebSocket Events** (Recommended)
- `message:new` - New message received
- `message:read` - Message read by recipient
- `typing:start` - User started typing
- `typing:stop` - User stopped typing
- `user:online` - User came online
- `user:offline` - User went offline

#### Frontend Implementation:

**1.1. Service File** (`src/utils/chatApi.js`):
```javascript
export const getConversations = async (params) => { ... }
export const getConversationMessages = async (conversationId, params) => { ... }
export const sendMessage = async (conversationId, messageData) => { ... }
export const markAsRead = async (conversationId, messageIds) => { ... }
export const createConversation = async (conversationData) => { ... }
// WebSocket connection management
export const connectChatWebSocket = (onMessage, onTyping, onUserStatus) => { ... }
export const disconnectChatWebSocket = () => { ... }
```

**1.2. UI Components**:
- Chat conversation list
- Message thread component
- Message input component
- Typing indicator
- Online/offline status
- Unread message badges

---

### 2. Market Benchmarks - Detailed Requirements

#### Backend API Required:

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
  400 Bad Request: Invalid benchmark symbols or timeRange value
  401 Unauthorized: Missing or invalid token
  500 Internal Server Error: Server error or data provider unavailable
```

#### Frontend Implementation:
- Add to `src/config/api.js`
- Create or update `src/utils/marketApi.js`
- Update main dashboard to fetch benchmarks
- Display benchmark comparison chart
- Add time range selector

---

### 3. Task & Reminders - Detailed Requirements

#### Backend APIs Required:

**3.1. Tasks API**
```
GET /api/v1/tasks
POST /api/v1/tasks
GET /api/v1/tasks/{id}
PUT /api/v1/tasks/{id}
DELETE /api/v1/tasks/{id}
PUT /api/v1/tasks/{id}/complete
PUT /api/v1/tasks/{id}/remind
```

**3.2. Reminders API**
```
GET /api/v1/reminders
POST /api/v1/reminders
PUT /api/v1/reminders/{id}
DELETE /api/v1/reminders/{id}
PUT /api/v1/reminders/{id}/snooze
```

#### Frontend Implementation:
- Create `src/utils/tasksApi.js`
- Create `src/utils/remindersApi.js`
- Build Task & Reminders UI
- Add forms for creation
- Add list views with filters
- Add calendar integration (optional)

---

### 4. Add Entity - Detailed Requirements

#### Backend API:
- ✅ Already exists: `POST /api/v1/entities`

#### Frontend Implementation:
- Create Add Entity modal component
- Form fields:
  - Entity name (required)
  - Entity type (dropdown)
  - Legal structure (dropdown)
  - Registration number
  - Registration date
  - Country/State
  - Initial compliance settings
- Validation
- Success/error handling
- Refresh entity list after creation

---

### 5. Investment Features - Detailed Requirements

#### UI Integration Needed:

**5.1. Adjust Goal**
- Add "Adjust Goal" button to goal cards
- Create adjustment modal with form:
  - Target amount
  - Deadline
  - Monthly contribution
  - Risk tolerance
- Connect to `adjustGoal()` API

**5.2. Strategy Backtest**
- Add "Backtest" button to strategy detail page
- Create backtest configuration modal:
  - Time period
  - Initial capital
  - Parameters
- Display backtest results:
  - Performance chart
  - Metrics (return, Sharpe ratio, etc.)
  - Comparison with benchmark

**5.3. Strategy Performance**
- Add performance section to strategy detail page
- Display:
  - Performance metrics
  - Historical performance chart
  - Risk metrics
  - Comparison charts

**5.4. Clone Strategy**
- Add "Clone" button to strategy cards
- Confirmation dialog
- Handle clone success/error
- Redirect to cloned strategy

**5.5. Investment Performance Analytics**
- Create analytics dashboard
- Display performance metrics
- Add time range filters
- Add asset type filters
- Display charts and graphs

**5.6. Investment Analytics**
- Create analytics page
- Display detailed analytics
- Add filtering options
- Export functionality

**5.7. Investment Recommendations**
- Create recommendations section
- Display personalized recommendations
- Add "Apply Recommendation" button
- Show recommendation details
- Track applied recommendations

---

### 6. Investment Watchlist - Detailed Requirements

#### Backend API Status:
- ⚠️ Needs verification if endpoints exist

#### Frontend Implementation:

**6.1. Service Functions**:
```javascript
// src/utils/investmentApi.js
export const getInvestmentWatchlist = async () => { ... }
export const addToInvestmentWatchlist = async (itemData) => { ... }
export const removeFromInvestmentWatchlist = async (itemId) => { ... }
```

**6.2. UI Components**:
- Watchlist section in Investment Overview
- "Add to Watchlist" buttons
- Watchlist management page
- Watchlist item cards
- Remove from watchlist functionality

---

## 🔧 Technical Implementation Notes

### Chat/Messaging System

**WebSocket vs REST**:
- **Recommended**: WebSocket for real-time messaging
- **Alternative**: REST with polling (less efficient)
- **Hybrid**: REST for history, WebSocket for real-time

**Message Storage**:
- Store messages in database
- Support message pagination
- Support file attachments
- Support message reactions (optional)

**Security**:
- Verify user permissions for conversations
- Encrypt sensitive messages
- Rate limiting for message sending
- Spam detection

---

### Market Benchmarks

**Data Source**:
- Integrate with financial data provider (Alpha Vantage, Yahoo Finance, etc.)
- Cache benchmark data (update every 15 minutes)
- Support multiple benchmark types (indices, stocks, ETFs)

**Performance**:
- Cache responses
- Use CDN for static benchmark data
- Optimize for dashboard load time

---

### Task & Reminders

**Reminder System**:
- Background job to send reminders
- Email notifications
- Push notifications (if mobile app exists)
- In-app notifications

**Task Management**:
- Support task categories
- Support task priorities
- Support task dependencies
- Support recurring tasks

---

## 📋 Implementation Checklist

### Chat/Messaging System
- [ ] Backend: Design database schema
- [ ] Backend: Implement REST APIs
- [ ] Backend: Implement WebSocket server
- [ ] Backend: Add message storage
- [ ] Backend: Add real-time delivery
- [ ] Frontend: Create `chatApi.js`
- [ ] Frontend: Add WebSocket client
- [ ] Frontend: Update Support Dashboard UI
- [ ] Frontend: Add typing indicators
- [ ] Frontend: Add online/offline status
- [ ] Testing: Test real-time messaging
- [ ] Testing: Test message persistence

### Market Benchmarks
- [ ] Backend: Integrate data provider
- [ ] Backend: Implement benchmarks API
- [ ] Backend: Add caching
- [ ] Frontend: Add to `marketApi.js`
- [ ] Frontend: Update main dashboard
- [ ] Frontend: Add time range selector
- [ ] Testing: Test benchmark data accuracy

### Task & Reminders
- [ ] Backend: Design database schema
- [ ] Backend: Implement Tasks API
- [ ] Backend: Implement Reminders API
- [ ] Backend: Add reminder job scheduler
- [ ] Frontend: Create `tasksApi.js`
- [ ] Frontend: Create `remindersApi.js`
- [ ] Frontend: Build Task & Reminders UI
- [ ] Frontend: Add forms
- [ ] Frontend: Add list views
- [ ] Testing: Test task CRUD operations
- [ ] Testing: Test reminder notifications

### Add Entity
- [ ] Frontend: Create Add Entity modal
- [ ] Frontend: Add form fields
- [ ] Frontend: Add validation
- [ ] Frontend: Connect to API
- [ ] Frontend: Add error handling
- [ ] Testing: Test entity creation

### Investment Features
- [ ] Frontend: Add Adjust Goal UI
- [ ] Frontend: Add Backtest UI
- [ ] Frontend: Add Performance UI
- [ ] Frontend: Add Clone Strategy UI
- [ ] Frontend: Add Analytics UI
- [ ] Frontend: Add Recommendations UI
- [ ] Testing: Test all investment features

### Investment Watchlist
- [ ] Backend: Verify endpoints exist
- [ ] Frontend: Implement service functions
- [ ] Frontend: Add watchlist UI
- [ ] Frontend: Add management features
- [ ] Testing: Test watchlist operations

---

## 🎯 Next Steps

1. **Prioritize**: Review priority list and decide implementation order
2. **Backend Team**: Share this document with backend team for API development
3. **Frontend Team**: Plan UI implementation for each section
4. **Design Team**: Create UI mockups for new features
5. **Testing**: Plan testing strategy for each feature

---

## 📞 Questions to Clarify

1. **Chat System**: 
   - Should chat be separate from support tickets?
   - Do we need group chats or only 1-on-1?
   - Should chat history be persistent?

2. **Market Benchmarks**:
   - Which benchmarks should be displayed by default?
   - How often should data be updated?
   - Do we need historical comparison?

3. **Task & Reminders**:
   - Should tasks be personal or shared?
   - Do we need task collaboration features?
   - Should reminders support multiple notification channels?

4. **Investment Watchlist**:
   - Is this separate from marketplace watchlist?
   - What types of items can be watched?
   - Should watchlist support alerts/notifications?

---

## 📋 Backend Implementation Checklist

### Chat/Messaging System
- [ ] Design database schema (conversations, messages, participants)
- [ ] Implement REST API endpoints (8 endpoints)
- [ ] Implement WebSocket server for real-time messaging
- [ ] Add message persistence and pagination
- [ ] Add file attachment support
- [ ] Implement typing indicators
- [ ] Implement online/offline status tracking
- [ ] Add message read receipts
- [ ] Add rate limiting for message sending
- [ ] Add spam detection
- [ ] Add conversation archiving
- [ ] Add conversation search functionality

### Market Benchmarks
- [ ] Integrate with financial data provider (Alpha Vantage, Yahoo Finance, etc.)
- [ ] Implement caching mechanism (update every 15 minutes)
- [ ] Implement benchmarks API endpoint
- [ ] Add support for multiple benchmark types (indices, stocks, ETFs)
- [ ] Add historical data retrieval
- [ ] Add error handling for data provider failures
- [ ] Add rate limiting

### Task & Reminders
- [ ] Design database schema (tasks, reminders)
- [ ] Implement Tasks API (7 endpoints)
- [ ] Implement Reminders API (5 endpoints)
- [ ] Add reminder notification system (background job)
- [ ] Add email notification support
- [ ] Add push notification support (if mobile app exists)
- [ ] Add SMS notification support (optional)
- [ ] Add task categories and tags
- [ ] Add task priorities
- [ ] Add task dependencies (optional)
- [ ] Add recurring tasks support (optional)
- [ ] Add task sharing/collaboration (optional)

### Investment Watchlist
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

1. **WebSocket Server**: 
   - Requires WebSocket support in production
   - Consider using Redis for pub/sub if multiple server instances
   - Implement connection management and reconnection logic

2. **Market Data Provider**:
   - Set up API keys and credentials
   - Implement fallback mechanisms if primary provider fails
   - Consider caching strategy for cost optimization

3. **Notification System**:
   - Set up email service (SendGrid, AWS SES, etc.)
   - Set up push notification service (Firebase, OneSignal, etc.)
   - Set up SMS service (Twilio, etc.) if needed
   - Implement background job queue (Celery, Bull, etc.)

4. **Database**:
   - Design indexes for frequently queried fields
   - Consider partitioning for large tables (messages, tasks)
   - Implement soft deletes where appropriate

---

## 📞 Contact & Questions

For questions or clarifications about these requirements, please contact:
- **Frontend Team**: [Your Contact]
- **Backend Team**: [Backend Contact]
- **Product Team**: [Product Contact]

---

**Last Updated**: 2024-01-15  
**Document Version**: 2.0  
**Status**: ✅ **Ready for Backend Team**
