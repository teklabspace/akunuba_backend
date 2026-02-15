from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings
import secrets
import random
import bcrypt
import logging

logger = logging.getLogger(__name__)

# Configure bcrypt context with proper settings for hashing
# We'll use passlib for hashing but bcrypt directly for verification to avoid initialization issues
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__ident="2b",  # Use bcrypt 2b format
    bcrypt__rounds=12,   # Standard rounds
)

# Pre-initialize passlib handler for hashing only (doesn't trigger bug detection)
try:
    # Just get the handler - don't trigger verification which causes bug detection
    _ = pwd_context.handler()
except Exception as e:
    logger.warning(f"Passlib handler initialization warning: {e}")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.
    Uses bcrypt directly to avoid passlib initialization issues.
    """
    try:
        # Use bcrypt directly for verification to bypass passlib's bug detection
        # This is more reliable and avoids the initialization errors
        if not plain_password or not hashed_password:
            return False
        
        # Ensure password is bytes
        if isinstance(plain_password, str):
            password_bytes = plain_password.encode('utf-8')
        else:
            password_bytes = plain_password
        
        # Ensure hash is bytes
        if isinstance(hashed_password, str):
            hash_bytes = hashed_password.encode('utf-8')
        else:
            hash_bytes = hashed_password
        
        # Use bcrypt.checkpw directly - this bypasses passlib entirely
        return bcrypt.checkpw(password_bytes, hash_bytes)
        
    except ValueError as e:
        error_msg = str(e)
        # Handle bcrypt 72-byte limit error
        if "cannot be longer than 72 bytes" in error_msg:
            if isinstance(plain_password, str):
                plain_password_bytes = plain_password.encode('utf-8')
                if len(plain_password_bytes) > 72:
                    truncated = plain_password_bytes[:72]
                    if isinstance(hashed_password, str):
                        hash_bytes = hashed_password.encode('utf-8')
                    else:
                        hash_bytes = hashed_password
                    return bcrypt.checkpw(truncated, hash_bytes)
        # Re-raise other ValueError
        raise
    except Exception as e:
        logger.error(f"Password verification error: {type(e).__name__}: {e}")
        raise


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=30)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None


def generate_otp() -> str:
    return f"{random.randint(100000, 999999)}"


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)

