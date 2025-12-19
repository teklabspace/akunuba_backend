try:
    # Try new SDK first (alpaca-py)
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, StopOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    ALPACA_AVAILABLE = True
    ALPACA_NEW_SDK = True
except ImportError:
    try:
        # Fallback to old SDK (alpaca-trade-api)
        from alpaca.trade.client import TradeClient as TradingClient
        from alpaca.trade.requests import MarketOrderRequest, LimitOrderRequest, StopOrderRequest
        from alpaca.trade.enums import OrderSide, TimeInForce
        ALPACA_AVAILABLE = True
        ALPACA_NEW_SDK = False
    except ImportError:
        ALPACA_AVAILABLE = False
        ALPACA_NEW_SDK = False
        TradingClient = None
        MarketOrderRequest = None
        LimitOrderRequest = None
        StopOrderRequest = None
        OrderSide = None
        TimeInForce = None

from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any, List
import httpx
import time
from datetime import datetime, timedelta


class AlpacaClient:
    _instance: Optional[TradingClient] = None
    _oauth_token: Optional[str] = None
    _oauth_token_expires_at: Optional[datetime] = None

    @classmethod
    def _get_oauth_token(cls) -> Optional[str]:
        """Get OAuth2 access token with caching and auto-refresh"""
        # Check if we have a valid cached token
        if cls._oauth_token and cls._oauth_token_expires_at:
            if datetime.utcnow() < cls._oauth_token_expires_at - timedelta(minutes=5):  # Refresh 5 min before expiry
                return cls._oauth_token
        
        # Request new token
        if not settings.ALPACA_OAUTH_CLIENT_ID or not settings.ALPACA_OAUTH_CLIENT_SECRET:
            logger.warning("Alpaca OAuth credentials not configured")
            return None
        
        try:
            payload = {
                "grant_type": "client_credentials",
                "client_id": settings.ALPACA_OAUTH_CLIENT_ID,
                "client_secret": settings.ALPACA_OAUTH_CLIENT_SECRET,
            }
            
            headers = {
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded"
            }
            
            with httpx.Client() as client:
                response = client.post(
                    settings.ALPACA_OAUTH_TOKEN_URL,
                    data=payload,
                    headers=headers,
                    timeout=30.0
                )
                response.raise_for_status()
                token_data = response.json()
                
                cls._oauth_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
                cls._oauth_token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                
                logger.info("Alpaca OAuth2 token obtained successfully")
                return cls._oauth_token
                
        except Exception as e:
            logger.error(f"Failed to get Alpaca OAuth2 token: {e}")
            return None

    @classmethod
    def get_client(cls) -> Optional[TradingClient]:
        """Get Alpaca client instance - supports both API key and OAuth2 authentication"""
        if not ALPACA_AVAILABLE:
            logger.warning("Alpaca SDK not installed. Install with: pip install alpaca-py")
            return None
        
        # Try OAuth2 first if enabled
        if settings.ALPACA_OAUTH_ENABLED:
            oauth_token = cls._get_oauth_token()
            if oauth_token:
                if cls._instance is None:
                    try:
                        # Note: Alpaca Python SDK may need OAuth token support
                        # For now, we'll use API key method but with OAuth token
                        # You may need to modify the SDK or use direct HTTP calls
                        logger.info("Using OAuth2 authentication for Alpaca")
                        # Fallback to API key method if OAuth not fully supported in SDK
                        if settings.ALPACA_API_KEY_ID and settings.ALPACA_SECRET_KEY:
                            is_paper = "paper" in settings.ALPACA_OAUTH_BASE_URL.lower()
                            if ALPACA_NEW_SDK:
                                cls._instance = TradingClient(
                                    api_key=settings.ALPACA_API_KEY_ID,
                                    secret_key=settings.ALPACA_SECRET_KEY,
                                    paper=is_paper
                                )
                            else:
                                cls._instance = TradingClient(
                                    api_key=settings.ALPACA_API_KEY_ID,
                                    secret_key=settings.ALPACA_SECRET_KEY,
                                    base_url=settings.ALPACA_OAUTH_BASE_URL,
                                    paper=is_paper
                                )
                        else:
                            logger.warning("OAuth2 enabled but API keys needed for SDK compatibility")
                            return None
                    except Exception as e:
                        logger.error(f"Failed to initialize Alpaca client with OAuth: {e}")
                        return None
                return cls._instance
        
        # Fallback to API key authentication
        if not settings.ALPACA_API_KEY_ID or not settings.ALPACA_SECRET_KEY:
            logger.warning("Alpaca API keys not configured")
            return None
        
        if cls._instance is None:
            try:
                is_paper = "paper" in settings.ALPACA_BASE_URL.lower()
                if ALPACA_NEW_SDK:
                    cls._instance = TradingClient(
                        api_key=settings.ALPACA_API_KEY_ID,
                        secret_key=settings.ALPACA_SECRET_KEY,
                        paper=is_paper
                    )
                else:
                    cls._instance = TradingClient(
                        api_key=settings.ALPACA_API_KEY_ID,
                        secret_key=settings.ALPACA_SECRET_KEY,
                        base_url=settings.ALPACA_BASE_URL,
                        paper=is_paper
                    )
                logger.info("Alpaca client initialized with API key authentication")
            except Exception as e:
                logger.error(f"Failed to initialize Alpaca client: {e}")
                return None
        return cls._instance

    @classmethod
    def get_oauth_headers(cls) -> Optional[Dict[str, str]]:
        """Get OAuth2 headers for direct API calls"""
        if not settings.ALPACA_OAUTH_ENABLED:
            return None
        
        token = cls._get_oauth_token()
        if not token:
            return None
        
        return {
            "Authorization": f"Bearer {token}",
            "accept": "application/json"
        }

    @classmethod
    def create_market_order(cls, symbol: str, qty: float, side: str) -> Optional[Dict[str, Any]]:
        if not ALPACA_AVAILABLE:
            logger.warning("Alpaca SDK not available")
            return None
        client = cls.get_client()
        if not client:
            return None
        try:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            order = client.submit_order(order_data=order_data)
            return order
        except Exception as e:
            logger.error(f"Failed to create Alpaca market order: {e}")
            return None

    @classmethod
    def create_limit_order(cls, symbol: str, qty: float, side: str, limit_price: float) -> Optional[Dict[str, Any]]:
        if not ALPACA_AVAILABLE:
            logger.warning("Alpaca SDK not available")
            return None
        client = cls.get_client()
        if not client:
            return None
        try:
            order_data = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY
            )
            order = client.submit_order(order_data=order_data)
            return order
        except Exception as e:
            logger.error(f"Failed to create Alpaca limit order: {e}")
            return None

    @classmethod
    def create_stop_order(cls, symbol: str, qty: float, side: str, stop_price: float) -> Optional[Dict[str, Any]]:
        if not ALPACA_AVAILABLE:
            logger.warning("Alpaca SDK not available")
            return None
        client = cls.get_client()
        if not client:
            return None
        try:
            order_data = StopOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
                stop_price=stop_price,
                time_in_force=TimeInForce.DAY
            )
            order = client.submit_order(order_data=order_data)
            return order
        except Exception as e:
            logger.error(f"Failed to create Alpaca stop order: {e}")
            return None

    @classmethod
    def cancel_order(cls, order_id: str) -> bool:
        client = cls.get_client()
        if not client:
            return False
        try:
            client.cancel_order_by_id(order_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel Alpaca order: {e}")
            return False

    @classmethod
    def get_account(cls) -> Optional[Dict[str, Any]]:
        """Get Alpaca account information"""
        client = cls.get_client()
        if not client:
            return None
        try:
            account = client.get_account()
            return account
        except Exception as e:
            logger.error(f"Failed to get Alpaca account: {e}")
            return None

    @classmethod
    def get_positions(cls) -> Optional[List[Dict[str, Any]]]:
        """Get all open positions"""
        client = cls.get_client()
        if not client:
            return None
        try:
            positions = client.list_positions()
            return [position._raw for position in positions] if hasattr(positions[0], '_raw') else positions
        except Exception as e:
            logger.error(f"Failed to get Alpaca positions: {e}")
            return None

    @classmethod
    def get_orders(cls, status: Optional[str] = None, limit: int = 50) -> Optional[List[Dict[str, Any]]]:
        """Get orders (optionally filtered by status)"""
        client = cls.get_client()
        if not client:
            return None
        try:
            orders = client.list_orders(status=status, limit=limit)
            return [order._raw for order in orders] if hasattr(orders[0], '_raw') else orders
        except Exception as e:
            logger.error(f"Failed to get Alpaca orders: {e}")
            return None

    @classmethod
    def get_order_by_id(cls, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order by ID"""
        client = cls.get_client()
        if not client:
            return None
        try:
            order = client.get_order_by_id(order_id)
            return order._raw if hasattr(order, '_raw') else order
        except Exception as e:
            logger.error(f"Failed to get Alpaca order: {e}")
            return None

    @classmethod
    def create_fractional_order(cls, symbol: str, notional: float, side: str) -> Optional[Dict[str, Any]]:
        """Create fractional share order (dollar amount instead of quantity)"""
        client = cls.get_client()
        if not client:
            return None
        try:
            order_data = MarketOrderRequest(
                symbol=symbol,
                notional=notional,  # Dollar amount instead of qty
                side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            order = client.submit_order(order_data=order_data)
            return order
        except Exception as e:
            logger.error(f"Failed to create Alpaca fractional order: {e}")
            return None

    @classmethod
    def get_portfolio_history(cls, period: str = "1M", timeframe: str = "1Day") -> Optional[Dict[str, Any]]:
        """Get portfolio history"""
        client = cls.get_client()
        if not client:
            return None
        try:
            history = client.get_portfolio_history(period=period, timeframe=timeframe)
            return history._raw if hasattr(history, '_raw') else history
        except Exception as e:
            logger.error(f"Failed to get Alpaca portfolio history: {e}")
            return None

    @classmethod
    def make_oauth_request(cls, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Make direct API request using OAuth2 token (for operations not supported by SDK)"""
        if not settings.ALPACA_OAUTH_ENABLED:
            logger.warning("OAuth2 not enabled, cannot make OAuth request")
            return None
        
        token = cls._get_oauth_token()
        if not token:
            logger.error("Failed to get OAuth2 token")
            return None
        
        base_url = settings.ALPACA_OAUTH_BASE_URL or settings.ALPACA_BASE_URL
        url = f"{base_url}{endpoint}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "accept": "application/json",
            "content-type": "application/json"
        }
        
        try:
            with httpx.Client() as client:
                if method.upper() == "GET":
                    response = client.get(url, headers=headers, timeout=30.0)
                elif method.upper() == "POST":
                    response = client.post(url, headers=headers, json=data, timeout=30.0)
                elif method.upper() == "PUT":
                    response = client.put(url, headers=headers, json=data, timeout=30.0)
                elif method.upper() == "DELETE":
                    response = client.delete(url, headers=headers, timeout=30.0)
                else:
                    logger.error(f"Unsupported HTTP method: {method}")
                    return None
                
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to make OAuth2 API request: {e}")
            return None

    @classmethod
    def get_transactions(cls, start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        """Get account transactions/history"""
        # Use OAuth2 direct API call for transactions
        if settings.ALPACA_OAUTH_ENABLED:
            endpoint = "/v2/account/activities"
            params = {}
            if start_date:
                params["start"] = start_date
            if end_date:
                params["end"] = end_date
            if limit:
                params["limit"] = limit
            
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            if query_string:
                endpoint = f"{endpoint}?{query_string}"
            
            result = cls.make_oauth_request("GET", endpoint)
            return result if isinstance(result, list) else None
        
        # Fallback: Try using SDK if available
        client = cls.get_client()
        if not client:
            return None
        try:
            # Note: Alpaca SDK may not have direct transaction endpoint
            # We'll use activities endpoint via direct API
            return None
        except Exception as e:
            logger.error(f"Failed to get Alpaca transactions: {e}")
            return None

    @classmethod
    def get_assets(cls) -> Optional[List[Dict[str, Any]]]:
        """Get all assets (positions) the user has"""
        return cls.get_positions()

