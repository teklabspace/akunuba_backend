"""Give reports.report_type its own PG enum.

`reports.report_type` and `asset_reports.report_type` were both mapped to the
PG type `reporttype`, whose labels are the ASSET set
(summary/detailed/tax/insurance). app/models/report.py declares an unrelated
ReportType (portfolio/performance/transaction/tax/custom), so every insert into
`reports` failed with InvalidTextRepresentation and the table had zero rows —
POST /reports/generate could never succeed, which is why the Export button had
nothing to download.

Same class of collision the codebase already hit with `assettype` being reused
by investment_watchlist: two Python enums sharing a class name end up sharing a
PG type name.

`reports` is empty, so the column swap needs no value migration; the USING cast
is present for safety only ('tax' is the sole overlapping label).

Revision ID: 042_platform_report_type
Revises: 041_portfolio_shares
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

revision = "042_platform_report_type"
down_revision = "041_portfolio_shares"
branch_labels = None
depends_on = None

PLATFORM_REPORT_TYPES = ("portfolio", "performance", "transaction", "tax", "custom")
ASSET_REPORT_TYPES = ("summary", "detailed", "tax", "insurance")


def upgrade() -> None:
    ENUM(*PLATFORM_REPORT_TYPES, name="platformreporttype").create(
        op.get_bind(), checkfirst=True
    )
    op.execute(
        "ALTER TABLE reports "
        "ALTER COLUMN report_type TYPE platformreporttype "
        "USING report_type::text::platformreporttype"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE reports "
        "ALTER COLUMN report_type TYPE reporttype "
        "USING report_type::text::reporttype"
    )
    ENUM(name="platformreporttype").drop(op.get_bind(), checkfirst=True)
