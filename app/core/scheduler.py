from urllib.parse import urlparse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.utils.logger import logger
from app.config import settings
from app.core.scheduler_locks import with_lock
from app.core.metrics import record_job_failure

# Optional Redis jobstore so jobs persist across restarts and are shared across instances
_jobstores = None
try:
    if getattr(settings, "REDIS_URL", None) and settings.REDIS_URL.startswith("redis://"):
        from apscheduler.jobstores.redis import RedisJobStore
        u = urlparse(settings.REDIS_URL)
        _jobstores = {
            "default": RedisJobStore(
                host=u.hostname or "localhost",
                port=u.port or 6379,
                db=int((u.path or "/0").strip("/") or 0),
                password=u.password or None,
            )
        }
        logger.info("Scheduler using Redis jobstore for persistence")
except Exception as e:
    logger.warning(f"Redis jobstore not used, jobs in-memory only: {e}")

scheduler = AsyncIOScheduler(timezone="UTC", jobstores=_jobstores or {})


def setup_scheduled_tasks():
    """Setup all scheduled background tasks. Jobs use Redis lock so only one instance runs each."""
    try:
        # Offer expiration - check every hour
        scheduler.add_job(
            with_lock("expire_offers", expire_offers),
            IntervalTrigger(hours=1),
            id='expire_offers',
            replace_existing=True,
            max_instances=1
        )
        
        # Portfolio recalculation - daily at 2 AM UTC
        scheduler.add_job(
            with_lock("recalculate_portfolios", recalculate_portfolios),
            CronTrigger(hour=2, minute=0),
            id='recalculate_portfolios',
            replace_existing=True,
            max_instances=1
        )
        
        # Subscription renewal check - daily at 3 AM UTC
        scheduler.add_job(
            with_lock("subscription_renewals", process_subscription_renewals),
            CronTrigger(hour=3, minute=0),
            id='subscription_renewals',
            replace_existing=True,
            max_instances=1
        )
        
        # Listing expiration - daily at 4 AM UTC
        scheduler.add_job(
            with_lock("expire_listings", expire_listings),
            CronTrigger(hour=4, minute=0),
            id='expire_listings',
            replace_existing=True,
            max_instances=1
        )
        
        # SLA monitoring - every 6 hours
        scheduler.add_job(
            with_lock("monitor_sla", monitor_sla_breaches),
            IntervalTrigger(hours=6),
            id='monitor_sla',
            replace_existing=True,
            max_instances=1
        )
        
        # Banking auto-sync: sync all linked accounts every 6 hours
        scheduler.add_job(
            with_lock("banking_sync_all", banking_sync_all),
            IntervalTrigger(hours=6),
            id='banking_sync_all',
            replace_existing=True,
            max_instances=1
        )
        
        # Subscription payment retry sync & downgrade - daily at 4:30 AM UTC
        scheduler.add_job(
            with_lock("subscription_retry_downgrade", process_subscription_retry_and_downgrade),
            CronTrigger(hour=4, minute=30),
            id='subscription_retry_downgrade',
            replace_existing=True,
            max_instances=1
        )
        
        logger.info("Background jobs scheduled successfully")
    except Exception as e:
        logger.error(f"Failed to setup scheduled tasks: {e}")


async def expire_offers():
    """Expire offers that have passed their expiration date"""
    from app.database import AsyncSessionLocal
    from app.models.marketplace import Offer, OfferStatus, MarketplaceListing
    from app.models.notification import NotificationType
    from sqlalchemy import select
    from datetime import datetime, timedelta
    from app.services.notification_service import NotificationService, NotificationType
    
    try:
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            result = await db.execute(
                select(Offer).where(
                    Offer.status == OfferStatus.PENDING,
                    Offer.expires_at < now
                )
            )
            expired_offers = result.scalars().all()
            
            for offer in expired_offers:
                offer.status = OfferStatus.EXPIRED
                
                # Notify buyer
                await NotificationService.create_notification(
                    db=db,
                    account_id=offer.account_id,
                    notification_type=NotificationType.OFFER_RECEIVED,
                    title="Offer Expired",
                    message=f"Your offer on listing has expired"
                )
                
                # Notify seller
                listing_result = await db.execute(
                    select(MarketplaceListing).where(MarketplaceListing.id == offer.listing_id)
                )
                listing = listing_result.scalar_one_or_none()
                if listing:
                    await NotificationService.create_notification(
                        db=db,
                        account_id=listing.account_id,
                        notification_type=NotificationType.OFFER_RECEIVED,
                        title="Offer Expired",
                        message=f"An offer on your listing has expired"
                    )
            
            await db.commit()
            logger.info(f"Expired {len(expired_offers)} offers")
            
            # Notify offers expiring in 24 hours
            expiring_soon = now + timedelta(hours=24)
            expiring_result = await db.execute(
                select(Offer).where(
                    Offer.status == OfferStatus.PENDING,
                    Offer.expires_at <= expiring_soon,
                    Offer.expires_at > now
                )
            )
            expiring_offers = expiring_result.scalars().all()
            
            for offer in expiring_offers:
                await NotificationService.create_notification(
                    db=db,
                    account_id=offer.account_id,
                    notification_type=NotificationType.OFFER_RECEIVED,
                    title="Offer Expiring Soon",
                    message=f"Your offer expires in 24 hours"
                )
            
            await db.commit()
    except Exception as e:
        logger.error(f"Error expiring offers: {e}")
        record_job_failure("expire_offers")


async def expire_listings():
    """Expire listings that have passed their expiration date"""
    from app.database import AsyncSessionLocal
    from app.models.marketplace import MarketplaceListing, ListingStatus
    from sqlalchemy import select
    from datetime import datetime, timedelta
    
    try:
        async with AsyncSessionLocal() as db:
            # Listings expire after 90 days of being active
            cutoff_date = datetime.utcnow() - timedelta(days=90)
            result = await db.execute(
                select(MarketplaceListing).where(
                    MarketplaceListing.status == ListingStatus.ACTIVE,
                    MarketplaceListing.created_at < cutoff_date
                )
            )
            old_listings = result.scalars().all()
            
            for listing in old_listings:
                listing.status = ListingStatus.CANCELLED
                # Notify seller
                from app.services.notification_service import NotificationService, NotificationType
                await NotificationService.create_notification(
                    db=db,
                    account_id=listing.account_id,
                    notification_type=NotificationType.LISTING_APPROVED,
                    title="Listing Expired",
                    message=f"Your listing has been automatically expired after 90 days"
                )
            
            await db.commit()
            logger.info(f"Expired {len(old_listings)} listings")
    except Exception as e:
        logger.error(f"Error expiring listings: {e}")
        record_job_failure("expire_listings")


async def recalculate_portfolios():
    """Recalculate all portfolio values"""
    from app.database import AsyncSessionLocal
    from app.models.account import Account
    from app.models.asset import Asset
    from app.models.portfolio import Portfolio
    from sqlalchemy import select
    from datetime import datetime
    
    try:
        async with AsyncSessionLocal() as db:
            accounts_result = await db.execute(select(Account))
            accounts = accounts_result.scalars().all()
            
            for account in accounts:
                assets_result = await db.execute(
                    select(Asset).where(Asset.account_id == account.id)
                )
                assets = assets_result.scalars().all()
                
                total_value = sum([asset.current_value for asset in assets])
                
                portfolio_result = await db.execute(
                    select(Portfolio).where(Portfolio.account_id == account.id)
                )
                portfolio = portfolio_result.scalar_one_or_none()
                
                if portfolio:
                    portfolio.total_value = total_value
                    portfolio.last_updated = datetime.utcnow()
                else:
                    portfolio = Portfolio(
                        account_id=account.id,
                        total_value=total_value,
                        currency="USD"
                    )
                    db.add(portfolio)
            
            await db.commit()
            logger.info(f"Recalculated portfolios for {len(accounts)} accounts")
    except Exception as e:
        logger.error(f"Error recalculating portfolios: {e}")
        record_job_failure("recalculate_portfolios")


async def process_subscription_renewals():
    """Process subscription renewals and handle failed payments"""
    from app.database import AsyncSessionLocal
    from app.models.payment import Subscription, SubscriptionStatus
    from app.integrations.stripe_client import StripeClient
    from sqlalchemy import select
    from datetime import datetime, timedelta
    
    try:
        async with AsyncSessionLocal() as db:
            # Find expired subscriptions
            expired_result = await db.execute(
                select(Subscription).where(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.current_period_end < datetime.utcnow()
                )
            )
            expired_subscriptions = expired_result.scalars().all()
            
            for subscription in expired_subscriptions:
                # Check Stripe for payment status
                if subscription.stripe_subscription_id:
                    try:
                        import stripe
                        stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
                        if stripe_sub.status == "active":
                            # Still active in Stripe, update local
                            subscription.current_period_start = datetime.fromtimestamp(
                                stripe_sub.current_period_start
                            )
                            subscription.current_period_end = datetime.fromtimestamp(
                                stripe_sub.current_period_end
                            )
                            continue
                        elif stripe_sub.status == "past_due":
                            subscription.status = SubscriptionStatus.PAST_DUE
                            # Retry logic handled by Stripe
                            continue
                    except Exception as e:
                        logger.error(f"Error checking Stripe subscription {subscription.id}: {e}")
                
                # Mark as expired and notify
                subscription.status = SubscriptionStatus.EXPIRED
                
                from app.services.notification_service import NotificationService, NotificationType
                await NotificationService.create_notification(
                    db=db,
                    account_id=subscription.account_id,
                    notification_type=NotificationType.GENERAL,
                    title="Subscription Expired",
                    message="Your subscription has expired. Please renew to continue using premium features."
                )
            
            await db.commit()
            logger.info(f"Processed {len(expired_subscriptions)} expired subscriptions")
    except Exception as e:
        logger.error(f"Error processing subscription renewals: {e}")
        record_job_failure("subscription_renewals")


async def monitor_sla_breaches():
    """Monitor support tickets for SLA breaches"""
    from app.database import AsyncSessionLocal
    from app.models.support import SupportTicket, TicketStatus
    from sqlalchemy import select
    from datetime import datetime
    from app.services.sla_service import SLAService
    
    try:
        async with AsyncSessionLocal() as db:
            open_tickets_result = await db.execute(
                select(SupportTicket).where(
                    SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS])
                )
            )
            open_tickets = open_tickets_result.scalars().all()
            
            breached_count = 0
            for ticket in open_tickets:
                if await SLAService.check_sla_breach(db, ticket):
                    breached_count += 1
                    if not ticket.sla_breached_at:
                        ticket.sla_breached_at = datetime.utcnow()
                        ticket.escalation_count += 1
                        await SLAService.escalate_ticket(db, ticket)
            
            await db.commit()
            logger.info(f"Monitored {len(open_tickets)} tickets, {breached_count} SLA breaches detected")
    except Exception as e:
        logger.error(f"Error monitoring SLA breaches: {e}")
        record_job_failure("monitor_sla")


async def banking_sync_all():
    """Sync transactions and balance for all active linked bank accounts. Runs every 6 hours."""
    from app.database import AsyncSessionLocal
    from app.models.banking import LinkedAccount
    from app.services.banking_sync_service import sync_linked_account_transactions, refresh_linked_account_balance
    from sqlalchemy import select
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(LinkedAccount).where(LinkedAccount.is_active == True)
            )
            linked_accounts = result.scalars().all()
            for la in linked_accounts:
                try:
                    await sync_linked_account_transactions(db, la.id)
                    await refresh_linked_account_balance(db, la.id)
                except Exception as e:
                    logger.warning(f"Banking sync failed for linked account {la.id}: {e}")
            logger.info(f"Banking sync completed for {len(linked_accounts)} linked accounts")
    except Exception as e:
        logger.error(f"Error in banking_sync_all: {e}")
        record_job_failure("banking_sync_all")


async def process_subscription_retry_and_downgrade():
    """Sync past_due from Stripe; downgrade to FREE after prolonged failure. Runs daily."""
    from app.database import AsyncSessionLocal
    from app.models.payment import Subscription, SubscriptionStatus, SubscriptionPlan
    from app.services.notification_service import NotificationService, NotificationType
    from sqlalchemy import select
    from datetime import datetime, timedelta
    import stripe
    try:
        async with AsyncSessionLocal() as db:
            # Sync past_due status from Stripe
            past_due_result = await db.execute(
                select(Subscription).where(Subscription.status == SubscriptionStatus.PAST_DUE)
            )
            for sub in past_due_result.scalars().all():
                if sub.stripe_subscription_id:
                    try:
                        stripe_sub = stripe.Subscription.retrieve(sub.stripe_subscription_id)
                        if stripe_sub.status == "active":
                            sub.status = SubscriptionStatus.ACTIVE
                            sub.current_period_start = datetime.fromtimestamp(stripe_sub.current_period_start)
                            sub.current_period_end = datetime.fromtimestamp(stripe_sub.current_period_end)
                        elif stripe_sub.status == "canceled" or stripe_sub.status == "unpaid":
                            sub.status = SubscriptionStatus.EXPIRED
                    except Exception as e:
                        logger.warning(f"Stripe sync for subscription {sub.id}: {e}")
            # Downgrade expired subscriptions (e.g. after 7 days) to FREE
            cutoff = datetime.utcnow() - timedelta(days=7)
            expired_result = await db.execute(
                select(Subscription).where(
                    Subscription.status.in_([SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELLED]),
                    Subscription.updated_at < cutoff
                )
            )
            for sub in expired_result.scalars().all():
                if sub.plan != SubscriptionPlan.FREE:
                    sub.plan = SubscriptionPlan.FREE
                    await NotificationService.create_notification(
                        db=db,
                        account_id=sub.account_id,
                        notification_type=NotificationType.GENERAL,
                        title="Subscription ended",
                        message="Your subscription has ended. You are now on the Free plan."
                    )
            await db.commit()
        logger.info("Subscription retry and downgrade job completed")
    except Exception as e:
        logger.error(f"Error in process_subscription_retry_and_downgrade: {e}")
        record_job_failure("subscription_retry_downgrade")

