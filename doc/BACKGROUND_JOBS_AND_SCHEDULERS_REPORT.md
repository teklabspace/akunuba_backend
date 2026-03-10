# Background Jobs, Schedulers, and Queues — Report

Searched the backend for: cron jobs, Bull/Celery/Agenda/Sidekiq/node-cron/workers/setInterval, and related patterns.

---

## 1) All background job files

| File | Purpose |
|------|--------|
| **`app/core/scheduler.py`** | **Only** background job definition file. Uses **APScheduler** (AsyncIOScheduler). |
| `app/main.py` | Starts scheduler on startup (`setup_scheduled_tasks()` then `scheduler.start()`), shuts it down on shutdown. Scheduler is **disabled in test** (`APP_ENV == "test"`). |

**No other job/queue infrastructure found:**

- **No** Celery
- **No** Bull / BullMQ (Node)
- **No** Agenda (Node)
- **No** node-cron (Node — this is a Python backend)
- **No** Sidekiq (Ruby)
- **No** dedicated worker processes or worker entrypoints
- **No** setInterval (JavaScript) or equivalent periodic timers outside the scheduler
- **No** FastAPI `BackgroundTasks` usage for scheduled work
- **No** separate queue (Redis Queue, RQ, Dramatiq, etc.)

**Dependency:** `APScheduler==3.10.4` in `requirements.txt`.

---

## 2) What tasks they perform

All tasks are **async functions** in `app/core/scheduler.py`:

| Job ID | Function | What it does |
|--------|----------|---------------|
| `expire_offers` | `expire_offers()` | Finds marketplace **offers** with `expires_at < now` and status PENDING → sets status EXPIRED. Creates in-app notifications for buyer and seller. Then finds offers expiring in next 24 hours and creates “Offer Expiring Soon” notifications. |
| `expire_listings` | `expire_listings()` | Finds **marketplace listings** that are ACTIVE and older than 90 days → sets status CANCELLED. Creates “Listing Expired” notification for seller. |
| `recalculate_portfolios` | `recalculate_portfolios()` | For every **account**, sums `Asset.current_value` for that account and writes the total to `Portfolio.total_value` (creates Portfolio if missing). Updates `last_updated`. |
| `subscription_renewals` | `process_subscription_renewals()` | Finds **subscriptions** that are ACTIVE and `current_period_end < now`. For each: if Stripe subscription exists, fetches from Stripe and syncs (period dates) or sets PAST_DUE; otherwise marks EXPIRED and creates “Subscription Expired” notification. |
| `monitor_sla` | `monitor_sla_breaches()` | Loads open/in-progress **support tickets**. For each, uses `SLAService.check_sla_breach()`. If breached: sets `sla_breached_at`, increments `escalation_count`, calls `SLAService.escalate_ticket()`. |

---

## 3) Whether they run on a schedule

**Yes.** All run on a **schedule** configured in `setup_scheduled_tasks()`:

| Job ID | Trigger | Schedule |
|--------|---------|----------|
| `expire_offers` | `IntervalTrigger(hours=1)` | **Every 1 hour** |
| `recalculate_portfolios` | `CronTrigger(hour=2, minute=0)` | **Daily at 02:00 UTC** |
| `subscription_renewals` | `CronTrigger(hour=3, minute=0)` | **Daily at 03:00 UTC** |
| `expire_listings` | `CronTrigger(hour=4, minute=0)` | **Daily at 04:00 UTC** |
| `monitor_sla` | `IntervalTrigger(hours=6)` | **Every 6 hours** |

- Timezone: **UTC** (`AsyncIOScheduler(timezone="UTC")`).
- Concurrency: `max_instances=1` for each job (no overlapping runs).
- No cron expressions or queues elsewhere; no on-demand job enqueue (only request handlers call Plaid sync/refresh explicitly).

---

## 4) Whether they handle the requested automations

| Automation | Handled by scheduler? | Notes |
|------------|----------------------|--------|
| **Marketplace expiration** | **Yes** | `expire_offers` (hourly) and `expire_listings` (daily 04:00 UTC). Offers by `expires_at`; listings by 90 days from creation. |
| **Subscription renewals** | **Yes** | `process_subscription_renewals` (daily 03:00 UTC). Syncs with Stripe, marks expired, sends notification. Does not charge cards (Stripe handles billing); job reconciles local state and notifies. |
| **Banking sync** | **No** | No scheduled job. Banking sync is **on-demand only**: `POST /banking/sync/{linked_account_id}` and `POST /banking/accounts/{linked_account_id}/refresh` (Plaid). No cron/interval for pulling transactions or balances. |
| **Portfolio recalculation** | **Yes** | `recalculate_portfolios` (daily 02:00 UTC). Recomputes `Portfolio.total_value` from `Asset.current_value` per account. |
| **Notification delivery** | **Partial** | No **dedicated** “notification delivery” job. When scheduler jobs (and other code) call `NotificationService.create_notification()`, it (1) inserts into DB and (2) **synchronously** sends email (if `send_email=True`) via `EmailService.send_notification_email()`. So delivery is inline, not a separate worker or queue. No scheduled “send pending notifications” or push-delivery job. |

---

## Summary: automations that exist vs missing

**Exist (scheduled in `app/core/scheduler.py`):**

- **Marketplace expiration** — offers (hourly), listings (daily).
- **Subscription renewal handling** — daily sync with Stripe + expire + notify.
- **Portfolio recalculation** — daily.
- **Support SLA monitoring** — every 6 hours (bonus; not in your list).
- **Notification creation + email** — triggered inline from the above jobs (and from API flows); no separate delivery job.

**Missing:**

- **Banking sync** — no scheduled Plaid sync. Only manual/API: `POST .../sync/{linked_account_id}` and `POST .../accounts/{linked_account_id}/refresh`. Adding a scheduled job (e.g. daily or every N hours) to refresh balances/transactions for linked accounts would fill this gap.
- **Dedicated notification delivery** — no queue or cron that “processes pending notifications” or “sends due reminders”; notifications are created and emailed inline. If you need retries, batching, or push, a separate worker/queue would be required.

**Tech stack note:**  
The stack is Python (FastAPI). Bull, node-cron, Agenda, and Sidekiq are Node/Ruby; they were not found and are not used. The only scheduler is **APScheduler** in `app/core/scheduler.py`.
