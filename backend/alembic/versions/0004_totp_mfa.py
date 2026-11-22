"""Optional TOTP enrollment, session revocation and persistent challenges."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"


def upgrade():
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("mfa_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("mfa_pending_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("mfa_pending_expires_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("mfa_last_step", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("mfa_recovery_hashes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    for prefix in ("mfa", "password"):
        op.add_column("users", sa.Column(prefix + "_failures", sa.Integer(), nullable=False, server_default=sa.text("0")))
        op.add_column("users", sa.Column(prefix + "_locked_until", sa.DateTime(), nullable=True))
    op.create_table(
        "mfa_challenges",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auth_version", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_mfa_challenges_user_id", "mfa_challenges", ["user_id"])
    op.create_index("ix_mfa_challenges_expires_at", "mfa_challenges", ["expires_at"])


def downgrade():
    op.drop_table("mfa_challenges")
    for name in (
        "password_locked_until", "password_failures", "mfa_locked_until", "mfa_failures",
        "mfa_recovery_hashes", "mfa_last_step", "mfa_pending_expires_at",
        "mfa_pending_secret", "mfa_secret", "mfa_enabled", "auth_version",
    ):
        op.drop_column("users", name)
