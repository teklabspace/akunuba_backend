# Linked Accounts Feature - Next.js Implementation Guide

Complete guide for implementing the Linked Accounts feature in Next.js with all API endpoints, TypeScript types, hooks, and components.

---

## Table of Contents

1. [All API Endpoints](#all-api-endpoints)
2. [TypeScript Types](#typescript-types)
3. [API Service Functions](#api-service-functions)
4. [React Hooks](#react-hooks)
5. [Plaid Link Integration](#plaid-link-integration)
6. [UI Components](#ui-components)
7. [Error Handling](#error-handling)
8. [Complete Example](#complete-example)

---

## All API Endpoints

### Base URL
```
/api/v1/banking
```

### 1. Get All Linked Accounts
```http
GET /api/v1/banking/accounts
Headers: Authorization: Bearer <token>
```

**Response:**
```json
[
  {
    "id": "uuid",
    "institution_name": "Chase Bank",
    "account_name": "Checking Account",
    "account_type": "banking",
    "balance": 5000.00,
    "currency": "USD"
  }
]
```

---

### 2. Get Linked Account Details
```http
GET /api/v1/banking/accounts/{linked_account_id}
Headers: Authorization: Bearer <token>
```

**Path Parameters:**
- `linked_account_id` (UUID, required)

**Response:**
```json
{
  "id": "uuid",
  "account_id": "uuid",
  "plaid_item_id": "item_xxx",
  "account_type": "banking",
  "institution_name": "Chase Bank",
  "account_name": "Checking Account",
  "account_number": "****4932",
  "routing_number": "021000021",
  "balance": 5000.00,
  "currency": "USD",
  "is_active": true,
  "last_synced_at": "2024-01-01T00:00:00Z",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

---

### 3. Create Plaid Link Token
```http
POST /api/v1/banking/link-token
Headers: Authorization: Bearer <token>
Body: (empty)
```

**Response:**
```json
{
  "link_token": "link-sandbox-xxx"
}
```

---

### 4. Link Bank Account
```http
POST /api/v1/banking/link
Headers: Authorization: Bearer <token>
Content-Type: application/json
Body: {
  "public_token": "public-sandbox-xxx"
}
```

**Response:**
```json
{
  "message": "2 account(s) linked successfully"
}
```

**Error Responses:**
- `403 Forbidden`: "Banking integration requires Annual subscription"
- `400 Bad Request`: "Failed to link account" or "No accounts found"

---

### 5. Refresh Account Balance
```http
POST /api/v1/banking/accounts/{linked_account_id}/refresh
Headers: Authorization: Bearer <token>
Body: (empty)
```

**Path Parameters:**
- `linked_account_id` (UUID, required)

**Response:**
```json
{
  "message": "Account balance refreshed successfully",
  "balance": 5200.00,
  "currency": "USD"
}
```

---

### 6. Sync Transactions
```http
POST /api/v1/banking/sync/{linked_account_id}
Headers: Authorization: Bearer <token>
Body: (empty)
```

**Path Parameters:**
- `linked_account_id` (UUID, required)

**Response:**
```json
{
  "message": "Synced 15 new transactions"
}
```

---

### 7. Get Account Transactions
```http
GET /api/v1/banking/accounts/{linked_account_id}/transactions?start_date=2024-01-01&end_date=2024-01-31&limit=50
Headers: Authorization: Bearer <token>
```

**Path Parameters:**
- `linked_account_id` (UUID, required)

**Query Parameters:**
- `start_date` (string, optional): YYYY-MM-DD
- `end_date` (string, optional): YYYY-MM-DD
- `limit` (number, optional): 1-500, default: 50

**Response:**
```json
{
  "transactions": [
    {
      "id": "uuid",
      "amount": -50.00,
      "currency": "USD",
      "description": "Coffee Shop",
      "category": "Food & Drink",
      "transaction_date": "2024-01-01T00:00:00Z",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "count": 15
}
```

---

### 8. Disconnect Account
```http
DELETE /api/v1/banking/accounts/{linked_account_id}
Headers: Authorization: Bearer <token>
```

**Path Parameters:**
- `linked_account_id` (UUID, required)

**Response:**
```json
{
  "message": "Account disconnected successfully"
}
```

---

## TypeScript Types

Create `types/banking.ts`:

```typescript
// types/banking.ts

export interface LinkedAccount {
  id: string;
  institution_name: string;
  account_name: string;
  account_type: 'banking' | 'brokerage' | 'crypto';
  balance: number | null;
  currency: string;
}

export interface LinkedAccountDetails extends LinkedAccount {
  account_id: string;
  plaid_item_id: string;
  account_number: string;
  routing_number: string;
  is_active: boolean;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Transaction {
  id: string;
  amount: number;
  currency: string;
  description: string | null;
  category: string | null;
  transaction_date: string;
  created_at: string;
}

export interface TransactionsResponse {
  transactions: Transaction[];
  count: number;
}

export interface LinkTokenResponse {
  link_token: string;
}

export interface LinkAccountResponse {
  message: string;
}

export interface RefreshBalanceResponse {
  message: string;
  balance: number;
  currency: string;
}

export interface SyncTransactionsResponse {
  message: string;
}

export interface DisconnectAccountResponse {
  message: string;
}

export interface GetTransactionsParams {
  start_date?: string;
  end_date?: string;
  limit?: number;
}
```

---

## API Service Functions

Create `lib/api/banking.ts`:

```typescript
// lib/api/banking.ts

import { 
  LinkedAccount, 
  LinkedAccountDetails,
  TransactionsResponse,
  LinkTokenResponse,
  LinkAccountResponse,
  RefreshBalanceResponse,
  SyncTransactionsResponse,
  DisconnectAccountResponse,
  GetTransactionsParams
} from '@/types/banking';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const BANKING_BASE = `${API_BASE_URL}/api/v1/banking`;

// Helper function to get auth token
const getAuthToken = (): string | null => {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('auth_token') || sessionStorage.getItem('auth_token');
};

// Helper function for API calls
const apiCall = async <T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> => {
  const token = getAuthToken();
  
  if (!token) {
    throw new Error('Authentication token not found');
  }

  const response = await fetch(endpoint, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: 'An error occurred' }));
    throw new Error(error.message || `HTTP error! status: ${response.status}`);
  }

  return response.json();
};

// 1. Get All Linked Accounts
export const getLinkedAccounts = async (): Promise<LinkedAccount[]> => {
  return apiCall<LinkedAccount[]>(`${BANKING_BASE}/accounts`);
};

// 2. Get Linked Account Details
export const getLinkedAccountDetails = async (
  linkedAccountId: string
): Promise<LinkedAccountDetails> => {
  return apiCall<LinkedAccountDetails>(`${BANKING_BASE}/accounts/${linkedAccountId}`);
};

// 3. Create Plaid Link Token
export const createLinkToken = async (): Promise<LinkTokenResponse> => {
  return apiCall<LinkTokenResponse>(`${BANKING_BASE}/link-token`, {
    method: 'POST',
  });
};

// 4. Link Bank Account
export const linkAccount = async (
  publicToken: string
): Promise<LinkAccountResponse> => {
  return apiCall<LinkAccountResponse>(`${BANKING_BASE}/link`, {
    method: 'POST',
    body: JSON.stringify({ public_token: publicToken }),
  });
};

// 5. Refresh Account Balance
export const refreshAccountBalance = async (
  linkedAccountId: string
): Promise<RefreshBalanceResponse> => {
  return apiCall<RefreshBalanceResponse>(
    `${BANKING_BASE}/accounts/${linkedAccountId}/refresh`,
    {
      method: 'POST',
    }
  );
};

// 6. Sync Transactions
export const syncTransactions = async (
  linkedAccountId: string
): Promise<SyncTransactionsResponse> => {
  return apiCall<SyncTransactionsResponse>(
    `${BANKING_BASE}/sync/${linkedAccountId}`,
    {
      method: 'POST',
    }
  );
};

// 7. Get Account Transactions
export const getAccountTransactions = async (
  linkedAccountId: string,
  params?: GetTransactionsParams
): Promise<TransactionsResponse> => {
  const queryParams = new URLSearchParams();
  
  if (params?.start_date) {
    queryParams.append('start_date', params.start_date);
  }
  if (params?.end_date) {
    queryParams.append('end_date', params.end_date);
  }
  if (params?.limit) {
    queryParams.append('limit', params.limit.toString());
  }

  const queryString = queryParams.toString();
  const url = `${BANKING_BASE}/accounts/${linkedAccountId}/transactions${
    queryString ? `?${queryString}` : ''
  }`;

  return apiCall<TransactionsResponse>(url);
};

// 8. Disconnect Account
export const disconnectAccount = async (
  linkedAccountId: string
): Promise<DisconnectAccountResponse> => {
  return apiCall<DisconnectAccountResponse>(
    `${BANKING_BASE}/accounts/${linkedAccountId}`,
    {
      method: 'DELETE',
    }
  );
};
```

---

## React Hooks

Create `hooks/useLinkedAccounts.ts`:

```typescript
// hooks/useLinkedAccounts.ts

import { useState, useEffect, useCallback } from 'react';
import {
  getLinkedAccounts,
  refreshAccountBalance,
  syncTransactions,
  disconnectAccount,
} from '@/lib/api/banking';
import { LinkedAccount } from '@/types/banking';

export const useLinkedAccounts = () => {
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAccounts = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getLinkedAccounts();
      setAccounts(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch accounts');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  const refreshBalance = useCallback(
    async (accountId: string) => {
      try {
        await refreshAccountBalance(accountId);
        await fetchAccounts(); // Refresh the list
      } catch (err) {
        throw new Error(
          err instanceof Error ? err.message : 'Failed to refresh balance'
        );
      }
    },
    [fetchAccounts]
  );

  const syncAccountTransactions = useCallback(
    async (accountId: string) => {
      try {
        await syncTransactions(accountId);
      } catch (err) {
        throw new Error(
          err instanceof Error ? err.message : 'Failed to sync transactions'
        );
      }
    },
    []
  );

  const removeAccount = useCallback(
    async (accountId: string) => {
      try {
        await disconnectAccount(accountId);
        await fetchAccounts(); // Refresh the list
      } catch (err) {
        throw new Error(
          err instanceof Error ? err.message : 'Failed to disconnect account'
        );
      }
    },
    [fetchAccounts]
  );

  return {
    accounts,
    loading,
    error,
    refreshAccounts: fetchAccounts,
    refreshBalance,
    syncAccountTransactions,
    removeAccount,
  };
};
```

Create `hooks/useAccountTransactions.ts`:

```typescript
// hooks/useAccountTransactions.ts

import { useState, useEffect, useCallback } from 'react';
import { getAccountTransactions } from '@/lib/api/banking';
import { Transaction, GetTransactionsParams } from '@/types/banking';

export const useAccountTransactions = (
  accountId: string | null,
  params?: GetTransactionsParams
) => {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState(0);

  const fetchTransactions = useCallback(async () => {
    if (!accountId) return;

    try {
      setLoading(true);
      setError(null);
      const data = await getAccountTransactions(accountId, params);
      setTransactions(data.transactions);
      setCount(data.count);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch transactions');
    } finally {
      setLoading(false);
    }
  }, [accountId, params]);

  useEffect(() => {
    fetchTransactions();
  }, [fetchTransactions]);

  return {
    transactions,
    loading,
    error,
    count,
    refreshTransactions: fetchTransactions,
  };
};
```

---

## Plaid Link Integration

### Installation

```bash
npm install react-plaid-link
# or
yarn add react-plaid-link
```

### Create Plaid Link Hook

Create `hooks/usePlaidLink.ts`:

```typescript
// hooks/usePlaidLink.ts

import { useState, useCallback, useEffect, useRef } from 'react';
import { usePlaidLink as usePlaidLinkHook } from 'react-plaid-link';
import { createLinkToken, linkAccount } from '@/lib/api/banking';

export const usePlaidLink = (onSuccess?: () => void) => {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shouldOpenRef = useRef(false);

  // Always call usePlaidLinkHook unconditionally to maintain hook order
  const { open, ready } = usePlaidLinkHook({
    token: linkToken,
    onSuccess: async (publicToken, metadata) => {
      try {
        setLoading(true);
        setError(null);
        await linkAccount(publicToken);
        setLinkToken(null);
        shouldOpenRef.current = false;
        onSuccess?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to link account');
        setLinkToken(null);
        shouldOpenRef.current = false;
      } finally {
        setLoading(false);
      }
    },
    onExit: (err, metadata) => {
      if (err) {
        setError(err.message || 'Plaid Link exited with error');
      }
      setLinkToken(null);
      shouldOpenRef.current = false;
    },
  });

  // Open Plaid Link when token becomes available
  useEffect(() => {
    if (linkToken && ready && shouldOpenRef.current) {
      open();
      shouldOpenRef.current = false;
    }
  }, [linkToken, ready, open]);

  const startLinkFlow = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      shouldOpenRef.current = true;
      const response = await createLinkToken();
      setLinkToken(response.link_token);
      // The useEffect will handle opening when token is ready
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create link token');
      setLinkToken(null);
      shouldOpenRef.current = false;
      setLoading(false);
    }
  }, []);

  return {
    startLinkFlow,
    ready: ready && !!linkToken && !loading,
    loading,
    error,
  };
};
```

**Important Notes:**
- ✅ **Always call `usePlaidLinkHook` unconditionally** - This ensures React Hooks are called in the same order every render
- ✅ **Use `useEffect` to open Plaid Link** - This ensures the link opens after the token is set and Plaid is ready
- ✅ **Use `useRef` to track intent** - This prevents race conditions when opening the link
- ❌ **Never conditionally call hooks** - All hooks must be called at the top level, in the same order

**Alternative Simpler Approach** (if you prefer a more straightforward implementation):

```typescript
// hooks/usePlaidLink.ts (Alternative - Simpler version)

import { useState, useCallback, useEffect } from 'react';
import { usePlaidLink as usePlaidLinkHook } from 'react-plaid-link';
import { createLinkToken, linkAccount } from '@/lib/api/banking';

export const usePlaidLink = (onSuccess?: () => void) => {
  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shouldOpen, setShouldOpen] = useState(false);

  // Always call usePlaidLinkHook - never conditionally
  const plaidLink = usePlaidLinkHook({
    token: linkToken,
    onSuccess: async (publicToken) => {
      try {
        setLoading(true);
        await linkAccount(publicToken);
        setLinkToken(null);
        setShouldOpen(false);
        onSuccess?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to link account');
      } finally {
        setLoading(false);
      }
    },
    onExit: () => {
      setLinkToken(null);
      setShouldOpen(false);
    },
  });

  // Open when token is ready
  useEffect(() => {
    if (shouldOpen && linkToken && plaidLink.ready) {
      plaidLink.open();
      setShouldOpen(false);
    }
  }, [shouldOpen, linkToken, plaidLink.ready, plaidLink.open]);

  const startLinkFlow = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await createLinkToken();
      setLinkToken(response.link_token);
      setShouldOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create link token');
      setLoading(false);
    }
  }, []);

  return {
    startLinkFlow,
    ready: plaidLink.ready && !!linkToken && !loading,
    loading,
    error,
  };
};
```

---

## UI Components

### Linked Accounts Bar Component

Create `components/banking/LinkedAccountsBar.tsx`:

```typescript
// components/banking/LinkedAccountsBar.tsx

'use client';

import React, { useState } from 'react';
import { useLinkedAccounts } from '@/hooks/useLinkedAccounts';
import { usePlaidLink } from '@/hooks/usePlaidLink';
import { LinkedAccountCard } from './LinkedAccountCard';
import { AddAccountButton } from './AddAccountButton';

export const LinkedAccountsBar: React.FC = () => {
  const { accounts, loading, error, refreshAccounts, refreshBalance, removeAccount } =
    useLinkedAccounts();
  const { startLinkFlow, ready, loading: linkLoading, error: linkError } =
    usePlaidLink(() => {
      refreshAccounts();
    });

  const handleAddAccount = () => {
    startLinkFlow();
  };

  const handleRefreshBalance = async (accountId: string) => {
    try {
      await refreshBalance(accountId);
    } catch (err) {
      console.error('Failed to refresh balance:', err);
    }
  };

  const handleRemoveAccount = async (accountId: string) => {
    if (confirm('Are you sure you want to disconnect this account?')) {
      try {
        await removeAccount(accountId);
      } catch (err) {
        console.error('Failed to remove account:', err);
      }
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Linked Accounts</h2>
        <AddAccountButton
          onClick={handleAddAccount}
          disabled={!ready || linkLoading}
          loading={linkLoading}
        />
      </div>

      {linkError && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {linkError}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      )}

      {accounts.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 rounded-lg">
          <p className="text-gray-500 mb-4">No linked accounts yet</p>
          <AddAccountButton
            onClick={handleAddAccount}
            disabled={!ready || linkLoading}
            loading={linkLoading}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {accounts.map((account) => (
            <LinkedAccountCard
              key={account.id}
              account={account}
              onRefreshBalance={() => handleRefreshBalance(account.id)}
              onRemove={() => handleRemoveAccount(account.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
};
```

### Linked Account Card Component

Create `components/banking/LinkedAccountCard.tsx`:

```typescript
// components/banking/LinkedAccountCard.tsx

'use client';

import React, { useState } from 'react';
import { LinkedAccount } from '@/types/banking';
import { formatCurrency } from '@/lib/utils';
import { AccountTransactionsModal } from './AccountTransactionsModal';

interface LinkedAccountCardProps {
  account: LinkedAccount;
  onRefreshBalance: () => Promise<void>;
  onRemove: () => Promise<void>;
}

export const LinkedAccountCard: React.FC<LinkedAccountCardProps> = ({
  account,
  onRefreshBalance,
  onRemove,
}) => {
  const [refreshing, setRefreshing] = useState(false);
  const [showTransactions, setShowTransactions] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await onRefreshBalance();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <>
      <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">
              {account.account_name}
            </h3>
            <p className="text-sm text-gray-500">{account.institution_name}</p>
          </div>
          <span className="px-2 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded">
            {account.account_type}
          </span>
        </div>

        <div className="mb-4">
          <p className="text-2xl font-bold text-gray-900">
            {formatCurrency(account.balance || 0, account.currency)}
          </p>
        </div>

        <div className="flex gap-2">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex-1 px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 rounded-md hover:bg-blue-100 disabled:opacity-50"
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <button
            onClick={() => setShowTransactions(true)}
            className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-gray-50 rounded-md hover:bg-gray-100"
          >
            Transactions
          </button>
          <button
            onClick={onRemove}
            className="px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-md hover:bg-red-100"
          >
            Remove
          </button>
        </div>
      </div>

      {showTransactions && (
        <AccountTransactionsModal
          accountId={account.id}
          accountName={account.account_name}
          onClose={() => setShowTransactions(false)}
        />
      )}
    </>
  );
};
```

### Add Account Button Component

Create `components/banking/AddAccountButton.tsx`:

```typescript
// components/banking/AddAccountButton.tsx

'use client';

import React from 'react';

interface AddAccountButtonProps {
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
}

export const AddAccountButton: React.FC<AddAccountButtonProps> = ({
  onClick,
  disabled,
  loading,
}) => {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
    >
      {loading ? (
        <>
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
          <span>Connecting...</span>
        </>
      ) : (
        <>
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 4v16m8-8H4"
            />
          </svg>
          <span>Add Account</span>
        </>
      )}
    </button>
  );
};
```

### Account Transactions Modal Component

Create `components/banking/AccountTransactionsModal.tsx`:

```typescript
// components/banking/AccountTransactionsModal.tsx

'use client';

import React, { useState } from 'react';
import { useAccountTransactions } from '@/hooks/useAccountTransactions';
import { formatCurrency, formatDate } from '@/lib/utils';

interface AccountTransactionsModalProps {
  accountId: string;
  accountName: string;
  onClose: () => void;
}

export const AccountTransactionsModal: React.FC<AccountTransactionsModalProps> = ({
  accountId,
  accountName,
  onClose,
}) => {
  const [dateRange, setDateRange] = useState<'30' | '90' | 'all'>('30');
  const { transactions, loading, error, count } = useAccountTransactions(
    accountId,
    dateRange !== 'all'
      ? {
          start_date: new Date(
            Date.now() - parseInt(dateRange) * 24 * 60 * 60 * 1000
          )
            .toISOString()
            .split('T')[0],
          end_date: new Date().toISOString().split('T')[0],
          limit: 100,
        }
      : { limit: 100 }
  );

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900">
              Transactions - {accountName}
            </h2>
            <p className="text-sm text-gray-500">{count} transactions</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex gap-2">
            {(['30', '90', 'all'] as const).map((range) => (
              <button
                key={range}
                onClick={() => setDateRange(range)}
                className={`px-4 py-2 rounded-md text-sm font-medium ${
                  dateRange === range
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {range === 'all' ? 'All Time' : `Last ${range} Days`}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
          ) : error ? (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          ) : transactions.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              No transactions found
            </div>
          ) : (
            <div className="space-y-2">
              {transactions.map((transaction) => (
                <div
                  key={transaction.id}
                  className="flex items-center justify-between p-4 bg-gray-50 rounded-lg"
                >
                  <div className="flex-1">
                    <p className="font-medium text-gray-900">
                      {transaction.description || 'Unknown'}
                    </p>
                    <p className="text-sm text-gray-500">
                      {transaction.category || 'Uncategorized'}
                    </p>
                    <p className="text-xs text-gray-400">
                      {formatDate(transaction.transaction_date)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p
                      className={`font-semibold ${
                        transaction.amount >= 0
                          ? 'text-green-600'
                          : 'text-red-600'
                      }`}
                    >
                      {formatCurrency(
                        Math.abs(transaction.amount),
                        transaction.currency
                      )}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
```

---

## Utility Functions

Create `lib/utils.ts`:

```typescript
// lib/utils.ts

export const formatCurrency = (amount: number, currency: string = 'USD'): string => {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency,
  }).format(amount);
};

export const formatDate = (dateString: string): string => {
  const date = new Date(dateString);
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(date);
};
```

---

## Error Handling

Create `lib/errorHandler.ts`:

```typescript
// lib/errorHandler.ts

export class BankingError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public code?: string
  ) {
    super(message);
    this.name = 'BankingError';
  }
}

export const handleBankingError = (error: unknown): string => {
  if (error instanceof BankingError) {
    switch (error.statusCode) {
      case 403:
        return 'Banking integration requires Annual subscription. Please upgrade your plan.';
      case 400:
        return error.message || 'Invalid request. Please try again.';
      case 404:
        return 'Account not found.';
      default:
        return error.message || 'An error occurred. Please try again.';
    }
  }

  if (error instanceof Error) {
    return error.message;
  }

  return 'An unexpected error occurred. Please try again.';
};
```

Update API service to use error handler:

```typescript
// In lib/api/banking.ts, update apiCall function:

import { BankingError, handleBankingError } from '@/lib/errorHandler';

const apiCall = async <T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> => {
  const token = getAuthToken();
  
  if (!token) {
    throw new BankingError('Authentication token not found', 401);
  }

  try {
    const response = await fetch(endpoint, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ 
        message: 'An error occurred' 
      }));
      
      throw new BankingError(
        error.message || `HTTP error! status: ${response.status}`,
        response.status,
        error.code
      );
    }

    return response.json();
  } catch (error) {
    if (error instanceof BankingError) {
      throw error;
    }
    throw new BankingError(
      error instanceof Error ? error.message : 'Network error occurred'
    );
  }
};
```

---

## Complete Example: Page Component

Create `app/preferences/linked-accounts/page.tsx`:

```typescript
// app/preferences/linked-accounts/page.tsx

'use client';

import React from 'react';
import { LinkedAccountsBar } from '@/components/banking/LinkedAccountsBar';

export default function LinkedAccountsPage() {
  return (
    <div className="container mx-auto px-4 py-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold mb-8">Linked Accounts</h1>
        <LinkedAccountsBar />
      </div>
    </div>
  );
}
```

---

## Environment Variables

Add to `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
# or for production:
# NEXT_PUBLIC_API_URL=https://your-api-domain.com
```

---

## Summary

### All 8 API Endpoints:
1. ✅ `GET /api/v1/banking/accounts` - Get all linked accounts
2. ✅ `GET /api/v1/banking/accounts/{id}` - Get account details
3. ✅ `POST /api/v1/banking/link-token` - Create Plaid link token
4. ✅ `POST /api/v1/banking/link` - Link bank account
5. ✅ `POST /api/v1/banking/accounts/{id}/refresh` - Refresh balance
6. ✅ `POST /api/v1/banking/sync/{id}` - Sync transactions
7. ✅ `GET /api/v1/banking/accounts/{id}/transactions` - Get transactions
8. ✅ `DELETE /api/v1/banking/accounts/{id}` - Disconnect account

### Implementation Checklist:
- ✅ TypeScript types defined
- ✅ API service functions created
- ✅ React hooks for data fetching
- ✅ Plaid Link integration
- ✅ UI components (Bar, Card, Modal, Button)
- ✅ Error handling
- ✅ Loading states
- ✅ Complete example page

### Next Steps:
1. Install dependencies: `npm install react-plaid-link`
2. Set up environment variables
3. Implement authentication token storage
4. Customize styling to match your design system
5. Add subscription check before showing "Add Account" button
6. Add toast notifications for success/error messages

---

## Troubleshooting

### React Hooks Order Error

**Error Message:**
```
React has detected a change in the order of Hooks called by [Component]
```

**Cause:**
- Hooks are being called conditionally
- Hooks are being called in different orders between renders
- A hook is being called inside a conditional statement or loop

**Solution:**
1. **Always call all hooks at the top level** - Never inside conditionals, loops, or nested functions
2. **Ensure `usePlaidLinkHook` is always called** - Even if the token is null
3. **Use `useEffect` to handle side effects** - Don't call hooks conditionally based on state

**Example of WRONG usage:**
```typescript
// ❌ WRONG - Conditional hook call
if (someCondition) {
  const { open } = usePlaidLinkHook({ token: linkToken });
}

// ❌ WRONG - Hook in callback
const handleClick = () => {
  const { open } = usePlaidLinkHook({ token: linkToken });
};
```

**Example of CORRECT usage:**
```typescript
// ✅ CORRECT - Always call hook
const { open } = usePlaidLinkHook({ 
  token: linkToken, // Can be null, but hook is always called
  onSuccess: handleSuccess 
});

// ✅ CORRECT - Use useEffect for conditional logic
useEffect(() => {
  if (linkToken && ready) {
    open();
  }
}, [linkToken, ready, open]);
```

---

### Plaid Link Token Creation Failed (400 Error)

**Error Message:**
```
Failed to create link token
```

**Possible Causes:**
1. Backend Plaid credentials not configured
2. User doesn't have an account record
3. Backend API endpoint not accessible
4. Authentication token missing or invalid

**Solution:**
1. Check backend logs for detailed error
2. Verify `PLAID_CLIENT_ID` and `PLAID_SECRET_KEY` are set in backend
3. Ensure user has a valid account record
4. Verify authentication token is being sent correctly

---

### Account Linking Failed (403 Forbidden)

**Error Message:**
```
Banking integration requires Annual subscription
```

**Cause:**
- User doesn't have the required subscription plan

**Solution:**
- Check user's subscription plan before showing "Add Account" button
- Show upgrade prompt if subscription is not Annual

```typescript
// Check subscription before allowing account linking
const { subscription } = useSubscription();
const canLinkAccounts = subscription?.plan === 'annual';

{canLinkAccounts ? (
  <AddAccountButton onClick={handleAddAccount} />
) : (
  <UpgradePrompt message="Upgrade to Annual plan to link bank accounts" />
)}
```

---

### Token Not Opening Plaid Link

**Symptoms:**
- Token is created successfully
- But Plaid Link modal doesn't open

**Solution:**
- Ensure `useEffect` is watching for token changes
- Check that `ready` is `true` before calling `open()`
- Verify Plaid Link script is loaded in your HTML

```typescript
useEffect(() => {
  if (linkToken && ready && shouldOpen) {
    open();
  }
}, [linkToken, ready, shouldOpen, open]);
```

---

### Transactions Not Syncing

**Error Message:**
```
Failed to sync transactions
```

**Possible Causes:**
1. Account not properly linked
2. Plaid access token expired
3. Network error

**Solution:**
1. Verify account is active: `is_active: true`
2. Check `last_synced_at` timestamp
3. Try refreshing the account balance first
4. Check backend logs for Plaid API errors
