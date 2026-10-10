import hashlib
import secrets
import os
import json
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Config

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = os.environ.get("SESSION_SECRET", "fallback-salt-change-me")
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def create_token() -> str:
    return secrets.token_hex(32)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security),
                      db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = credentials.credentials
    stored_row = db.query(Config).filter(Config.key == "session_token").first()
    if not stored_row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    try:
        stored_token = json.loads(stored_row.value)
    except (ValueError, TypeError):
        stored_token = stored_row.value
    if stored_token != token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def verify_webhook_key(api_key: str, db: Session) -> bool:
    stored = db.query(Config).filter(Config.key == "webhook_api_key").first()
    if not stored:
        return False
    try:
        stored_key = json.loads(stored.value)
    except (ValueError, TypeError):
        stored_key = stored.value
    return api_key == stored_key
