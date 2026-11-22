"""
auth.py — утилиты для JWT-аутентификации.

Функции:
  - hash_password / verify_password : bcrypt-хеширование
  - create_access_token             : генерация access JWT
  - create_refresh_token            : генерация refresh JWT
  - decode_token                    : верификация и декодирование JWT
  - get_current_user                : FastAPI dependency — возвращает текущего пользователя
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from db import get_session
import models

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ─── Хеширование пароля ───────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Возвращает bcrypt-хеш пароля."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Сравнивает открытый пароль с хешем."""
    return pwd_context.verify(plain, hashed)


# ─── Работа с JWT ─────────────────────────────────────────────────────────────

def _create_token(data: dict, expires_delta: timedelta) -> str:
    """Внутренняя функция создания JWT-токена."""
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, auth_version: int = 0, mfa: bool = False) -> str:
    """Создаёт короткоживущий access-токен."""
    return _create_token(
        {"sub": str(user_id), "type": "access", "auth_version": auth_version, "mfa": mfa},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: int, auth_version: int = 0, mfa: bool = False) -> str:
    """Создаёт долгоживущий refresh-токен."""
    return _create_token(
        {"sub": str(user_id), "type": "refresh", "auth_version": auth_version, "mfa": mfa},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_claims(token: str, expected_type: str = "access") -> dict:
    """
    Декодирует JWT-токен.

    Возвращает проверенные claims или бросает HTTPException 401.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")
        if user_id is None or token_type != expected_type or "exp" not in payload:
            raise credentials_exception
        int(user_id)
        return payload
    except (JWTError, ValueError, TypeError):
        raise credentials_exception


def decode_token(token: str, expected_type: str = "access") -> int:
    return int(decode_claims(token, expected_type)["sub"])


def session_user(token: str, db: Session, expected_type: str = "access", lock: bool = False):
    claims = decode_claims(token, expected_type)
    query = db.query(models.User).filter_by(id=int(claims["sub"]))
    if lock:
        query = query.with_for_update().populate_existing()
    user = query.first()
    # Legacy tokens belong to version zero, and only to accounts without MFA.
    if (user is None or type(claims.get("auth_version", 0)) is not int
            or claims.get("auth_version", 0) != user.auth_version
            or (user.mfa_enabled and claims.get("mfa") is not True)):
        raise HTTPException(status_code=401, detail="Сессия истекла. Войдите снова.")
    return user


def issue_tokens(user: models.User, mfa: bool = False):
    from schemas import Token
    if user.mfa_enabled and not mfa:
        raise HTTPException(status_code=401, detail="Требуется второй фактор")
    return Token(
        access_token=create_access_token(user.id, user.auth_version, mfa),
        refresh_token=create_refresh_token(user.id, user.auth_version, mfa),
    )


def get_locked_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_session)):
    return session_user(token, db, lock=True)


# ─── FastAPI Dependency ───────────────────────────────────────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_session),
) -> models.User:
    """
    FastAPI dependency.
    Извлекает текущего пользователя из Bearer-токена.
    """
    return session_user(token, db)
