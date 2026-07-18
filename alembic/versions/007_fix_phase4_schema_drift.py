"""Fix schema drift for live Phase 4 smoke tests.

Revision ID: 007
Revises: 006
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "007"
down_revision = "006"
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

    # tasks.priority is used as a PostgreSQL enum by the ORM.
    taskpriority = postgresql.ENUM(
        "LOW",
        "NORMAL",
        "HIGH",
        "CRITICAL",
        name="taskpriority",
    )
    taskpriority.create(op.get_bind(), checkfirst=True)

    op.execute("ALTER TABLE tasks ALTER COLUMN priority DROP DEFAULT")
    op.alter_column(
        "tasks",
        "priority",
        existing_type=sa.Integer(),
        type_=taskpriority,
        postgresql_using="'NORMAL'::taskpriority",
        nullable=False,
    )
    op.execute("ALTER TABLE tasks ALTER COLUMN priority SET DEFAULT 'NORMAL'::taskpriority")

    # Node assignment lifecycle uses ASSIGNED during Phase 4 room dispatch.
    op.execute("ALTER TYPE nodeassignmentstatus ADD VALUE IF NOT EXISTS 'ASSIGNED'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be safely removed without recreating the enum.
    # Leave nodeassignmentstatus.ASSIGNED in place on downgrade.

    op.execute("ALTER TABLE tasks ALTER COLUMN priority DROP DEFAULT")
    op.alter_column(
        "tasks",
        "priority",
        existing_type=postgresql.ENUM(
            "LOW",
            "NORMAL",
            "HIGH",
            "CRITICAL",
            name="taskpriority",
            create_type=False,
        ),
        type_=sa.Integer(),
        postgresql_using="1",
        nullable=False,
    )
    op.execute("ALTER TABLE tasks ALTER COLUMN priority SET DEFAULT 1")

    op.drop_column("user_quotas", "storage_used_gb")
    op.drop_column("user_quotas", "max_storage_gb")

    op.drop_column("users", "last_login_at")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "is_verified")
