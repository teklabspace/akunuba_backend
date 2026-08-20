"""Close schema drift: tasks, reminders, offers.counter_amount

Found during the 2026-08-19 QA audit by building a database from `alembic upgrade head`
alone and diffing it against the ORM metadata. Three things the migration chain never
created, even though the application depends on them:

  * `tasks` and `reminders` tables  - the Settings tasks/reminders feature
  * `offers.counter_amount`         - the seller's counter price

Production has them (counter-offers work there), so they were applied by hand at some
point rather than through a migration. The consequence is that any environment built
from migrations - staging, disaster recovery, a new region, a new developer - comes up
broken: creating an offer raised
`UndefinedColumnError: column "counter_amount" of relation "offers" does not exist`
(reproduced, HTTP 500), and tasks/reminders had no tables at all.

This is written defensively (IF NOT EXISTS / inspector checks) so it is a no-op against
databases that already have these objects, including production.

Revision ID: 044_schema_drift
Revises: 043_ticket_updated_at_default
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "044_schema_drift"
down_revision = "043_ticket_updated_at_default"
branch_labels = None
depends_on = None


TASK_STATUS = ("pending", "in_progress", "completed", "cancelled")
TASK_PRIORITY = ("low", "medium", "high", "urgent")
REMINDER_STATUS = ("pending", "snoozed", "completed", "cancelled")


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # Enum names must match what SQLAlchemy's SQLEnum derives from the Python enum
    # class names (TaskStatus -> taskstatus), or the ORM will not bind to them.
    for enum_name, values in (
        ("taskstatus", TASK_STATUS),
        ("taskpriority", TASK_PRIORITY),
        ("reminderstatus", REMINDER_STATUS),
    ):
        labels = ", ".join(f"'{v}'" for v in values)
        bind.execute(
            sa.text(
                f"DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{enum_name}') THEN "
                f"CREATE TYPE {enum_name} AS ENUM ({labels}); "
                f"END IF; END $$;"
            )
        )

    if not _has_table("tasks"):
        op.create_table(
            "tasks",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("account_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("accounts.id"), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", postgresql.ENUM(*TASK_STATUS, name="taskstatus",
                                                create_type=False), nullable=False,
                      server_default="pending"),
            sa.Column("priority", postgresql.ENUM(*TASK_PRIORITY, name="taskpriority",
                                                  create_type=False), nullable=False,
                      server_default="medium"),
            sa.Column("category", sa.String(100), nullable=True),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reminder_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        # Every read of this table is scoped to the caller's account.
        op.create_index("ix_tasks_account_id", "tasks", ["account_id"])

    if not _has_table("reminders"):
        op.create_table(
            "reminders",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("account_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("accounts.id"), nullable=False),
            # ondelete CASCADE mirrors the ORM's cascade="all, delete-orphan"; without it
            # deleting a task would leave orphaned reminder rows behind.
            sa.Column("task_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("reminder_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", postgresql.ENUM(*REMINDER_STATUS, name="reminderstatus",
                                                create_type=False), nullable=False,
                      server_default="pending"),
            sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notification_channels", sa.String(100), nullable=True),
            sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_reminders_account_id", "reminders", ["account_id"])
        # The due-reminder sweep queries by date across accounts.
        op.create_index("ix_reminders_reminder_date", "reminders", ["reminder_date"])

    if not _has_column("offers", "counter_amount"):
        op.add_column("offers", sa.Column("counter_amount", sa.Numeric(20, 2), nullable=True))


def downgrade() -> None:
    if _has_column("offers", "counter_amount"):
        op.drop_column("offers", "counter_amount")
    if _has_table("reminders"):
        op.drop_table("reminders")
    if _has_table("tasks"):
        op.drop_table("tasks")
    # Enum types are intentionally left in place: dropping a type that another
    # environment still references would fail the downgrade.
