import httpx
from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta


class PolygonClient:
    BASE_URL = "https://api.polygon.io"

    @staticmethod
    def _get_params() -> Dict[str, str]:
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured")
            return {}
        return {"apiKey": settings.POLYGON_API_KEY}

    @staticmethod
    def get_ticker_details(ticker: str) -> Optional[Dict[str, Any]]:
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v2/reference/tickers/{ticker}",
                    params=PolygonClient._get_params(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Polygon ticker details: {e}")
            return None

    @staticmethod
    def get_aggregates(ticker: str, multiplier: int, timespan: str, from_date: str, to_date: str) -> Optional[Dict[str, Any]]:
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}",
                    params=PolygonClient._get_params(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Polygon aggregates: {e}")
            return None

    @staticmethod
    def get_last_trade(ticker: str) -> Optional[Dict[str, Any]]:
        """Get last trade for a ticker"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v2/last/trade/{ticker}",
                    params=PolygonClient._get_params(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Polygon last trade: {e}")
            return None

    @staticmethod
    def get_last_quote(ticker: str) -> Optional[Dict[str, Any]]:
        """Get last quote (bid/ask) for a ticker"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v2/last/nbbo/{ticker}",
                    params=PolygonClient._get_params(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Polygon last quote: {e}")
            return None

    @staticmethod
    def get_snapshot(ticker: str) -> Optional[Dict[str, Any]]:
        """Get snapshot (current price, volume, etc.) for a ticker"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}",
                    params=PolygonClient._get_params(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Polygon snapshot: {e}")
            return None

    @staticmethod
    def get_ticker_news(ticker: str, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Get news articles for a ticker"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            params = PolygonClient._get_params()
            params["ticker"] = ticker
            params["limit"] = str(limit)
            
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v2/reference/news",
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])
        except Exception as e:
            logger.error(f"Failed to get Polygon ticker news: {e}")
            return None

    @staticmethod
    def search_tickers(query: str, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Search for tickers by name or symbol"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            params = PolygonClient._get_params()
            params["search"] = query
            params["limit"] = str(limit)
            
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v3/reference/tickers",
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])
        except Exception as e:
            logger.error(f"Failed to search Polygon tickers: {e}")
            return None

    @staticmethod
    def get_daily_open_close(ticker: str, date: str) -> Optional[Dict[str, Any]]:
        """Get open/close prices for a specific date"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v1/open-close/{ticker}/{date}",
                    params=PolygonClient._get_params(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Polygon daily open/close: {e}")
            return None

    @staticmethod
    def get_current_price(ticker: str) -> Optional[float]:
        """Get current price for a ticker (simplified)"""
        snapshot = PolygonClient.get_snapshot(ticker)
        if snapshot and snapshot.get("ticker"):
            ticker_data = snapshot["ticker"]
            # Try different price fields
            price = (
                ticker_data.get("lastTrade", {}).get("p") or
                ticker_data.get("day", {}).get("c") or
                ticker_data.get("prevDay", {}).get("c")
            )
            return float(price) if price else None
        return None

    @staticmethod
    def get_market_status() -> Optional[Dict[str, Any]]:
        """Get current market status (open/closed)"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v1/marketstatus/now",
                    params=PolygonClient._get_params(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Polygon market status: {e}")
            return None

    @staticmethod
    def get_grouped_daily(date: str) -> Optional[Dict[str, Any]]:
        """Get grouped daily bars for all tickers on a specific date"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v2/aggs/grouped/locale/us/market/stocks/{date}",
                    params=PolygonClient._get_params(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Polygon grouped daily: {e}")
            return None

    @staticmethod
    def get_trades(ticker: str, timestamp: Optional[int] = None, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Get recent trades for a ticker"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            params = PolygonClient._get_params()
            if timestamp:
                params["timestamp"] = str(timestamp)
            params["limit"] = str(limit)
            
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v3/trades/{ticker}",
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])
        except Exception as e:
            logger.error(f"Failed to get Polygon trades: {e}")
            return None

    @staticmethod
    def get_quotes(ticker: str, timestamp: Optional[int] = None, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Get recent quotes for a ticker"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            params = PolygonClient._get_params()
            if timestamp:
                params["timestamp"] = str(timestamp)
            params["limit"] = str(limit)
            
            with httpx.Client() as client:
                response = client.get(
                    f"{PolygonClient.BASE_URL}/v3/quotes/{ticker}",
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("results", [])
        except Exception as e:
            logger.error(f"Failed to get Polygon quotes: {e}")
            return None

