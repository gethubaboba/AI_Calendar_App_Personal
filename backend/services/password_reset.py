"""Single-use reset credentials and bounded, non-enumerating email requests."""
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError

from auth import hash_password
from db import SessionLocal
from models import MFAChallenge, PasswordResetMailSlot, PasswordResetRate, PasswordResetToken, User
from services.reset_mail import send_reset_mail

logger = logging.getLogger(__name__)
REQUEST_MESSAGE = "Если для этого адреса доступно восстановление, мы отправим инструкции на почту."
RESET_MESSAGE = "Пароль изменён. Войдите с новым паролем."
INVALID_MESSAGE = "Ссылка недействительна или истекла. Запросите новую."
TOKEN_SECONDS = 15 * 60
COOLDOWN_SECONDS = 60
EMAIL_HOURLY_LIMIT = 5
GLOBAL_MINUTE_LIMIT = 10
GLOBAL_HOURLY_LIMIT = 100
LEASE_SECONDS = 60
RATE_LOCK_ID = 1347572564
COMMON_PASSWORDS = {
    "password1234", "password12345", "password123456", "password123!",
    "qwerty123456", "qwerty12345678", "123456789012", "123456789012345",
    "letmein123456", "admin12345678", "changeme12345",
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bounded_transaction(db):
    db.execute(text("SET LOCAL statement_timeout = '2s'"))
    db.execute(text("SET LOCAL lock_timeout = '1s'"))


def reserve_delivery(db, email):
    """No account lookup here; all valid addresses follow the same request path."""
    now = utcnow()
    try:
        bounded_transaction(db)
        if not db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": RATE_LOCK_ID}).scalar():
            db.rollback()
            return None
        minute = db.get(PasswordResetRate, "global-minute")
        hour = db.get(PasswordResetRate, "global-hour")
        for rate, seconds in ((minute, 60), (hour, 3600)):
            if now >= rate.window_start + timedelta(seconds=seconds):
                rate.window_start, rate.count = now, 0
        if minute.count >= GLOBAL_MINUTE_LIMIT or hour.count >= GLOBAL_HOURLY_LIMIT:
            db.rollback()
            return None
        db.query(PasswordResetRate).filter(
            PasswordResetRate.key.notin_(("global-minute", "global-hour")),
            PasswordResetRate.last_request_at < now - timedelta(days=1),
        ).delete(synchronize_session=False)
        key = digest(email)
        email_rate = db.get(PasswordResetRate, key)
        if email_rate is None:
            email_rate = PasswordResetRate(key=key, window_start=now, count=0, last_request_at=now)
            db.add(email_rate)
        else:
            if now >= email_rate.window_start + timedelta(hours=1):
                email_rate.window_start, email_rate.count = now, 0
            if (now < email_rate.last_request_at + timedelta(seconds=COOLDOWN_SECONDS)
                    or email_rate.count >= EMAIL_HOURLY_LIMIT):
                db.rollback()
                return None
        slot = (db.query(PasswordResetMailSlot).filter(PasswordResetMailSlot.lease_until <= now)
                .order_by(PasswordResetMailSlot.id).with_for_update(skip_locked=True).first())
        if slot is None:
            db.rollback()
            return None
        owner = secrets.token_hex(16)
        slot.owner, slot.lease_until = owner, now + timedelta(seconds=LEASE_SECONDS)
        for rate in (minute, hour, email_rate):
            rate.count += 1
            rate.last_request_at = now
        slot_id = slot.id
        db.commit()
        return slot_id, owner
    except SQLAlchemyError:
        db.rollback()
        logger.warning("password_reset_request_storage_unavailable")
        raise HTTPException(503, "Восстановление пароля временно недоступно") from None


def deliver_reset(email, config, slot_id, owner):
    """Runs after the HTTP response, with its own session and no shared request DB."""
    token_hash = None
    try:
        with SessionLocal() as db:
            bounded_transaction(db)
            slot = db.query(PasswordResetMailSlot).filter_by(id=slot_id, owner=owner).with_for_update().first()
            if slot is None or slot.lease_until <= utcnow():
                return
            slot.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
            db.commit()
            bounded_transaction(db)
            # Existing email spelling is retained for delivery. Ambiguous legacy
            # case variants are suppressed instead of selecting an arbitrary user.
            users = (db.query(User).filter(func.lower(User.email) == email)
                     .order_by(User.id).limit(2).with_for_update().all())
            if len(users) != 1 or not users[0].password_hash:
                return
            user = users[0]
            token = secrets.token_urlsafe(32)
            token_hash = digest(token)
            recipient = user.email
            db.query(PasswordResetToken).filter_by(user_id=user.id).delete(synchronize_session=False)
            db.add(PasswordResetToken(token_hash=token_hash, user_id=user.id,
                                       auth_version=user.auth_version,
                                       expires_at=utcnow() + timedelta(seconds=TOKEN_SECONDS)))
            db.commit()
        # Network work happens without database/user locks, under a hard process timeout.
        if send_reset_mail(config, recipient, token):
            token_hash = None
        else:
            logger.warning("password_reset_delivery_failed")
    except Exception:
        # Never log SMTP exceptions, addresses, tokens, or SQL parameters.
        logger.warning("password_reset_delivery_failed")
    finally:
        try:
            with SessionLocal() as db:
                bounded_transaction(db)
                if token_hash:
                    db.query(PasswordResetToken).filter_by(token_hash=token_hash).delete(synchronize_session=False)
                db.query(PasswordResetMailSlot).filter_by(id=slot_id, owner=owner).update(
                    {"owner": None, "lease_until": utcnow()}, synchronize_session=False)
                db.commit()
        except SQLAlchemyError:
            # The lease expires even if cleanup cannot reach the database.
            logger.warning("password_reset_cleanup_failed")


def validate_new_password(password):
    try:
        byte_length = len(password.encode("utf-8"))
    except UnicodeError:
        raise HTTPException(422, "Пароль должен содержать допустимые символы UTF-8.") from None
    if (not 12 <= len(password) <= 72 or byte_length > 72
            or len(password.strip()) < 12 or "\x00" in password
            or password.isdigit() or len(set(password)) < 4
            or password.casefold() in COMMON_PASSWORDS):
        raise HTTPException(422, "Используйте пароль от 12 символов, до 72 байт UTF-8. "
                            "Простой или распространённый пароль не подходит.")


def reset_password(db, token, new_password):
    validate_new_password(new_password)
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(400, INVALID_MESSAGE)
    try:
        bounded_transaction(db)
        token_hash = digest(token)
        credential = db.get(PasswordResetToken, token_hash)
        if credential is None:
            raise HTTPException(400, INVALID_MESSAGE)
        # Same lock order as login/MFA. Refresh the token after acquiring user.
        user = db.query(User).filter_by(id=credential.user_id).with_for_update().populate_existing().first()
        credential = (db.query(PasswordResetToken).filter_by(token_hash=token_hash)
                      .with_for_update().populate_existing().first())
        if (user is None or credential is None or credential.expires_at <= utcnow()
                or credential.auth_version != user.auth_version):
            raise HTTPException(400, INVALID_MESSAGE)
        user.password_hash = hash_password(new_password)
        user.auth_version += 1
        user.password_failures = 0
        user.password_locked_until = None
        user.mfa_pending_secret = None
        user.mfa_pending_expires_at = None
        # Enabled TOTP, accepted timecode, recovery hashes and MFA limits survive.
        db.query(MFAChallenge).filter_by(user_id=user.id).delete(synchronize_session=False)
        db.query(PasswordResetToken).filter_by(user_id=user.id).delete(synchronize_session=False)
        db.commit()
        return {"message": RESET_MESSAGE}
    except SQLAlchemyError:
        db.rollback()
        logger.warning("password_reset_write_unavailable")
        raise HTTPException(503, "Восстановление пароля временно недоступно") from None
