"""Initial migration - all models

Revision ID: 001_initial
Revises: 
Create Date: 2024-12-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(100)),
        sa.Column('last_name', sa.String(100)),
        sa.Column('phone', sa.String(20)),
        sa.Column('role', sa.Enum('INVESTOR', 'ADVISOR', 'ADMIN', name='role'), nullable=False, default='INVESTOR'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False, default=False),
        sa.Column('email_verification_token', sa.String(255)),
        sa.Column('email_verified_at', sa.DateTime(timezone=True)),
        sa.Column('otp_code', sa.String(6)),
        sa.Column('otp_expires_at', sa.DateTime(timezone=True)),
        sa.Column('password_reset_token', sa.String(255)),
        sa.Column('password_reset_expires_at', sa.DateTime(timezone=True)),
        sa.Column('refresh_token', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('last_login', sa.DateTime(timezone=True)),
    )
    
    # Accounts table
    op.create_table(
        'accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('account_type', sa.Enum('INDIVIDUAL', 'CORPORATE', 'TRUST', name='accounttype'), nullable=False),
        sa.Column('account_name', sa.String(255), nullable=False),
        sa.Column('is_joint', sa.Boolean(), nullable=False, default=False),
        sa.Column('joint_users', sa.String(500)),
        sa.Column('tax_id', sa.String(50)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Joint account invitations
    op.create_table(
        'joint_account_invitations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('invited_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('invited_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('token', sa.String(255), nullable=False, unique=True),
        sa.Column('status', sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED', name='invitationstatus'), nullable=False, default='PENDING'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # KYC Verifications
    op.create_table(
        'kyc_verifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False, unique=True),
        sa.Column('persona_inquiry_id', sa.String(255), unique=True),
        sa.Column('status', sa.Enum('NOT_STARTED', 'IN_PROGRESS', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'EXPIRED', name='kycstatus'), nullable=False, default='NOT_STARTED'),
        sa.Column('verification_level', sa.String(50)),
        sa.Column('persona_response', postgresql.JSONB),
        sa.Column('documents_submitted', sa.Boolean(), default=False),
        sa.Column('verified_at', sa.DateTime(timezone=True)),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('rejection_reason', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # KYB Verifications
    op.create_table(
        'kyb_verifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False, unique=True),
        sa.Column('persona_kyb_inquiry_id', sa.String(255), unique=True),
        sa.Column('verification_type', sa.String(50), nullable=False),
        sa.Column('status', sa.Enum('NOT_STARTED', 'IN_PROGRESS', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'EXPIRED', name='kybstatus'), nullable=False, default='NOT_STARTED'),
        sa.Column('business_name', sa.String(255)),
        sa.Column('business_registration_number', sa.String(100)),
        sa.Column('business_address', sa.String(500)),
        sa.Column('persona_response', postgresql.JSONB),
        sa.Column('documents_submitted', sa.Boolean(), default=False),
        sa.Column('verified_at', sa.DateTime(timezone=True)),
        sa.Column('rejection_reason', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Assets
    op.create_table(
        'assets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('asset_type', sa.Enum('STOCK', 'BOND', 'REAL_ESTATE', 'LUXURY_ASSET', 'CRYPTO', 'OTHER', name='assettype'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('symbol', sa.String(50)),
        sa.Column('description', sa.Text()),
        sa.Column('current_value', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('metadata', postgresql.JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Asset Valuations
    op.create_table(
        'asset_valuations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('asset_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('assets.id'), nullable=False),
        sa.Column('value', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('valuation_method', sa.String(100)),
        sa.Column('valuation_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Asset Ownership
    op.create_table(
        'asset_ownership',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('asset_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('assets.id'), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('ownership_percentage', sa.Numeric(5, 2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Portfolios
    op.create_table(
        'portfolios',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False, unique=True),
        sa.Column('total_value', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('performance_data', postgresql.JSONB),
        sa.Column('asset_allocation', postgresql.JSONB),
        sa.Column('last_updated', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Orders
    op.create_table(
        'orders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('order_type', sa.Enum('MARKET', 'LIMIT', 'STOP', name='ordertype'), nullable=False),
        sa.Column('symbol', sa.String(50), nullable=False),
        sa.Column('quantity', sa.Numeric(20, 8), nullable=False),
        sa.Column('price', sa.Numeric(20, 2)),
        sa.Column('stop_price', sa.Numeric(20, 2)),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'SUBMITTED', 'FILLED', 'PARTIALLY_FILLED', 'CANCELLED', 'REJECTED', name='orderstatus'), nullable=False, default='PENDING'),
        sa.Column('alpaca_order_id', sa.String(255)),
        sa.Column('filled_quantity', sa.Numeric(20, 8)),
        sa.Column('filled_price', sa.Numeric(20, 2)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Order History
    op.create_table(
        'order_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('orders.id'), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'SUBMITTED', 'FILLED', 'PARTIALLY_FILLED', 'CANCELLED', 'REJECTED', name='orderstatus'), nullable=False),
        sa.Column('notes', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Marketplace Listings
    op.create_table(
        'marketplace_listings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('asset_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('assets.id'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('asking_price', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('listing_fee', sa.Numeric(20, 2)),
        sa.Column('listing_fee_paid', sa.Boolean(), default=False),
        sa.Column('status', sa.Enum('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'ACTIVE', 'SOLD', 'CANCELLED', name='listingstatus'), nullable=False, default='DRAFT'),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('approved_at', sa.DateTime(timezone=True)),
        sa.Column('metadata', postgresql.JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Offers
    op.create_table(
        'offers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('marketplace_listings.id'), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('offer_amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', 'COUNTERED', 'EXPIRED', 'WITHDRAWN', name='offerstatus'), nullable=False, default='PENDING'),
        sa.Column('message', sa.Text()),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Escrow Transactions
    op.create_table(
        'escrow_transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('marketplace_listings.id'), nullable=False),
        sa.Column('offer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('offers.id'), nullable=False),
        sa.Column('buyer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('seller_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('commission', sa.Numeric(20, 2)),
        sa.Column('status', sa.Enum('PENDING', 'FUNDED', 'RELEASED', 'REFUNDED', 'DISPUTED', name='escrowstatus'), nullable=False, default='PENDING'),
        sa.Column('stripe_payment_intent_id', sa.String(255)),
        sa.Column('released_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Payments
    op.create_table(
        'payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('payment_method', sa.Enum('CARD', 'ACH', 'CRYPTO', name='paymentmethod'), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'REFUNDED', 'CANCELLED', name='paymentstatus'), nullable=False, default='PENDING'),
        sa.Column('stripe_payment_intent_id', sa.String(255)),
        sa.Column('stripe_charge_id', sa.String(255)),
        sa.Column('description', sa.String(500)),
        sa.Column('metadata', sa.String(1000)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Refunds
    op.create_table(
        'refunds',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('payment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payments.id'), nullable=False),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('stripe_refund_id', sa.String(255), unique=True),
        sa.Column('reason', sa.String(100)),
        sa.Column('status', sa.String(50), default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Invoices
    op.create_table(
        'invoices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('payment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payments.id')),
        sa.Column('invoice_number', sa.String(100), nullable=False, unique=True),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('description', sa.String(500)),
        sa.Column('due_date', sa.DateTime(timezone=True)),
        sa.Column('paid_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Subscriptions
    op.create_table(
        'subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False, unique=True),
        sa.Column('plan', sa.Enum('FREE', 'MONTHLY', 'ANNUAL', name='subscriptionplan'), nullable=False),
        sa.Column('status', sa.Enum('ACTIVE', 'CANCELLED', 'EXPIRED', 'PAST_DUE', name='subscriptionstatus'), nullable=False, default='ACTIVE'),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('stripe_subscription_id', sa.String(255)),
        sa.Column('current_period_start', sa.DateTime(timezone=True)),
        sa.Column('current_period_end', sa.DateTime(timezone=True)),
        sa.Column('cancelled_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Linked Accounts (Banking)
    op.create_table(
        'linked_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('plaid_item_id', sa.String(255)),
        sa.Column('plaid_access_token', sa.String(500)),
        sa.Column('account_type', sa.Enum('BANKING', 'BROKERAGE', 'CRYPTO', name='linkedaccounttype')),
        sa.Column('institution_name', sa.String(255)),
        sa.Column('account_name', sa.String(255)),
        sa.Column('account_number', sa.String(100)),
        sa.Column('routing_number', sa.String(50)),
        sa.Column('balance', sa.Numeric(20, 2)),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True)),
        sa.Column('metadata', postgresql.JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Transactions (Banking)
    op.create_table(
        'transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('linked_account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('linked_accounts.id'), nullable=False),
        sa.Column('plaid_transaction_id', sa.String(255), unique=True),
        sa.Column('amount', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('description', sa.String(500)),
        sa.Column('category', sa.String(100)),
        sa.Column('transaction_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('metadata', postgresql.JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Documents
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('document_type', sa.Enum('KYC', 'KYC_DOCUMENT', 'ASSET_DOCUMENT', 'CONTRACT', 'INVOICE', 'REPORT', 'OTHER', name='documenttype'), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_path', sa.String(500)),
        sa.Column('file_size', sa.Integer()),
        sa.Column('mime_type', sa.String(100)),
        sa.Column('supabase_storage_path', sa.String(500)),
        sa.Column('description', sa.Text()),
        sa.Column('metadata', sa.String(1000)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Support Tickets
    op.create_table(
        'support_tickets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('subject', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED', name='ticketstatus'), nullable=False, default='OPEN'),
        sa.Column('priority', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'URGENT', name='ticketpriority'), nullable=False, default='MEDIUM'),
        sa.Column('category', sa.String(50)),
        sa.Column('assigned_to', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('sla_target_hours', sa.Integer()),
        sa.Column('first_response_at', sa.DateTime(timezone=True)),
        sa.Column('sla_breached_at', sa.DateTime(timezone=True)),
        sa.Column('escalation_count', sa.Integer(), default=0),
        sa.Column('last_escalated_at', sa.DateTime(timezone=True)),
        sa.Column('resolved_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Ticket Replies
    op.create_table(
        'ticket_replies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('ticket_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('support_tickets.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.String(10), default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Notifications
    op.create_table(
        'notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('notification_type', sa.Enum('ORDER_FILLED', 'ORDER_CANCELLED', 'OFFER_RECEIVED', 'OFFER_ACCEPTED', 'LISTING_APPROVED', 'PAYMENT_RECEIVED', 'KYC_APPROVED', 'SUPPORT_REPLY', 'GENERAL', name='notificationtype'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, default=False),
        sa.Column('read_at', sa.DateTime(timezone=True)),
        sa.Column('metadata', sa.String(1000)),
        sa.Column('email_sent', sa.Boolean(), nullable=False, default=False),
        sa.Column('email_sent_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('notifications')
    op.drop_table('ticket_replies')
    op.drop_table('support_tickets')
    op.drop_table('documents')
    op.drop_table('transactions')
    op.drop_table('linked_accounts')
    op.drop_table('subscriptions')
    op.drop_table('invoices')
    op.drop_table('refunds')
    op.drop_table('payments')
    op.drop_table('escrow_transactions')
    op.drop_table('offers')
    op.drop_table('marketplace_listings')
    op.drop_table('order_history')
    op.drop_table('orders')
    op.drop_table('portfolios')
    op.drop_table('asset_ownership')
    op.drop_table('asset_valuations')
    op.drop_table('assets')
    op.drop_table('kyb_verifications')
    op.drop_table('kyc_verifications')
    op.drop_table('joint_account_invitations')
    op.drop_table('accounts')
    op.drop_table('users')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS notificationtype")
    op.execute("DROP TYPE IF EXISTS ticketpriority")
    op.execute("DROP TYPE IF EXISTS ticketstatus")
    op.execute("DROP TYPE IF EXISTS documenttype")
    op.execute("DROP TYPE IF EXISTS linkedaccounttype")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")
    op.execute("DROP TYPE IF EXISTS subscriptionplan")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
    op.execute("DROP TYPE IF EXISTS paymentmethod")
    op.execute("DROP TYPE IF EXISTS escrowstatus")
    op.execute("DROP TYPE IF EXISTS offerstatus")
    op.execute("DROP TYPE IF EXISTS listingstatus")
    op.execute("DROP TYPE IF EXISTS orderstatus")
    op.execute("DROP TYPE IF EXISTS ordertype")
    op.execute("DROP TYPE IF EXISTS assettype")
    op.execute("DROP TYPE IF EXISTS kybstatus")
    op.execute("DROP TYPE IF EXISTS kycstatus")
    op.execute("DROP TYPE IF EXISTS invitationstatus")
    op.execute("DROP TYPE IF EXISTS accounttype")
    op.execute("DROP TYPE IF EXISTS role")

