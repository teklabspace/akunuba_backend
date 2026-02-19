# Backend APIs Not Implemented / Need Implementation

**Document Purpose**: List of APIs that are defined in the frontend configuration but are either:
- Not implemented on the backend
- Returning errors (405, 400, 500, etc.)
- Need backend fixes
- Marked as "structure only" in frontend code

**Target Audience**: Backend Development Team  
**Last Updated**: Based on comprehensive frontend codebase analysis

---

## 🔴 CRITICAL - APIs Returning Errors (Need Immediate Fix)

### 1. `GET /api/v1/accounts/stats`
- **Status**: ❌ **500 Internal Server Error**
- **Error**: `TypeError: can't subtract offset-naive and offset-aware datetimes`
- **Location**: `app/api/v1/accounts.py`, line 551
- **Issue**: `datetime.utcnow()` returns naive datetime, but `account.created_at` is timezone-aware
- **Fix Required**:
  ```python
  # Change from:
  account_age_days = (datetime.utcnow() - account.created_at).days
  
  # To:
  from datetime import datetime, timezone
  now = datetime.now(timezone.utc)
  account_age_days = (now - account.created_at).days
  ```
- **Frontend Usage**: Used in `src/app/dashboard/page.js`
- **Priority**: 🔥 **HIGH** - Dashboard depends on this

---

### 2. `GET /api/v1/payments/stats`
- **Status**: ❌ **405 Method Not Allowed**
- **Error**: HTTP 405 Method Not Allowed
- **Issue**: Endpoint not implemented or misconfigured
- **Fix Required**:
  - Implement `@router.get("/stats")` handler in `app/api/v1/payments.py`
  - Or remove from API contract if not needed
- **Frontend Usage**: Defined in `src/utils/paymentsApi.js` → `getPaymentStats()`
- **Priority**: 🔥 **HIGH** - Frontend expects this endpoint

---

### 3. `GET /api/v1/assets/summary`
- **Status**: ❌ **422 Unprocessable Entity**
- **Error**: `path.asset_id: Input should be a valid UUID, invalid character: expected an optional prefix of 'urn:uuid:' followed by [0-9a-fA-F-], found 's' at 1`
- **Issue**: Route conflict - `/assets/{asset_id}` is matching `/assets/summary` before the summary route
- **Fix Required**:
  - Register `/assets/summary` route **before** `/assets/{asset_id}` route
  - Example:
    ```python
    @router.get("/assets/summary")  # Must be first
    async def get_assets_summary():
        ...
    
    @router.get("/assets/{asset_id}")  # Must be after
    async def get_asset(asset_id: UUID):
        ...
    ```
- **Frontend Usage**: Defined in `src/utils/assetsApi.js` → `getAssetsSummary()`
- **Priority**: 🔥 **HIGH** - Route ordering issue

---

### 4. `GET /api/v1/portfolio/history`
- **Status**: ❌ **Returns HTML Error Page Instead of JSON**
- **Error**: Frontend receives HTML error page instead of JSON response
- **Issue**: Backend returns HTML error page on unhandled exceptions
- **Fix Required**:
  - Ensure endpoint always returns JSON (even on errors)
  - Use FastAPI `HTTPException` for error responses
  - Add proper error handling to return structured JSON errors
  - Validate `days` query parameter correctly
- **Frontend Usage**: Used in `src/app/dashboard/page.js` for historical performance graph
- **Priority**: 🔥 **HIGH** - Dashboard chart depends on this

---

### 5. `GET /api/v1/compliance/dashboard`
- **Status**: ❌ **500 Internal Server Error / 503 Service Unavailable**
- **Error 1**: `asyncpg.exceptions.InvalidTextRepresentationError: invalid input value for enum auditstatus: "PENDING"`
- **Error 2**: 503 Service Unavailable (backend not reachable)
- **Issue 1**: Enum mismatch - Database enum uses lowercase (`'pending'`) but query sends uppercase (`"PENDING"`)
- **Issue 2**: Backend server connectivity issues
- **Fix Required**:
  1. **Fix enum value handling**:
     - Normalize status strings to match DB enum (use lowercase `'pending'` instead of `'PENDING'`)
     - Or update enum definition to include uppercase values
  2. **Improve error handling**:
     - Catch DB exceptions and return JSON error (not raw stack trace)
  3. **Ensure backend availability**:
     - Confirm backend runs consistently on `http://localhost:8000`
- **Frontend Usage**: Used in `src/app/dashboard/compliance/page.js`
- **Priority**: 🔥 **HIGH** - Compliance dashboard depends on this

---

## 🟡 HIGH PRIORITY - APIs Not Implemented (Frontend Expects These)

### 6. Investment Management - Extra APIs

These APIs are defined in `src/config/api.js` (lines 157-167) and marked as "Structure only - not integrated" in the frontend, but the frontend service functions exist and may be called.

#### 6.1 `GET /api/v1/investment/performance`
- **Status**: ⚠️ **Not Verified** - May not be implemented
- **Endpoint**: `GET /api/v1/investment/performance`
- **Frontend Function**: `getInvestmentPerformance()` in `src/utils/investmentApi.js` (line 440)
- **Purpose**: Get performance metrics for investments
- **Priority**: 🟡 **MEDIUM** - Frontend has service function ready

#### 6.2 `GET /api/v1/investment/analytics`
- **Status**: ⚠️ **Not Verified** - May not be implemented
- **Endpoint**: `GET /api/v1/investment/analytics`
- **Frontend Function**: `getInvestmentAnalytics()` in `src/utils/investmentApi.js` (line 460)
- **Purpose**: Get detailed analytics for investments
- **Priority**: 🟡 **MEDIUM** - Frontend has service function ready

#### 6.3 `GET /api/v1/investment/recommendations`
- **Status**: ⚠️ **Not Verified** - May not be implemented
- **Endpoint**: `GET /api/v1/investment/recommendations`
- **Frontend Function**: `getInvestmentRecommendations()` in `src/utils/investmentApi.js` (line 480)
- **Purpose**: Get personalized investment recommendations
- **Priority**: 🟡 **MEDIUM** - Frontend has service function ready

#### 6.4 `POST /api/v1/investment/goals/{goal_id}/adjust`
- **Status**: ❌ **Not Implemented** - No frontend service function exists
- **Endpoint**: `POST /api/v1/investment/goals/{goal_id}/adjust`
- **Frontend Function**: ❌ Not implemented in `src/utils/investmentApi.js`
- **Purpose**: Adjust investment goal parameters
- **Priority**: 🟡 **MEDIUM** - Defined in API config but no implementation

#### 6.5 `POST /api/v1/investment/strategies/{strategy_id}/backtest`
- **Status**: ❌ **Not Implemented** - No frontend service function exists
- **Endpoint**: `POST /api/v1/investment/strategies/{strategy_id}/backtest`
- **Frontend Function**: ❌ Not implemented in `src/utils/investmentApi.js`
- **Purpose**: Backtest investment strategies
- **Priority**: 🟡 **MEDIUM** - Defined in API config but no implementation

#### 6.6 `GET /api/v1/investment/strategies/{strategy_id}/performance`
- **Status**: ❌ **Not Implemented** - No frontend service function exists
- **Endpoint**: `GET /api/v1/investment/strategies/{strategy_id}/performance`
- **Frontend Function**: ❌ Not implemented in `src/utils/investmentApi.js`
- **Purpose**: Get performance metrics for a strategy
- **Priority**: 🟡 **MEDIUM** - Defined in API config but no implementation

#### 6.7 `POST /api/v1/investment/strategies/{strategy_id}/clone`
- **Status**: ❌ **Not Implemented** - No frontend service function exists
- **Endpoint**: `POST /api/v1/investment/strategies/{strategy_id}/clone`
- **Frontend Function**: ❌ Not implemented in `src/utils/investmentApi.js`
- **Purpose**: Clone an existing strategy
- **Priority**: 🟡 **MEDIUM** - Defined in API config but no implementation

#### 6.8 Investment Watchlist APIs
- **Status**: ❌ **Not Implemented** - No frontend service functions exist
- **Endpoints**:
  - `GET /api/v1/investment/watchlist`
  - `POST /api/v1/investment/watchlist`
  - `DELETE /api/v1/investment/watchlist/{id}`
- **Frontend Functions**: ❌ Not implemented in `src/utils/investmentApi.js`
- **Purpose**: Manage watchlist for investment opportunities/strategies
- **Note**: Separate from Marketplace watchlist (which is implemented)
- **Priority**: 🟡 **MEDIUM** - Defined in API config but no implementation

---

## 🟢 MEDIUM PRIORITY - APIs That May Need Verification

### 7. Analytics APIs

These APIs have frontend service functions but may not be fully implemented on the backend.

#### 7.1 `GET /api/v1/analytics/portfolio`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `GET /api/v1/analytics/portfolio`
- **Frontend Function**: `getPortfolioAnalytics()` in `src/utils/analyticsApi.js`
- **Frontend Usage**: ❌ Not used in UI (Analytics page uses hardcoded data)
- **Priority**: 🟢 **LOW** - Not currently used but may be needed

#### 7.2 `GET /api/v1/analytics/performance`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `GET /api/v1/analytics/performance`
- **Frontend Function**: `getPerformanceAnalytics()` in `src/utils/analyticsApi.js`
- **Frontend Usage**: ❌ Not used in UI (Analytics page uses hardcoded data)
- **Priority**: 🟢 **LOW** - Not currently used but may be needed

#### 7.3 `GET /api/v1/analytics/risk`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `GET /api/v1/analytics/risk`
- **Frontend Function**: `getRiskAnalytics()` in `src/utils/analyticsApi.js`
- **Frontend Usage**: ❌ Not used in UI (Analytics page uses hardcoded data)
- **Priority**: 🟢 **LOW** - Not currently used but may be needed

---

### 8. Portfolio APIs - Need Verification

#### 8.1 `GET /api/v1/portfolio/risk`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `GET /api/v1/portfolio/risk`
- **Frontend Function**: `getPortfolioRisk()` in `src/utils/portfolioApi.js`
- **Frontend Usage**: ⚠️ Not found in UI pages (may not be used)
- **Priority**: 🟢 **LOW** - Verify if implemented and working

#### 8.2 `GET /api/v1/portfolio/benchmark`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `GET /api/v1/portfolio/benchmark`
- **Frontend Function**: `getPortfolioBenchmark()` in `src/utils/portfolioApi.js`
- **Frontend Usage**: ⚠️ Not found in UI pages (may not be used)
- **Priority**: 🟢 **LOW** - Verify if implemented and working

---

### 9. Reports APIs - Need Verification

#### 9.1 `POST /api/v1/reports/generate`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `POST /api/v1/reports/generate`
- **Frontend Function**: `generateReport()` in `src/utils/reportsApi.js`
- **Frontend Usage**: ⚠️ Need to verify if used in reports pages
- **Priority**: 🟢 **LOW** - Verify implementation

#### 9.2 `GET /api/v1/reports`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `GET /api/v1/reports`
- **Frontend Function**: `listReports()` in `src/utils/reportsApi.js`
- **Frontend Usage**: ⚠️ Need to verify if used in reports pages
- **Priority**: 🟢 **LOW** - Verify implementation

#### 9.3 `GET /api/v1/reports/{id}`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `GET /api/v1/reports/{id}`
- **Frontend Function**: `getReport()` in `src/utils/reportsApi.js`
- **Frontend Usage**: ⚠️ Need to verify if used in reports pages
- **Priority**: 🟢 **LOW** - Verify implementation

#### 9.4 `GET /api/v1/reports/{id}/download`
- **Status**: ⚠️ **Needs Verification**
- **Endpoint**: `GET /api/v1/reports/{id}/download`
- **Frontend Function**: `downloadReport()` in `src/utils/reportsApi.js`
- **Frontend Usage**: ⚠️ Need to verify if used in reports pages
- **Priority**: 🟢 **LOW** - Verify implementation

---

## 📋 Summary Table

| Priority | Count | Status |
|----------|-------|--------|
| 🔴 **CRITICAL** (Returning Errors) | 5 | Need immediate fix |
| 🟡 **HIGH** (Not Implemented) | 8 | Need implementation |
| 🟢 **MEDIUM** (Needs Verification) | 9 | Verify implementation |

**Total APIs Requiring Attention**: 22

---

## 🎯 Recommended Implementation Order

### Phase 1: Critical Fixes (This Week)
1. ✅ Fix `GET /api/v1/accounts/stats` - 500 error (datetime issue)
2. ✅ Fix `GET /api/v1/assets/summary` - 422 error (route conflict)
3. ✅ Fix `GET /api/v1/portfolio/history` - HTML error page
4. ✅ Fix `GET /api/v1/compliance/dashboard` - 500 error (enum mismatch)

### Phase 2: Missing Endpoints (This Month)
5. ✅ Implement `GET /api/v1/payments/stats` - 405 error
6. ✅ Verify and implement Investment Performance API
7. ✅ Verify and implement Investment Analytics API
8. ✅ Verify and implement Investment Recommendations API

### Phase 3: Additional Features (Next Month)
9. ✅ Implement Investment Goal Adjust API
10. ✅ Implement Strategy Backtest API
11. ✅ Implement Strategy Performance API
12. ✅ Implement Clone Strategy API
13. ✅ Implement Investment Watchlist APIs (3 endpoints)

### Phase 4: Verification (Ongoing)
14. ✅ Verify Analytics APIs (3 endpoints)
15. ✅ Verify Portfolio Risk & Benchmark APIs (2 endpoints)
16. ✅ Verify Reports APIs (4 endpoints)

---

## 📝 Implementation Notes

### Error Response Format
All APIs should return JSON errors, not HTML:
```python
from fastapi import HTTPException

# Good - Returns JSON
raise HTTPException(status_code=400, detail="Invalid input")

# Bad - Returns HTML (current issue with /portfolio/history)
# Unhandled exceptions that return HTML error pages
```

### Route Ordering
When defining routes, specific routes must come before parameterized routes:
```python
# Correct order:
@router.get("/assets/summary")  # Specific route first
async def get_assets_summary():
    ...

@router.get("/assets/{asset_id}")  # Parameterized route after
async def get_asset(asset_id: UUID):
    ...
```

### Enum Handling
Ensure enum values match database definitions:
```python
# Check database enum definition
# Use exact case as defined in database
status = "pending"  # Not "PENDING" if DB uses lowercase
```

### Timezone Handling
Always use timezone-aware datetimes:
```python
from datetime import datetime, timezone

# Good
now = datetime.now(timezone.utc)

# Bad (causes 500 error)
now = datetime.utcnow()  # Naive datetime
```

---

## 🔗 Related Documentation

- **Frontend API Config**: `src/config/api.js`
- **Backend API Issues**: `doc/BACKEND_API_ISSUES.md`
- **Frontend Integration Status**: `doc/FEATURE_API_INTEGRATION_STATUS.md`
- **API Documentation**: `doc/FRONTEND_API_DOCUMENTATION.md`

---

## 📞 Contact

For questions about frontend expectations or API contracts, refer to:
- Frontend API configuration in `src/config/api.js`
- Service function implementations in `src/utils/*Api.js`
- Frontend usage in `src/app/dashboard/**/*.js`

---

**Last Updated**: Based on comprehensive frontend codebase analysis  
**Next Review**: After backend fixes are implemented
