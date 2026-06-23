## Backend API Contract & Requirements (Cursor Dashboard Integration)

**Purpose**: This document is for the backend team. It lists the API endpoints the frontend expects in order to fully integrate the dashboard and related pages, with notes on status, required request/response structure, and priorities.  
**Base URL**: `/api/v1`  
**Auth**: All endpoints (except auth) must require `Authorization: Bearer <token>`.  
**Reference**: Field‑level schemas for many endpoints are already defined in `doc/FRONTEND_API_DOCUMENTATION.md`. This doc focuses on **what must exist and behave correctly** for full integration.

---

## 1. Conventions & Error Handling

- **Transport**
  - JSON request/response.
  - Use ISO‑8601 timestamps (e.g. `2024-01-01T00:00:00Z`).
  - Monetary values as decimals (e.g. `150000.00`).
- **Standard error shape**
  - On all non‑2xx responses, return JSON (never HTML):
    ```json
    {
      "detail": "Human readable error message"
    }
    ```
  - Use proper HTTP status codes: `400, 401, 403, 404, 422, 500`.

---

## 2. Endpoints to Implement (New / Structure‑Only)

These endpoints are defined/used in the frontend, but are either missing on the backend or only exist as “structure only”.

### 2.1 Analytics Page – Portfolio / Performance / Risk

Used by `/dashboard/analytics` and analytics sections.

- **GET `/analytics/portfolio`**
  - **Purpose**: High‑level portfolio analytics (totals, returns, allocation).
  - **Query params** (optional):
    - `time_range`: `1M | 3M | 6M | 1Y | ALL` (default `1Y`).
  - **Suggested response** (can mirror `GET /investment/analytics`):
    ```json
    {
      "total_invested": 140000.0,
      "current_value": 150000.0,
      "total_return": 10000.0,
      "total_return_percentage": 7.14,
      "annualized_return": 8.5,
      "sharpe_ratio": 1.2,
      "volatility": 12.5,
      "beta": 0.95,
      "alpha": 2.3,
      "max_drawdown": -5.2,
      "asset_allocation": {
        "stocks": 66.67,
        "bonds": 20.0,
        "crypto": 10.0,
        "other": 3.33
      },
      "sector_allocation": {
        "technology": 35.0,
        "healthcare": 20.0
      }
    }
    ```

- **GET `/analytics/performance`**
  - **Purpose**: Time‑series performance analytics for charts.
  - **Query params** (optional):
    - `days`: integer, 1–365 (default 30).
  - **Suggested response** (can mirror `GET /portfolio/performance` + history):
    ```json
    {
      "period_days": 30,
      "current_value": 145000.0,
      "historical_value": 140000.0,
      "total_return": 5000.0,
      "total_return_percentage": 3.57,
      "daily_values": [
        { "date": "2024-01-01", "value": 140000.0 }
      ],
      "best_performer": {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "return_percentage": 5.2,
        "value": 50000.0
      },
      "worst_performer": {
        "symbol": "TSLA",
        "name": "Tesla Inc.",
        "return_percentage": -2.1,
        "value": 20000.0
      }
    }
    ```

- **GET `/analytics/risk`**
  - **Purpose**: Risk metrics for risk widgets on analytics page.
  - **Suggested response** (can mirror `GET /portfolio/risk`):
    ```json
    {
      "volatility": 2.5,
      "concentration_risk": 35.5,
      "diversification_score": 75.0,
      "asset_type_count": 4,
      "total_assets": 15
    }
    ```

### 2.2 Investment Management – Extra APIs

Front‑end service: `src/utils/investmentApi.js`  
Used across investment overview, goals, and strategies flows.

> Note: `GET /investment/performance`, `GET /investment/analytics`, and `GET /investment/recommendations` are already documented in `FRONTEND_API_DOCUMENTATION.md`. Backend must implement them to match that spec.

- **GET `/investment/performance`**
  - **Status**: Must conform to spec in `FRONTEND_API_DOCUMENTATION.md` (section “Investment APIs – Get Investment Performance”).

- **GET `/investment/analytics`**
  - **Status**: Must conform to spec in `FRONTEND_API_DOCUMENTATION.md` (“Get Investment Analytics”).

- **GET `/investment/recommendations`**
  - **Status**: Must conform to spec in `FRONTEND_API_DOCUMENTATION.md` (“Get Investment Recommendations”).

- **POST `/investment/goals/{goal_id}/adjust`**
  - **Purpose**: Adjust an existing investment goal.
  - **Path params**:
    - `goal_id`: UUID of the goal.
  - **Request body** (example):
    ```json
    {
      "target_amount": 200000.0,
      "monthly_contribution": 1500.0,
      "target_date": "2030-12-31",
      "risk_level": "moderate"
    }
    ```
  - **Response** (200): Updated goal object consistent with existing goal schema (same fields as other goal CRUD endpoints: id, name, target_amount, current_amount, progress, target_date, risk_level, created_at, updated_at).

- **POST `/investment/strategies/{strategy_id}/backtest`**
  - **Purpose**: Run a backtest for a saved strategy.
  - **Path params**:
    - `strategy_id`: UUID.
  - **Request body** (example):
    ```json
    {
      "start_date": "2020-01-01",
      "end_date": "2024-01-01",
      "initial_capital": 10000.0,
      "benchmark": "SPY"
    }
    ```
  - **Response** (200) – example shape:
    ```json
    {
      "strategy_id": "uuid",
      "start_date": "2020-01-01",
      "end_date": "2024-01-01",
      "initial_capital": 10000.0,
      "ending_value": 14500.0,
      "total_return_percentage": 45.0,
      "max_drawdown": -12.5,
      "sharpe_ratio": 1.1,
      "equity_curve": [
        { "date": "2020-01-01", "value": 10000.0 }
      ],
      "benchmark_curve": [
        { "date": "2020-01-01", "value": 10000.0 }
      ]
    }
    ```

- **GET `/investment/strategies/{strategy_id}/performance`**
  - **Purpose**: Current live performance of a strategy.
  - **Response** (200) – example shape:
    ```json
    {
      "strategy_id": "uuid",
      "since_inception_return_percentage": 18.5,
      "ytd_return_percentage": 6.2,
      "volatility": 10.5,
      "max_drawdown": -8.3,
      "trades_count": 120,
      "win_rate": 63.0
    }
    ```

- **POST `/investment/strategies/{strategy_id}/clone`**
  - **Purpose**: Clone an existing strategy into a new one (for the same user).
  - **Request body** (optional):
    ```json
    {
      "name_override": "My Strategy Copy 1"
    }
    ```
  - **Response** (201): Newly created strategy object, same schema as existing strategies (id, name, description, parameters, owner_id, created_at, etc.).

- **Investment Watchlist**
  - **GET `/investment/watchlist`**
    - **Purpose**: List watched investment opportunities/strategies.
    - **Response** (200):
      ```json
      {
        "data": [
          {
            "id": "uuid",
            "item_type": "strategy",
            "item_id": "uuid",
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "added_at": "2024-01-01T00:00:00Z",
            "notes": "Long term core position"
          }
        ]
      }
      ```
  - **POST `/investment/watchlist`**
    - **Purpose**: Add a new item to the investment watchlist.
    - **Request body**:
      ```json
      {
        "item_type": "strategy",           // or "asset"
        "item_id": "uuid",
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "notes": "optional notes"
      }
      ```
    - **Response** (201): Created watchlist entry (same fields as in GET).
  - **DELETE `/investment/watchlist/{id}`**
    - **Purpose**: Remove an item from watchlist.
    - **Response** (204) with empty body, or (200) with `{ "message": "Removed" }`.

### 2.3 Reports – Listing, Details, Download

Service: `src/utils/reportsApi.js`.  
Some functions exist; backend must provide these endpoints so the reports UI can be implemented.

- **POST `/reports/generate`**
  - **Spec**: Already partially defined in `FRONTEND_API_DOCUMENTATION.md` (“Generate Report”). Backend should implement according to that contract (report_type, date_range, filters, format; return a report job object).

- **GET `/reports`**
  - **Purpose**: List generated reports for current user/account.
  - **Query params** (optional):
    - `status`: `generating | ready | failed | all` (default `all`).
    - `page`, `limit` for pagination.
  - **Response** (200):
    ```json
    {
      "data": [
        {
          "id": "uuid",
          "report_type": "portfolio",
          "format": "pdf",
          "status": "ready",
          "created_at": "2024-01-01T00:00:00Z",
          "generated_at": "2024-01-01T00:05:00Z",
          "download_url": "/api/v1/reports/uuid/download"
        }
      ],
      "page": 1,
      "limit": 20,
      "total": 5
    }
    ```

- **GET `/reports/{id}`**
  - **Purpose**: Get details of a single report job.
  - **Response** (200): Same object as a single entry from `/reports` list.

- **GET `/reports/{id}/download`**
  - **Purpose**: Download generated report.
  - **Response**:
    - For PDF: `Content-Type: application/pdf` with binary body.
    - For CSV: `Content-Type: text/csv`.
    - On error: JSON error as described in section 1 (not HTML).

- **GET `/reports/statistics`**
  - **Spec**: Already documented in `FRONTEND_API_DOCUMENTATION.md` (“Get Report Statistics”). Backend must implement as documented.

---

## 3. Endpoints to Fix / Make Compatible

These endpoints already exist but currently return errors or unexpected formats. Frontend is coded against the documented contract and expects them to behave accordingly.

### 3.1 `GET /accounts/stats`

- **Current issue**: 500 error due to naive vs timezone‑aware datetime subtraction.  
- **Expected behavior**:
  - Implement exactly as documented in `FRONTEND_API_DOCUMENTATION.md` (“Get Account Stats”).
  - Use timezone‑aware datetime math:
    ```python
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    account_age_days = (now - account.created_at).days
    ```

### 3.2 `GET /payments/stats`

- **Current issue**: 405 Method Not Allowed.  
- **Expected behavior**:
  - Implement `GET /payments/stats` according to `FRONTEND_API_DOCUMENTATION.md` (“Get Payment Stats”).
  - Return totals, counts, and method breakdown as documented.

### 3.3 `GET /assets/summary`

- **Current issue**: 422 error because `/assets/{asset_id}` route is matching `/assets/summary` first.  
- **Expected behavior**:
  - Ensure a concrete route for `/assets/summary` is defined and registered **before** `/assets/{asset_id}`.
  - Response shape must match `FRONTEND_API_DOCUMENTATION.md` (“Get Assets Summary”).

### 3.4 `GET /portfolio/history`

- **Current issue**: Returns an HTML error page instead of JSON when failing.  
- **Expected behavior**:
  - Always return JSON, even on errors (use `HTTPException` or JSON error handler).
  - Success response is already documented in `FRONTEND_API_DOCUMENTATION.md` (“Get Portfolio History”).

### 3.5 `GET /compliance/dashboard`

- **Current issues**:
  - 500 error due to enum mismatch (`"PENDING"` vs enum `auditstatus` values like `'pending'`).
  - 503 errors when backend at `http://localhost:8000` is unreachable.
- **Expected behavior**:
  - Normalize enum values to match DB (e.g. always store/query lowercase).
  - Ensure backend availability and return JSON errors (no raw stack traces/HTML).

### 3.6 Dashboard‑Related “Available but Not Used Yet” Endpoints

These endpoints are already documented and partially implemented; backend must keep their contracts stable so the dashboard can start using them:

- Portfolio:
  - `GET /portfolio/summary`
  - `GET /portfolio/performance`
  - `GET /portfolio/allocation`
  - `GET /portfolio/holdings/top`
  - `GET /portfolio/activity/recent`
  - `GET /portfolio/market-summary`
  - `GET /portfolio/alerts`
  - `GET /portfolio/risk`
  - `GET /portfolio/benchmark`
- Accounts & banking:
  - `GET /accounts/me`
  - `GET /accounts`
  - `GET /accounts/stats`
  - `GET /banking/accounts`
- Payments:
  - `GET /payments/history`
  - `GET /payments/stats`
- Assets:
  - `GET /assets/summary`
  - `GET /assets/value-trends`
- Notifications:
  - `GET /users/notifications` and/or `GET /notifications`

For these endpoints, the **authoritative field‑level schema** is the one in `doc/FRONTEND_API_DOCUMENTATION.md`. Backend should treat that as the contract.

---

## 4. Marketplace Watchlist – Remove Action

Used on `/dashboard/marketplace` when removing an item from a user’s marketplace watchlist.

- **DELETE `/marketplace/watchlist/{watchlistItemId}`**
  - **Purpose**: Remove a listing from the user’s marketplace watchlist.
  - **Path params**:
    - `watchlistItemId`: UUID or unique identifier of the watchlist record (must match what is returned from the “add/watchlist/list” endpoints).
  - **Response**:
    - On success: `204 No Content` (preferred) or `200 OK` with:
      ```json
      { "message": "Removed from watchlist" }
      ```
    - On invalid id: `404` with JSON error.

---

## 5. Priority Summary for Backend

- **Highest priority**
  - Implement: `/analytics/portfolio`, `/analytics/performance`, `/analytics/risk`.
  - Fix: `/accounts/stats`, `/assets/summary`, `/portfolio/history`, `/compliance/dashboard`, `/payments/stats`.
- **High priority**
  - Implement investment extras: goals adjust, strategy backtest, strategy performance, clone, investment watchlist.
  - Ensure `GET /investment/performance`, `/investment/analytics`, `/investment/recommendations` follow the documented contract.
- **Medium priority**
  - Implement full reports flow: `/reports` list, `/reports/{id}`, `/reports/{id}/download`, verify `/reports/generate` + `/reports/statistics`.
  - Keep all documented portfolio/accounts/assets/payments endpoints stable so the dashboard can progressively adopt them.

Once these endpoints are implemented/fixed to match this contract and `FRONTEND_API_DOCUMENTATION.md`, the Cursor frontend can fully integrate dashboard, analytics, investment, marketplace watchlist, and reports features without further backend changes.

