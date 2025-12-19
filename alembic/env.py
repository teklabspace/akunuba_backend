from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import asyncio
from app.database import Base
from app.config import settings

# Import all models to ensure they're registered with Base.metadata
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetValuation, AssetOwnership
from app.models.portfolio import Portfolio
from app.models.order import Order, OrderHistory
from app.models.marketplace import MarketplaceListing, Offer, EscrowTransaction
from app.models.payment import Payment, Refund, Invoice, Subscription
from app.models.banking import LinkedAccount, Transaction
from app.models.kyc import KYCVerification
from app.models.kyb import KYBVerification
from app.models.document import Document
from app.models.support import SupportTicket
from app.models.ticket_reply import TicketReply
from app.models.notification import Notification
from app.models.joint_invitation import JointAccountInvitation

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Use asyncpg-compatible URL for migrations
database_url = settings.DATABASE_URL
if database_url.startswith("postgresql+asyncpg://"):
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

