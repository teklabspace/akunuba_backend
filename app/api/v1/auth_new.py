from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel

# asyncpg errors (e.g. InternalServerError) are not subclasses of SQLAlchemyError
_DB_SESSION_ERRORS: tuple[type[BaseException], ...] = (SQLAlchemyError,)
try:
    from asyncpg.exceptions import PostgresError as _AsyncpgPostgresError

    _DB_SESSION_ERRORS = (SQLAlchemyError, _AsyncpgPostgresError)
except ImportError:
    pass
from app.database import get_db
from app.models.user import User
from app.models.account import Account
from app.models.kyc import KYCVerification, KYCStatus
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, decode_refresh_token, generate_otp, generate_verification_token, generate_reset_token
import json

# Try to import pyotp for 2FA verification during login
try:
    import pyotp
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False
    pyotp = None
from app.core.exceptions import UnauthorizedException, ConflictException, NotFoundException, BadRequestException
from app.core.rate_limit import limiter, LOGIN_RATE_LIMIT, AUTH_RATE_LIMIT
from app.schemas.user import UserCreate, UserLogin, TokenResponse, LoginUserResponse, OTPRequest, OTPVerify, PasswordResetRequest, PasswordReset, RefreshTokenRequest, EmailVerificationRequest
from app.utils.logger import logger
from datetime import timedelta, datetime, timezone
from app.config import settings
from app.integrations.supabase_client import SupabaseClient
from app.services.email_service import EmailService
import httpx
import secrets
import base64
from urllib.parse import urlencode, urlparse

GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

router = APIRouter()
security = HTTPBearer()


def _should_expose_otp_in_response(email_sent: bool) -> bool:
    if settings.APP_ENV == "development":
        return True
    return not email_sent and settings.EMAIL_RETURN_OTP_ON_FAILURE


async def _send_otp_and_build_response(user: User, otp_code: str) -> dict:
    """Send OTP email and return a consistent payload for register/request-otp."""
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"
    email_sent = await EmailService.send_otp_email(
        to_email=user.email,
        to_name=user_name,
        otp_code=otp_code,
    )

    if email_sent:
        response = {
            "message": "OTP sent to your email",
            "email_sent": True,
            "requires_email_verification": True,
            "next_step": "verify_otp",
        }
    else:
        logger.error(f"OTP email delivery failed for {user.email}")
        response = {
            "message": "Account created. Enter the verification code to continue.",
            "email_sent": False,
            "requires_email_verification": True,
            "next_step": "verify_otp",
            "detail": (
                "We could not deliver the verification email. "
                "If you do not receive a code, contact support or try again later."
            ),
        }

    if _should_expose_otp_in_response(email_sent):
        response["otp"] = otp_code
        if not email_sent:
            response["message"] = "Verification code generated. Enter it below to continue."

    return response

class GoogleAuthRequest(BaseModel):
    code: str
    redirect_uri: str = None

class GoogleTokenRequest(BaseModel):
    id_token: str


async def get_user_verification_status(user: User, db: AsyncSession) -> dict:
    """Helper function to get user verification status (KYC and email)
    
    Business Rule: Email must be verified before KYC can be approved.
    So is_kyc_verified can only be True if is_email_verified is also True.
    """
    # Check if email is verified (via OTP or email verification link)
    # Email is verified if:
    # 1. email_verified_at is set (email verification link clicked), OR
    # 2. is_verified is True (OTP verified or email verified)
    is_email_verified = user.email_verified_at is not None or user.is_verified
    
    # Check if KYC is approved (only possible if email is verified first)
    is_kyc_verified = False
    if is_email_verified:  # Only check KYC if email is verified
        try:
            # Get user's account
            account_result = await db.execute(
                select(Account).where(Account.user_id == user.id)
            )
            account = account_result.scalar_one_or_none()
            
            if account:
                # Check if KYC exists and is approved
                kyc_result = await db.execute(
                    select(KYCVerification).where(KYCVerification.account_id == account.id)
                )
                kyc = kyc_result.scalar_one_or_none()
                if kyc and kyc.status == KYCStatus.APPROVED:
                    is_kyc_verified = True
        except Exception as e:
            logger.warning(f"Error checking KYC status for user {user.id}: {e}")
    
    # Overall verification: True if KYC is verified (which requires email verification)
    # OR if only email is verified
    is_verified = is_kyc_verified or is_email_verified
    
    return {
        "is_verified": is_verified,
        "is_kyc_verified": is_kyc_verified,
        "is_email_verified": is_email_verified
    }


def get_frontend_google_redirect_url() -> str:
    """
    Default post-OAuth redirect target (when `state`/`return_to` is not used).

    Configure via FRONTEND_BASE_URL (Render env), e.g.:
    - https://akunuba.vercel.app
    - https://akunuba.io
    """
    if settings.APP_ENV == "development":
        return "http://localhost:3000/auth/google/callback"

    base = (getattr(settings, "FRONTEND_BASE_URL", "") or "").strip()
    if not base:
        base = "https://akunuba.io"

    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        # Fail safe to a known-good production domain
        base = "https://akunuba.io"

    base = _normalize_origin(base)
    return f"{base}/auth/google/callback"


def get_frontend_signup_url() -> str:
    """Signup page used when Google returns a user who has no account yet."""
    if settings.APP_ENV == "development":
        return "http://localhost:3000/signup"

    base = (getattr(settings, "FRONTEND_BASE_URL", "") or "").strip()
    if not base:
        base = "https://akunuba.io"

    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        base = "https://akunuba.io"

    base = _normalize_origin(base)
    return f"{base}/signup"


# Values for `oauth_next` query param — lets the SPA route immediately (no /auth/refresh wait).
OAUTH_NEXT_DASHBOARD = "dashboard"
OAUTH_NEXT_PERSONA_WAIT = "persona_wait"
OAUTH_NEXT_VERIFY_EMAIL = "verify_email"


def _normalize_origin(origin: str) -> str:
    return origin.rstrip("/")


def _allowed_oauth_return_origins() -> set[str]:
    """
    Allowlist for where we may redirect after Google OAuth completes.

    Primary source: CORS_ORIGINS (already maintained for browser origins).
    Also include common local dev origins even if CORS_ORIGINS is production-only.
    """
    origins: set[str] = set()
    for o in getattr(settings, "CORS_ORIGINS", []) or []:
        if o:
            origins.add(_normalize_origin(str(o)))

    # Common local dev ports (explicit, safe defaults)
    origins.update(
        {
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        }
    )

    # Production defaults (even if CORS_ORIGINS string parsing differs)
    origins.update(
        {
            "https://akunuba.io",
            "https://www.akunuba.io",
            "https://akunuba.vercel.app",
        }
    )

    # Also allow whatever FRONTEND_BASE_URL is configured to (normalized origin)
    fb = (getattr(settings, "FRONTEND_BASE_URL", "") or "").strip()
    if fb:
        p = urlparse(fb)
        if p.scheme in ("http", "https") and p.netloc:
            origins.add(_normalize_origin(f"{p.scheme}://{p.netloc}"))

    return origins


def _validate_frontend_callback_url(url: str) -> str:
    """
    Validate a full callback URL like https://example.com/auth/google/callback
    to prevent open redirects.
    """
    if not url:
        raise BadRequestException("return_to is required")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BadRequestException("return_to must be http(s)")

    if not parsed.netloc:
        raise BadRequestException("return_to must include a host")

    # Require exact callback path (frontend route)
    if not parsed.path.endswith("/auth/google/callback"):
        raise BadRequestException("return_to must end with /auth/google/callback")

    origin = _normalize_origin(f"{parsed.scheme}://{parsed.netloc}")
    if origin not in _allowed_oauth_return_origins():
        raise BadRequestException("return_to origin is not allowed")

    # Disallow weird embedded credentials in netloc
    if "@" in parsed.netloc:
        raise BadRequestException("return_to is invalid")

    return url


def _encode_oauth_state(return_to: str) -> str:
    raw = return_to.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_oauth_state(state: str) -> str:
    if not state:
        raise BadRequestException("Missing OAuth state")
    padded = state + "=" * ((4 - len(state) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        raise BadRequestException("Invalid OAuth state")
    return _validate_frontend_callback_url(decoded)


@router.get("/google/login")
async def google_login(return_to: str | None = None, state: str | None = None):
    """
    Start Google OAuth2 flow by redirecting to Google's authorization endpoint.

    Optional:
    - return_to: full URL to your frontend callback route, e.g.
      http://localhost:3000/auth/google/callback
      This is passed through Google OAuth using the `state` parameter and echoed back
      to `/google/callback`, then used for the final redirect with tokens.

    Advanced:
    - state: if you already encode return_to yourself, you can pass state directly
      (must be base64url of the full return_to URL).
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET or not settings.GOOGLE_REDIRECT_URI:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on the server",
        )

    oauth_state: str | None = None
    if return_to:
        validated = _validate_frontend_callback_url(return_to)
        oauth_state = _encode_oauth_state(validated)
    elif state:
        # Validate by decoding (also supports clients pre-encoding state)
        validated = _decode_oauth_state(state)
        oauth_state = _encode_oauth_state(validated)

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    if oauth_state:
        params["state"] = oauth_state

    url = f"{GOOGLE_AUTH_BASE_URL}?{urlencode(params)}"
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Google OAuth2 callback handler.
    Exchanges authorization code for tokens, fetches user info,
    creates/logs in the user, then redirects to frontend with tokens.
    """
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Google OAuth error: {error}")

    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code from Google")

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET or not settings.GOOGLE_REDIRECT_URI:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on the server",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )

        if token_resp.status_code != 200:
            google_error = None
            google_error_description = None
            try:
                token_error_payload = token_resp.json()
                google_error = token_error_payload.get("error")
                google_error_description = token_error_payload.get("error_description")
            except Exception:
                token_error_payload = {"raw": token_resp.text}

            logger.error(
                "Google token exchange failed: "
                f"status={token_resp.status_code}, "
                f"error={google_error}, "
                f"error_description={google_error_description}, "
                f"payload={token_error_payload}"
            )

            error_hint = google_error or "token_exchange_failed"
            if google_error == "invalid_grant":
                detail = (
                    "Google authorization code expired or was already used. "
                    "Start the Google sign-in flow again from your app (do not refresh this page)."
                )
            else:
                detail = f"Failed to exchange authorization code with Google ({error_hint})"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
            )

        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No access token returned from Google",
            )

        async with httpx.AsyncClient(timeout=10.0) as client:
            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if userinfo_resp.status_code != 200:
            logger.error(f"Google userinfo fetch failed: {userinfo_resp.status_code} {userinfo_resp.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch user info from Google",
            )

        userinfo = userinfo_resp.json()
        email = userinfo.get("email")
        google_first = userinfo.get("given_name") or ""
        google_last = userinfo.get("family_name") or ""
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google did not provide an email address",
            )

        try:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
        except _DB_SESSION_ERRORS as e:
            logger.error(f"Database error while fetching user for Google OAuth callback ({email}): {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection error. Please try again later.",
            )

        if not user:
            signup_url = get_frontend_signup_url()
            signup_qs = urlencode(
                {
                    "email": email,
                    "first_name": google_first,
                    "last_name": google_last,
                    "oauth": "google",
                }
            )
            return RedirectResponse(f"{signup_url}?{signup_qs}")

        user.last_login = datetime.utcnow()
        access_token_app = create_access_token(data={"sub": str(user.id)})
        refresh_token_app = create_refresh_token(data={"sub": str(user.id)})
        user.refresh_token = refresh_token_app
        try:
            await db.commit()
        except _DB_SESSION_ERRORS as e:
            logger.error(f"Database error while updating login tokens for user {user.id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection error. Please try again later.",
            )

        if state:
            frontend_redirect = _decode_oauth_state(state)
        else:
            frontend_redirect = get_frontend_google_redirect_url()

        verification_status = await get_user_verification_status(user, db)
        if verification_status["is_kyc_verified"]:
            oauth_next = OAUTH_NEXT_DASHBOARD
        elif verification_status["is_email_verified"]:
            oauth_next = OAUTH_NEXT_PERSONA_WAIT
        else:
            oauth_next = OAUTH_NEXT_VERIFY_EMAIL

        redirect_url = (
            f"{frontend_redirect}?"
            f"{urlencode({'access_token': access_token_app, 'refresh_token': refresh_token_app, 'oauth_next': oauth_next})}"
        )
        return RedirectResponse(redirect_url)

    except HTTPException:
        raise
    except _DB_SESSION_ERRORS as e:
        logger.error(f"Database error during Google OAuth callback: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection error. Please try again later.",
        )
    except Exception as e:
        logger.error(f"Error handling Google OAuth callback: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete Google login",
        )

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(LOGIN_RATE_LIMIT)
async def register(request: Request, user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing_user = await db.execute(select(User).where(User.email == user_data.email))
    if existing_user.scalar_one_or_none():
        raise ConflictException("User with this email already exists")
    hashed_password = get_password_hash(user_data.password)
    verification_token = generate_verification_token()
    otp_code = generate_otp()
    user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        phone=user_data.phone,
        email_verification_token=verification_token,
        otp_code=otp_code,
        otp_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    try:
        supabase = SupabaseClient.get_client()
        supabase.auth.admin.create_user({"email": user_data.email, "password": user_data.password, "email_confirm": False, "user_metadata": {"first_name": user_data.first_name, "last_name": user_data.last_name, "phone": user_data.phone}})
    except Exception as e:
        logger.warning(f"Failed to create Supabase Auth user: {e}")
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    user.refresh_token = refresh_token
    await db.commit()
    await db.refresh(user)
    user_name = f"{user_data.first_name or ''} {user_data.last_name or ''}".strip() or "User"
    await EmailService.send_verification_email(
        to_email=user.email, to_name=user_name, verification_token=verification_token
    )
    otp_delivery = await _send_otp_and_build_response(user, otp_code)
    logger.info(f"User registered: {user.email}, email_sent={otp_delivery['email_sent']}")
    
    # Get verification status (KYC and email)
    verification_status = await get_user_verification_status(user, db)
    
    # Return simplified user object with verification flags
    user_response = LoginUserResponse(
        id=user.id,
        role=user.role,
        is_verified=verification_status["is_verified"],
        is_kyc_verified=verification_status["is_kyc_verified"],
        is_email_verified=verification_status["is_email_verified"]
    )
    
    response_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user_response,
        **otp_delivery,
    }
    if settings.APP_ENV == "development":
        response_data["verification_token"] = verification_token
    return response_data


@router.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT)
async def login(request: Request, credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """
    Login endpoint with 2FA support.
    
    If 2FA is enabled:
    - First call (without totp_code): Returns requires_2fa=true and temp_token
    - Second call (with totp_code): Verifies 2FA and returns access_token
    """
    try:
        result = await db.execute(select(User).where(User.email == credentials.email))
        user = result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Database error during login for {credentials.email}: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed. Please try again later."
        )
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise UnauthorizedException("Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
    
    # Check if 2FA is enabled and verified
    if user.two_factor_auth_enabled and user.two_factor_auth_verified:
        # 2FA is required
        if not credentials.totp_code:
            # First step: Password verified, now require 2FA code
            # Create a temporary token for 2FA verification (short-lived, 5 minutes)
            temp_token = create_access_token(
                data={"sub": str(user.id), "type": "2fa_pending", "login": True},
                expires_delta=timedelta(minutes=5)
            )
            
            logger.info(f"User {user.email} requires 2FA verification")
            
            return TokenResponse(
                access_token=None,
                refresh_token=None,
                token_type="bearer",
                user=None,
                requires_2fa=True,
                temp_token=temp_token,
                message="Please enter your 2FA code from your authenticator app"
            )
        
        # Second step: Verify 2FA code
        if not TOTP_AVAILABLE:
            raise BadRequestException("2FA verification is not available. Please contact support.")
        
        if not user.two_factor_auth_secret:
            raise BadRequestException("2FA is enabled but secret is missing. Please reset 2FA.")
        
        # Verify TOTP code
        totp = pyotp.TOTP(user.two_factor_auth_secret)
        is_valid = totp.verify(credentials.totp_code, valid_window=1)
        
        # Also check backup codes
        backup_codes_valid = False
        if user.two_factor_backup_codes:
            try:
                backup_codes = json.loads(user.two_factor_backup_codes)
                if credentials.totp_code in backup_codes:
                    backup_codes_valid = True
                    # Remove used backup code
                    backup_codes.remove(credentials.totp_code)
                    user.two_factor_backup_codes = json.dumps(backup_codes)
                    await db.commit()
            except (json.JSONDecodeError, ValueError):
                pass
        
        if not is_valid and not backup_codes_valid:
            raise UnauthorizedException("Invalid 2FA code. Please try again.")
        
        # 2FA verified, proceed with login
        logger.info(f"2FA verified for user {user.email}")
    
    # Complete login (2FA verified or not required)
    user.last_login = datetime.utcnow()
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    user.refresh_token = refresh_token
    await db.commit()
    await db.refresh(user)
    logger.info(f"User logged in: {user.email}")
    
    # Get verification status (KYC and email)
    verification_status = await get_user_verification_status(user, db)
    
    # Return simplified user object with verification flags
    user_response = LoginUserResponse(
        id=user.id,
        role=user.role,
        is_verified=verification_status["is_verified"],
        is_kyc_verified=verification_status["is_kyc_verified"],
        is_email_verified=verification_status["is_email_verified"]
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=user_response
    )

@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def refresh_token_endpoint(request: Request, body: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_refresh_token(body.refresh_token)
    if not payload:
        raise UnauthorizedException("Invalid refresh token")
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.refresh_token != body.refresh_token:
        raise UnauthorizedException("Invalid refresh token")
    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})
    user.refresh_token = new_refresh_token
    await db.commit()
    await db.refresh(user)
    
    # Get verification status (KYC and email)
    verification_status = await get_user_verification_status(user, db)
    
    # Return simplified user object with verification flags
    user_response = LoginUserResponse(
        id=user.id,
        role=user.role,
        is_verified=verification_status["is_verified"],
        is_kyc_verified=verification_status["is_kyc_verified"],
        is_email_verified=verification_status["is_email_verified"]
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        user=user_response
    )

@router.post("/request-otp")
async def request_otp(request: OTPRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", request.email)
    now = datetime.now(timezone.utc)
    # Reuse a still-valid OTP instead of minting a new one on every call. Register
    # already generated and emailed a code; if the verify page (or the user) then
    # hits resend, regenerating would silently invalidate the code the user
    # already received, so their first (correct) entry gets rejected and only a
    # later resend "works". Reusing the live code makes the initial code and any
    # resend identical. Only mint a fresh code once the old one has expired.
    existing_expiry = user.otp_expires_at
    if existing_expiry is not None and existing_expiry.tzinfo is None:
        existing_expiry = existing_expiry.replace(tzinfo=timezone.utc)
    if user.otp_code and existing_expiry is not None and existing_expiry > now:
        otp_code = user.otp_code
    else:
        otp_code = generate_otp()
        user.otp_code = otp_code
    # Refresh the expiry window so the (reused or new) code stays valid.
    user.otp_expires_at = now + timedelta(minutes=10)
    await db.commit()
    return await _send_otp_and_build_response(user, otp_code)

@router.post("/verify-otp")
async def verify_otp(request: OTPVerify, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(User).where(User.email == request.email))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User", request.email)
        
        # Convert both to strings for comparison to handle type mismatches.
        # Strip BOTH sides — a stray space on either the stored or submitted code
        # would otherwise reject a correct OTP.
        user_otp = str(user.otp_code).strip() if user.otp_code else None
        request_otp = str(request.otp_code).strip()
        
        if not user_otp or user_otp != request_otp:
            raise BadRequestException("Invalid OTP code")
        
        # Use timezone-aware datetime for comparison
        now = datetime.now(timezone.utc)
        if user.otp_expires_at and user.otp_expires_at < now:
            raise BadRequestException("OTP code has expired")
        
        # If purpose is "password_reset", don't clear the OTP - it will be used again in reset-password
        # For email verification or other purposes, clear the OTP after verification
        if request.purpose != "password_reset":
            user.otp_code = None
            user.otp_expires_at = None
            user.is_verified = True
            user.email_verified_at = now
        # For password reset, keep the OTP so it can be used in reset-password endpoint
        
        await db.commit()
        logger.info(f"OTP verified successfully for user: {user.email}, purpose: {request.purpose or 'email_verification'}")
        return {"message": "OTP verified successfully"}
    except (NotFoundException, BadRequestException) as e:
        # Re-raise known exceptions
        raise
    except Exception as e:
        # Log the full error with traceback for debugging
        logger.error(f"Error verifying OTP for {request.email}: {e}", exc_info=True)
        # In development, return the actual error message for debugging
        error_detail = str(e) if settings.APP_DEBUG else "An error occurred while verifying OTP"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail
        )


@router.post("/request-password-reset")
@limiter.limit(AUTH_RATE_LIMIT)
async def request_password_reset(request: Request, body: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        return {"message": "If the email exists, a password reset link has been sent"}
    
    # Generate both reset token and OTP for flexibility
    reset_token = generate_reset_token()
    otp_code = generate_otp()
    
    user.password_reset_token = reset_token
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    user.otp_code = otp_code
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    
    await db.commit()
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"
    
    # Send both token-based reset email and OTP email
    await EmailService.send_password_reset_email(to_email=user.email, to_name=user_name, reset_token=reset_token)
    await EmailService.send_otp_email(to_email=user.email, to_name=user_name, otp_code=otp_code)
    
    return {"message": "If the email exists, a password reset link has been sent"}

@router.post("/reset-password")
@limiter.limit(AUTH_RATE_LIMIT)
async def reset_password(request: Request, body: PasswordReset, db: AsyncSession = Depends(get_db)):
    # Support both token-based and OTP-based password reset
    if body.token:
        # Token-based reset (original method)
        result = await db.execute(select(User).where(User.password_reset_token == body.token))
        user = result.scalar_one_or_none()
        if not user:
            raise BadRequestException("Invalid reset token")
        if user.password_reset_expires_at and user.password_reset_expires_at < datetime.now(timezone.utc):
            raise BadRequestException("Reset token has expired")
    elif body.email and body.otp_code:
        # OTP-based reset
        result = await db.execute(select(User).where(User.email == body.email))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User", body.email)
        
        # Verify OTP
        user_otp = str(user.otp_code) if user.otp_code else None
        request_otp = str(body.otp_code).strip()
        
        if not user_otp or user_otp != request_otp:
            raise BadRequestException("Invalid OTP code")
        
        # Check OTP expiration
        now = datetime.now(timezone.utc)
        if user.otp_expires_at and user.otp_expires_at < now:
            raise BadRequestException("OTP code has expired")
    else:
        raise BadRequestException("No reset token found. Please use the link from your email or request a new password reset.")
    
    # Reset password
    user.hashed_password = get_password_hash(body.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    user.otp_code = None
    user.otp_expires_at = None
    await db.commit()
    logger.info(f"Password reset successfully for user: {user.email}")
    return {"message": "Password reset successfully"}

@router.post("/verify-email")
async def verify_email(request: EmailVerificationRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email_verification_token == request.token))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", request.token)
    if user.is_verified:
        raise BadRequestException("Email already verified")
    user.is_verified = True
    user.email_verification_token = None
    user.email_verified_at = datetime.utcnow()
    await db.commit()
    return {"message": "Email verified successfully"}

@router.post("/resend-verification")
async def resend_verification(request: OTPRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", request.email)
    if user.is_verified:
        raise BadRequestException("Email already verified")
    verification_token = generate_verification_token()
    user.email_verification_token = verification_token
    await db.commit()
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"
    await EmailService.send_verification_email(to_email=user.email, to_name=user_name, verification_token=verification_token)
    return {"message": "Verification email sent"}
   