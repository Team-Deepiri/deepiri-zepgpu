"""Fix schema drift for live Phase 4 smoke tests.

Revision ID: 012_fix_phase4_schema_drift
Revises: 011_schema_alignment
Create Date: 2026-07-17
"""

revision = "012_fix_phase4_schema_drift"
down_revision = "011_schema_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: these columns were already added in migration 007.
    # This migration was a duplicate created during schema drift fixes.
    pass


def downgrade() -> None:
    # No-op: corresponding upgrade is a no-op.
    pass
