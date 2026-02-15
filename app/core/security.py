from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings
import secrets
import random

# Monkey patch passlib to skip bcrypt bug detection
# This prevents the "password cannot be longer than 72 bytes" error during initialization
try:
    from passlib.handlers import bcrypt
    original_detect_wrap_bug = bcrypt.detect_wrap_bug
    
    def patched_detect_wrap_bug(ident):
        # Skip bug detection - always return False (no bug detected)
        # This prevents the 72-byte password error during initialization
        return False
    
    bcrypt.detect_wrap_bug = patched_detect_wrap_bug
except Exception as e:
    # If patching fails, log but continue
    import logging
    logging.warning(f"Failed to patch bcrypt bug detection: {e}")

# Configure bcrypt context with proper settings
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__ident="2b",  # Use bcrypt 2b format
    bcrypt__rounds=12,   # Standard rounds
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.
    Handles bcrypt 72-byte limit and initialization errors.
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError as e:
        error_msg = str(e)
        # Handle bcrypt 72-byte limit error
        if "cannot be longer than 72 bytes" in error_msg:
            # This shouldn't happen for normal passwords, but handle it just in case
            if isinstance(plain_password, str):
                plain_password_bytes = plain_password.encode('utf-8')
                if len(plain_password_bytes) > 72:
                    truncated = plain_password_bytes[:72].decode('utf-8', errors='ignore')
                    return pwd_context.verify(truncated, hashed_password)
        # Re-raise other ValueError
        raise
    except Exception as e:
        # Log unexpected errors for debugging
        import logging
        logger = logging.getLogger(__name__)
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

