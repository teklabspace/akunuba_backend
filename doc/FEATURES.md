# Fullego Backend — Feature Map & Interconnection Guide

> **Stack**: FastAPI · PostgreSQL (Supabase) · SQLAlchemy Async · APScheduler · Redis · JWT

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Master Feature Interconnection Map](#2-master-feature-interconnection-map)
3. [Feature Modules](#3-feature-modules)
4. [Cross-Feature Data Flows](#4-cross-feature-data-flows)
5. [External Integrations Map](#5-external-integrations-map)
6. [Subscription Plan Gate Map](#6-subscription-plan-gate-map)
7. [Background Jobs Map](#7-background-jobs-map)

---

## 1. System Overview

Fullego is an **enterprise-grade wealth management platform** that lets investors register, verify their identity, manage real-world and financial assets, trade, transact via marketplace, and stay compliant — all through one unified API.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FULLEGO BACKEND                                 │
│                                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │   AUTH   │  │  ASSETS  │  │PORTFOLIO │  │MARKET-   │  │COMPLIANCE│ │
│  │  & KYC   │  │   MGT    │  │& TRADING │  │  PLACE   │  │ CENTER   │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │PAYMENTS &│  │ BANKING  │  │  CHAT &  │  │ENTITIES &│  │REFERRALS │ │
│  │   SUBS   │  │ (PLAID)  │  │  NOTIFS  │  │  AUDIT   │  │& REPORTS │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │
│                                                                         │
│  ─────── Shared Infrastructure ───────────────────────────────────     │
│  Rate Limiting · JWT Auth · RBAC · APScheduler · Redis · Sentry        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Master Feature Interconnection Map

```
                        ┌───────────────────────────────────┐
                        │        USER REGISTRATION          │
                        │  POST /auth/register               │
                        │  • Creates User record             │
                        │  • Sends OTP via Email Service     │
                        └─────────────┬─────────────────────┘
                                      │ OTP verified
                                      ▼
                        ┌───────────────────────────────────┐
                        │       EMAIL VERIFICATION          │◄─── Email Service
                        │  POST /auth/verify-otp             │     (Mailpit/Resend)
                        │  • Unlocks account creation        │
                        └─────────────┬─────────────────────┘
                                      │ triggers
                          ┌───────────┼───────────────┐
                          ▼           ▼               ▼
              ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
              │   ACCOUNT    │ │ SUBSCRIPTION │ │  USER PREF   │
              │  CREATION    │ │  (FREE tier) │ │  CREATION    │
              │  Individual/ │ │  auto-setup  │ │  auto-setup  │
              │  Corporate/  │ └──────────────┘ └──────────────┘
              │  Trust       │
              └──────┬───────┘
                     │ account_id gates all features below
                     │
        ┌────────────┼────────────────────────────────┐
        ▼            ▼                                 ▼
┌──────────────┐ ┌──────────────┐           ┌──────────────────┐
│     KYC      │ │     KYB      │           │   GOOGLE OAUTH   │
│ VERIFICATION │ │ VERIFICATION │           │  (alternative    │
│  (Persona)   │ │  (Persona)   │           │   login path)    │
│              │ │  Corporate/  │           └──────────────────┘
│ ┌──────────┐ │ │  Trust only  │
│ │ Inquiry  │ │ └──────┬───────┘
│ │ Created  │ │        │
│ │ Docs     │ │        │ KYC + KYB approved
│ │ Uploaded │ │        │ ──────────────────────────────────────────┐
│ │ Webhook  │ │        │                                           │
│ └──────────┘ │        │                                           ▼
└──────┬───────┘        │                              ┌─────────────────────┐
       │ KYC approved   │                              │  MARKETPLACE ACCESS  │
       └────────────────┘                              │  • Create Listings   │
                │                                      │  • Make/Accept Offers│
                │                                      │  • Escrow (Stripe)   │
                │                                      └──────────┬──────────┘
                ▼                                                  │
┌───────────────────────────┐                                      │
│      ASSET MANAGEMENT     │◄─────────────────────────────────────┘
│  • Create / Edit / Delete │   Assets can be listed on marketplace
│  • Photos & Documents     │
│  • Appraisals             │
│  • Sale Requests          │
│  • Transfers              │
│  • Share Links            │
│  • Asset Reports          │
└──────┬──────────┬─────────┘
       │          │
       ▼          ▼
┌───────────┐ ┌─────────────────────┐
│  ASSET    │ │   FILE STORAGE      │
│VALUATIONS │ │  (Supabase Buckets) │
│ (history) │ │  Photos, Docs,      │
└──────┬────┘ │  Reports, KYC docs  │
       │      └─────────────────────┘
       │ feeds into
       ▼
┌─────────────────────────────────────┐
│           PORTFOLIO ENGINE          │
│  • Total value aggregation          │
│  • Asset allocation by type         │
│  • Performance metrics (daily ROI)  │
│  • Risk metrics calculation         │
└────────────────┬────────────────────┘
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
┌──────────┐ ┌────────┐ ┌──────────────┐
│ANALYTICS │ │REPORTS │ │   TRADING    │
│(PostHog) │ │(PDF/   │ │   ORDERS     │
│• Usage   │ │CSV/    │ │ (Alpaca API) │
│• Events  │ │XLSX)   │ │ • Market     │
│• Risk    │ └────────┘ │ • Limit      │
└──────────┘            │ • Stop       │
                        └──────┬───────┘
                               │ order events
                               ▼
                    ┌────────────────────┐
                    │   NOTIFICATIONS    │
                    │  • ORDER_FILLED    │◄── all system events
                    │  • OFFER_RECEIVED  │    feed here
                    │  • KYC_APPROVED    │
                    │  • SUPPORT_REPLY   │
                    │  In-app + Email    │
                    └────────┬───────────┘
                             │
                    ┌────────┴───────────┐
                    ▼                    ▼
           ┌──────────────┐    ┌──────────────────┐
           │ EMAIL SERVICE│    │  CHAT (Sendbird)  │
           │  (Resend /   │    │  • Conversations  │
           │   Mailpit)   │    │  • Messages       │
           │  OTP, KYC,   │    │  • Attachments    │
           │  Support     │    │  • WS /ws/chat    │
           └──────────────┘    └──────────────────┘
```

---

### Payments & Subscriptions Interconnection

```
┌────────────────────────────────────────────────────────────────────────┐
│                    PAYMENT & SUBSCRIPTION FLOW                         │
│                                                                        │
│  User selects plan                                                     │
│       │                                                                │
│       ▼                                                                │
│  ┌──────────────┐    Stripe API    ┌──────────────────────────────┐   │
│  │ POST /payments│ ──────────────► │  Stripe Payment Intent       │   │
│  │ /create-intent│                 │  or Subscription Object      │   │
│  └──────────────┘                  └──────────────┬───────────────┘   │
│                                                    │ webhook           │
│                                                    ▼                   │
│                                    ┌──────────────────────────────┐   │
│                                    │  POST /webhooks/stripe        │   │
│                                    │  • payment_intent.succeeded   │   │
│                                    │  • customer.subscription.*    │   │
│                                    └──────────────┬───────────────┘   │
│                                                    │                   │
│                      ┌─────────────────────────────┤                  │
│                      ▼                             ▼                   │
│          ┌───────────────────┐         ┌────────────────────────┐     │
│          │ Subscription Model│         │  Marketplace Escrow     │     │
│          │  Plan: FREE /     │         │  Status: FUNDED →       │     │
│          │  MONTHLY / ANNUAL │         │  RELEASED               │     │
│          └─────────┬─────────┘         └────────────────────────┘     │
│                    │                                                   │
│         ┌──────────┴──────────────────────────────────────┐           │
│         │         FEATURE GATE (by plan)                  │           │
│         │  FREE     → 5 assets, no trading, no analytics   │           │
│         │  MONTHLY  → 20 assets, marketplace listing       │           │
│         │  ANNUAL   → unlimited, trading, banking, chat    │           │
│         └─────────────────────────────────────────────────┘           │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Banking & Compliance Interconnection

```
┌────────────────────────────────────────────────────────────────────────┐
│                      BANKING (Plaid) FLOW                              │
│                                                                        │
│  POST /banking/link-token                                              │
│       │  (Plaid Link Token created)                                    │
│       ▼                                                                │
│  Frontend opens Plaid modal → user picks bank                         │
│       │                                                                │
│       ▼                                                                │
│  POST /banking/link  → stores access_token in LinkedAccount           │
│       │                                                                │
│       ├─► GET /banking/accounts   → list balances                     │
│       ├─► POST /banking/sync/{id} → pull transactions → Transaction   │
│       │                             model updated                      │
│       └─► Background Job (daily 6 AM UTC) auto-syncs all accounts     │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│               ENTITIES & COMPLIANCE FLOW                               │
│                                                                        │
│  POST /entities  →  Entity created (Corp / Trust / LLC …)             │
│       │                                                                │
│       ├──► EntityPerson  (Trustees, Directors, Signatories)           │
│       ├──► EntityDocument (Articles, Trust Deed, Op. Agreement)       │
│       ├──► EntityCompliance (KYC/AML, FATCA status)                   │
│       └──► EntityAuditTrail (every action logged)                     │
│                 ▲                                                      │
│                 │  auto-logged on every Create/Update/Delete          │
│                                                                        │
│  ComplianceTasks ──────────────────────────────────────────────┐      │
│  ComplianceAudits ─────────────────────────────────────────────┤      │
│  ComplianceAlerts ─────────────────────────────────────────────┤      │
│  ComplianceScore  ─────────────────────────────────────────────┤      │
│  CompliancePolicies ───────────────────────────────────────────┤      │
│                                                         ▼      │      │
│                                              GET /compliance/  │      │
│                                              dashboard         │      │
│                                              (Score, Audits,   │      │
│                                               Alerts summary)  │      │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Support & SLA Interconnection

```
┌────────────────────────────────────────────────────────────────────────┐
│                     SUPPORT TICKET LIFECYCLE                           │
│                                                                        │
│  POST /support/tickets                                                 │
│       │  Priority: LOW | MEDIUM | HIGH | URGENT                       │
│       ▼                                                                │
│  Ticket OPEN  ──────────────────────────────────────────────────┐     │
│       │                                                          │     │
│       ├──► SLA Target set (based on priority)                   │     │
│       │    LOW: 48h | MEDIUM: 24h | HIGH: 8h | URGENT: 2h       │     │
│       │                                                          │     │
│       ├──► Agent assignment (optional)                           │     │
│       │                                                          │     │
│       ├──► POST /tickets/{id}/replies  → SLA clock ticking       │     │
│       │                                                          │     │
│       │    ┌─────────────────────────────────────────────────┐  │     │
│       │    │  SLA MONITOR (every 30 min background job)       │  │     │
│       │    │  • Checks sla_target_hours vs created_at         │  │     │
│       │    │  • Breached? → escalation_count++                │  │     │
│       │    │             → Notification to admin              │  │     │
│       │    └─────────────────────────────────────────────────┘  │     │
│       │                                                          │     │
│       └──► RESOLVED / CLOSED  ◄────────────────────────────────┘     │
│                │                                                       │
│                └──► Notification: SUPPORT_REPLY sent to user          │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Referral System Interconnection

```
┌────────────────────────────────────────────────────────────────────────┐
│                         REFERRAL FLOW                                  │
│                                                                        │
│  Existing User                                                         │
│       │                                                                │
│       ▼                                                                │
│  POST /referrals/generate-code  →  Referral record (PENDING)          │
│       │  unique code (indexed)                                         │
│       │                                                                │
│  New User signs up with referral code                                  │
│       │                                                                │
│       ▼                                                                │
│  POST /auth/register?ref=CODE                                          │
│       │  → referred_account linked                                     │
│       │                                                                │
│       ▼                                                                │
│  New User subscribes (MONTHLY / ANNUAL)                               │
│       │                                                                │
│       ▼                                                                │
│  Referral Status: PENDING → COMPLETED                                  │
│  ReferralReward created  (type: signup / first_payment / subscription) │
│       │                                                                │
│       ▼                                                                │
│  GET /referrals/leaderboard  →  top referrers ranked                  │
│  GET /referrals/stats        →  total rewards earned                  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Feature Modules

### 3.1 Authentication & Identity

| Sub-feature | Endpoint(s) | Depends On | Unlocks |
|---|---|---|---|
| Register | `POST /auth/register` | — | Email Verification |
| Email OTP Verify | `POST /auth/verify-otp` | Email Service | Account Creation |
| Login | `POST /auth/login` | User record | JWT Token |
| Google OAuth | `GET /auth/google/login` `GET /auth/google/callback` | Google Client ID | JWT Token |
| 2FA Setup | `POST /users/2fa/setup` | Verified account | TOTP QR code |
| 2FA Verify | `POST /users/2fa/verify` | 2FA setup | Full login |
| Password Reset | `POST /auth/forgot-password` | Email Service | — |
| Refresh Token | `POST /auth/refresh` | Valid refresh JWT | New access token |

---

### 3.2 KYC / KYB Verification

```
         KYC Flow (all account types)
         ─────────────────────────────
         Email Verified
              │
              ▼
         POST /kyc/start
              │  Creates Persona Inquiry
              │  Status: IN_PROGRESS
              ▼
         POST /kyc/submit
              │  Uploads docs, submits to Persona
              │  Status: PENDING_REVIEW
              ▼
         GET /kyc/webhook (Persona webhook)
              │  Persona decision received
              ▼
         Status: APPROVED / REJECTED / EXPIRED


         KYB Flow (Corporate & Trust only)
         ─────────────────────────────────
         KYC Approved
              │
              ▼
         POST /kyb/start
         PUT  /kyb/{id}  (ownership, directors)
         POST /kyb/documents
              │
              ▼
         Persona KYB Inquiry → Webhook → APPROVED
```

---

### 3.3 Asset Management

```
Asset Model (core)
├── AssetCategory       ← defines form schema per category
├── AssetValuation      ← price history (ordered desc)
├── AssetOwnership      ← multi-account partial ownership %
├── AssetPhoto          ← images (primary + thumbnails)
├── AssetDocument       ← purchase agreements, insurance
├── AssetAppraisal      ← valuation requests (Concierge/API/Standard)
├── AssetSaleRequest    ← sale inquiries with target price
├── AssetTransfer       ← Gift / Sale / Inheritance
├── AssetShare          ← time-limited share links
└── AssetReport         ← PDF/CSV summaries

Category Groups:
  Assets · Portfolio · Liabilities · Shadow Wealth
  Philanthropy · Lifestyle · Governance
```

---

### 3.4 Portfolio & Trading

```
Portfolio (1:1 with Account)
├── Total Value (Decimal 20,2)
├── Asset Allocation (JSONB)       ← aggregated from Asset table
├── Performance Data (JSONB)       ← daily returns history
└── Last Updated

Trading Orders (via Alpaca)
├── Types: MARKET / LIMIT / STOP
├── Sides: BUY / SELL
├── Status lifecycle:
│     PENDING → SUBMITTED → FILLED
│                         → PARTIALLY_FILLED
│                         → CANCELLED / REJECTED
└── OrderHistory for audit trail

Market Data (via Polygon.io)
├── Ticker details
├── OHLC aggregates
├── Last trade / bid-ask quotes
└── Daily performance calc
```

---

### 3.5 Marketplace

```
Listing lifecycle:
  DRAFT → PENDING_APPROVAL → APPROVED → ACTIVE → SOLD / CANCELLED
               │
               └── Admin review required

Offer lifecycle:
  PENDING → ACCEPTED → triggers Escrow creation
          → REJECTED
          → COUNTERED  (negotiation loop)
          → EXPIRED (background job hourly)
          → WITHDRAWN

Escrow lifecycle (Stripe-backed):
  PENDING → FUNDED → RELEASED  (asset ownership transferred)
                   → REFUNDED
                   → DISPUTED
```

---

### 3.6 Payments & Subscriptions

| Plan | Assets | Documents | Marketplace | Trading | Analytics | Banking | Chat |
|---|---|---|---|---|---|---|---|
| FREE | 5 | 10 | View + offer | View only | — | — | — |
| MONTHLY | 20 | Unlimited | Create listing | View only | Basic | — | — |
| ANNUAL | Unlimited | Unlimited | Create listing | Full orders | Advanced | Yes | Yes |

---

### 3.7 Banking (Plaid)

```
LinkedAccount
├── Plaid Item ID + Access Token
├── Types: BANKING / BROKERAGE / CRYPTO
├── Balance + Currency
└── Last Sync Timestamp

Transaction
├── Plaid Transaction ID (unique)
├── Amount, Currency, Category
└── Metadata (JSONB)

Background Job: daily 6 AM UTC auto-syncs all linked accounts
```

---

### 3.8 Documents & File Storage

```
Storage Buckets (Supabase):
  documents/  photos/  reports/  kyc-docs/  entity-docs/

DocumentShare permissions:
  VIEW · DOWNLOAD · EDIT
  └── Token-based public link with optional expiry
```

---

### 3.9 Entities & Compliance

```
Entity
├── EntityPerson       (Trustee, Director, Signatory, Beneficiary …)
├── EntityDocument     (Cert of Incorporation, Trust Deed …)
├── EntityCompliance   (KYC/AML, FATCA, CRS status)
└── EntityAuditTrail   (every action timestamped)

Compliance Center:
├── ComplianceTask     (AML / KYC / GDPR deadlines)
├── ComplianceAudit    (Internal / External / Regulatory)
├── ComplianceAlert    (CRITICAL / HIGH / MEDIUM / LOW severity)
├── ComplianceScore    (0–100, with trend delta)
├── ComplianceMetrics  (per category breakdown)
├── ComplianceReport   (generated PDF/Excel/CSV)
└── CompliancePolicy   (versioned policies with review schedule)
```

---

### 3.10 Chat & Notifications

```
Chat (Sendbird-backed):
  Conversation ─► ConversationParticipant (role: PARTICIPANT/ADMIN/MODERATOR)
               ─► Message ─► MessageAttachment
                           ─► MessageRead (read receipts)

WebSocket: WS /ws/chat  ←→  Redis pub/sub (multi-instance safe)

Notifications:
  Types: ORDER_FILLED · OFFER_RECEIVED · OFFER_ACCEPTED
         LISTING_APPROVED · PAYMENT_RECEIVED · KYC_APPROVED
         SUPPORT_REPLY · GENERAL
  Channels: in-app · email (Resend/Mailpit) · Sendbird push
```

---

### 3.11 Support Tickets

```
SLA Targets by Priority:
  LOW: 48h · MEDIUM: 24h · HIGH: 8h · URGENT: 2h

Background Monitor: every 30 minutes
  → calculates time elapsed vs sla_target_hours
  → on breach: escalation_count++, admin notified
```

---

### 3.12 Tasks & Reminders

```
Task
├── Status: PENDING → IN_PROGRESS → COMPLETED / CANCELLED
├── Priority: LOW / MEDIUM / HIGH / URGENT
├── Due date + Reminder date
└── Category (free text)

Reminder
├── Optionally linked to a Task
├── Status: PENDING → SNOOZED → COMPLETED / CANCELLED
├── Channels: email · push · SMS
└── Notified_at tracked (prevents re-sends)
```

---

### 3.13 Referrals

```
Referral
├── Referral Code (unique, indexed)
├── Status: PENDING → COMPLETED / CANCELLED
├── Reward Amount + Currency
└── Reward Paid (bool + timestamp)

ReferralReward
├── Types: signup · first_payment · subscription
└── Linked to Referral + Account
```

---

### 3.14 Reports

```
Report Types:   PORTFOLIO · PERFORMANCE · TRANSACTION · TAX · CUSTOM
Report Formats: PDF · CSV · XLSX · JSON
Status:         PENDING → GENERATING → COMPLETED / FAILED

Generation is async (background job); download URL stored on completion.
```

---

## 4. Cross-Feature Data Flows

### Flow A — New User Full Onboarding

```
1.  POST /auth/register
        ↓ OTP email sent (Mailpit/Resend)
2.  POST /auth/verify-otp
        ↓ Account created (INDIVIDUAL by default)
        ↓ Subscription created (FREE)
        ↓ UserPreferences created
3.  POST /kyc/start
        ↓ Persona inquiry created
4.  [User uploads docs via Persona hosted flow]
5.  GET  /kyc/webhook  ← Persona notifies
        ↓ KYC status → APPROVED
        ↓ Notification: KYC_APPROVED
6.  User now has full marketplace + asset access (within FREE plan limits)
```

---

### Flow B — Asset → Marketplace → Escrow

```
1.  POST /assets               → Asset created (ACTIVE)
2.  POST /marketplace/listings → Listing DRAFT → PENDING_APPROVAL
3.  Admin: PUT /marketplace/listings/{id}  → APPROVED → ACTIVE
4.  Buyer: POST /marketplace/listings/{id}/offers → Offer PENDING
5.  Seller: POST /marketplace/offers/{id}/accept  → Offer ACCEPTED
        ↓  EscrowTransaction created (PENDING)
6.  POST /payments/create-intent → Stripe PaymentIntent
7.  POST /webhooks/stripe        → payment_intent.succeeded
        ↓  Escrow → FUNDED
8.  Admin confirms delivery
        ↓  Escrow → RELEASED
        ↓  Asset ownership transferred to buyer
        ↓  Notification: PAYMENT_RECEIVED (seller)
```

---

### Flow C — Portfolio Recalculation (background, daily 2 AM UTC)

```
All active Accounts
    │
    ▼
For each Account → fetch all Assets
    │
    ├─► Polygon.io API: get current market prices
    ├─► Sum asset.current_value by type
    ├─► Calculate asset allocation percentages
    ├─► Compute daily return (new_value - prev_value) / prev_value
    └─► Update Portfolio record (total_value, asset_allocation, performance_data)
```

---

### Flow D — Banking Sync (background, daily 6 AM UTC)

```
All LinkedAccounts (not expired)
    │
    ▼
Plaid API → get transactions (last 30 days)
    │
    ├─► Upsert Transaction records (plaid_transaction_id unique)
    ├─► Update LinkedAccount.balance
    └─► Update LinkedAccount.last_sync_at
```

---

### Flow E — Support SLA Breach (background, every 30 min)

```
All OPEN / IN_PROGRESS tickets
    │
    ▼
For each ticket:
    elapsed = now - created_at
    target  = sla_target_hours (by priority)
    │
    ├─ elapsed > target AND sla_breached_at IS NULL
    │       → sla_breached_at = now
    │       → escalation_count++
    │       → last_escalated_at = now
    │       → Notification → admin
    │
    └─ elapsed > target + 2h AND escalation_count < 3
            → escalate again → Notification → senior admin
```

---

## 5. External Integrations Map

```
┌──────────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                                  │
│                                                                      │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐               │
│  │  SUPABASE   │   │   PERSONA   │   │   STRIPE    │               │
│  │             │   │             │   │             │               │
│  │ PostgreSQL  │   │ KYC / KYB   │   │ Payments    │               │
│  │ File Storage│   │ Document    │   │ Subscriptions│              │
│  │ (S3-like)   │   │ Verification│   │ Escrow      │               │
│  │ Auth JWT    │   │ Webhooks    │   │ Webhooks    │               │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘               │
│         │                 │                 │                       │
│         └────────┬────────┘                 │                       │
│                  │                          │                       │
│         ┌────────▼────────────────────────────────────────────┐    │
│         │                  FULLEGO API                         │    │
│         └────────┬────────────────────────────────────────────┘    │
│                  │                                                  │
│  ┌───────────────┼──────────────────────────────────────────────┐  │
│  │               │                                              │  │
│  ▼               ▼               ▼               ▼             ▼  │
│ ┌──────────┐ ┌────────┐ ┌─────────────┐ ┌────────────┐ ┌────────┐│
│ │  PLAID   │ │ALPACA  │ │ POLYGON.IO  │ │ SENDBIRD   │ │POSTHOG ││
│ │          │ │        │ │             │ │            │ │        ││
│ │ Bank     │ │ Stock  │ │ Market Data │ │ Real-time  │ │Analytics│
│ │ Account  │ │Trading │ │ OHLC,Quotes │ │ Chat       │ │Events  ││
│ │ Linking  │ │Orders  │ │ Ticker Info │ │ Channels   │ │Identity││
│ │Transactions│Positions│ Daily Perf  │ │ Messages   │ │Tracking││
│ └──────────┘ └────────┘ └─────────────┘ └────────────┘ └────────┘│
│                                                                     │
│  ┌────────────────────┐   ┌───────────────────────────────────┐    │
│  │  MAILPIT / RESEND  │   │  GOOGLE OAUTH                     │    │
│  │  Email delivery    │   │  Social login                     │    │
│  │  OTP, KYC alerts,  │   │  google.com/o/oauth2              │    │
│  │  Support replies   │   └───────────────────────────────────┘    │
│  └────────────────────┘                                            │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  REDIS  (optional)                                          │    │
│  │  • WebSocket pub/sub (chat multi-instance)                  │    │
│  │  • APScheduler jobstore (distributed locks)                 │    │
│  └────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 6. Subscription Plan Gate Map

```
Feature Request
      │
      ▼
  ┌──────────────────────────────────┐
  │  deps.py: check_subscription()   │
  │  + check_feature_access()        │
  └──────────────┬───────────────────┘
                 │
     ┌───────────┼───────────────┐
     ▼           ▼               ▼
  ┌──────┐  ┌─────────┐  ┌──────────┐
  │ FREE │  │ MONTHLY │  │ ANNUAL   │
  └──────┘  └─────────┘  └──────────┘
     │           │               │
     │     All FREE +       All MONTHLY +
     │           │               │
  5 assets   20 assets      Unlimited assets
  10 docs    Unlimited docs  Unlimited docs
  Browse     Create listing  Trading orders
  marketplace Make offers    Banking (Plaid)
  View        Basic analytics Chat (Sendbird)
  portfolio   —               Advanced analytics
  No orders                   Priority support
  No analytics                Premium reports
  Basic support
```

---

## 7. Background Jobs Map

```
APScheduler (async) + optional Redis jobstore
Distributed lock prevents duplicate runs across instances

┌──────────────────────────────────────────────────────────────────────┐
│  Job Name              │ Schedule       │ What it does               │
├──────────────────────────────────────────────────────────────────────┤
│  expire_offers         │ Hourly         │ PENDING offers past expiry │
│                        │                │ → EXPIRED                  │
├──────────────────────────────────────────────────────────────────────┤
│  recalculate_portfolios│ Daily 2AM UTC  │ Aggregates asset values,   │
│                        │                │ updates Portfolio model     │
├──────────────────────────────────────────────────────────────────────┤
│  process_subscriptions │ Daily 3AM UTC  │ Handles renewals,          │
│                        │                │ downgrades, expirations     │
├──────────────────────────────────────────────────────────────────────┤
│  expire_listings       │ Daily 4AM UTC  │ Marks old marketplace      │
│                        │                │ listings EXPIRED            │
├──────────────────────────────────────────────────────────────────────┤
│  monitor_sla           │ Every 30 min   │ Checks support ticket SLA, │
│                        │                │ escalates breaches          │
├──────────────────────────────────────────────────────────────────────┤
│  banking_sync          │ Daily 6AM UTC  │ Plaid transaction sync for │
│                        │                │ all LinkedAccounts          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Role & Permission Summary

```
Role        │ Can Do
────────────┼──────────────────────────────────────────────────────────
ADMIN       │ Read/write all: users, assets, portfolio, trading,
            │ listings, subscriptions, analytics, support
            │ Approve KYC, listings, documents
            │ Assign support tickets, escalate SLAs
────────────┼──────────────────────────────────────────────────────────
INVESTOR    │ Read/write own: assets, portfolio
            │ Read: listings, analytics
            │ Write: own listings, offers, orders (plan permitting)
            │ Read/write: own support tickets, tasks, reminders
────────────┼──────────────────────────────────────────────────────────
ADVISOR     │ Read: assets, portfolio, listings, analytics
            │ Write: own tasks, reminders
            │ Assigned by ADMIN to accounts
```

---

*Generated from live codebase — d:\Fiver\Fullego_Backend — 2026-06-17*
