from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.utils.logger import logger
from app.config import settings

scheduler = AsyncIOScheduler(timezone="UTC")


def setup_scheduled_tasks():
    """Setup all scheduled background tasks"""
    try:
        # Offer expiration - check every hour
        scheduler.add_job(
            expire_offers,
            IntervalTrigger(hours=1),
            id='expire_offers',
            replace_existing=True,
            max_instances=1
        )
        
        # Portfolio recalculation - daily at 2 AM UTC
        scheduler.add_job(
            recalculate_portfolios,
            CronTrigger(hour=2, minute=0),
            id='recalculate_portfolios',
            replace_existing=True,
            max_instances=1
        )
        
        # Subscription renewal check - daily at 3 AM UTC
        scheduler.add_job(
            process_subscription_renewals,
            CronTrigger(hour=3, minute=0),
            id='subscription_renewals',
            replace_existing=True,
            max_instances=1
        )
        
        # Listing expiration - daily at 4 AM UTC
        scheduler.add_job(
            expire_listings,
            CronTrigger(hour=4, minute=0),
            id='expire_listings',
            replace_existing=True,
            max_instances=1
        )
        
        # SLA monitoring - every 6 hours
        scheduler.add_job(
            monitor_sla_breaches,
            IntervalTrigger(hours=6),
            id='monitor_sla',
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

