-- ============================================================
-- SUPABASE DATABASE RESET SQL SCRIPT
-- ============================================================
-- WARNING: This will delete ALL data from ALL tables!
-- Run this in Supabase Dashboard → SQL Editor
-- ============================================================

-- Method 1: Truncate all tables (removes data, keeps structure)
-- This is the recommended method as it's faster and preserves indexes

-- Disable foreign key checks temporarily
SET session_replication_role = 'replica';

-- Truncate all tables in order (respecting foreign key constraints)
TRUNCATE TABLE 
    ticket_replies,
    notifications,
    transactions,
    linked_accounts,
    subscriptions,
    invoices,
    refunds,
    payments,
    escrow_transactions,
    offers,
    marketplace_listings,
    order_histories,
    orders,
    asset_valuations,
    asset_ownerships,
    assets,
    portfolios,
    documents,
    kyb_verifications,
    kyc_verifications,
    support_tickets,
    joint_account_invitations,
    accounts,
    users
CASCADE;

-- Re-enable foreign key checks
SET session_replication_role = 'origin';

-- ============================================================
-- ALTERNATIVE: Drop and recreate all tables
-- ============================================================
-- Uncomment the following if you want to drop all tables:
-- 
-- DROP SCHEMA public CASCADE;
-- CREATE SCHEMA public;
-- GRANT ALL ON SCHEMA public TO postgres;
-- GRANT ALL ON SCHEMA public TO public;
-- 
-- Then run your migrations again:
-- alembic upgrade head
-- ============================================================

-- ============================================================
-- VERIFY: Check table counts (should all be 0)
-- ============================================================
SELECT 
    'users' as table_name, COUNT(*) as row_count FROM users
UNION ALL
SELECT 'accounts', COUNT(*) FROM accounts
UNION ALL
SELECT 'assets', COUNT(*) FROM assets
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'payments', COUNT(*) FROM payments
UNION ALL
SELECT 'documents', COUNT(*) FROM documents
UNION ALL
SELECT 'kyc_verifications', COUNT(*) FROM kyc_verifications
UNION ALL
SELECT 'kyb_verifications', COUNT(*) FROM kyb_verifications
ORDER BY table_name;
