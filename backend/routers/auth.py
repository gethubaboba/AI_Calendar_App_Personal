"""
routers/auth.py — эндпоинты аутентификации.

POST /api/auth/register  — регистрация нового пользователя
POST /api/auth/login     — вход, возвращает JWT-токены
POST /api/auth/refresh   — обновление access-токена по refresh-токену
GET  /api/auth/me        — информация о текущем пользователе
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db import get_session
import models
import schemas
from auth import (
    hash_password,
    issue_tokens,
    session_user,
    get_current_user,
    get_locked_user,
)
from services import mfa

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def register(data: schemas.UserCreate, db: Session = Depends(get_session)):
    """Регистрация нового пользователя по email и паролю."""
    existing = db.query(models.User).filter(models.User.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким email уже существует",
        )
    user = models.User(
        email=data.email,
        name=data.name,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return issue_tokens(user)


@router.post("/login", response_model=schemas.Token | schemas.MFARequired)
def login(data: schemas.UserLogin, db: Session = Depends(get_session)):
    """Вход пользователя. Возвращает access + refresh токены."""
    user = db.query(models.User).filter(models.User.email == data.email).with_for_update().first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    mfa.require_password(db, user, data.password)
    if user.mfa_enabled:
        return mfa.new_challenge(db, user)
    tokens = issue_tokens(user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=schemas.Token)
def refresh_token(data: schemas.TokenRefresh, db: Session = Depends(get_session)):
    """Обновление access-токена по refresh-токену."""
    user = session_user(data.refresh_token, db, expected_type="refresh", lock=True)
    return issue_tokens(user, mfa=user.mfa_enabled)


@router.post("/mfa/verify", response_model=schemas.Token)
def verify_mfa(data: schemas.MFAVerify, db: Session = Depends(get_session)):
    try:
        token_hash = mfa.digest(data.challenge_token)
    except UnicodeError:
        raise HTTPException(401, "Недействительный запрос входа") from None
    challenge = db.get(models.MFAChallenge, token_hash)
    if challenge is None:
        raise HTTPException(401, "Недействительный запрос входа")
    # Always lock user before challenge. Refresh the latter after waiting so two
    # requests holding an earlier snapshot cannot consume it twice.
    user = db.query(models.User).filter_by(id=challenge.user_id).with_for_update().populate_existing().first()
    challenge = (db.query(models.MFAChallenge).filter_by(token_hash=token_hash)
                 .with_for_update().populate_existing().first())
    if (user is None or challenge is None or not user.mfa_enabled
            or challenge.auth_version != user.auth_version
            or challenge.expires_at <= mfa.utcnow() or challenge.attempts >= mfa.MAX_FAILURES):
        raise HTTPException(401, "Запрос входа истёк. Введите пароль снова.")
    mfa.accept_factor(db, user, data.code, challenge)
    tokens = issue_tokens(user, mfa=True)
    db.delete(challenge)
    db.commit()
    return tokens


@router.get("/mfa/status")
def mfa_status(user: models.User = Depends(get_current_user)):
    return {"enabled": user.mfa_enabled, "recovery_codes_remaining": len(user.mfa_recovery_hashes)}


@router.post("/mfa/setup")
def setup_mfa(data: schemas.MFASetup, user=Depends(get_locked_user), db: Session = Depends(get_session)):
    return mfa.setup(db, user, data.password)


@router.post("/mfa/enable", response_model=schemas.MFAEnabled)
def enable_mfa(data: schemas.MFACode, user=Depends(get_locked_user), db: Session = Depends(get_session)):
    return mfa.enable(db, user, data.code)


@router.post("/mfa/disable", response_model=schemas.Token)
def disable_mfa(data: schemas.MFADisable, user=Depends(get_locked_user), db: Session = Depends(get_session)):
    return mfa.disable(db, user, data.password, data.code)


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(get_current_user)):
    """Возвращает профиль текущего аутентифицированного пользователя."""
    return current_user
