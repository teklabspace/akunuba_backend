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
        """
        Get or create Plaid API client instance.
        
        Returns:
            PlaidApi instance or None if SDK is not available
            
        Raises:
            ValueError: If credentials are missing
            Exception: If client initialization fails
        """
        if not PLAID_AVAILABLE:
            logger.warning("Plaid SDK not installed. Install with: pip install plaid-python")
            return None
        
        # Validate credentials before initializing
        if not settings.PLAID_CLIENT_ID or not settings.PLAID_SECRET_KEY:
            logger.warning("Plaid credentials not configured")
            return None
        
        if cls._instance is None:
            try:
                # Map environment string to the full Plaid API base URL.
                # The Plaid SDK uses `host` directly as the base path, so it
                # must be a full URL, not the bare environment name.
                plaid_host_map = {
                    "sandbox": "https://sandbox.plaid.com",
                    "development": "https://development.plaid.com",
                    "production": "https://production.plaid.com",
                }

                plaid_host = plaid_host_map.get(
                    settings.PLAID_ENV.lower(),
                    "https://sandbox.plaid.com"  # Default to sandbox
                )
                
                configuration = Configuration(
                    host=plaid_host,
                    api_key={
                        "clientId": settings.PLAID_CLIENT_ID,
                        "secret": settings.PLAID_SECRET_KEY,
                    }
                )
                api_client = ApiClient(configuration)
                cls._instance = plaid_api.PlaidApi(api_client)
                logger.info(f"Plaid client initialized for {plaid_host} environment")
            except Exception as e:
                logger.error(f"Failed to initialize Plaid client: {e}", exc_info=True)
                raise
        return cls._instance

    @classmethod
    def get_webhook_verification_key(cls, key_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the JWK used to verify a Plaid webhook's Plaid-Verification JWT.

        Returns the JWK dict (kty/crv/x/y/kid/...) or None if it can't be retrieved.
        """
        try:
            from plaid.model.webhook_verification_key_get_request import (
                WebhookVerificationKeyGetRequest,
            )
            client = cls.get_client()
            if client is None:
                return None
            request = WebhookVerificationKeyGetRequest(key_id=key_id)
            response = client.webhook_verification_key_get(request)
            key = response.to_dict().get("key")
            return dict(key) if key else None
        except Exception as e:
            logger.error(f"Failed to fetch Plaid webhook verification key {key_id}: {e}")
            return None

    @classmethod
    def create_link_token(cls, user_id: str, account_id: str) -> str:
        """
        Create a Plaid Link token for account linking.
        
        Args:
            user_id: Unique identifier for the user
            account_id: Unique identifier for the account
            
        Returns:
            Link token string
            
        Raises:
            ValueError: If Plaid client is not available or credentials are missing
            Exception: If Plaid API call fails
        """
        # Check if Plaid SDK is available
        if not PLAID_AVAILABLE:
            error_msg = "Plaid SDK not installed. Install with: pip install plaid-python"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Check if credentials are configured
        if not settings.PLAID_CLIENT_ID or not settings.PLAID_SECRET_KEY:
            error_msg = "Plaid credentials not configured. Please set PLAID_CLIENT_ID and PLAID_SECRET_KEY"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        try:
            client = cls.get_client()
            if client is None:
                error_msg = "Failed to initialize Plaid client"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Create link token request. investments/liabilities are billed by
            # Plaid per linked Item as soon as the product is attached, whether
            # or not the corresponding data endpoint is ever called — there is
            # no cheaper "optional" tier for these two products.
            request = {
                "user": {
                    "client_user_id": user_id,
                },
                "client_name": "Akunuba",
                "products": ["transactions", "auth", "investments", "liabilities"],
                "country_codes": ["US"],
                "language": "en",
            }
            
            # Call Plaid API
            response = client.link_token_create(request)
            
            # Extract link token from response
            # Plaid API returns a response object, access link_token attribute
            if hasattr(response, 'link_token'):
                link_token = response.link_token
            elif isinstance(response, dict):
                link_token = response.get("link_token")
            else:
                # Try to access as dictionary
                link_token = response["link_token"]
            
            if not link_token:
                error_msg = "Plaid API returned empty link token"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            logger.info(f"Link token created successfully for user {user_id}")
            return link_token
            
        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception as e:
            error_msg = f"Failed to create Plaid link token: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise Exception(error_msg) from e

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

    @classmethod
    def get_item(cls, access_token: str) -> Dict[str, Any]:
        """The Item behind an access token — institution_id lives here, not on
        the accounts themselves."""
        try:
            client = cls.get_client()
            request = {"access_token": access_token}
            response = client.item_get(request)
            return response
        except Exception as e:
            logger.error(f"Failed to get Plaid item: {e}")
            raise

    @classmethod
    def get_institution(cls, institution_id: str) -> Dict[str, Any]:
        """Institution metadata (real display name, products, etc.) by id."""
        try:
            client = cls.get_client()
            request = {
                "institution_id": institution_id,
                "country_codes": ["US"],
            }
            response = client.institutions_get_by_id(request)
            return response
        except Exception as e:
            logger.error(f"Failed to get Plaid institution {institution_id}: {e}")
            raise

    @classmethod
    def get_investment_holdings(cls, access_token: str) -> Dict[str, Any]:
        """Current holdings + securities for every investment-type account under
        this access token. Requires the Investments product on the Item.

        _check_return_type=False: confirmed against Plaid's own sandbox that
        the generated SDK's response models declare some fields (e.g. a
        security's close_price_as_of) required-non-null more strictly than
        Plaid's actual API — a real sandbox response tripped this exact
        validator on liabilities_get (see get_liabilities below) and raised
        instead of returning data. The response is still used as a plain
        dict via .get() throughout this codebase, so skipping the SDK's
        internal type-check does not change how callers consume it.
        """
        try:
            client = cls.get_client()
            request = {"access_token": access_token}
            response = client.investments_holdings_get(request, _check_return_type=False)
            return response
        except Exception as e:
            logger.error(f"Failed to get Plaid investment holdings: {e}")
            raise

    @classmethod
    def get_liabilities(cls, access_token: str) -> Dict[str, Any]:
        """Detailed credit/mortgage/student liability data for every relevant
        account under this access token. Requires the Liabilities product.

        _check_return_type=False: required, not defensive paranoia — a real
        Plaid sandbox response for a mortgage liability came back with
        account_number: null, which the generated SDK's strict response
        model rejects (`ApiTypeError`) before this method ever sees the
        data. Confirmed the flag resolves it and the response remains
        dict-accessible exactly like every other PlaidClient response here.
        """
        try:
            client = cls.get_client()
            request = {"access_token": access_token}
            response = client.liabilities_get(request, _check_return_type=False)
            return response
        except Exception as e:
            logger.error(f"Failed to get Plaid liabilities: {e}")
            raise

