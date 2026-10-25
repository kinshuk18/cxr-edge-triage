"""Create idempotent studies table and transactional outbox.

Revision ID: 0001_init
Revises:
Create Date: 2026-10-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "studies",
        sa.Column("study_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("sha256_orig", sa.String(length=64), nullable=False),
        sa.Column("sha256_stored", sa.String(length=64), nullable=False),
        sa.Column("idem_key", sa.String(length=200), nullable=True),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("fmt", sa.String(length=16), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("patient_pseudo", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="QUEUED"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker", sa.String(length=128), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "sha256_orig", name="uq_studies_tenant_sha256"),
        sa.CheckConstraint("attempts >= 0", name="ck_studies_attempts_nonnegative"),
        sa.CheckConstraint("status IN ('QUEUED','PROCESSING','DONE','FAILED')", name="ck_studies_status"),
    )
    op.create_index(
        "uq_studies_tenant_idem_key",
        "studies",
        ["tenant_id", "idem_key"],
        unique=True,
        postgresql_where=sa.text("idem_key IS NOT NULL"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "study_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("studies.study_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("routing_key", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("routing_key IN ('stat','routine')", name="ck_outbox_routing_key"),
    )
    op.create_index(
        "ix_outbox_pending_created_at",
        "outbox",
        ["created_at", "id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade():
    op.drop_index("ix_outbox_pending_created_at", table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("uq_studies_tenant_idem_key", table_name="studies")
    op.drop_table("studies")
