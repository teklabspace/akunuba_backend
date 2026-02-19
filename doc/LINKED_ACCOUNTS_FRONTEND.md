# Linked Accounts Bar - Frontend Implementation Guide

## Overview

The linked accounts bar in the frontend displays all accounts that users can link to their Fullego account. This includes banking accounts, brokerage accounts, and investment accounts.

---

## Account Types Users Can Link

### 1. **Banking Accounts** (via Plaid Integration)
- **Types**: Checking accounts, Savings accounts
- **Integration**: Plaid Link
- **Account Type in DB**: `banking`
- **Display Type**: `checking` or `savings` (mapped from Plaid account type)

**Supported Institutions**: Any US bank/institution supported by Plaid (Chase, Bank of America, Wells Fargo, etc.)

**Features**:
- View account balance
- View transaction history
- Sync transactions automatically
- Refresh balance manually
- Disconnect account

---

### 2. **Brokerage Accounts** (via Alpaca Integration)
- **Type**: Trading/Brokerage accounts
- **Integration**: Alpaca API
- **Account Type in DB**: `brokerage`
- **Display Type**: `brokerage`

**Features**:
- View portfolio value
- View buying power
- View cash balance
- Trading capabilities

**Note**: Brokerage accounts are typically connected automatically when Alpaca credentials are configured, not through a user-initiated linking flow.

---

### 3. **Investment Accounts** (Portfolio-based)
- **Type**: Investment portfolios
- **Integration**: Internal portfolio system
- **Account Type**: Based on user's portfolio holdings
- **Display Type**: `investment`

**Features**:
- View total portfolio value
- Based on assets held in the portfolio

---

## How Users Link Accounts

### Banking Accounts Linking Flow (Plaid)

**Step 1: Request Link Token**
```http
POST /api/v1/banking/link-token
Headers: Authorization: Bearer <token>
```

**Response:**
```json
{
  "link_token": "link-sandbox-xxx"
}
```

**Step 2: Initialize Plaid Link**
- Use the `link_token` to initialize Plaid Link SDK in the frontend
- Plaid Link is a pre-built UI component that handles the OAuth flow

**Step 3: User Completes Plaid Flow**
- User selects their bank
- User enters credentials (handled securely by Plaid)
- User selects which accounts to link
- Plaid returns a `public_token`

**Step 4: Complete Account Linking**
```http
POST /api/v1/banking/link
Headers: Authorization: Bearer <token>
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

**Important Requirements:**
- ⚠️ **Requires Annual subscription** - Users must have the `BANKING` feature enabled
- If not eligible, API returns `403 Forbidden` with message: "Banking integration requires Annual subscription"

---

### Brokerage Accounts

Brokerage accounts are connected via Alpaca API credentials configured at the system level. Users don't manually link these accounts - they're automatically available when:
- Alpaca API keys are configured in the backend
- User has a valid Alpaca account

---

### Investment Accounts

Investment accounts are automatically created based on the user's portfolio holdings. No manual linking required.

---

## Frontend API Endpoints

### Get All Linked Accounts
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
  },
  {
    "id": "uuid",
    "institution_name": "Bank of America",
    "account_name": "Savings Account",
    "account_type": "banking",
    "balance": 10000.00,
    "currency": "USD"
  }
]
```

**Use Case**: Display all linked accounts in the linked accounts bar

---

### Get Account Details
```http
GET /api/v1/banking/accounts/{linked_account_id}
Headers: Authorization: Bearer <token>
```

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

### Refresh Account Balance
```http
POST /api/v1/banking/accounts/{linked_account_id}/refresh
Headers: Authorization: Bearer <token>
```

**Response:**
```json
{
  "message": "Account balance refreshed successfully",
  "balance": 5200.00,
  "currency": "USD"
}
```

**Use Case**: Manual refresh button in the UI

---

### Sync Transactions
```http
POST /api/v1/banking/sync/{linked_account_id}
Headers: Authorization: Bearer <token>
```

**Response:**
```json
{
  "message": "Synced 15 new transactions"
}
```

**Use Case**: Manual sync button to fetch latest transactions from Plaid

---

### Get Account Transactions
```http
GET /api/v1/banking/accounts/{linked_account_id}/transactions?start_date=2024-01-01&end_date=2024-01-31&limit=50
Headers: Authorization: Bearer <token>
```

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

### Disconnect Account
```http
DELETE /api/v1/banking/accounts/{linked_account_id}
Headers: Authorization: Bearer <token>
```

**Response:**
```json
{
  "message": "Account disconnected successfully"
}
```

**Use Case**: Remove account from linked accounts bar

---

## Frontend Implementation Recommendations

### Linked Accounts Bar UI Components

1. **Account List Display**
   - Show institution name
   - Show account name
   - Show account type (checking/savings/brokerage/investment)
   - Show balance with currency
   - Show masked account number (last 4 digits)
   - Show last synced timestamp

2. **Add Account Button**
   - Triggers Plaid Link flow
   - Should check subscription eligibility first
   - Show error message if user doesn't have Annual subscription

3. **Account Actions (per account)**
   - **Refresh** button → Calls `/banking/accounts/{id}/refresh`
   - **Sync** button → Calls `/banking/sync/{id}`
   - **View Transactions** → Opens transaction history modal
   - **Disconnect** button → Calls `DELETE /banking/accounts/{id}`

4. **Account Status Indicators**
   - Active/Inactive status
   - Last synced time
   - Connection status (connected/disconnected)

---

## Account Type Mapping

The backend maps account types as follows:

```python
# From LinkedAccount.account_type (BankingAccountType enum)
BANKING → "checking" or "savings" (display)
BROKERAGE → "brokerage" (display)
CRYPTO → "investment" (display)
```

---

## Error Handling

### Common Error Scenarios

1. **No Annual Subscription**
   - Status: `403 Forbidden`
   - Message: "Banking integration requires Annual subscription"
   - **Frontend Action**: Show upgrade prompt or disable "Add Account" button

2. **Plaid Link Token Creation Failed**
   - Status: `400 Bad Request`
   - Message: "Failed to create link token"
   - **Frontend Action**: Show error message, allow retry

3. **Account Linking Failed**
   - Status: `400 Bad Request`
   - Message: "Failed to link account"
   - **Frontend Action**: Show error message, allow user to try again

4. **No Accounts Found**
   - Status: `400 Bad Request`
   - Message: "No accounts found"
   - **Frontend Action**: Inform user that no accounts were found in their bank

---

## Plaid Link Integration

### Frontend Setup

1. **Install Plaid Link**
   ```bash
   npm install react-plaid-link
   # or
   yarn add react-plaid-link
   ```

2. **Example React Component**
   ```jsx
   import { usePlaidLink } from 'react-plaid-link';
   
   function LinkAccountButton() {
     const [linkToken, setLinkToken] = useState(null);
     
     // Step 1: Get link token
     const fetchLinkToken = async () => {
       const response = await fetch('/api/v1/banking/link-token', {
         method: 'POST',
         headers: {
           'Authorization': `Bearer ${token}`
         }
       });
       const data = await response.json();
       setLinkToken(data.link_token);
     };
     
     // Step 2: Initialize Plaid Link
     const { open, ready } = usePlaidLink({
       token: linkToken,
       onSuccess: async (public_token, metadata) => {
         // Step 3: Complete linking
         await fetch('/api/v1/banking/link', {
           method: 'POST',
           headers: {
             'Authorization': `Bearer ${token}`,
             'Content-Type': 'application/json'
           },
           body: JSON.stringify({ public_token })
         });
         
         // Refresh accounts list
         window.location.reload();
       },
       onExit: (err, metadata) => {
         if (err) {
           console.error('Plaid Link error:', err);
         }
       }
     });
     
     return (
       <button 
         onClick={() => {
           fetchLinkToken().then(() => open());
         }}
         disabled={!ready}
       >
         Add Bank Account
       </button>
     );
   }
   ```

---

## Summary

### Account Types in Linked Accounts Bar:
1. ✅ **Banking Accounts** (Checking/Savings) - Linked via Plaid
2. ✅ **Brokerage Accounts** - Connected via Alpaca (automatic)
3. ✅ **Investment Accounts** - Based on portfolio (automatic)

### Linking Process:
- **Banking**: User-initiated via Plaid Link flow (requires Annual subscription)
- **Brokerage**: Automatic via Alpaca API configuration
- **Investment**: Automatic based on portfolio holdings

### Key APIs:
- `GET /api/v1/banking/accounts` - List all linked accounts
- `POST /api/v1/banking/link-token` - Get Plaid link token
- `POST /api/v1/banking/link` - Complete account linking
- `POST /api/v1/banking/accounts/{id}/refresh` - Refresh balance
- `POST /api/v1/banking/sync/{id}` - Sync transactions
- `DELETE /api/v1/banking/accounts/{id}` - Disconnect account
