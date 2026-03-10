# Backend Implementation Report — Real Scan

Generated from a full codebase scan. For each API module: route existence, implementation file, business logic depth, external integrations, TODOs, database models, background jobs, and tests.

---

## Summary

| Module        | Status              | Routes | Models | External Integrations     | Background Jobs | Tests |
|---------------|---------------------|--------|--------|---------------------------|-----------------|-------|
| Auth          | Fully implemented   | Yes    | Yes    | Supabase Auth, Email      | No              | No    |
| Users         | Fully implemented   | Yes    | Yes    | —                         | No              | No    |
| KYC           | Fully implemented   | Yes    | Yes    | Persona, Supabase         | No              | No    |
| KYB           | Fully implemented   | Yes    | Yes    | Persona, Supabase         | No              | No    |
| Accounts      | Partially implemented | Yes  | Yes    | Alpaca                    | No              | No    |
| Banking       | Fully implemented   | Yes    | Yes    | Plaid                     | No              | No    |
| Assets        | Fully implemented   | Yes    | Yes    | Supabase Storage          | No              | No    |
| Portfolio     | Fully implemented   | Yes    | Yes    | Polygon, Alpaca, Plaid    | Yes (recalc)    | No    |
| Investment    | Fully implemented   | Yes    | Yes    | Alpaca, Polygon            | No              | No    |
| Market        | Fully implemented   | Yes    | No     | Polygon                   | No              | No    |
| Trading       | Fully implemented   | Yes    | Yes    | Alpaca                    | No              | No    |
| Payments      | Fully implemented   | Yes    | Yes    | Stripe                    | No              | No    |
| Subscriptions | Partially implemented | Yes  | Yes    | Stripe                    | Yes (renewals)  | No    |
| Marketplace   | Fully implemented   | Yes    | Yes    | Stripe                    | Yes (expire)    | No    |
| Documents     | Fully implemented   | Yes    | Yes    | Supabase Storage          | No              | No    |
| Files         | Fully implemented   | Yes    | No     | Supabase Storage          | No              | No    |
| Support       | Fully implemented   | Yes    | Yes    | Supabase, SLA service     | Yes (SLA)       | No    |
| Chat          | Partially implemented | Yes  | No (Sendbird) | Sendbird              | No              | No    |
| Chat (conv.)  | Fully implemented   | Yes    | Yes    | Redis (WebSocket)         | No              | No    |
| Notifications | Fully implemented   | Yes    | Yes    | —                         | No              | No    |
| Tasks         | Fully implemented   | Yes    | Yes    | —                         | No              | No    |
| Reminders     | Fully implemented   | Yes    | Yes    | —                         | No              | No    |
| Referrals     | Fully implemented   | Yes    | Yes    | —                         | No              | No    |
| Reports       | Fully implemented   | Yes    | Yes    | —                         | No              | No    |
| Analytics     | Partially implemented | Yes  | No     | PostHog                   | No              | No    |
| Concierge     | Fully implemented   | Yes    | Yes    | Supabase                  | No              | No    |
| CRM           | Fully implemented   | Yes    | Yes    | —                         | No              | No    |
| Entities      | Fully implemented   | Yes    | Yes    | Supabase                  | No              | No    |
| Compliance    | Fully implemented   | Yes    | Yes    | Supabase                  | No              | No    |
| Admin         | Fully implemented   | Yes    | Yes    | Stripe, NotificationService | No            | No    |

**Tests:** No API/module tests found. Only root-level scripts: `test_storage_connection.py`, `test_db_connection.py`, `test_supabase.py`.

**Background jobs** (in `app/core/scheduler.py`): `expire_offers`, `recalculate_portfolios`, `process_subscription_renewals`, `expire_listings`, `monitor_sla_breaches`.

**TODO/FIXME in app code:**  
`assets.py` (report generation async), `payments.py` (default payment method, default deletion check), `accounts.py` (joint invite email), `subscriptions.py` (`cancel_at_period_end` field).

---

## 1. Auth

**Status:** Fully implemented  
**Routes:** Yes — in code  
**File:** `app/api/v1/auth_new.py`  

**Routes:**  
`POST /register`, `POST /login`, `POST /refresh`, `POST /request-otp`, `POST /verify-otp`, `POST /request-password-reset`, `POST /reset-password`, `POST /verify-email`, `POST /resend-verification`

**Services:**  
- `app.core.security`: tokens, password hash, OTP, verification/reset tokens  
- `app.services.email_service`: verification, OTP, password reset emails  

**Database models:**  
`User`, `Account`, `KYCVerification` (for verification status)

**External integrations:**  
- Supabase Auth (admin create_user on register)  
- EmailService (SendGrid or similar via `email_service`)

**Missing pieces:**  
None critical. Optional: 2FA libraries (pyotp, qrcode) optional; login works with or without.

**Files:**  
`app/api/v1/auth_new.py`, `app/core/security.py`, `app/services/email_service.py`, `app/schemas/user.py`, `app/integrations/supabase_client.py`

---

## 2. Users

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/users.py`  

**Routes:**  
`GET /me`, `PUT /me`, `GET ""`, `GET /{user_id}`, `DELETE /{user_id}`, `PUT /{user_id}/role`, `GET /stats/summary`, `GET /notifications`, `PUT /notifications`, `GET /privacy`, `PUT /privacy`, `GET /two-factor-auth/status`, `POST /two-factor-auth/setup`, `POST /two-factor-auth/verify`, `PUT /two-factor-auth`, `PUT /change-password`, `POST /deactivate`, `POST /delete`

**Services:**  
None dedicated; logic in route handlers. Permissions via `app.core.permissions`.

**Database models:**  
`User`, `UserPreferences`, `Account`, `KYCVerification`

**External integrations:**  
None (2FA is pyotp/qrcode local).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/users.py`, `app/models/user.py`, `app/models/user_preferences.py`

---

## 3. KYC

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/kyc.py`  

**Routes:**  
`POST /start`, plus document upload, status, verification URL, submit, etc. (multiple endpoints in same file).

**Services:**  
None; PersonaClient used directly in routes.

**Database models:**  
`KYCVerification`, `Account`, `Document` (for uploads)

**External integrations:**  
- Persona (create_inquiry, get_inquiry, submit_inquiry, upload_document, list_documents, verification URL)  
- Supabase Storage (document upload)

**Missing pieces:**  
None. Fallback when Persona not configured in development.

**Files:**  
`app/api/v1/kyc.py`, `app/models/kyc.py`, `app/integrations/persona_client.py`

---

## 4. KYB

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/kyb.py`  

**Routes:**  
`POST /start`, status, document upload, submit, etc.

**Services:**  
None; PersonaClient and Supabase used in routes.

**Database models:**  
`KYBVerification`, `Account`, `Document`

**External integrations:**  
- Persona (create_inquiry, get_inquiry, submit_inquiry)  
- Supabase (document storage)

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/kyb.py`, `app/models/kyb.py`, `app/integrations/persona_client.py`, `app/integrations/supabase_client.py`

---

## 5. Accounts

**Status:** Partially implemented  
**Routes:** Yes  
**File:** `app/api/v1/accounts.py`  

**Routes:**  
`POST ""`, `GET ""`, `GET /me`, `PUT /me`, `POST /verify`, `GET /joint-users`, `POST /joint-users/invite`, `POST /joint-users/accept-invitation`, `DELETE /joint-users/{user_id}`, `GET /settings`, `PUT /settings`, `GET /stats`, `DELETE /me`, `POST /admin/{account_id}/suspend`, `POST /admin/{account_id}/activate`

**Services:**  
None; AlpacaClient used for brokerage account in `GET ""`.

**Database models:**  
`Account`, `User`, `KYCVerification`, `JointAccountInvitation`, `Payment`, `Asset`, `LinkedAccount`

**External integrations:**  
Alpaca (get_account for brokerage in account list).

**Missing pieces:**  
- **Bug:** `and_` is used in `get_user_accounts` (lines 97–99) but not imported from `sqlalchemy` (only `select`, `func` are). Results in `NameError` when listing accounts with type checking/savings.  
- TODO: “Send invitation email” for joint invite (line 381).

**Files:**  
`app/api/v1/accounts.py`, `app/models/account.py`, `app/models/joint_invitation.py`, `app/integrations/alpaca_client.py`

---

## 6. Banking (Plaid)

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/banking.py`  

**Routes:**  
`POST /link-token`, `POST /link`, `GET /accounts`, `POST /sync/{linked_account_id}`, `DELETE /accounts/{linked_account_id}`, `GET /accounts/{linked_account_id}`, `POST /accounts/{linked_account_id}/refresh`, `GET /accounts/{linked_account_id}/transactions`

**Services:**  
None; PlaidClient used in routes.

**Database models:**  
`LinkedAccount`, `Transaction` (banking), `Account`

**External integrations:**  
Plaid (link token, exchange token, get accounts, get transactions). Subscription feature flag (Banking) enforced.

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/banking.py`, `app/models/banking.py`, `app/integrations/plaid_client.py`

---

## 7. Assets

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/assets.py`  

**Routes:**  
Many: CRUD assets, valuations, ownership, photos, documents, appraisals, sale-requests, transfer, share, reports, value-trends, files/upload, categories, category-groups, summary, etc.

**Services:**  
None; SupabaseClient used in routes.

**Database models:**  
`Asset`, `AssetValuation`, `AssetOwnership`, `AssetPhoto`, `AssetDocument`, `AssetAppraisal`, `AssetSaleRequest`, `AssetTransfer`, `AssetShare`, `AssetReport`, etc.

**External integrations:**  
Supabase Storage (images bucket for photos, documents bucket for documents).

**Missing pieces:**  
- TODO in assets: “Generate actual report file asynchronously” (line 2558).

**Files:**  
`app/api/v1/assets.py`, `app/models/asset.py`, `app/integrations/supabase_client.py`

---

## 8. Portfolio

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/portfolio.py`  

**Routes:**  
`GET ""`, `GET /performance`, `GET /history`, `GET /allocation`, `GET /risk`, `GET /benchmark`, `GET /summary`, `GET /holdings/top`, `GET /activity/recent`, `GET /market-summary`, `GET /alerts`, crypto summary/performance/breakdown/holdings, cash-flow summary/trends/transactions/accounts/transfers, trade-engine search/assets/orders (place, get, cancel), etc.

**Services:**  
None; integrations used in routes.

**Database models:**  
`Portfolio`, `Asset`, `Order`, `LinkedAccount`, `Transaction` (banking), `Notification`

**External integrations:**  
- Polygon (prices, snapshots, aggregates, search, ticker details)  
- Alpaca (transactions, account, place/cancel orders)  
- Plaid (via linked accounts for cash flow)

**Background jobs:**  
`recalculate_portfolios` (scheduler) updates portfolio total_value from assets.

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/portfolio.py`, `app/models/portfolio.py`, `app/models/order.py`, `app/integrations/polygon_client.py`, `app/integrations/alpaca_client.py`, `app/integrations/plaid_client.py`, `app/core/scheduler.py`

---

## 9. Investment

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/investment.py`  

**Routes:**  
`GET /overview/assets`, `GET /overview/activity`, `GET /overview/crypto-prices`, `GET /overview/trader-profile`, `GET /performance`, `GET /analytics`, `GET /recommendations`, `POST /goals/{goal_id}/adjust`, `POST /strategies/{strategy_id}/backtest`, `GET /strategies/{strategy_id}/performance`, `POST /strategies/{strategy_id}/clone`, `GET /watchlist`, `POST /watchlist`, `DELETE /watchlist/{id}`

**Services:**  
None; Alpaca and Polygon used in routes.

**Database models:**  
`Asset`, `AssetValuation`, `InvestmentWatchlist` (watchlist)

**External integrations:**  
- Alpaca (account, transactions; cash for recommendations)  
- Polygon (crypto prices, stock prices for watchlist)

**Missing pieces:**  
Goals and strategies are in-memory/placeholder (no Goal/Strategy DB models). Backtest and clone return stub-like data.

**Files:**  
`app/api/v1/investment.py`, `app/models/asset.py`, `app/models/watchlist.py`, `app/integrations/alpaca_client.py`, `app/integrations/polygon_client.py`

---

## 10. Market

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/market.py`  

**Routes:**  
`GET /benchmarks` (symbols, timeRange query params)

**Services:**  
None; PolygonClient in routes.

**Database models:**  
None (market data only).

**External integrations:**  
Polygon (current price, daily open/close, aggregates, ticker details). In-memory cache (15 min TTL) for benchmark responses.

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/market.py`, `app/integrations/polygon_client.py`

---

## 11. Trading (Alpaca)

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/trading.py`  

**Routes:**  
`GET /transactions`, `GET /assets` (Alpaca positions)

**Services:**  
None; AlpacaClient in routes.

**Database models:**  
`Account` (for auth only); positions/transactions come from Alpaca API.

**External integrations:**  
Alpaca (get_transactions, get_assets, get_account). Read-only in this module; order placement is under Portfolio trade-engine.

**Missing pieces:**  
None. Trading “module” is read-only; actual order placement is in `portfolio.py` trade-engine.

**Files:**  
`app/api/v1/trading.py`, `app/integrations/alpaca_client.py`

---

## 12. Payments

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/payments.py`  

**Routes:**  
`POST /create-intent`, `POST /webhook`, `GET /history`, `POST /invoices`, `GET /payment-methods`, `POST /payment-methods`, `DELETE /payment-methods/{method_id}`, refund and list refunds, `GET /invoices`, `GET /invoices/{invoice_id}`, `POST /invoices/{invoice_id}/pay`, `GET /stats`

**Services:**  
None; StripeClient in routes.

**Database models:**  
`Payment`, `Invoice`, `Refund` (payment models)

**External integrations:**  
Stripe (payment intents, webhooks, customer, payment methods, refunds).

**Missing pieces:**  
- TODO: “Track default payment method” (line 507).  
- TODO: “Check if it's default and prevent deletion if it is” (line 600).

**Files:**  
`app/api/v1/payments.py`, `app/models/payment.py`, `app/integrations/stripe_client.py`

---

## 13. Subscriptions

**Status:** Partially implemented  
**Routes:** Yes  
**File:** `app/api/v1/subscriptions.py`  

**Routes:**  
`GET /plans`, `POST ""`, `GET ""`, `POST /cancel`, `POST /renew`, `PUT /upgrade`, `GET /history`, `POST /webhook`, `GET /permissions`, `GET /limits`

**Services:**  
None; StripeClient in routes.

**Database models:**  
`Subscription` (and related payment models)

**External integrations:**  
Stripe (customer, payment intent, cancel subscription, webhook signature verification).

**Background jobs:**  
`process_subscription_renewals` (scheduler) marks expired, syncs with Stripe, notifies.

**Missing pieces:**  
- TODO: “Add cancel_at_period_end field to model” (lines 406, 461).  
- cancel_at_period_end not persisted in DB.

**Files:**  
`app/api/v1/subscriptions.py`, `app/models/payment.py`, `app/integrations/stripe_client.py`, `app/core/scheduler.py`

---

## 14. Marketplace

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/marketplace.py`  

**Routes:**  
Listings (create, list, get, update, delete, approve, activate, pay-fee), offers (create, accept, reject, counter, withdraw), escrow (get, release, fund, dispute, refund), search, market-highlights, market-trends, market-summary, watchlist (CRUD, check).

**Services:**  
None; StripeClient for payments in routes.

**Database models:**  
`MarketplaceListing`, `Offer`, `EscrowTransaction`, `WatchlistItem` (marketplace watchlist)

**External integrations:**  
Stripe (payment intents, refunds for escrow).

**Background jobs:**  
`expire_offers`, `expire_listings` (scheduler).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/marketplace.py`, `app/models/marketplace.py`, `app/integrations/stripe_client.py`, `app/core/scheduler.py`

---

## 15. Documents

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/documents.py`  

**Routes:**  
`POST /upload`, `GET ""`, `GET /{document_id}/download`, `DELETE /{document_id}`, `GET /{document_id}`, `PUT /{document_id}`, `GET /stats/summary`, `POST /{document_id}/share`, `GET /{document_id}/preview`

**Services:**  
None; SupabaseClient in routes.

**Database models:**  
`Document`, `DocumentShare`, `Account`

**External integrations:**  
Supabase Storage (documents bucket).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/documents.py`, `app/models/document.py`, `app/models/document_share.py`, `app/integrations/supabase_client.py`

---

## 16. Files

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/files.py`  

**Routes:**  
`POST /upload` (file_type: photo | document, optional asset_id)

**Services:**  
None; SupabaseClient in routes.

**Database models:**  
None (upload returns URL/metadata only; asset-linked docs are in assets/documents).

**External integrations:**  
Supabase Storage (images bucket for photo, documents bucket for document).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/files.py`, `app/integrations/supabase_client.py`

---

## 17. Support

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/support.py`  

**Routes:**  
`POST /tickets`, `GET /tickets`, `GET /tickets/{ticket_id}`, `PUT /tickets/{ticket_id}`, `POST /tickets/{ticket_id}/replies`, `GET /tickets/{ticket_id}/replies`, `GET /tickets/stats`, `POST /tickets/{ticket_id}/assign`, `POST /tickets/{ticket_id}/documents`, `GET /tickets/{ticket_id}/documents`, `GET /tickets/{ticket_id}/history`

**Services:**  
- `SLAService`: SLA targets, breach check, escalate  
- `TicketAssignmentService`: auto-assign

**Database models:**  
`SupportTicket`, `TicketReply`, `Document`

**External integrations:**  
Supabase Storage (ticket document uploads).

**Background jobs:**  
`monitor_sla_breaches` (scheduler) checks SLA and escalates.

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/support.py`, `app/models/support.py`, `app/models/ticket_reply.py`, `app/services/sla_service.py`, `app/services/ticket_assignment_service.py`, `app/core/scheduler.py`

---

## 18. Chat

**Status:** Partially implemented  
**Routes:** Yes  
**File:** `app/api/v1/chat.py`  

**Routes:**  
`POST /users` (Sendbird user), `POST /channels`, `POST /messages/send`, `GET /channels`, `GET /channels/{channel_url}`, `GET /channels/{channel_url}/messages`, `DELETE /channels/{channel_url}/leave`, `PUT /channels/{channel_url}`, `DELETE /channels/{channel_url}`

**Services:**  
None; SendbirdClient in routes.

**Database models:**  
None in this file (Sendbird is external; in-app chat uses Conversation/Message in chat_conversations).

**External integrations:**  
Sendbird (create user, create channel, send message, get channels, get channel, get messages, update channel, delete channel). Feature flag (Chat) enforced.

**Missing pieces:**  
Dual chat system: Sendbird (this module) vs in-app conversations + WebSocket (chat_conversations + websocket_chat). Clarify which is canonical.

**Files:**  
`app/api/v1/chat.py`, `app/integrations/sendbird_client.py`

---

## 19. Chat (Conversations + WebSocket)

**Status:** Fully implemented  
**Routes:** Yes  
**Files:** `app/api/v1/chat_conversations.py`, `app/api/v1/websocket_chat.py`  

**Routes (REST):**  
`GET /conversations`, `GET /conversations/{id}/messages`, `POST /conversations/{id}/messages`, `PUT /conversations/{id}/read`, `DELETE /messages/{message_id}`, `GET /conversations/{id}/participants`, `POST /conversations`, `PUT /conversations/{id}`  

**WebSocket:**  
`/ws/chat` (registered on app in main.py)

**Services:**  
`app.core.websocket_manager`: ConnectionManager with Redis pub/sub for multi-instance.

**Database models:**  
`Conversation`, `ConversationParticipant`, `Message`, `MessageAttachment`, `MessageRead`

**External integrations:**  
Redis (pub/sub for WebSocket broadcast across instances).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/chat_conversations.py`, `app/api/v1/websocket_chat.py`, `app/core/websocket_manager.py`, `app/models/chat.py`

---

## 20. Notifications

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/notifications.py`  

**Routes:**  
`GET ""`, `POST /{notification_id}/read`, `POST /read-all`, `GET /unread-count`, `GET /unread`, `GET /settings`, `PUT /settings`, `POST ""` (create), `DELETE /{notification_id}`, `DELETE ""`

**Services:**  
NotificationService used elsewhere (scheduler, marketplace); routes use DB directly.

**Database models:**  
`Notification` (and NotificationType)

**External integrations:**  
None (in-app only).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/notifications.py`, `app/models/notification.py`, `app/services/notification_service.py`

---

## 21. Tasks

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/tasks.py`  

**Routes:**  
`GET ""`, `POST ""`, `GET /{task_id}`, `PUT /{task_id}`, `DELETE /{task_id}`, `PUT /{task_id}/complete`, `PUT /{task_id}/remind`

**Services:**  
None.

**Database models:**  
`Task`, `Reminder` (from `app.models.task`)

**External integrations:**  
None.

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/tasks.py`, `app/models/task.py`

---

## 22. Reminders

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/reminders.py`  

**Routes:**  
`GET ""`, `POST ""`, `PUT /{reminder_id}`, `DELETE /{reminder_id}`, `PUT /{reminder_id}/snooze`

**Services:**  
None.

**Database models:**  
`Reminder` (in `app.models.task`)

**External integrations:**  
None. “notificationChannels” stored but no push/email sending in this module.

**Missing pieces:**  
None. Optional: actual delivery (push/email) for reminderDate.

**Files:**  
`app/api/v1/reminders.py`, `app/models/task.py`

---

## 23. Referrals

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/referrals.py`  

**Routes:**  
`GET ""` (stats), `GET /list`, `GET /code`, `POST /generate-code`, `GET /rewards`, `GET /leaderboard`

**Services:**  
None; generate_reference_id helper.

**Database models:**  
`Referral`, `ReferralReward`, `ReferralStatus`

**External integrations:**  
None.

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/referrals.py`, `app/models/referral.py`

---

## 24. Reports

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/reports.py`  

**Routes:**  
`GET /portfolio`, `GET /performance`, `GET /transactions`, plus other report endpoints (e.g. tax, compliance, support, appraisals) — full list in file.

**Services:**  
None; DB and model logic in routes.

**Database models:**  
`Report`, `Asset`, `Portfolio`, `Payment`, `SupportTicket`, `Document`, `AssetAppraisal`, etc.

**External integrations:**  
None (generated from DB).

**Missing pieces:**  
None. Some report types may return empty or placeholder sections if data missing.

**Files:**  
`app/api/v1/reports.py`, `app/models/report.py`, various model imports

---

## 25. Analytics

**Status:** Partially implemented  
**Routes:** Yes  
**File:** `app/api/v1/analytics.py`  

**Routes:**  
`POST /identify`, `POST /track`, `POST /track-batch`, `POST /page-view`, `GET /dashboard`, `GET /portfolio`, `GET /performance`, `GET /risk`

**Services:**  
None; PosthogClient in routes.

**Database models:**  
None for analytics (PostHog holds events).

**External integrations:**  
PostHog (identify, track, batch track). Dashboard endpoint returns config/status and points to PostHog dashboard; portfolio/performance/risk may be computed from DB or stubbed.

**Missing pieces:**  
Dashboard/portfolio/performance/risk may be thin; main value is forwarding to PostHog.

**Files:**  
`app/api/v1/analytics.py`, `app/integrations/posthog_client.py`

---

## 26. Concierge

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/concierge.py`  

**Routes:**  
`GET /appraisals`, `GET /appraisals/{id}`, `PATCH /appraisals/{id}/status`, `POST /appraisals/{id}/assign`, `POST /appraisals/{id}/documents`, `GET /appraisals/{id}/documents`, `POST /appraisals/{id}/comments`, `GET /appraisals/{id}/comments`, `PUT /appraisals/{id}/valuation`, `GET /appraisals/{id}/report`, `GET /statistics`

**Services:**  
None; Supabase used for document upload in routes.

**Database models:**  
`AssetAppraisal`, `Asset`, `Document`, `AppraisalType`, `AppraisalStatus`

**External integrations:**  
Supabase Storage (concierge document uploads).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/concierge.py`, `app/models/asset.py` (AssetAppraisal), `app/integrations/supabase_client.py`

---

## 27. CRM

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/crm.py`  

**Routes:**  
`GET /users`, `GET /dashboard/overview`, plus other dashboard/assignment endpoints (see file).

**Services:**  
None; permission checks and DB queries in routes.

**Database models:**  
`User`, `Account`, `SupportTicket`, `Document`, `AssetAppraisal`

**External integrations:**  
None.

**Missing pieces:**  
“Team” filter noted as not implemented (no team model). Filtering by role only.

**Files:**  
`app/api/v1/crm.py`, various models

---

## 28. Entities

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/entities.py`  

**Routes:**  
Many: CRUD entities, types, hierarchy, children, parent, compliance, people, audit-trail, documents (list, add, get, download, status, delete).

**Services:**  
None; SupabaseClient in routes.

**Database models:**  
`Entity`, `EntityType`, `EntityStatus`, `EntityCompliance`, `EntityPerson`, `EntityDocument`, `EntityAuditTrail`, etc.

**External integrations:**  
Supabase Storage (entity document upload/download/delete).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/entities.py`, `app/models/entity.py`, `app/integrations/supabase_client.py`

---

## 29. Compliance

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/compliance.py`  

**Routes:**  
Dashboard, tasks (CRUD, reassign, complete), audits (CRUD), alerts (get, acknowledge, resolve), score/history, metrics, reports (generate, get, download), policies (CRUD).

**Services:**  
None; SupabaseClient for report download and document upload.

**Database models:**  
`ComplianceTask`, `ComplianceTaskDocument`, `ComplianceTaskComment`, `ComplianceTaskHistory`, `ComplianceAudit`, `ComplianceAlert`, `ComplianceScore`, `ComplianceMetrics`, `ComplianceReport`, `CompliancePolicy`, plus enums.

**External integrations:**  
Supabase (storage for policy/report documents, client for download).

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/compliance.py`, `app/models/compliance.py`, `app/integrations/supabase_client.py`

---

## 30. Admin

**Status:** Fully implemented  
**Routes:** Yes  
**File:** `app/api/v1/admin.py`  

**Routes:**  
`GET /dashboard`, `GET /disputes`, `GET /disputes/{dispute_id}`, `POST /disputes/{dispute_id}/resolve`

**Services:**  
- StripeClient (release payment, refund)  
- NotificationService (notifications on resolve)

**Database models:**  
User, Account, Subscription, KYC/KYB, MarketplaceListing, SupportTicket, Asset, Payment, Escrow (for dashboard and disputes).

**External integrations:**  
Stripe (release, refund). NotificationService for in-app notifications.

**Missing pieces:**  
None.

**Files:**  
`app/api/v1/admin.py`, `app/integrations/stripe_client.py`, `app/services/notification_service.py`

---

## Integrations Summary

| Integration   | Used by                                                                 |
|---------------|-------------------------------------------------------------------------|
| Supabase Auth | Auth (register)                                                         |
| Supabase Storage | Assets, Documents, Files, KYC, KYB, Support, Concierge, Entities, Compliance |
| Plaid         | Banking                                                                 |
| Alpaca        | Accounts (brokerage), Portfolio (orders, account, transactions), Investment, Trading |
| Polygon       | Portfolio, Investment, Market (prices, aggregates, ticker details)     |
| Stripe        | Payments, Subscriptions, Marketplace (payments/refunds), Admin (disputes) |
| Persona       | KYC, KYB                                                                |
| Sendbird      | Chat (legacy/alternate chat)                                            |
| PostHog       | Analytics                                                               |
| Redis         | WebSocket chat (pub/sub)                                                |
| EmailService  | Auth (verification, OTP, password reset)                                |

---

## Background Jobs (app/core/scheduler.py)

| Job                       | Trigger     | Purpose                                      |
|---------------------------|------------|----------------------------------------------|
| expire_offers             | Every 1h   | Mark expired offers, notify; warn expiring soon |
| recalculate_portfolios    | Daily 02:00 UTC | Recompute portfolio total_value from assets |
| process_subscription_renewals | Daily 03:00 UTC | Sync with Stripe, mark expired, notify   |
| expire_listings           | Daily 04:00 UTC | Auto-expire old active listings (90 days)  |
| monitor_sla_breaches      | Every 6h  | Check support ticket SLA, escalate          |

---

## Tests

- **API/module tests:** None found under `app/` or `tests/`.
- **Root-level scripts:** `test_storage_connection.py`, `test_db_connection.py`, `test_supabase.py` (likely one-off connection checks).

Recommendation: Add pytest (or similar) and tests per module for critical paths.

---

*Report generated by scanning the Fullego Backend codebase.*
