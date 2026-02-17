from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from passlib.context import CryptContext

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password for storing."""
    return pwd_context.hash(password)


def create_session_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    """Create a simple session token containing user_id and expiration."""
    if expires_delta is None:
        expires_delta = timedelta(days=7)  # Default 7 days
    
    expire = datetime.now(timezone.utc) + expires_delta
    # Simple format: user_id:expiration_timestamp
    token_data = f"{user_id}:{int(expire.timestamp())}"
    return token_data


def decode_session_token(token: str) -> dict[str, Any] | None:
    """Decode a session token and return user info if valid."""
    try:
        parts = token.split(":")
        if len(parts) != 2:
            return None
        
        user_id = int(parts[0])
        expire_timestamp = int(parts[1])
        
        # Check if expired
        now = datetime.now(timezone.utc)
        expire = datetime.fromtimestamp(expire_timestamp, tz=timezone.utc)
        
        if now > expire:
            return None
        
        return {"user_id": user_id}
    except (ValueError, IndexError):
        return None
