"""Fix schema drift for live Phase 4 smoke tests.

Revision ID: 012_fix_phase4_schema_drift
Revises: 011_schema_alignment
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "012_fix_phase4_schema_drift"
down_revision = "011_schema_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # User model fields used by auth/profile code.
    op.add_column(
        "users",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("users", sa.Column("first_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    # UserQuota model fields used during registration.
    op.add_column(
        "user_quotas",
        sa.Column(
            "max_storage_gb",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )
    op.add_column(
        "user_quotas",
        sa.Column(
            "storage_used_gb",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        ),
    )

    # Keep tasks.priority as INTEGER — ORM/API still use TaskPriority IntEnum values.
    # A native Postgres enum here breaks Integer-backed inserts.

    # Node assignment lifecycle uses ASSIGNED during Phase 4 room dispatch.
    op.execute("ALTER TYPE nodeassignmentstatus ADD VALUE IF NOT EXISTS 'ASSIGNED'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be safely removed without recreating the enum.
    # Leave nodeassignmentstatus.ASSIGNED in place on downgrade.

    op.drop_column("user_quotas", "storage_used_gb")
    op.drop_column("user_quotas", "max_storage_gb")

    op.drop_column("users", "last_login_at")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "is_verified")
