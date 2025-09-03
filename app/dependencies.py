from fastapi.security import HTTPBearer
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
import jwt

from .db import get_db
from .models import Admin
from .config import settings

bearer_scheme = HTTPBearer()

def get_current_user(
    credentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
):
    token = credentials.credentials  # самият JWT от header-а
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.scalar(select(Admin).where(Admin.username == username))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user
