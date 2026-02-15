from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings
import secrets
import random

# Configure bcrypt context with proper settings
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__ident="2b",  # Use bcrypt 2b format
    bcrypt__rounds=12,   # Standard rounds
)

# Pre-initialize bcrypt handler to avoid lazy initialization bug detection error
# The bug detection uses a long test password (>72 bytes) which causes an error
# We catch this and continue - the handler will still work for normal passwords
try:
    # Get the handler to trigger initialization
    handler = pwd_context.handler()
    # Try to initialize with a simple hash
    # This may trigger bug detection, but we'll catch and ignore that error
    try:
        test_hash = handler.hash("test")
    except ValueError as ve:
        # This is expected - the bug detection uses a long password
        # The handler is still usable for normal password verification
        if "cannot be longer than 72 bytes" in str(ve):
            # This is the bug detection error - it's safe to ignore
            import logging
            logging.debug(f"Bcrypt bug detection triggered (expected): {ve}")
        else:
            raise
except Exception as e:
    # If initialization fails completely, log but continue
    import logging
    logging.warning(f"Bcrypt pre-initialization warning: {e}")


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

