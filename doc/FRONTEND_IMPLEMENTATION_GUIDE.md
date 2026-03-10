# Frontend Implementation Guide - Complete Code Files

**Date**: 2024-01-15  
**Status**: ✅ Ready for Implementation  
**Priority**: 🔴 High Priority

---

## 📋 Executive Summary

This document provides **complete, ready-to-use code** for all frontend requirements identified in `FRONTEND_REQUIREMENTS_ANALYSIS.md`. All code follows existing patterns and conventions from the codebase.

**Total Files to Create/Update**: 6 files
- ✅ API Configuration updates
- ✅ Chat API utility (8 functions)
- ✅ Market API utility (1 function)
- ✅ Tasks API utility (7 functions)
- ✅ Reminders API utility (5 functions)
- ✅ Investment Watchlist functions (3 functions)

---

## 1. API Configuration Updates

### File: `src/config/api.js`

**Add these endpoint configurations to your existing `API_ENDPOINTS` object:**

```javascript
// Add to your existing API_ENDPOINTS object

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

MARKET: {
  BASE: '/market',
  BENCHMARKS: '/market/benchmarks',
},

TASKS: {
  BASE: '/tasks',
  LIST: '/tasks',
  DETAILS: (id) => `/tasks/${id}`,
  UPDATE: (id) => `/tasks/${id}`,
  DELETE: (id) => `/tasks/${id}`,
  COMPLETE: (id) => `/tasks/${id}/complete`,
  REMIND: (id) => `/tasks/${id}/remind`,
},

REMINDERS: {
  BASE: '/reminders',
  LIST: '/reminders',
  DETAILS: (id) => `/reminders/${id}`,
  UPDATE: (id) => `/reminders/${id}`,
  DELETE: (id) => `/reminders/${id}`,
  SNOOZE: (id) => `/reminders/${id}/snooze`,
},

// Update existing INVESTMENT section to include watchlist endpoints
INVESTMENT: {
  // ... existing endpoints ...
  WATCHLIST: {
    LIST: '/investment/watchlist',
    ADD: '/investment/watchlist',
    REMOVE: (id) => `/investment/watchlist/${id}`,
  },
  // ... rest of existing endpoints ...
},
```

---

## 2. Chat API Utility File

### File: `src/utils/chatApi.js` (CREATE NEW FILE)

**Complete implementation:**

```javascript
import { API_ENDPOINTS } from '@/config/api';
import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api/client';

/**
 * Transform snake_case keys to camelCase
 * @param {Object} obj - Object to transform
 * @returns {Object} Transformed object
 */
const transformKeys = (obj) => {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) {
    return obj.map(transformKeys);
  }
  if (typeof obj !== 'object') return obj;
  
  const transformed = {};
  for (const [key, value] of Object.entries(obj)) {
    const camelKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    transformed[camelKey] = typeof value === 'object' ? transformKeys(value) : value;
  }
  return transformed;
};

/**
 * Transform camelCase keys to snake_case
 * @param {Object} obj - Object to transform
 * @returns {Object} Transformed object
 */
const transformToSnake = (obj) => {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) {
    return obj.map(transformToSnake);
  }
  if (typeof obj !== 'object') return obj;
  
  const transformed = {};
  for (const [key, value] of Object.entries(obj)) {
    const snakeKey = key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
    transformed[snakeKey] = typeof value === 'object' ? transformToSnake(value) : value;
  }
  return transformed;
};

/**
 * Get all conversations for the current user
 * @param {string} status - Filter by status: 'active' | 'archived' | 'all' (default: 'active')
 * @param {number} limit - Number of results (default: 20)
 * @param {number} offset - Pagination offset (default: 0)
 * @returns {Promise<Object>} Conversations list with pagination
 */
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

/**
 * Get messages for a conversation
 * @param {string} conversationId - UUID of the conversation
 * @param {number} limit - Number of messages (default: 50)
 * @param {string|null} before - ISO 8601 timestamp - get messages before this time
 * @param {string|null} after - ISO 8601 timestamp - get messages after this time
 * @returns {Promise<Object>} Messages list with pagination
 */
export const getMessages = async (conversationId, limit = 50, before = null, after = null) => {
  try {
    const params = new URLSearchParams({
      limit: limit.toString(),
    });
    
    if (before) params.append('before', before);
    if (after) params.append('after', after);
    
    const endpoint = `${API_ENDPOINTS.CHAT.CONVERSATION_MESSAGES(conversationId)}?${params}`;
    const response = await apiGet(endpoint);
    return transformKeys(response);
  } catch (error) {
    console.error('Error fetching messages:', error);
    throw error;
  }
};

/**
 * Send a message in a conversation
 * @param {string} conversationId - UUID of the conversation
 * @param {string} content - Message content (max 5000 characters)
 * @param {Array<string>} attachments - Optional array of file IDs
 * @returns {Promise<Object>} Created message object
 */
export const sendMessage = async (conversationId, content, attachments = []) => {
  try {
    const endpoint = API_ENDPOINTS.CHAT.SEND_MESSAGE(conversationId);
    const response = await apiPost(endpoint, {
      content,
      attachments: attachments.length > 0 ? attachments : undefined,
    });
    return transformKeys(response.message || response);
  } catch (error) {
    console.error('Error sending message:', error);
    throw error;
  }
};

/**
 * Mark messages as read
 * @param {string} conversationId - UUID of the conversation
 * @param {Array<string>|null} messageIds - Optional array of message UUIDs. If not provided, marks all as read
 * @returns {Promise<Object>} Update result
 */
export const markAsRead = async (conversationId, messageIds = null) => {
  try {
    const endpoint = API_ENDPOINTS.CHAT.MARK_READ(conversationId);
    const body = messageIds ? { messageIds } : {};
    const response = await apiPut(endpoint, body);
    return transformKeys(response);
  } catch (error) {
    console.error('Error marking messages as read:', error);
    throw error;
  }
};

/**
 * Delete a message
 * @param {string} messageId - UUID of the message
 * @returns {Promise<boolean>} Success status
 */
export const deleteMessage = async (messageId) => {
  try {
    const endpoint = API_ENDPOINTS.CHAT.DELETE_MESSAGE(messageId);
    await apiDelete(endpoint);
    return true;
  } catch (error) {
    console.error('Error deleting message:', error);
    throw error;
  }
};

/**
 * Get conversation participants
 * @param {string} conversationId - UUID of the conversation
 * @returns {Promise<Array>} Array of participant objects
 */
export const getParticipants = async (conversationId) => {
  try {
    const endpoint = API_ENDPOINTS.CHAT.PARTICIPANTS(conversationId);
    const response = await apiGet(endpoint);
    return transformKeys(response.participants || []);
  } catch (error) {
    console.error('Error fetching participants:', error);
    throw error;
  }
};

/**
 * Create a new conversation
 * @param {Array<string>} participantIds - Array of user UUIDs (min 1, max 10)
 * @param {string|null} subject - Optional subject (max 200 characters)
 * @param {string|null} initialMessage - Optional initial message (max 5000 characters)
 * @returns {Promise<Object>} Created conversation object
 */
export const createConversation = async (participantIds, subject = null, initialMessage = null) => {
  try {
    const endpoint = API_ENDPOINTS.CHAT.CONVERSATIONS;
    const body = {
      participantIds,
      ...(subject && { subject }),
      ...(initialMessage && { initialMessage }),
    };
    const response = await apiPost(endpoint, body);
    return transformKeys(response.conversation || response);
  } catch (error) {
    console.error('Error creating conversation:', error);
    throw error;
  }
};

/**
 * Update conversation (mute, archive, subject)
 * @param {string} conversationId - UUID of the conversation
 * @param {Object} updates - Update object with optional fields: subject, muted, archived
 * @returns {Promise<Object>} Updated conversation object
 */
export const updateConversation = async (conversationId, updates) => {
  try {
    const endpoint = API_ENDPOINTS.CHAT.UPDATE_CONVERSATION(conversationId);
    const response = await apiPut(endpoint, updates);
    return transformKeys(response.conversation || response);
  } catch (error) {
    console.error('Error updating conversation:', error);
    throw error;
  }
};
```

---

## 3. Market API Utility File

### File: `src/utils/marketApi.js` (CREATE NEW FILE)

**Complete implementation:**

```javascript
import { API_ENDPOINTS } from '@/config/api';
import { apiGet } from '@/lib/api/client';

/**
 * Transform snake_case keys to camelCase
 * @param {Object} obj - Object to transform
 * @returns {Object} Transformed object
 */
const transformKeys = (obj) => {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) {
    return obj.map(transformKeys);
  }
  if (typeof obj !== 'object') return obj;
  
  const transformed = {};
  for (const [key, value] of Object.entries(obj)) {
    const camelKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    transformed[camelKey] = typeof value === 'object' ? transformKeys(value) : value;
  }
  return transformed;
};

/**
 * Get market benchmark data
 * @param {Array<string>|string} benchmarks - Array of benchmark symbols or comma-separated string (e.g., ['SPY', 'DIA', 'TSLA'] or 'SPY,DIA,TSLA')
 * @param {string} timeRange - Time range: '1D' | '1W' | '1M' | '3M' | '6M' | '1Y' | 'ALL' (default: '1Y')
 * @returns {Promise<Object>} Benchmarks data with historical data
 */
export const getBenchmarks = async (benchmarks = ['SPY', 'DIA', 'TSLA'], timeRange = '1Y') => {
  try {
    // Handle both array and string formats
    const benchmarksParam = Array.isArray(benchmarks) 
      ? benchmarks.join(',') 
      : benchmarks;
    
    const params = new URLSearchParams({
      benchmarks: benchmarksParam,
      timeRange,
    });
    
    const endpoint = `${API_ENDPOINTS.MARKET.BENCHMARKS}?${params}`;
    const response = await apiGet(endpoint);
    return transformKeys(response);
  } catch (error) {
    console.error('Error fetching benchmarks:', error);
    throw error;
  }
};
```

---

## 4. Tasks API Utility File

### File: `src/utils/tasksApi.js` (CREATE NEW FILE)

**Complete implementation:**

```javascript
import { API_ENDPOINTS } from '@/config/api';
import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api/client';

/**
 * Transform snake_case keys to camelCase
 * @param {Object} obj - Object to transform
 * @returns {Object} Transformed object
 */
const transformKeys = (obj) => {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) {
    return obj.map(transformKeys);
  }
  if (typeof obj !== 'object') return obj;
  
  const transformed = {};
  for (const [key, value] of Object.entries(obj)) {
    const camelKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    transformed[camelKey] = typeof value === 'object' ? transformKeys(value) : value;
  }
  return transformed;
};

/**
 * Transform camelCase keys to snake_case
 * @param {Object} obj - Object to transform
 * @returns {Object} Transformed object
 */
const transformToSnake = (obj) => {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) {
    return obj.map(transformToSnake);
  }
  if (typeof obj !== 'object') return obj;
  
  const transformed = {};
  for (const [key, value] of Object.entries(obj)) {
    const snakeKey = key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
    transformed[snakeKey] = typeof value === 'object' ? transformToSnake(value) : value;
  }
  return transformed;
};

/**
 * Get user tasks with filters and pagination
 * @param {Object} filters - Filter object with optional fields: status, priority, category, dueDateFrom, dueDateTo
 * @param {number} limit - Number of tasks (default: 20, max: 100)
 * @param {number} offset - Pagination offset (default: 0)
 * @returns {Promise<Object>} Tasks list with pagination
 */
export const getTasks = async (filters = {}, limit = 20, offset = 0) => {
  try {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    
    // Add filters to params
    if (filters.status) params.append('status', filters.status);
    if (filters.priority) params.append('priority', filters.priority);
    if (filters.category) params.append('category', filters.category);
    if (filters.dueDateFrom) params.append('due_date_from', filters.dueDateFrom);
    if (filters.dueDateTo) params.append('due_date_to', filters.dueDateTo);
    
    const endpoint = `${API_ENDPOINTS.TASKS.LIST}?${params}`;
    const response = await apiGet(endpoint);
    return transformKeys(response);
  } catch (error) {
    console.error('Error fetching tasks:', error);
    throw error;
  }
};

/**
 * Create a new task
 * @param {Object} taskData - Task data with fields: title, description, priority, category, dueDate, reminderDate
 * @returns {Promise<Object>} Created task object
 */
export const createTask = async (taskData) => {
  try {
    const endpoint = API_ENDPOINTS.TASKS.LIST;
    const transformedData = transformToSnake(taskData);
    const response = await apiPost(endpoint, transformedData);
    return transformKeys(response.task || response);
  } catch (error) {
    console.error('Error creating task:', error);
    throw error;
  }
};

/**
 * Get task details
 * @param {string} taskId - UUID of the task
 * @returns {Promise<Object>} Task object
 */
export const getTaskDetails = async (taskId) => {
  try {
    const endpoint = API_ENDPOINTS.TASKS.DETAILS(taskId);
    const response = await apiGet(endpoint);
    return transformKeys(response.task || response);
  } catch (error) {
    console.error('Error fetching task details:', error);
    throw error;
  }
};

/**
 * Update a task
 * @param {string} taskId - UUID of the task
 * @param {Object} updates - Update object with optional fields: title, description, priority, category, dueDate, reminderDate
 * @returns {Promise<Object>} Updated task object
 */
export const updateTask = async (taskId, updates) => {
  try {
    const endpoint = API_ENDPOINTS.TASKS.UPDATE(taskId);
    const transformedData = transformToSnake(updates);
    const response = await apiPut(endpoint, transformedData);
    return transformKeys(response.task || response);
  } catch (error) {
    console.error('Error updating task:', error);
    throw error;
  }
};

/**
 * Delete a task
 * @param {string} taskId - UUID of the task
 * @returns {Promise<boolean>} Success status
 */
export const deleteTask = async (taskId) => {
  try {
    const endpoint = API_ENDPOINTS.TASKS.DELETE(taskId);
    await apiDelete(endpoint);
    return true;
  } catch (error) {
    console.error('Error deleting task:', error);
    throw error;
  }
};

/**
 * Mark task as complete
 * @param {string} taskId - UUID of the task
 * @returns {Promise<Object>} Updated task object
 */
export const markTaskComplete = async (taskId) => {
  try {
    const endpoint = API_ENDPOINTS.TASKS.COMPLETE(taskId);
    const response = await apiPut(endpoint);
    return transformKeys(response.task || response);
  } catch (error) {
    console.error('Error marking task as complete:', error);
    throw error;
  }
};

/**
 * Set task reminder
 * @param {string} taskId - UUID of the task
 * @param {string} reminderDate - ISO 8601 datetime string
 * @returns {Promise<Object>} Updated task object
 */
export const setTaskReminder = async (taskId, reminderDate) => {
  try {
    const endpoint = API_ENDPOINTS.TASKS.REMIND(taskId);
    const response = await apiPut(endpoint, {
      reminderDate,
    });
    return transformKeys(response.task || response);
  } catch (error) {
    console.error('Error setting task reminder:', error);
    throw error;
  }
};
```

---

## 5. Reminders API Utility File

### File: `src/utils/remindersApi.js` (CREATE NEW FILE)

**Complete implementation:**

```javascript
import { API_ENDPOINTS } from '@/config/api';
import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api/client';

/**
 * Transform snake_case keys to camelCase
 * @param {Object} obj - Object to transform
 * @returns {Object} Transformed object
 */
const transformKeys = (obj) => {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) {
    return obj.map(transformKeys);
  }
  if (typeof obj !== 'object') return obj;
  
  const transformed = {};
  for (const [key, value] of Object.entries(obj)) {
    const camelKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    transformed[camelKey] = typeof value === 'object' ? transformKeys(value) : value;
  }
  return transformed;
};

/**
 * Transform camelCase keys to snake_case
 * @param {Object} obj - Object to transform
 * @returns {Object} Transformed object
 */
const transformToSnake = (obj) => {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) {
    return obj.map(transformToSnake);
  }
  if (typeof obj !== 'object') return obj;
  
  const transformed = {};
  for (const [key, value] of Object.entries(obj)) {
    const snakeKey = key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
    transformed[snakeKey] = typeof value === 'object' ? transformToSnake(value) : value;
  }
  return transformed;
};

/**
 * Get user reminders with filters and pagination
 * @param {Object} filters - Filter object with optional fields: status, dueDateFrom, dueDateTo
 * @param {number} limit - Number of reminders (default: 20, max: 100)
 * @param {number} offset - Pagination offset (default: 0)
 * @returns {Promise<Object>} Reminders list with pagination
 */
export const getReminders = async (filters = {}, limit = 20, offset = 0) => {
  try {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    
    // Add filters to params
    if (filters.status) params.append('status', filters.status);
    if (filters.dueDateFrom) params.append('due_date_from', filters.dueDateFrom);
    if (filters.dueDateTo) params.append('due_date_to', filters.dueDateTo);
    
    const endpoint = `${API_ENDPOINTS.REMINDERS.LIST}?${params}`;
    const response = await apiGet(endpoint);
    return transformKeys(response);
  } catch (error) {
    console.error('Error fetching reminders:', error);
    throw error;
  }
};

/**
 * Create a new reminder
 * @param {Object} reminderData - Reminder data with fields: title, description, reminderDate, taskId, notificationChannels
 * @returns {Promise<Object>} Created reminder object
 */
export const createReminder = async (reminderData) => {
  try {
    const endpoint = API_ENDPOINTS.REMINDERS.LIST;
    const transformedData = transformToSnake(reminderData);
    const response = await apiPost(endpoint, transformedData);
    return transformKeys(response.reminder || response);
  } catch (error) {
    console.error('Error creating reminder:', error);
    throw error;
  }
};

/**
 * Get reminder details
 * @param {string} reminderId - UUID of the reminder
 * @returns {Promise<Object>} Reminder object
 */
export const getReminderDetails = async (reminderId) => {
  try {
    const endpoint = API_ENDPOINTS.REMINDERS.DETAILS(reminderId);
    const response = await apiGet(endpoint);
    return transformKeys(response.reminder || response);
  } catch (error) {
    console.error('Error fetching reminder details:', error);
    throw error;
  }
};

/**
 * Update a reminder
 * @param {string} reminderId - UUID of the reminder
 * @param {Object} updates - Update object with optional fields: title, description, reminderDate, notificationChannels
 * @returns {Promise<Object>} Updated reminder object
 */
export const updateReminder = async (reminderId, updates) => {
  try {
    const endpoint = API_ENDPOINTS.REMINDERS.UPDATE(reminderId);
    const transformedData = transformToSnake(updates);
    const response = await apiPut(endpoint, transformedData);
    return transformKeys(response.reminder || response);
  } catch (error) {
    console.error('Error updating reminder:', error);
    throw error;
  }
};

/**
 * Delete a reminder
 * @param {string} reminderId - UUID of the reminder
 * @returns {Promise<boolean>} Success status
 */
export const deleteReminder = async (reminderId) => {
  try {
    const endpoint = API_ENDPOINTS.REMINDERS.DELETE(reminderId);
    await apiDelete(endpoint);
    return true;
  } catch (error) {
    console.error('Error deleting reminder:', error);
    throw error;
  }
};

/**
 * Snooze a reminder
 * @param {string} reminderId - UUID of the reminder
 * @param {string} snoozeUntil - ISO 8601 datetime string
 * @returns {Promise<Object>} Updated reminder object
 */
export const snoozeReminder = async (reminderId, snoozeUntil) => {
  try {
    const endpoint = API_ENDPOINTS.REMINDERS.SNOOZE(reminderId);
    const response = await apiPut(endpoint, {
      snoozeUntil,
    });
    return transformKeys(response.reminder || response);
  } catch (error) {
    console.error('Error snoozing reminder:', error);
    throw error;
  }
};
```

---

## 6. Investment Watchlist Functions

### File: `src/utils/investmentApi.js` (UPDATE EXISTING FILE)

**Add these functions to your existing `investmentApi.js` file:**

```javascript
// Add these functions to your existing investmentApi.js file

/**
 * Get investment watchlist items
 * @returns {Promise<Object>} Watchlist items with total count
 */
export const getWatchlist = async () => {
  try {
    const endpoint = API_ENDPOINTS.INVESTMENT.WATCHLIST.LIST;
    const response = await apiGet(endpoint);
    return transformKeys(response);
  } catch (error) {
    console.error('Error fetching watchlist:', error);
    throw error;
  }
};

/**
 * Add an item to investment watchlist
 * @param {string} symbol - Asset symbol (e.g., 'AAPL')
 * @param {string} assetType - Asset type: 'stock' | 'crypto' | 'etf' | 'bond'
 * @param {string|null} name - Optional asset name
 * @returns {Promise<Object>} Created watchlist item
 */
export const addToWatchlist = async (symbol, assetType, name = null) => {
  try {
    const endpoint = API_ENDPOINTS.INVESTMENT.WATCHLIST.ADD;
    const body = {
      symbol: symbol.toUpperCase(),
      assetType,
      ...(name && { name }),
    };
    const response = await apiPost(endpoint, body);
    return transformKeys(response.watchlistItem || response);
  } catch (error) {
    console.error('Error adding to watchlist:', error);
    throw error;
  }
};

/**
 * Remove an item from investment watchlist
 * @param {string} itemId - UUID of the watchlist item
 * @returns {Promise<boolean>} Success status
 */
export const removeFromWatchlist = async (itemId) => {
  try {
    const endpoint = API_ENDPOINTS.INVESTMENT.WATCHLIST.REMOVE(itemId);
    await apiDelete(endpoint);
    return true;
  } catch (error) {
    console.error('Error removing from watchlist:', error);
    throw error;
  }
};
```

---

## 7. Usage Examples

### Chat API Usage

```javascript
import { 
  getConversations, 
  getMessages, 
  sendMessage, 
  markAsRead,
  createConversation 
} from '@/utils/chatApi';

// Get conversations
const conversations = await getConversations('active', 20, 0);

// Get messages
const messages = await getMessages(conversationId, 50);

// Send message
const newMessage = await sendMessage(conversationId, 'Hello!', []);

// Mark as read
await markAsRead(conversationId, [messageId1, messageId2]);

// Create conversation
const conversation = await createConversation(
  [userId1, userId2],
  'Support Request',
  'Hello, I need help...'
);
```

### Market API Usage

```javascript
import { getBenchmarks } from '@/utils/marketApi';

// Get default benchmarks
const benchmarks = await getBenchmarks();

// Get specific benchmarks
const customBenchmarks = await getBenchmarks(['SPY', 'DIA', 'TSLA'], '1M');
```

### Tasks API Usage

```javascript
import { 
  getTasks, 
  createTask, 
  updateTask, 
  markTaskComplete,
  deleteTask 
} from '@/utils/tasksApi';

// Get tasks with filters
const tasks = await getTasks({ status: 'pending', priority: 'high' }, 20, 0);

// Create task
const newTask = await createTask({
  title: 'Review portfolio',
  description: 'Review and rebalance',
  priority: 'high',
  category: 'investment',
  dueDate: '2024-01-20T00:00:00Z',
});

// Mark as complete
await markTaskComplete(taskId);

// Update task
await updateTask(taskId, { priority: 'medium' });
```

### Reminders API Usage

```javascript
import { 
  getReminders, 
  createReminder, 
  snoozeReminder,
  deleteReminder 
} from '@/utils/remindersApi';

// Get reminders
const reminders = await getReminders({ status: 'pending' }, 20, 0);

// Create reminder
const newReminder = await createReminder({
  title: 'Portfolio review',
  reminderDate: '2024-01-19T09:00:00Z',
  notificationChannels: ['email', 'push'],
});

// Snooze reminder
await snoozeReminder(reminderId, '2024-01-20T09:00:00Z');
```

### Watchlist API Usage

```javascript
import { 
  getWatchlist, 
  addToWatchlist, 
  removeFromWatchlist 
} from '@/utils/investmentApi';

// Get watchlist
const watchlist = await getWatchlist();

// Add to watchlist
const item = await addToWatchlist('AAPL', 'stock', 'Apple Inc.');

// Remove from watchlist
await removeFromWatchlist(itemId);
```

---

## 8. Error Handling Pattern

**Recommended error handling pattern for all API calls:**

```javascript
import { toast } from 'react-toastify'; // or your toast library

const handleApiCall = async () => {
  try {
    const result = await someApiFunction();
    toast.success('Operation successful');
    return result;
  } catch (error) {
    console.error('API Error:', error);
    
    // Extract user-friendly message
    const errorMessage = error?.response?.data?.detail 
      || error?.message 
      || 'An unexpected error occurred';
    
    toast.error(errorMessage);
    throw error;
  }
};
```

---

## 9. TypeScript Types (Optional)

**If using TypeScript, add these type definitions:**

```typescript
// types/chat.ts
export interface Conversation {
  id: string;
  participants: Participant[];
  lastMessage?: LastMessage;
  unreadCount: number;
  updatedAt: string;
  subject?: string;
}

export interface Message {
  id: string;
  conversationId: string;
  senderId: string;
  senderName: string;
  content: string;
  timestamp: string;
  isRead: boolean;
  attachments: Attachment[];
}

// types/tasks.ts
export interface Task {
  id: string;
  title: string;
  description?: string;
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
  priority: 'low' | 'medium' | 'high' | 'urgent';
  category?: string;
  dueDate?: string;
  reminderDate?: string;
  completedAt?: string;
  createdAt: string;
  updatedAt: string;
}

// types/reminders.ts
export interface Reminder {
  id: string;
  title: string;
  description?: string;
  reminderDate: string;
  status: 'pending' | 'snoozed' | 'completed' | 'cancelled';
  taskId?: string;
  notificationChannels?: string[];
  snoozedUntil?: string;
  createdAt: string;
  updatedAt: string;
}

// types/market.ts
export interface Benchmark {
  symbol: string;
  name: string;
  currentValue: number;
  change: number;
  changePercentage: number;
  currency: string;
  historicalData: HistoricalDataPoint[];
}

export interface HistoricalDataPoint {
  date: string;
  value: number;
}

// types/watchlist.ts
export interface WatchlistItem {
  id: string;
  symbol: string;
  name?: string;
  assetType: 'stock' | 'crypto' | 'etf' | 'bond';
  currentPrice?: number;
  change?: number;
  changePercentage?: number;
  addedAt: string;
}
```

---

## 10. Implementation Checklist

### Phase 1: Configuration ✅
- [ ] Update `src/config/api.js` with all new endpoint configurations
- [ ] Verify `INVESTMENT.WATCHLIST` endpoints are correct

### Phase 2: Create API Utility Files ✅
- [ ] Create `src/utils/chatApi.js` with all 8 functions
- [ ] Create `src/utils/marketApi.js` with benchmarks function
- [ ] Create `src/utils/tasksApi.js` with all 7 functions
- [ ] Create `src/utils/remindersApi.js` with all 5 functions
- [ ] Update `src/utils/investmentApi.js` with watchlist functions

### Phase 3: Testing ✅
- [ ] Test all chat API functions
- [ ] Test market benchmarks API
- [ ] Test all tasks API functions
- [ ] Test all reminders API functions
- [ ] Test watchlist API functions

### Phase 4: Integration ✅
- [ ] Integrate chat APIs into chat components
- [ ] Integrate market APIs into dashboard
- [ ] Integrate tasks APIs into tasks components
- [ ] Integrate reminders APIs into reminders components
- [ ] Integrate watchlist APIs into investment components

---

## 📝 Notes

1. **Key Transformation**: All code includes `transformKeys` and `transformToSnake` functions to handle API response format (snake_case) to frontend format (camelCase).

2. **Error Handling**: All functions include try-catch blocks and console.error logging. Add toast notifications in your components.

3. **Authentication**: All API calls automatically include Bearer token via `apiGet`, `apiPost`, `apiPut`, `apiDelete` from your base client.

4. **Pagination**: All list endpoints support `limit` and `offset` parameters.

5. **Date Format**: All dates are ISO 8601 format. Transform for display in UI components.

---

## 🎯 Next Steps

1. **Copy Code**: Copy all code files to your project
2. **Update Config**: Add endpoint configurations to `api.js`
3. **Test**: Test each API function individually
4. **Integrate**: Start integrating into your components
5. **Error Handling**: Add user-friendly error messages in components

---

**Document Version**: 1.0  
**Last Updated**: 2024-01-15  
**Status**: ✅ Complete - Ready for Implementation
