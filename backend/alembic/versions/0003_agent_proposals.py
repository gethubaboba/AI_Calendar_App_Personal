from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"


def upgrade():
    op.create_table("agent_proposals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("changes", sa.JSON, nullable=False))
    for key in ("user_id", "expires_at"):
        op.create_index("ix_agent_proposals_" + key, "agent_proposals", [key])


def downgrade():
    op.drop_table("agent_proposals")
