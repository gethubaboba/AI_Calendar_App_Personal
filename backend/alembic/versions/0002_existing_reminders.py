"""Schedule in-app reminders for existing calendar entries."""
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.execute("""
        INSERT INTO notifications (user_id, event_id, message, is_read, send_at, sent)
        SELECT e.user_id, e.id, to_char(e.date, 'DD.MM.YYYY') || ' — ' || e.title,
               false, e.date, false
        FROM events AS e
        WHERE e.date >= CURRENT_DATE - 1
          AND NOT EXISTS (SELECT 1 FROM notifications AS n WHERE n.event_id = e.id)
    """)


def downgrade():
    # The baseline schema supports these reminders. Preserve their read state.
    pass
