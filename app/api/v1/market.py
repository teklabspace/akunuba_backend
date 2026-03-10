from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.integrations.polygon_client import PolygonClient
from app.core.exceptions import BadRequestException
from app.utils.logger import logger
from pydantic import BaseModel

router = APIRouter()


class BenchmarkDataPoint(BaseModel):
    date: str
    value: float


class BenchmarkResponse(BaseModel):
    symbol: str
    name: str
    currentValue: float
    change: float
    changePercentage: float
    currency: str = "USD"
    historicalData: List[BenchmarkDataPoint] = []


class BenchmarksResponse(BaseModel):
    benchmarks: List[BenchmarkResponse]
    timeRange: str
    updatedAt: str


# Simple in-memory cache for benchmark responses (15 minute TTL)
_BENCHMARK_CACHE = {}
_BENCHMARK_CACHE_TTL_SECONDS = 15 * 60


@router.get("/benchmarks", response_model=BenchmarksResponse)
async def get_market_benchmarks(
    benchmarks: Optional[List[str]] = Query(None, description="Array of benchmark symbols (e.g., ['SPY','DIA','TSLA'])"),
    timeRange: str = Query("1Y", description="Time range: 1D, 1W, 1M, 3M, 6M, 1Y, ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get market benchmark data"""
    # Default benchmarks
    default_benchmarks = ["SPY", "DIA", "TSLA"]

    if benchmarks:
        benchmark_list = [b.strip().upper() for b in benchmarks if b.strip()]
        if len(benchmark_list) > 10:
            raise BadRequestException("Maximum 10 benchmarks allowed per request")
    else:
        benchmark_list = default_benchmarks

    # Validate timeRange
    valid_ranges = ["1D", "1W", "1M", "3M", "6M", "1Y", "ALL"]
    if timeRange not in valid_ranges:
        raise BadRequestException(f"Invalid timeRange. Must be one of: {', '.join(valid_ranges)}")

    # Check cache
    cache_key = (tuple(benchmark_list), timeRange)
    now = datetime.utcnow()
    cached = _BENCHMARK_CACHE.get(cache_key)
    if cached:
        cached_time, cached_response = cached
        if (now - cached_time).total_seconds() < _BENCHMARK_CACHE_TTL_SECONDS:
            return cached_response

    # Map timeRange to days
    time_range_map = {
        "1D": 1,
        "1W": 7,
        "1M": 30,
        "3M": 90,
        "6M": 180,
        "1Y": 365,
        "ALL": 365 * 5,  # 5 years max
    }
    days = time_range_map.get(timeRange, 365)

    benchmark_responses: List[BenchmarkResponse] = []

    for symbol in benchmark_list:
        try:
            # Get current price
            current_price = PolygonClient.get_current_price(symbol)
            if not current_price:
                logger.warning(f"Could not get price for {symbol}")
                continue

            # Get previous day for change calculation
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
            prev_data = PolygonClient.get_daily_open_close(symbol, yesterday)
            prev_price = prev_data.get("close") if prev_data else current_price

            change = current_price - prev_price
            change_percentage = (change / prev_price * 100) if prev_price > 0 else 0

            # Get historical data
            historical_data: List[BenchmarkDataPoint] = []
            if timeRange != "1D":
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=days)

                # Get aggregates for historical data
                multiplier = 1
                timespan = "day"
                if timeRange == "1W":
                    timespan = "hour"
                elif timeRange in ["1M", "3M"]:
                    timespan = "day"

                aggregates = PolygonClient.get_aggregates(
                    ticker=symbol,
                    multiplier=multiplier,
                    timespan=timespan,
                    from_date=start_date.strftime("%Y-%m-%d"),
                    to_date=end_date.strftime("%Y-%m-%d"),
                )

                if aggregates and aggregates.get("results"):
                    for result in aggregates["results"]:
                        timestamp_ms = result.get("t", 0)
                        timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
                        value = result.get("c", 0)  # Close price
                        historical_data.append(
                            BenchmarkDataPoint(
                                date=timestamp.strftime("%Y-%m-%d"),
                                value=float(value),
                            )
                        )

            # Get symbol name
            ticker_details = PolygonClient.get_ticker_details(symbol)
            name = symbol
            if ticker_details and ticker_details.get("results"):
                name = ticker_details["results"].get("name", symbol)

            benchmark_responses.append(
                BenchmarkResponse(
                    symbol=symbol,
                    name=name,
                    currentValue=round(current_price, 2),
                    change=round(change, 2),
                    changePercentage=round(change_percentage, 2),
                    currency="USD",
                    historicalData=historical_data,
                )
            )
        except Exception as e:
            logger.error(f"Failed to get benchmark data for {symbol}: {e}")
            continue

    response = BenchmarksResponse(
        benchmarks=benchmark_responses,
        timeRange=timeRange,
        updatedAt=now.isoformat() + "Z",
    )
    _BENCHMARK_CACHE[cache_key] = (now, response)
    return response
