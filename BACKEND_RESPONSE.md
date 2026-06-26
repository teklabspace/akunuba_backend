# Backend Team → Frontend — Subscription & Plans Sync (Reply)

Replying point-by-point to `BACKEND_MESSAGE.md`. All endpoints below are live in
`app/api/v1/subscriptions.py`, `app/api/v1/payments.py`, and `app/api/v1/admin.py`.

---

## 1. Plan IDs & Prices — ✅ Confirmed, exact match

Backend uses the same fixed IDs and prices (`PLANS_CONFIG` in `subscriptions.py`):

| Plan ID     | Monthly | Annual | Custom |
|-------------|---------|--------|--------|
| `starter`   | 49.00   | 470.00 | no     |
| `pro`       | 299.00  | 2870.00| no     |
| `premium`   | 899.00  | 8630.00| no     |
| `concierge` | null    | null   | yes (`is_custom: true`) |

Note: we also accept legacy `plan_`-prefixed IDs (e.g. `plan_starter`) and normalize
them, so you won't break if an old ID leaks through during migration.

---

## 2. `GET /api/v1/subscriptions/plans` — ⚠️ Option A, but read this

We return **Option A**: `{ "plans": [ ... ] }`.

**Correction:** each plan object does **not** have a single `price` field. It exposes
**both** prices so you can render the monthly/annual toggle without a second call:

```json
{
  "plans": [
    {
      "id": "starter",
      "name": "Starter",
      "description": "Perfect for new or casual investors",
      "monthly_price": 49.00,
      "annual_price": 470.00,
      "currency": "USD",
      "features": ["Basic portfolio dashboard", "..."],
      "limits": { "max_accounts": 2, "max_assets": 10 },
      "popular": false,
      "is_custom": false
    }
  ]
}
```

For `concierge`, `monthly_price` and `annual_price` are `null` and `is_custom` is `true`.

➡️ **Action for frontend:** in `subscriptionsApi.js`, map `monthly_price` / `annual_price`
(pick by the selected billing cycle) instead of expecting a flat `price`.

---

## 3. `POST /api/v1/subscriptions` — ✅ Confirmed

- `billing_cycle` accepts **`"monthly"`** and **`"annual"`** (anything else → 400).
- Success returns **201** with this shape:

```json
{
  "subscription": {
    "id": "uuid", "plan_id": "pro", "plan_name": "Pro", "status": "active",
    "amount": 299.00, "currency": "USD", "billing_cycle": "monthly",
    "current_period_start": "...", "current_period_end": "...",
    "cancel_at_period_end": false, "canceled_at": null,
    "features": ["..."], "created_at": "..."
  },
  "payment_intent": {
    "id": "pi_...", "client_secret": "pi_..._secret_...",
    "status": "requires_action", "amount": 299.00, "currency": "USD"
  },
  "requires_action": true,
  "client_secret": "pi_..._secret_..."
}
```

- **Yes** — when Stripe needs 3DS/confirmation, `requires_action: true` and
  `client_secret` are surfaced **at the top level** (so you don't have to dig into
  `payment_intent`). `requires_action` is `true` whenever the intent status is not
  `succeeded`/`processing`.
- Admin/advisor accounts are rejected here with **403** (see #6).

---

## 4. `PUT /api/v1/subscriptions/upgrade` — ✅ Handles both

One endpoint handles **upgrades and downgrades** — there is no separate downgrade route.
Send `plan_id` and/or `billing_cycle` (at least one required). We compute a prorated
charge; if payment is required the response includes `payment_intent`,
`requires_action`, and top-level `client_secret`, same convention as #3.

---

## 5. `POST /api/v1/subscriptions/cancel` — ✅ Confirmed

No subscription ID needed — it cancels the subscription tied to the authenticated
user's token. Body is **optional**; if you send one you may include:
`{ "cancel_immediately": false, "cancellation_reason": "..." }`.
Default (`cancel_immediately: false`) marks it to lapse at period end and returns
`cancel_at_period_end: true`.

---

## 6. Admin & Advisor Roles — ✅ Confirmed, enforced

- `GET /api/v1/subscriptions` for an admin/advisor returns **200** (no 404) with:
  ```json
  { "subscription": null, "subscription_required": false,
    "message": "Your account does not require a subscription." }
  ```
- `POST /api/v1/subscriptions` by an admin/advisor is rejected with **403**:
  `"Your account does not require a subscription."`

---

## 7. `PATCH /api/v1/admin/subscriptions/{id}/plan` — ✅ Contract confirmed

The admin endpoint now mirrors the user-facing `PUT /subscriptions/upgrade` contract.
**Send `plan_id` (+ optional `billing_cycle`):**

```json
{ "plan_id": "pro", "billing_cycle": "monthly", "reason": "optional reason string" }
```

- `plan_id` ∈ `starter` | `pro` | `premium` | `concierge` (legacy `plan_`-prefixed IDs
  are normalized too).
- `billing_cycle` ∈ `monthly` | `annual`. **Optional** — if omitted we infer it from the
  subscription's current period (annual if the period is > 60 days), else default to
  `monthly`.
- `reason` is optional.

**Backward compatible:** the old single-field body still works —

```json
{ "plan": "monthly", "reason": "Customer request" }
```

`plan` accepts product IDs (`starter`/`pro`/`premium`/`concierge`) **and** legacy internal
values (`free`/`monthly`/`annual`). When `plan` is `"monthly"`/`"annual"` and no explicit
`billing_cycle` is given, it is also used as the billing cycle. Legacy mapping:
`free→starter`, `monthly→pro`, `annual→premium`.

**Any value that doesn't resolve to a known plan returns `400` (never `500`).** On success
the plan, price (`amount`), and a fresh billing period are all updated coherently, and a
cancelled/expired subscription is reactivated. Response `data`:

```json
{
  "id": "uuid", "account_id": "uuid",
  "old_plan": "starter", "new_plan": "pro", "plan_id": "pro",
  "billing_cycle": "monthly", "internal_plan": "monthly",
  "amount": 299.00, "currency": "USD", "status": "active",
  "current_period_end": "..."
}
```

➡️ **Action for frontend:** update the admin dropdown (`PLAN_OPTIONS`) to send `plan_id`
∈ `starter`/`pro`/`premium`/`concierge` (with an optional `billing_cycle`). The current
`{ "plan": "monthly" }` payload keeps working, so this change is non-breaking and can be
done independently.

---

## 8. Payment Methods — Stripe, collect `paymentMethodId` on the frontend first

Yes, we use **Stripe**. Flow:

1. Frontend collects card via Stripe.js / Elements and produces a `payment_method_id`
   (e.g. `pm_...`).
2. **Add:** `POST /api/v1/payments/payment-methods`
   ```json
   { "payment_method_id": "pm_...", "is_default": true }
   ```
   Returns the saved method `{ id, type, card: { brand, last4, ... }, is_default }`.
3. **List:** `GET /api/v1/payments/payment-methods` → `{ "data": [ ... ] }`.
4. **Delete:** `DELETE /api/v1/payments/payment-methods/{method_id}`.

We never receive raw card data — only the Stripe `payment_method_id`.

---

### Summary of frontend action items
- **#2:** update `subscriptionsApi.js` to read `monthly_price` / `annual_price` (no flat
  `price` field); handle `is_custom`/`null` pricing for `concierge`.
- **#8:** wire Stripe.js to produce `payment_method_id` before calling the add endpoint.

Everything else is confirmed as-is.
