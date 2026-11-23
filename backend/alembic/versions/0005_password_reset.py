"""Password reset tokens, persistent request limits and bounded mail slots."""
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"


def upgrade():
    op.create_table(
        "password_reset_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("auth_version", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"])
    rates = op.create_table(
        "password_reset_rates",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.DateTime, nullable=False),
        sa.Column("count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_request_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_password_reset_rates_last_request_at", "password_reset_rates", ["last_request_at"])
    slots = op.create_table(
        "password_reset_mail_slots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime, nullable=False),
    )
    epoch = datetime(1970, 1, 1)
    op.bulk_insert(rates, [{"key": key, "window_start": epoch, "count": 0, "last_request_at": epoch}
                           for key in ("global-minute", "global-hour")])
    op.bulk_insert(slots, [{"id": index, "owner": None, "lease_until": epoch} for index in range(1, 5)])


def downgrade():
    op.drop_table("password_reset_mail_slots")
    op.drop_table("password_reset_rates")
    op.drop_table("password_reset_tokens")
