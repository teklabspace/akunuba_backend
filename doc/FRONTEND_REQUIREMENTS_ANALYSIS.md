# Frontend Requirements Analysis - Newly Implemented APIs

**Date**: 2024-01-15  
**Status**: ✅ **COMPLETED - See Implementation Guide**  
**Priority**: 🔴 High Priority

---

## 📋 Executive Summary

After reviewing the `NEWLY_IMPLEMENTED_APIS_FRONTEND_GUIDE.md` and `FRONTEND_TEAM_NEW_APIS_SUMMARY.md` documents, all required frontend code has been created and documented.

**✅ All Requirements Fulfilled**: Complete code files provided in `FRONTEND_IMPLEMENTATION_GUIDE.md`

**📚 Implementation Guide**: See `FRONTEND_IMPLEMENTATION_GUIDE.md` for complete, ready-to-use code files

---

## ✅ All Components Provided

### 1. API Configuration Updates ✅ **COMPLETED**

**File**: `src/config/api.js`

**Status**: ✅ Complete code provided in `FRONTEND_IMPLEMENTATION_GUIDE.md`

**Endpoints Provided**:
- ✅ **CHAT** endpoints (8 endpoints) - Complete configuration
- ✅ **MARKET** endpoints (1 endpoint) - Complete configuration
- ✅ **TASKS** endpoints (7 endpoints) - Complete configuration
- ✅ **REMINDERS** endpoints (5 endpoints) - Complete configuration
- ✅ **INVESTMENT.WATCHLIST** endpoints (3 endpoints) - Complete configuration

**Action Required**: Copy the endpoint configurations from `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 1 to your `src/config/api.js` file.

---

### 2. Chat API Utility File ✅ **COMPLETED**

**File**: `src/utils/chatApi.js`

**Status**: ✅ Complete implementation provided in `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 2

**Functions Provided** (8 endpoints):
1. ✅ `getConversations(status, limit, offset)`
2. ✅ `getMessages(conversationId, limit, before, after)`
3. ✅ `sendMessage(conversationId, content, attachments)`
4. ✅ `markAsRead(conversationId, messageIds)`
5. ✅ `deleteMessage(messageId)`
6. ✅ `getParticipants(conversationId)`
7. ✅ `createConversation(participantIds, subject, initialMessage)`
8. ✅ `updateConversation(conversationId, updates)`

**Action Required**: Copy the complete file from `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 2 to create `src/utils/chatApi.js`

---

### 3. Market API Utility File ✅ **COMPLETED**

**File**: `src/utils/marketApi.js`

**Status**: ✅ Complete implementation provided in `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 3

**Functions Provided** (1 endpoint):
1. ✅ `getBenchmarks(benchmarks, timeRange)`

**Action Required**: Copy the complete file from `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 3 to create `src/utils/marketApi.js`

---

### 4. Tasks API Utility File ✅ **COMPLETED**

**File**: `src/utils/tasksApi.js`

**Status**: ✅ Complete implementation provided in `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 4

**Functions Provided** (7 endpoints):
1. ✅ `getTasks(filters, limit, offset)`
2. ✅ `createTask(taskData)`
3. ✅ `getTaskDetails(taskId)`
4. ✅ `updateTask(taskId, updates)`
5. ✅ `deleteTask(taskId)`
6. ✅ `markTaskComplete(taskId)`
7. ✅ `setTaskReminder(taskId, reminderDate)`

**Note**: These are user tasks, separate from compliance tasks (COMPLIANCE.TASKS).

**Action Required**: Copy the complete file from `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 4 to create `src/utils/tasksApi.js`

---

### 5. Reminders API Utility File ✅ **COMPLETED**

**File**: `src/utils/remindersApi.js`

**Status**: ✅ Complete implementation provided in `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 5

**Functions Provided** (5 endpoints):
1. ✅ `getReminders(filters, limit, offset)`
2. ✅ `createReminder(reminderData)`
3. ✅ `updateReminder(reminderId, updates)`
4. ✅ `deleteReminder(reminderId)`
5. ✅ `snoozeReminder(reminderId, snoozeUntil)`

**Action Required**: Copy the complete file from `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 5 to create `src/utils/remindersApi.js`

---

### 6. Investment Watchlist Functions ✅ **COMPLETED**

**File**: `src/utils/investmentApi.js`

**Status**: ✅ Complete implementation provided in `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 6

**Functions Provided** (3 endpoints):
1. ✅ `getWatchlist()`
2. ✅ `addToWatchlist(symbol, assetType, name)`
3. ✅ `removeFromWatchlist(itemId)`

**Action Required**: Add the functions from `FRONTEND_IMPLEMENTATION_GUIDE.md` Section 6 to your existing `src/utils/investmentApi.js` file

---

## ✅ Already Implemented

### File Upload API ✅

**Status**: Already implemented in multiple places:
- `src/utils/assetsApi.js` - `uploadFile()`
- `src/utils/documentsApi.js` - `uploadDocument()`
- `src/utils/entityApi.js` - `uploadDocument()`

**Note**: The chat system can use any of these, but it's recommended to standardize on one or create a shared utility.

**Recommendation**: Consider creating a shared `src/utils/fileUploadApi.js` or use the existing `assetsApi.uploadFile()` function.

---

## 📝 Implementation Checklist

### Phase 1: API Configuration (Priority: 🔴 High) ✅

- [x] Add `CHAT` endpoints to `src/config/api.js` - **Code provided in Section 1**
- [x] Add `MARKET` endpoints to `src/config/api.js` - **Code provided in Section 1**
- [x] Add `TASKS` endpoints to `src/config/api.js` - **Code provided in Section 1**
- [x] Add `REMINDERS` endpoints to `src/config/api.js` - **Code provided in Section 1**
- [x] Verify `INVESTMENT.WATCHLIST` endpoints exist and are correct - **Code provided in Section 1**

### Phase 2: API Utility Files (Priority: 🔴 High) ✅

- [x] Create `src/utils/chatApi.js` with all 8 functions - **Complete file in Section 2**
- [x] Create `src/utils/marketApi.js` with benchmarks function - **Complete file in Section 3**
- [x] Create `src/utils/tasksApi.js` with all 7 functions - **Complete file in Section 4**
- [x] Create `src/utils/remindersApi.js` with all 5 functions - **Complete file in Section 5**
- [x] Verify/Implement watchlist functions in `src/utils/investmentApi.js` - **Functions in Section 6**

### Phase 3: Code Quality (Priority: 🟡 Medium) ✅

- [x] Ensure all functions use `apiGet`, `apiPost`, `apiPut`, `apiDelete` from `@/lib/api/client` - **All files follow this pattern**
- [x] Implement snake_case to camelCase transformation (use existing pattern) - **transformKeys() included in all files**
- [x] Add error handling with user-friendly messages - **Try-catch blocks in all functions**
- [x] Add JSDoc comments for all functions - **All functions documented**
- [x] Follow existing code patterns and conventions - **Matches existing codebase patterns**

**📚 All code is ready-to-use in `FRONTEND_IMPLEMENTATION_GUIDE.md`**

---

## 🔍 Code Patterns to Follow

### Example: API Configuration Pattern

```javascript
// In src/config/api.js
CHAT: {
  BASE: '/chat',
  CONVERSATIONS: '/chat/conversations',
  GET_CONVERSATION: (id) => `/chat/conversations/${id}`,
  CONVERSATION_MESSAGES: (id) => `/chat/conversations/${id}/messages`,
  SEND_MESSAGE: (id) => `/chat/conversations/${id}/messages`,
  MARK_READ: (id) => `/chat/conversations/${id}/read`,
  DELETE_MESSAGE: (id) => `/chat/messages/${id}`,
  PARTICIPANTS: (id) => `/chat/conversations/${id}/participants`,
  UPDATE_CONVERSATION: (id) => `/chat/conversations/${id}`,
},
```

### Example: API Utility File Pattern

```javascript
// In src/utils/chatApi.js
import { API_ENDPOINTS } from '@/config/api';
import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api/client';

// Transform functions (copy from investmentApi.js)
const transformKeys = (obj) => { /* ... */ };
const transformToSnake = (obj) => { /* ... */ };

export const getConversations = async (status = 'active', limit = 20, offset = 0) => {
  try {
    const params = new URLSearchParams({
      status,
      limit: limit.toString(),
      offset: offset.toString(),
    });
    
    const endpoint = `${API_ENDPOINTS.CHAT.CONVERSATIONS}?${params}`;
    const response = await apiGet(endpoint);
    return transformKeys(response);
  } catch (error) {
    console.error('Error fetching conversations:', error);
    throw error;
  }
};
```

---

## 📚 Reference Files

### For API Configuration:
- `src/config/api.js` - See existing patterns (NOTIFICATIONS, REFERRALS, etc.)

### For API Utility Files:
- `src/utils/notificationsApi.js` - Good example for simple CRUD operations
- `src/utils/investmentApi.js` - Good example for complex operations with transformations
- `src/utils/referralsApi.js` - Good example for simple API calls

### For Base Client:
- `src/lib/api/client.js` - Base API client functions

---

## 🚨 Important Notes

1. **Naming Convention**: 
   - Use `camelCase` for function names
   - Use `UPPER_SNAKE_CASE` for endpoint constants
   - Transform API responses from `snake_case` to `camelCase`

2. **Error Handling**:
   - Always wrap API calls in try-catch
   - Use user-friendly error messages
   - Log errors for debugging

3. **Authentication**:
   - All endpoints require Bearer token
   - Base client handles this automatically via `apiGet`, `apiPost`, etc.

4. **Pagination**:
   - Always support `limit` and `offset` parameters
   - Return pagination metadata in responses

5. **Date Handling**:
   - All dates are ISO 8601 format
   - Use UTC for consistency
   - Transform dates for display in UI components

---

## 🎯 Next Steps

1. **✅ DONE**: All code files created and documented in `FRONTEND_IMPLEMENTATION_GUIDE.md`
2. **Copy Code**: Copy all code from `FRONTEND_IMPLEMENTATION_GUIDE.md` to your frontend project
3. **Test**: Test each API function individually
4. **Integrate**: Start integrating APIs into your React components
5. **Optional**: Standardize file upload utility (optional - existing implementations work)

---

## 📞 Questions to Clarify

1. **File Upload**: Should we create a shared `fileUploadApi.js` or use existing `assetsApi.uploadFile()`?
2. **Tasks vs Compliance Tasks**: Are user tasks different from compliance tasks? (They appear to be separate systems)
3. **WebSocket**: Should we prepare for WebSocket integration for chat, or wait for backend implementation?
4. **Error Messages**: Should we create a shared error message utility or keep them in each API file?

---

**Document Version**: 2.0  
**Last Updated**: 2024-01-15  
**Status**: ✅ **COMPLETED**

---

## 📚 Complete Implementation Guide

**All code files are provided in**: `FRONTEND_IMPLEMENTATION_GUIDE.md`

This guide includes:
- ✅ Complete API configuration code
- ✅ All 4 new API utility files (chatApi.js, marketApi.js, tasksApi.js, remindersApi.js)
- ✅ Watchlist functions for investmentApi.js
- ✅ Usage examples for all functions
- ✅ Error handling patterns
- ✅ TypeScript type definitions (optional)
- ✅ Complete implementation checklist

**Ready to copy and use immediately!**
