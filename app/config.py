from pydantic_settings import BaseSettings
from typing import List, Union
from pydantic import field_validator


class Settings(BaseSettings):
    APP_NAME: str = "Fullego Backend"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: Union[List[str], str] = ["http://localhost:3000", "http://localhost:5173"]
    
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            # Handle comma-separated string from environment variables
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    # Supabase Configuration
    # Configure via environment variables
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str
    
    DATABASE_URL: str
    
    STRIPE_SECRET_KEY: str
    STRIPE_PUBLISHABLE_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    
    PLAID_CLIENT_ID: str = ""
    PLAID_SECRET_KEY: str = ""
    PLAID_PUBLIC_KEY: str = ""
    PLAID_ENV: str = "sandbox"
    
    PERSONA_API_KEY: str
    PERSONA_TEMPLATE_ID: str = ""  # Inquiry Template ID (starts with 'itmpl_') - defines verification flow
    PERSONA_FILE_ACCESS_TOKEN_EXPIRY: int = 21600  # seconds (6 hours default)
    PERSONA_REDIRECT_URI: str = ""  # Redirect URI after Persona verification completes (e.g., https://yourapp.com/kyc/complete)
    
    SENDBIRD_APP_ID: str
    SENDBIRD_API_TOKEN: str
    
    # Polygon Market Data API
    POLYGON_API_KEY: str = ""
    
    # Polygon S3-Compatible File Storage (Optional)
    POLYGON_S3_ACCESS_KEY_ID: str = ""
    POLYGON_S3_SECRET_ACCESS_KEY: str = ""
    POLYGON_S3_ENDPOINT: str = "https://files.massive.com"
    
    # Alpaca API Key Authentication (Legacy)
    ALPACA_API_KEY_ID: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
    
    # Alpaca OAuth2 Authentication (Recommended)
    ALPACA_OAUTH_ENABLED: bool = False
    ALPACA_OAUTH_CLIENT_ID: str = ""
    ALPACA_OAUTH_CLIENT_SECRET: str = ""
    ALPACA_OAUTH_TOKEN_URL: str = "https://authx.alpaca.markets/v1/oauth2/token"
    ALPACA_OAUTH_BASE_URL: str = "https://api.alpaca.markets"  # or https://paper-api.alpaca.markets for paper
    
    POSTHOG_API_KEY: str = ""
    POSTHOG_PROJECT_API_KEY: str = ""
    POSTHOG_HOST: str = "https://us.i.posthog.com"
    
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_ZONE_ID: str = ""
    
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    
    # Email Service (Resend)
    RESEND_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "onboarding@resend.dev"
    EMAIL_FROM_NAME: str = "Fullego"
    EMAIL_ENABLED: bool = True
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/auth/google/callback"
    
    MAX_UPLOAD_SIZE: int = 10485760
    ALLOWED_FILE_TYPES: List[str] = ["pdf", "doc", "docx", "jpg", "jpeg", "png"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
