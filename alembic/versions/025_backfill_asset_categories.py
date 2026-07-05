"""Backfill categories on legacy/uncategorized assets

Marketplace browse is now category-driven and listings require a categorized
asset before approval/auto-publish, so existing NULL category_id rows would
become unreachable/second-class. Maps the legacy asset_type to the closest
canonical category; everything else lands in a new "Other" catch-all category
(group "Assets"). Also fills assets.category_group from the resolved category.

Revision ID: 025_backfill_asset_categories
Revises: 024_appraisal_doc_type
Create Date: 2026-07-05

"""
import uuid

from alembic import op


revision = "025_backfill_asset_categories"
down_revision = "024_appraisal_doc_type"
branch_labels = None
depends_on = None


# Legacy asset_type (stored UPPERCASE) -> canonical seeded category name.
# Types with no clean canonical match (LUXURY_ASSET, OTHER, NULL) fall through
# to the "Other" catch-all.
_ASSET_TYPE_TO_CATEGORY = {
    "REAL_ESTATE": "Real Estate",
    "STOCK": "Public Equities",
    "BOND": "Fixed Income",
    "CRYPTO": "Crypto Assets",
}


def upgrade() -> None:
    # 1. Ensure the "Other" catch-all category exists (idempotent).
    other_id = str(uuid.uuid4())
    op.execute(
        f"""
        INSERT INTO asset_categories (id, name, category_group, description, is_active, created_at)
        SELECT '{other_id}', 'Other', 'Assets'::categorygroup,
               'Catch-all for assets without a more specific category', true, now()
        WHERE NOT EXISTS (SELECT 1 FROM asset_categories WHERE name = 'Other')
        """
    )

    # 2. Map uncategorized assets from their legacy asset_type where a canonical
    #    category exists in this environment.
    when_clauses = "\n".join(
        f"              WHEN '{asset_type}' THEN '{category}'"
        for asset_type, category in _ASSET_TYPE_TO_CATEGORY.items()
    )
    op.execute(
        f"""
        UPDATE assets a
        SET category_id = c.id
        FROM asset_categories c
        WHERE a.category_id IS NULL
          AND c.name = CASE a.asset_type::text
{when_clauses}
              ELSE 'Other'
          END
        """
    )

    # 3. Safety net: any asset still NULL (e.g. a mapped canonical category was
    #    never seeded in this environment) goes to "Other".
    op.execute(
        """
        UPDATE assets
        SET category_id = (SELECT id FROM asset_categories WHERE name = 'Other' LIMIT 1)
        WHERE category_id IS NULL
        """
    )

    # 4. Fill the denormalized category_group from the resolved category.
    op.execute(
        """
        UPDATE assets a
        SET category_group = c.category_group
        FROM asset_categories c
        WHERE a.category_id = c.id
          AND a.category_group IS NULL
        """
    )


def downgrade() -> None:
    # Data backfill — original NULLs are not recorded, so this is irreversible.
    # The "Other" category is left in place (assets may reference it).
    pass
