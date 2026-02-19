# Backend Implementation: Plaid Link Token Endpoint

Complete implementation guide for the Plaid Link Token endpoint used in the Linked Accounts feature.

---

## Overview

**Endpoint**: `POST /api/v1/banking/link-token`

**Purpose**: Creates a Plaid Link token that the frontend uses to initialize Plaid Link for connecting bank accounts.

**Status**: ✅ **IMPLEMENTED** - Ready for testing

---

## Implementation Details

### 1. Endpoint Location

**File**: `app/api/v1/banking.py`

**Route**: `/api/v1/banking/link-token`

**Method**: `POST`

**Authentication**: Required (Bearer token)

---

### 2. Request

**Headers**:
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Body**: None (empty body)

**Example**:
```bash
curl -X POST "http://localhost:8000/api/v1/banking/link-token" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json"
```

---

### 3. Response

**Success (200)**:
```json
{
  "link_token": "link-sandbox-xxx"
}
```

**Error (400)**: Bad Request
```json
{
  "detail": "Plaid not configured: Plaid credentials not configured. Please set PLAID_CLIENT_ID and PLAID_SECRET_KEY"
}
```

**Error (404)**: Not Found
```json
{
  "detail": "Account not found"
}
```

---

## Code Implementation

### Endpoint Handler

```python
# app/api/v1/banking.py

@router.post("/link-token", response_model=LinkTokenResponse)
async def create_link_token(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create Plaid link token for account linking.
    
    This endpoint creates a link token that the frontend uses to initialize
    Plaid Link for connecting bank accounts.
    
    Returns:
        LinkTokenResponse with link_token string
        
    Raises:
        404: If user account not found
        400: If Plaid credentials not configured or API call fails
    """
    # Verify user has an account record
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    try:
        link_token = PlaidClient.create_link_token(
            user_id=str(current_user.id),
            account_id=str(account.id)
        )
        logger.info(f"Link token created successfully for user {current_user.id}")
        return LinkTokenResponse(link_token=link_token)
    except ValueError as e:
        # Credentials not configured or SDK not available
        logger.error(f"Plaid configuration error: {e}")
        raise BadRequestException(f"Plaid not configured: {str(e)}")
    except Exception as e:
        # Plaid API error
        logger.error(f"Failed to create Plaid link token: {e}", exc_info=True)
        raise BadRequestException(f"Failed to create link token: {str(e)}")
```

### Plaid Client Implementation

```python
# app/integrations/plaid_client.py

@classmethod
def create_link_token(cls, user_id: str, account_id: str) -> str:
    """
    Create a Plaid Link token for account linking.
    
    Args:
        user_id: Unique identifier for the user
        account_id: Unique identifier for the account
        
    Returns:
        Link token string
        
    Raises:
        ValueError: If Plaid client is not available or credentials are missing
        Exception: If Plaid API call fails
    """
    # Check if Plaid SDK is available
    if not PLAID_AVAILABLE:
        error_msg = "Plaid SDK not installed. Install with: pip install plaid-python"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # Check if credentials are configured
    if not settings.PLAID_CLIENT_ID or not settings.PLAID_SECRET_KEY:
        error_msg = "Plaid credentials not configured. Please set PLAID_CLIENT_ID and PLAID_SECRET_KEY"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    try:
        client = cls.get_client()
        if client is None:
            error_msg = "Failed to initialize Plaid client"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Create link token request
        request = {
            "user": {
                "client_user_id": user_id,
            },
            "client_name": "Fullego",
            "products": ["transactions", "auth"],
            "country_codes": ["US"],
            "language": "en",
        }
        
        # Call Plaid API
        response = client.link_token_create(request)
        
        # Extract link token from response
        if hasattr(response, 'link_token'):
            link_token = response.link_token
        elif isinstance(response, dict):
            link_token = response.get("link_token")
        else:
            link_token = response["link_token"]
        
        if not link_token:
            error_msg = "Plaid API returned empty link token"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Link token created successfully for user {user_id}")
        return link_token
        
    except ValueError:
        raise
    except Exception as e:
        error_msg = f"Failed to create Plaid link token: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise Exception(error_msg) from e
```

---

## Configuration Requirements

### Environment Variables

The following environment variables must be set:

```env
# Plaid Configuration
PLAID_CLIENT_ID=your_plaid_client_id_here
PLAID_SECRET_KEY=your_plaid_secret_key_here
PLAID_ENV=sandbox  # Options: sandbox, development, production
```

### Where to Get Plaid Credentials

1. **Sign up for Plaid**: Go to https://dashboard.plaid.com/signup
2. **Get API Keys**: 
   - Navigate to **Team Settings** → **Keys**
   - Copy your **Client ID** → Set as `PLAID_CLIENT_ID`
   - Copy your **Secret Key** → Set as `PLAID_SECRET_KEY`
3. **Choose Environment**:
   - **Sandbox**: For testing (default)
   - **Development**: For development testing
   - **Production**: For live applications

### Setting Environment Variables

**Local Development (.env file)**:
```env
PLAID_CLIENT_ID=your_client_id
PLAID_SECRET_KEY=your_secret_key
PLAID_ENV=sandbox
```

**Production (Render/Heroku/etc)**:
Set these as environment variables in your hosting platform's dashboard.

---

## Dependencies

### Required Python Package

The Plaid Python SDK must be installed:

```bash
pip install plaid-python==9.0.0
```

**Already in requirements.txt**: ✅ Yes

---

## Testing

### 1. Manual Testing with cURL

```bash
# Get your access token first (from login endpoint)
ACCESS_TOKEN="your_access_token_here"

# Create link token
curl -X POST "http://localhost:8000/api/v1/banking/link-token" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json"
```

**Expected Response**:
```json
{
  "link_token": "link-sandbox-xxx"
}
```

### 2. Testing with Postman

1. Import the Postman collection: `Fullego_Backend_API.postman_collection.json`
2. Navigate to **Banking** → **Create Link Token**
3. Set the `Authorization` header with your Bearer token
4. Send the request

### 3. Testing with Python

```python
import requests

# Your API base URL
BASE_URL = "http://localhost:8000"
ACCESS_TOKEN = "your_access_token_here"

# Create link token
response = requests.post(
    f"{BASE_URL}/api/v1/banking/link-token",
    headers={
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
```

### 4. Integration Testing

The frontend should:
1. Call this endpoint to get `link_token`
2. Initialize Plaid Link with the token
3. User completes Plaid flow
4. Frontend receives `public_token`
5. Frontend calls `/api/v1/banking/link` with `public_token`

---

## Error Handling

### Common Errors and Solutions

#### 1. **400 Bad Request: "Plaid not configured"**

**Cause**: Plaid credentials not set in environment variables

**Solution**:
1. Check `.env` file has `PLAID_CLIENT_ID` and `PLAID_SECRET_KEY`
2. Verify values are not empty
3. Restart the server after adding credentials

#### 2. **400 Bad Request: "Plaid SDK not installed"**

**Cause**: `plaid-python` package not installed

**Solution**:
```bash
pip install plaid-python==9.0.0
# or
pip install -r requirements.txt
```

#### 3. **400 Bad Request: "Failed to create link token"**

**Cause**: Plaid API error (invalid credentials, network issue, etc.)

**Solution**:
1. Check Plaid credentials are correct
2. Verify `PLAID_ENV` matches your credentials environment
3. Check backend logs for detailed error message
4. Verify Plaid account is active

#### 4. **404 Not Found: "Account not found"**

**Cause**: User doesn't have an account record

**Solution**: User must have an account record created first (usually done during registration)

---

## Troubleshooting

### Check Plaid Client Initialization

Add this to verify Plaid client is working:

```python
# Test script: test_plaid.py
from app.integrations.plaid_client import PlaidClient
from app.config import settings

print(f"Plaid Client ID: {settings.PLAID_CLIENT_ID[:10]}..." if settings.PLAID_CLIENT_ID else "Not set")
print(f"Plaid Environment: {settings.PLAID_ENV}")

try:
    client = PlaidClient.get_client()
    if client:
        print("✅ Plaid client initialized successfully")
    else:
        print("❌ Plaid client is None")
except Exception as e:
    print(f"❌ Error: {e}")
```

### Verify Environment Variables

```python
# Check if variables are loaded
from app.config import settings

print(f"PLAID_CLIENT_ID: {'Set' if settings.PLAID_CLIENT_ID else 'Not set'}")
print(f"PLAID_SECRET_KEY: {'Set' if settings.PLAID_SECRET_KEY else 'Not set'}")
print(f"PLAID_ENV: {settings.PLAID_ENV}")
```

### Check Logs

The endpoint logs detailed information:
- ✅ Success: `"Link token created successfully for user {user_id}"`
- ❌ Error: `"Plaid configuration error: {error}"` or `"Failed to create Plaid link token: {error}"`

---

## Frontend Integration

### Frontend Flow

1. **User clicks "Add Account"**
2. **Frontend calls**: `POST /api/v1/banking/link-token`
3. **Backend returns**: `{ "link_token": "link-sandbox-xxx" }`
4. **Frontend initializes Plaid Link** with the token
5. **User completes Plaid flow**
6. **Plaid returns**: `public_token`
7. **Frontend calls**: `POST /api/v1/banking/link` with `public_token`

### Frontend Code Example

```typescript
// Get link token
const response = await fetch('/api/v1/banking/link-token', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  }
});

const { link_token } = await response.json();

// Initialize Plaid Link
const { open, ready } = usePlaidLink({
  token: link_token,
  onSuccess: (public_token) => {
    // Call /api/v1/banking/link with public_token
  }
});
```

---

## Security Considerations

1. **Authentication Required**: Endpoint requires valid Bearer token
2. **User-Specific Tokens**: Link tokens are created per user
3. **Token Expiration**: Plaid link tokens expire after a set time (typically 4 hours)
4. **Environment Isolation**: Use sandbox credentials for development, production for live

---

## Next Steps

After implementing this endpoint:

1. ✅ **Test with Postman/curl** - Verify endpoint works
2. ✅ **Configure Plaid credentials** - Set environment variables
3. ✅ **Test frontend integration** - Verify frontend can get tokens
4. ✅ **Test full flow** - Link an account end-to-end

---

## Summary

✅ **Status**: Implemented and ready for testing

✅ **Endpoint**: `POST /api/v1/banking/link-token`

✅ **Requirements**:
- Plaid credentials configured
- `plaid-python` package installed
- User must have account record

✅ **Response**: `{ "link_token": "link-sandbox-xxx" }`

---

## Support

If you encounter issues:

1. Check backend logs for detailed error messages
2. Verify Plaid credentials are correct
3. Ensure `plaid-python` is installed
4. Test with Postman collection
5. Check Plaid Dashboard for API status

For Plaid-specific issues, refer to:
- Plaid Documentation: https://plaid.com/docs/
- Plaid Dashboard: https://dashboard.plaid.com/
