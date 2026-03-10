## Cursor Dashboard Backend Changes & Integration Guide

**Purpose**: This doc summarizes the backend work done for the Cursor dashboard / analytics integration and lists what the frontend can now rely on.  
**Base URL**: `/api/v1`  
**Auth**: All endpoints below require `Authorization: Bearer <token>` and return JSON (including on errors, with `{ "detail": "..." }`).

---

## 1. Analytics Endpoints (New / Confirmed)

- **GET `/analytics/portfolio`**
  - **Use for**: High‑level portfolio analytics on `/dashboard/analytics`.
  - **Query params**:
    - `time_range` – `1M | 3M | 6M | 1Y | ALL` (default `1Y`).
  - **Response (shape)**:
    - Totals: `total_invested`, `current_value`, `total_return`, `total_return_percentage`.
    - Aggregates: `asset_count`, `asset_allocation` (percent by type), `performance_by_period` (e.g. `{ "1M": 3.2, ... }`).

- **GET `/analytics/performance`**
  - **Use for**: Time‑series performance analytics and volatility widgets.
  - **Query params**:
    - `time_range` – same options as `/analytics/portfolio` (mapped to a day window internally).
  - **Response (shape)**:
    - Returns overall performance metrics for the selected window: `total_return`, `total_return_percentage`, `annualized_return`, `volatility`, `sharpe_ratio`, `max_drawdown`, plus `daily_returns` (array of `{ date, return }` in percent).

- **GET `/analytics/risk`**
  - **Use for**: Risk widgets on analytics page.
  - **Response (shape)**:
    - `volatility`, `concentration_risk`, `diversification_score`, `asset_type_count`, `total_assets`, plus some extra fields like `beta`, `value_at_risk`, `risk_level`.

**Frontend notes**
- These endpoints are **additive** and do not change existing portfolio APIs; use them specifically for analytics views.
- All three endpoints are stable and safe to integrate; unexpected errors will surface as JSON with `4xx/5xx` and a `detail` string.

---

## 2. Fixed Core Dashboard Endpoints

The following endpoints had known issues and are now fixed to match `FRONTEND_API_DOCUMENTATION.md` and always return JSON (no HTML error pages).

- **GET `/accounts/stats`**
  - **Status**: Fixed timezone bug (naive vs aware datetimes).
  - **Behavior**:
    - Returns account statistics per docs (`account_age_days`, `total_transactions`, `portfolio_value`, `kyc_status`, etc.).
    - No more 500s from datetime subtraction; missing account still returns a proper `404` JSON error.

- **GET `/payments/stats`**
  - **Status**: Implemented as a proper `GET` endpoint.
  - **Behavior**:
    - Returns `total_revenue`, `total_transactions`, `average_transaction_value`, and `payment_method_breakdown` as documented.

- **GET `/assets/summary`**
  - **Status**: Routing conflict fixed (registered **before** `/assets/{asset_id}`).
  - **Behavior**:
    - Returns an object with total asset counts/values and breakdown by type; safe to call without 422/UUID errors.

- **GET `/portfolio/history`**
  - **Status**: Hardened to **always** return JSON.
  - **Behavior**:
    - On success: array of `{ date, value, currency }` points.
    - On unexpected internal errors: returns an empty array `[]` instead of an HTML error page; missing account still gives a JSON `404`.

- **GET `/compliance/dashboard`**
  - **Status**: Enum mismatch and error‑handling fixed.
  - **Behavior**:
    - Correctly uses the DB enum values (no more `"PENDING"` vs `'pending'` issues).
    - On unexpected errors, returns a safe JSON payload with zeros rather than propagating raw SQL errors or HTML.

**Frontend notes**
- You can rely on these endpoints for dashboard widgets without defensive HTML parsing; treat non‑2xx as JSON errors.

---

## 3. Investment APIs (Performance, Analytics, Goals, Strategies, Watchlist)

All investment endpoints described in `FRONTEND_API_DOCUMENTATION.md` now exist and return JSON with stable shapes.

- **GET `/investment/performance`**
  - **Use for**: Investment‑specific performance charts.
  - **Query**: `days` and/or `time_range` (`1D, 1W, 1M, 3M, 6M, 1Y, ALL`).
  - **Response**: `total_return`, `total_return_percentage`, `period_days`, `current_value`, `historical_value`, `daily_returns`, `best_performer`, `worst_performer`, `asset_breakdown`.

- **GET `/investment/analytics`**
  - **Use for**: Deeper analytics (totals, annualized return, allocation).
  - **Query**: `time_range` (`1M, 3M, 6M, 1Y, ALL`).
  - **Response**: `total_invested`, `current_value`, `total_return`, `total_return_percentage`, `annualized_return`, `volatility`, `asset_allocation`, `performance_by_period`, etc.

- **GET `/investment/recommendations`**
  - **Use for**: Recommendation cards on investment views.
  - **Response**:
    - `data`: array of recommendation items (`id`, `type`, `symbol`, `name`, `reason`, `confidence`, `current_price`, `target_price`, `potential_return`, `risk_level`, `time_horizon`, `created_at`).
    - `portfolio_insights`: diversification / risk notes and suggested actions.

- **POST `/investment/goals/{goal_id}/adjust`**
  - **Use for**: Adjusting a goal from the UI (target amount, date, contribution, etc.).
  - **Current behavior**:
    - Returns a confirmation object: `{ id, message, updated_fields, updated_at }`.
    - Backend does **not** yet persist real goal entities; treat this as a **structure stub** suitable for UI flows and mock confirmations.

- **POST `/investment/strategies/{strategy_id}/backtest`**
  - **Use for**: Backtest modal results.
  - **Request**: `{ start_date, end_date, initial_capital, parameters? }`.
  - **Response**: Synthetic backtest result with `initial_capital`, `final_value`, `total_return`, `total_return_percentage`, `sharpe_ratio`, `max_drawdown`, `win_rate`, `trades_count`, `performance_metrics`.

- **GET `/investment/strategies/{strategy_id}/performance`**
  - **Use for**: Live strategy performance widget.
  - **Response**: `strategy_id`, `period` (start/end/days), nested `performance` block (returns, sharpe, drawdown, volatility, beta, alpha), `trades` block (`total`, `win_rate`), plus `current_value` and `initial_value`.

- **POST `/investment/strategies/{strategy_id}/clone`**
  - **Use for**: “Clone strategy” UX.
  - **Request**: `{ new_name, adjust_parameters? }`.
  - **Response**: `{ original_strategy_id, new_strategy_id, name, status, cloned_at, message }` (placeholder; no real strategy objects yet).

- **Investment Watchlist**
  - **GET `/investment/watchlist`**
    - Returns `{ data: [] }` today (no DB model yet); safe to integrate as an empty list.
  - **POST `/investment/watchlist`**
    - Accepts `{ symbol, asset_type, notes? }` and returns a watchlist item object with id, prices, and timestamps (stubbed).
  - **DELETE `/investment/watchlist/{id}`**
    - Returns `{ message: "Item removed from watchlist successfully", id }` (always succeeds for now).

**Frontend notes**
- Performance and analytics endpoints are fully usable.
- Goals/strategies/watchlist endpoints are **contract‑complete but mostly stubbed**; they’re suitable for FE flows and demos but do not yet drive real portfolio behavior.

---

## 4. Reports: Generate, List, Details, Download, Statistics

All reports endpoints referenced in the Cursor contract are wired and return JSON:

- **POST `/reports/generate`**
  - Accepts `{ report_type, date_range, filters, format }`.
  - Returns a job object with `id`, `status` (starts as `generating`), `report_type`, `format`, timestamps.

- **GET `/reports`**
  - Query: `type`, `status_filter`, `page`, `limit`.
  - Returns `{ data: [...], pagination: { page, limit, total, pages } }` where each entry includes id, type, status, format, start/end dates, created/generated timestamps, and `file_url`.

- **GET `/reports/{id}`**
  - Returns detailed job info including `filters` and `parameters` (the JSON payload backing the report).

- **GET `/reports/{id}/download`**
  - For now, returns a JSON payload:
    - If `format === json`: direct JSON body as an attachment.
    - For other formats (`pdf/csv/xlsx`), returns a JSON message plus data; true file generation is not yet implemented.

- **GET `/reports/statistics`**
  - Admin‑only (requires proper role/permission).
  - Returns aggregate counts for tasks/tickets/appraisals to power CRM‑style dashboards.

**Frontend notes**
- You can safely build list/detail/“generate report” flows on top of these.
- For actual file downloads, treat the current JSON as a placeholder; UI can show the raw JSON or a “coming soon” message.

---

## 5. Marketplace Watchlist – Remove Action

- **DELETE `/marketplace/watchlist/{watchlistItemId}`**
  - **Use for**: Removing a listing from the marketplace watchlist on `/dashboard/marketplace`.
  - **Path param**: `watchlistItemId` – this is the `id` returned by the marketplace watchlist APIs (UUID).
  - **Responses**:
    - `200 OK` with `{ "message": "Item removed from watchlist successfully" }` on success.
    - `404` JSON error if the item does not exist or is not owned by the current user.

**Frontend notes**
- This endpoint is ready to be wired into “Remove from watchlist” actions; no special handling beyond standard JSON error checks is required.

---

## 6. What the Frontend Needs to Do

- **Use the new analytics endpoints** for `/dashboard/analytics`:
  - `/analytics/portfolio`, `/analytics/performance`, `/analytics/risk` (see section 1).
- **Rely on fixed core endpoints** without extra HTML/error parsing:
  - `/accounts/stats`, `/assets/summary`, `/portfolio/history`, `/payments/stats`, `/compliance/dashboard`.
- **Align service functions**:
  - Ensure `investmentApi.js`, `analyticsApi.js`, `assetsApi.js`, `paymentsApi.js`, and `reportsApi.js` call the exact paths and query params described here and in `FRONTEND_API_DOCUMENTATION.md`.
- **Handle stubbed behavior gracefully**:
  - Treat some investment goal/strategy/watchlist and report download responses as placeholders (no real persistence yet); design UI text accordingly (“preview data”, “demo mode”, etc.).

