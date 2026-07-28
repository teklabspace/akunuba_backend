import time
import httpx
from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta


class PolygonClient:
    BASE_URL = "https://api.polygon.io"

    # Free-tier keys get 403 on snapshot endpoints. Remember the first 403 so
    # we stop wasting rate-limit budget (5 req/min on free tier) on calls that
    # can never succeed for this key.
    _snapshot_unavailable = False

    # In-process TTL cache. The free key allows 5 req/min and one trade-engine
    # page load fires several calls, so every repeated request MUST be served
    # from memory. On errors (usually 429) a stale entry is better than none.
    _cache: Dict[str, tuple] = {}

    @classmethod
    def snapshot_unavailable(cls) -> bool:
        return cls._snapshot_unavailable

    @staticmethod
    def _get_params() -> Dict[str, str]:
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured")
            return {}
        return {"apiKey": settings.POLYGON_API_KEY}

    @staticmethod
    def _cached_get(url: str, params: Dict[str, str], ttl: int) -> Optional[Dict[str, Any]]:
        """GET with TTL cache; serves a stale entry when the live call fails."""
        key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        now = time.time()
        hit = PolygonClient._cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        try:
            with httpx.Client() as client:
                response = client.get(url, params=params, timeout=30.0)
                response.raise_for_status()
                data = response.json()
        except Exception:
            if hit:
                logger.warning(f"Polygon request failed, serving stale cache: {url}")
                return hit[1]
            raise
        if len(PolygonClient._cache) > 500:
            expired = [k for k, v in PolygonClient._cache.items() if v[0] <= now]
            for k in expired:
                PolygonClient._cache.pop(k, None)
        PolygonClient._cache[key] = (now + ttl, data)
        return data

    @staticmethod
    def get_ticker_details(ticker: str) -> Optional[Dict[str, Any]]:
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            # Reference data barely changes — cache for a day.
            return PolygonClient._cached_get(
                f"{PolygonClient.BASE_URL}/v2/reference/tickers/{ticker}",
                PolygonClient._get_params(),
                ttl=86400,
            )
        except Exception as e:
            logger.error(f"Failed to get Polygon ticker details: {e}")
            return None

    @staticmethod
    def get_aggregates(ticker: str, multiplier: int, timespan: str, from_date: str, to_date: str) -> Optional[Dict[str, Any]]:
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            # Free-tier bars are end-of-day anyway — 5 minutes of cache costs
            # nothing in freshness and saves the rate limit. limit=50000 (the
            # max) so long hourly ranges are never silently truncated.
            params = PolygonClient._get_params()
            params["limit"] = "50000"
            return PolygonClient._cached_get(
                f"{PolygonClient.BASE_URL}/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}",
                params,
                ttl=300,
            )
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
        if PolygonClient._snapshot_unavailable:
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
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                PolygonClient._snapshot_unavailable = True
                logger.warning("Polygon snapshot endpoint forbidden (free-tier key) - disabling snapshot calls")
            else:
                logger.error(f"Failed to get Polygon snapshot: {e}")
            return None
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
    def search_tickers(query: str, limit: int = 10, market: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """Search for tickers by name or symbol.

        market: Polygon market filter — "stocks", "crypto", "fx" — or None for all.
        """
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            params = PolygonClient._get_params()
            if query:
                params["search"] = query
            params["limit"] = str(limit)
            params["active"] = "true"
            if market:
                params["market"] = market

            # 10-minute cache: the browse list (empty query) is requested on
            # every trade-engine page load and never changes intraday.
            data = PolygonClient._cached_get(
                f"{PolygonClient.BASE_URL}/v3/reference/tickers",
                params,
                ttl=600,
            )
            return (data or {}).get("results", [])
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
    def get_previous_close(ticker: str) -> Optional[Dict[str, Any]]:
        """Get previous-day bar for a ticker (available on free-tier keys)"""
        if not settings.POLYGON_API_KEY:
            logger.warning("Polygon API key not configured - skipping request")
            return None
        try:
            return PolygonClient._cached_get(
                f"{PolygonClient.BASE_URL}/v2/aggs/ticker/{ticker}/prev",
                PolygonClient._get_params(),
                ttl=300,
            )
        except Exception as e:
            logger.error(f"Failed to get Polygon previous close: {e}")
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
            if price:
                return float(price)
        # Snapshot requires a paid Polygon plan (403 on free-tier keys) —
        # fall back to the previous-day close, which free keys can access.
        prev = PolygonClient.get_previous_close(ticker)
        if prev and prev.get("results"):
            close = prev["results"][0].get("c")
            return float(close) if close else None
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

