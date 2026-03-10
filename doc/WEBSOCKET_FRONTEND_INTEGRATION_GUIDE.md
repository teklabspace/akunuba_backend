# WebSocket Real-Time Chat Integration Guide

This guide provides complete instructions for integrating WebSocket-based real-time chat functionality into your frontend application.

## Table of Contents
1. [Overview](#overview)
2. [Connection Setup](#connection-setup)
3. [Event Types](#event-types)
4. [Client Implementation](#client-implementation)
5. [Error Handling](#error-handling)
6. [Best Practices](#best-practices)

---

## Overview

The WebSocket API enables real-time bidirectional communication for chat features. It supports:
- **Real-time message delivery** - Messages appear instantly without polling
- **Typing indicators** - Show when users are typing
- **Read receipts** - Track when messages are read
- **Presence updates** - Know when users are online/offline
- **Multi-instance support** - Works across multiple backend servers via Redis

### WebSocket Endpoint

```
wss://your-api-domain/ws/chat?token=<JWT_ACCESS_TOKEN>
```

**Note**: Use `ws://` for local development (HTTP) and `wss://` for production (HTTPS).

---

## Connection Setup

### 1. Get Access Token

First, authenticate the user and obtain a JWT access token using the standard login endpoint:

```javascript
// Example: Login to get token
const response = await fetch('https://api.yourapp.com/api/v1/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password })
});

const { access_token } = await response.json();
```

### 2. Establish WebSocket Connection

```javascript
const token = 'your-jwt-access-token';
const wsUrl = `wss://api.yourapp.com/ws/chat?token=${token}`;
const ws = new WebSocket(wsUrl);
```

### 3. Connection States

```javascript
ws.onopen = () => {
  console.log('WebSocket connected');
  // Connection is ready
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
  // Handle connection errors
};

ws.onclose = (event) => {
  console.log('WebSocket closed:', event.code, event.reason);
  // Handle reconnection if needed
};
```

---

## Event Types

### Server → Client Events

#### 1. `connected`
Sent immediately after successful connection.

```json
{
  "type": "connected",
  "user_id": "uuid",
  "message": "WebSocket connection established"
}
```

#### 2. `message:new`
New message received in a conversation.

```json
{
  "type": "message:new",
  "conversation_id": "uuid",
  "message_id": "uuid",
  "sender_id": "uuid",
  "sender_name": "John Doe",
  "content": "Hello, how are you?",
  "timestamp": "2024-01-15T10:30:00Z",
  "attachments": [
    {
      "id": "uuid",
      "type": "image/png",
      "url": "https://..."
    }
  ]
}
```

#### 3. `message:read`
Message read receipt from another user.

```json
{
  "type": "message:read",
  "conversation_id": "uuid",
  "message_id": "uuid",
  "user_id": "uuid",
  "read_at": "2024-01-15T10:31:00Z"
}
```

#### 4. `typing:update`
Typing indicator update.

```json
{
  "type": "typing:update",
  "conversation_id": "uuid",
  "user_id": "uuid",
  "is_typing": true
}
```

#### 5. `joined`
Confirmation that user joined a conversation.

```json
{
  "type": "joined",
  "conversation_id": "uuid",
  "message": "Joined conversation uuid"
}
```

#### 6. `read:acknowledged`
Confirmation that read receipt was processed.

```json
{
  "type": "read:acknowledged",
  "conversation_id": "uuid"
}
```

#### 7. `error`
Error message from server.

```json
{
  "type": "error",
  "message": "Error description"
}
```

### Client → Server Events

#### 1. `join`
Join a conversation to receive real-time updates.

```json
{
  "type": "join",
  "conversation_id": "uuid"
}
```

#### 2. `typing:start`
Notify that user started typing.

```json
{
  "type": "typing:start",
  "conversation_id": "uuid"
}
```

#### 3. `typing:stop`
Notify that user stopped typing.

```json
{
  "type": "typing:stop",
  "conversation_id": "uuid"
}
```

#### 4. `mark:read`
Mark a message (or all messages) as read.

```json
{
  "type": "mark:read",
  "conversation_id": "uuid",
  "data": {
    "message_id": "uuid"  // Optional: specific message, omit for all messages
  }
}
```

---

## Client Implementation

### Complete Example: React Hook

```javascript
import { useEffect, useRef, useState, useCallback } from 'react';

function useChatWebSocket(token) {
  const [ws, setWs] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [messages, setMessages] = useState([]);
  const [typingUsers, setTypingUsers] = useState(new Set());
  const reconnectTimeoutRef = useRef(null);
  const wsRef = useRef(null);

  const connect = useCallback(() => {
    if (!token) return;

    const wsUrl = `wss://api.yourapp.com/ws/chat?token=${token}`;
    const websocket = new WebSocket(wsUrl);
    wsRef.current = websocket;

    websocket.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };

    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };

    websocket.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsConnected(false);
    };

    websocket.onclose = (event) => {
      console.log('WebSocket closed:', event.code, event.reason);
      setIsConnected(false);
      
      // Auto-reconnect (exponential backoff)
      if (event.code !== 1000) { // Not a normal closure
        const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts));
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, delay);
      }
    };

    setWs(websocket);
  }, [token]);

  const handleWebSocketMessage = (data) => {
    switch (data.type) {
      case 'connected':
        console.log('Connected as user:', data.user_id);
        break;

      case 'message:new':
        setMessages(prev => [...prev, {
          id: data.message_id,
          conversationId: data.conversation_id,
          senderId: data.sender_id,
          senderName: data.sender_name,
          content: data.content,
          timestamp: data.timestamp,
          attachments: data.attachments || []
        }]);
        break;

      case 'message:read':
        setMessages(prev => prev.map(msg =>
          msg.id === data.message_id
            ? { ...msg, isRead: true, readAt: data.read_at }
            : msg
        ));
        break;

      case 'typing:update':
        setTypingUsers(prev => {
          const newSet = new Set(prev);
          if (data.is_typing) {
            newSet.add(data.user_id);
            // Auto-remove after 3 seconds
            setTimeout(() => {
              setTypingUsers(current => {
                const updated = new Set(current);
                updated.delete(data.user_id);
                return updated;
              });
            }, 3000);
          } else {
            newSet.delete(data.user_id);
          }
          return newSet;
        });
        break;

      case 'error':
        console.error('WebSocket error:', data.message);
        break;

      default:
        console.log('Unknown WebSocket event:', data.type);
    }
  };

  const joinConversation = useCallback((conversationId) => {
    if (ws && isConnected) {
      ws.send(JSON.stringify({
        type: 'join',
        conversation_id: conversationId
      }));
    }
  }, [ws, isConnected]);

  const sendTypingStart = useCallback((conversationId) => {
    if (ws && isConnected) {
      ws.send(JSON.stringify({
        type: 'typing:start',
        conversation_id: conversationId
      }));
    }
  }, [ws, isConnected]);

  const sendTypingStop = useCallback((conversationId) => {
    if (ws && isConnected) {
      ws.send(JSON.stringify({
        type: 'typing:stop',
        conversation_id: conversationId
      }));
    }
  }, [ws, isConnected]);

  const markAsRead = useCallback((conversationId, messageId = null) => {
    if (ws && isConnected) {
      ws.send(JSON.stringify({
        type: 'mark:read',
        conversation_id: conversationId,
        data: messageId ? { message_id: messageId } : {}
      }));
    }
  }, [ws, isConnected]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return {
    ws,
    isConnected,
    messages,
    typingUsers,
    joinConversation,
    sendTypingStart,
    sendTypingStop,
    markAsRead
  };
}
```

### Usage in Component

```javascript
function ChatComponent({ conversationId, token }) {
  const {
    isConnected,
    messages,
    typingUsers,
    joinConversation,
    sendTypingStart,
    sendTypingStop,
    markAsRead
  } = useChatWebSocket(token);

  useEffect(() => {
    if (isConnected && conversationId) {
      joinConversation(conversationId);
    }
  }, [isConnected, conversationId, joinConversation]);

  const handleTyping = (e) => {
    if (e.target.value.length > 0) {
      sendTypingStart(conversationId);
    } else {
      sendTypingStop(conversationId);
    }
  };

  return (
    <div>
      <div>Status: {isConnected ? 'Connected' : 'Disconnected'}</div>
      
      {typingUsers.size > 0 && (
        <div>Someone is typing...</div>
      )}
      
      <div>
        {messages.map(msg => (
          <div key={msg.id}>
            <strong>{msg.senderName}:</strong> {msg.content}
            {msg.isRead && <span>✓✓</span>}
          </div>
        ))}
      </div>
      
      <input
        type="text"
        onChange={handleTyping}
        onBlur={() => sendTypingStop(conversationId)}
      />
    </div>
  );
}
```

---

## Error Handling

### Connection Errors

```javascript
ws.onerror = (error) => {
  console.error('WebSocket error:', error);
  // Show user-friendly message
  showNotification('Connection error. Attempting to reconnect...');
};

ws.onclose = (event) => {
  if (event.code === 1008) {
    // Invalid token - redirect to login
    console.error('Authentication failed');
    window.location.href = '/login';
  } else if (event.code === 1011) {
    // Server error
    console.error('Server error');
    showNotification('Server error. Please try again later.');
  } else {
    // Normal closure or network issue
    console.log('Connection closed');
    // Attempt reconnection
  }
};
```

### Message Errors

```javascript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'error') {
    console.error('Server error:', data.message);
    showNotification(`Error: ${data.message}`);
  } else {
    // Handle normal messages
  }
};
```

---

## Best Practices

### 1. **Token Refresh**
- WebSocket tokens expire like REST API tokens
- Implement token refresh before expiration
- Reconnect with new token if connection fails due to auth

```javascript
async function refreshTokenAndReconnect() {
  const newToken = await refreshAccessToken();
  // Close old connection
  ws.close();
  // Connect with new token
  connect(newToken);
}
```

### 2. **Reconnection Strategy**
- Use exponential backoff for reconnection
- Limit maximum reconnection attempts
- Show connection status to user

### 3. **Typing Indicators**
- Debounce typing start/stop events (e.g., 500ms)
- Auto-stop typing after 3 seconds of inactivity
- Only send typing events when user is actively typing

```javascript
let typingTimeout;
const debouncedTypingStop = () => {
  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(() => {
    sendTypingStop(conversationId);
  }, 3000);
};
```

### 4. **Message Ordering**
- Messages may arrive out of order
- Sort by timestamp on client side
- Use message IDs for deduplication

### 5. **Connection Lifecycle**
- Connect when user opens chat
- Disconnect when user leaves chat page
- Reconnect on app focus (if disconnected)

### 6. **Performance**
- Limit message history in memory
- Use pagination for older messages
- Clean up old typing indicators

---

## Integration with REST API

WebSocket complements the REST API. Use REST for:
- **Initial message load** - `GET /api/v1/chat/conversations/{id}/messages`
- **Sending messages** - `POST /api/v1/chat/conversations/{id}/messages`
- **Marking as read** - `PUT /api/v1/chat/conversations/{id}/read`

Use WebSocket for:
- **Real-time message delivery** - Receive new messages instantly
- **Typing indicators** - Show/hide typing status
- **Read receipts** - Update read status in real-time

### Example: Sending Message

```javascript
// Send via REST API
async function sendMessage(conversationId, content) {
  const response = await fetch(
    `https://api.yourapp.com/api/v1/chat/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ content })
    }
  );
  
  const result = await response.json();
  // Message will also be broadcast via WebSocket to other participants
  return result;
}
```

---

## Testing

### Local Development

```javascript
// Use ws:// for local development
const wsUrl = `ws://localhost:8000/ws/chat?token=${token}`;
```

### Production

```javascript
// Use wss:// for production
const wsUrl = `wss://api.yourapp.com/ws/chat?token=${token}`;
```

### Test Connection

```javascript
const ws = new WebSocket(wsUrl);

ws.onopen = () => {
  console.log('✅ Connected');
  // Test join
  ws.send(JSON.stringify({
    type: 'join',
    conversation_id: 'test-conversation-id'
  }));
};

ws.onmessage = (event) => {
  console.log('📨 Message:', JSON.parse(event.data));
};
```

---

## Troubleshooting

### Connection Fails
- **Check token**: Ensure JWT token is valid and not expired
- **Check URL**: Verify WebSocket URL format (`ws://` or `wss://`)
- **Check CORS**: Ensure WebSocket connections are allowed
- **Check network**: Verify firewall/proxy allows WebSocket connections

### Messages Not Received
- **Verify join**: Ensure you sent `join` event for the conversation
- **Check permissions**: Verify user has access to the conversation
- **Check Redis**: If using multiple instances, ensure Redis is configured

### Typing Indicators Not Working
- **Check debouncing**: Ensure typing events are sent correctly
- **Check conversation_id**: Verify correct conversation ID is used
- **Check WebSocket connection**: Ensure connection is active

---

## Summary

The WebSocket API provides real-time chat functionality with:
- ✅ Real-time message delivery
- ✅ Typing indicators
- ✅ Read receipts
- ✅ Multi-instance support via Redis
- ✅ Automatic reconnection
- ✅ Error handling

For complete API documentation, see:
- [Chat Conversations REST API](./NEWLY_IMPLEMENTED_APIS_FRONTEND_GUIDE.md#chat--messaging)
- [Frontend Implementation Guide](./FRONTEND_IMPLEMENTATION_GUIDE.md)
