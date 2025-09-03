# app/security.py
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
import jwt  # библиотека PyJWT
from .config import settings  # ВАЖНО: една точка, защото файлът е в app/

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_access_token(token: str) -> dict:
    # Ще използваме това в guard-овете
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
