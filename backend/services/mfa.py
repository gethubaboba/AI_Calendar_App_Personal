"""TOTP enrollment and verification. Call with the user's row locked."""
import hashlib
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from auth import issue_tokens, verify_password
from models import MFAChallenge

MAX_FAILURES = 5
LOCK_SECONDS = 300
CHALLENGE_SECONDS = 300
SETUP_SECONDS = 600
RECOVERY_COUNT = 10


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cipher():
    try:
        return Fernet(os.environ.get("MFA_ENCRYPTION_KEY", "").encode("ascii"))
    except (ValueError, UnicodeError):
        raise HTTPException(503, "Двухфакторная аутентификация временно недоступна") from None


def decrypt_secret(encrypted):
    try:
        return cipher().decrypt(encrypted.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeError):
        raise HTTPException(503, "Двухфакторная аутентификация временно недоступна") from None


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def check_limit(user, prefix):
    until = getattr(user, prefix + "_locked_until")
    if until and until > utcnow():
        raise HTTPException(429, "Слишком много попыток. Повторите позже.",
                            headers={"Retry-After": str(max(1, math.ceil((until - utcnow()).total_seconds())))})
    if until:
        setattr(user, prefix + "_failures", 0)
        setattr(user, prefix + "_locked_until", None)


def failed_attempt(db, user, prefix, challenge=None):
    failures = getattr(user, prefix + "_failures") + 1
    setattr(user, prefix + "_failures", failures)
    if challenge:
        challenge.attempts += 1
    if failures >= MAX_FAILURES:
        setattr(user, prefix + "_locked_until", utcnow() + timedelta(seconds=LOCK_SECONDS))
    # A failed request still persists its retry counter while the row is locked.
    db.commit()
    if failures >= MAX_FAILURES:
        raise HTTPException(429, "Слишком много попыток. Повторите через 5 минут.",
                            headers={"Retry-After": str(LOCK_SECONDS)})
    raise HTTPException(401, "Неверные учётные данные или код")


def require_password(db, user, password):
    check_limit(user, "password")
    if not user.password_hash or not verify_password(password, user.password_hash):
        failed_attempt(db, user, "password")
    user.password_failures = 0
    user.password_locked_until = None


def new_challenge(db, user):
    check_limit(user, "mfa")
    # At most one active challenge per account. A new password login replaces it.
    db.query(MFAChallenge).filter_by(user_id=user.id).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    db.add(MFAChallenge(token_hash=digest(token), user_id=user.id,
                        auth_version=user.auth_version,
                        expires_at=utcnow() + timedelta(seconds=CHALLENGE_SECONDS)))
    db.commit()
    return {"mfa_required": True, "challenge_token": token}


def totp_step(encrypted, code, last_step=None):
    secret = decrypt_secret(encrypted)
    if not re.fullmatch(r"[0-9]{6}", code):
        return None
    try:
        step = pyotp.TOTP(secret).verify_and_get_timecode(
            code, for_time=utcnow().replace(tzinfo=timezone.utc), valid_window=1)
    except pyotp.OTPVerificationError:
        return None
    if last_step is not None and step <= last_step:
        return None
    return step


def accept_factor(db, user, code, challenge=None):
    check_limit(user, "mfa")
    normalized = code.strip().replace("-", "").replace(" ", "").upper()
    # Random 128-bit recovery values are SHA-256 hashed. Check these first so
    # recovery still works if a TOTP encryption key has become unavailable.
    if re.fullmatch(r"[0-9A-F]{32}", normalized):
        wanted = digest(normalized)
        for stored in user.mfa_recovery_hashes:
            if secrets.compare_digest(stored, wanted):
                user.mfa_recovery_hashes = [entry for entry in user.mfa_recovery_hashes if entry != stored]
                user.mfa_failures = 0
                user.mfa_locked_until = None
                return
    else:
        step = totp_step(user.mfa_secret, code.strip(), user.mfa_last_step)
        if step is not None:
            user.mfa_last_step = step
            user.mfa_failures = 0
            user.mfa_locked_until = None
            return
    failed_attempt(db, user, "mfa", challenge)


def setup(db, user, password):
    if user.mfa_enabled:
        raise HTTPException(409, "Двухфакторная аутентификация уже включена")
    check_limit(user, "mfa")
    require_password(db, user, password)
    secret = pyotp.random_base32()
    user.mfa_pending_secret = cipher().encrypt(secret.encode("ascii")).decode("ascii")
    user.mfa_pending_expires_at = utcnow() + timedelta(seconds=SETUP_SECONDS)
    db.commit()
    return {"secret": secret, "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(
        name=user.email, issuer_name="Smart Calendar")}


def enable(db, user, code):
    if user.mfa_enabled:
        raise HTTPException(409, "Двухфакторная аутентификация уже включена")
    check_limit(user, "mfa")
    if not user.mfa_pending_secret or user.mfa_pending_expires_at <= utcnow():
        raise HTTPException(409, "Настройка истекла. Начните заново.")
    step = totp_step(user.mfa_pending_secret, code.strip())
    if step is None:
        failed_attempt(db, user, "mfa")
    recovery = [secrets.token_hex(16).upper() for _ in range(RECOVERY_COUNT)]
    user.mfa_secret = user.mfa_pending_secret
    user.mfa_pending_secret = None
    user.mfa_pending_expires_at = None
    user.mfa_enabled = True
    user.mfa_last_step = step
    user.mfa_recovery_hashes = [digest(value) for value in recovery]
    user.mfa_failures = 0
    user.mfa_locked_until = None
    user.auth_version += 1
    db.query(MFAChallenge).filter_by(user_id=user.id).delete(synchronize_session=False)
    tokens = issue_tokens(user, mfa=True)
    db.commit()
    return {**tokens.model_dump(),
            "recovery_codes": ["-".join(value[i:i + 8] for i in range(0, 32, 8)) for value in recovery]}


def disable(db, user, password, code):
    if not user.mfa_enabled:
        raise HTTPException(409, "Двухфакторная аутентификация уже выключена")
    require_password(db, user, password)
    accept_factor(db, user, code)
    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_pending_secret = None
    user.mfa_pending_expires_at = None
    user.mfa_last_step = None
    user.mfa_recovery_hashes = []
    user.auth_version += 1
    db.query(MFAChallenge).filter_by(user_id=user.id).delete(synchronize_session=False)
    tokens = issue_tokens(user)
    db.commit()
    return tokens
