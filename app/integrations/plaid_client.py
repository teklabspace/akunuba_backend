try:
    from plaid.api import plaid_api
    from plaid.configuration import Configuration
    from plaid.api_client import ApiClient
    PLAID_AVAILABLE = True
except ImportError:
    PLAID_AVAILABLE = False
    plaid_api = None
    Configuration = None
    ApiClient = None

from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any


class PlaidClient:
    _instance: Optional[plaid_api.PlaidApi] = None

    @classmethod
    def get_client(cls) -> Optional[plaid_api.PlaidApi]:
        if not PLAID_AVAILABLE:
            logger.warning("Plaid SDK not installed. Install with: pip install plaid-python")
            return None
        if cls._instance is None:
            try:
                configuration = Configuration(
                    host=settings.PLAID_ENV,
                    api_key={
                        "clientId": settings.PLAID_CLIENT_ID,
                        "secret": settings.PLAID_SECRET_KEY,
                    }
                )
                api_client = ApiClient(configuration)
                cls._instance = plaid_api.PlaidApi(api_client)
                logger.info("Plaid client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Plaid client: {e}")
                raise
        return cls._instance

    @classmethod
    def create_link_token(cls, user_id: str, account_id: str) -> Dict[str, Any]:
        try:
            client = cls.get_client()
            request = {
                "user": {
                    "client_user_id": user_id,
                },
                "client_name": "Fullego",
                "products": ["transactions", "auth"],
                "country_codes": ["US"],
                "language": "en",
            }
            response = client.link_token_create(request)
            return response["link_token"]
        except Exception as e:
            logger.error(f"Failed to create Plaid link token: {e}")
            raise

    @classmethod
    def exchange_public_token(cls, public_token: str) -> Dict[str, Any]:
        try:
            client = cls.get_client()
            request = {"public_token": public_token}
            response = client.item_public_token_exchange(request)
            return response
        except Exception as e:
            logger.error(f"Failed to exchange Plaid public token: {e}")
            raise

    @classmethod
    def get_accounts(cls, access_token: str) -> Dict[str, Any]:
        try:
            client = cls.get_client()
            request = {"access_token": access_token}
            response = client.accounts_get(request)
            return response
        except Exception as e:
            logger.error(f"Failed to get Plaid accounts: {e}")
            raise

    @classmethod
    def get_transactions(cls, access_token: str, start_date: str, end_date: str) -> Dict[str, Any]:
        try:
            client = cls.get_client()
            request = {
                "access_token": access_token,
                "start_date": start_date,
                "end_date": end_date,
            }
            response = client.transactions_get(request)
            return response
        except Exception as e:
            logger.error(f"Failed to get Plaid transactions: {e}")
            raise

