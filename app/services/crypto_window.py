"""Time windows for the crypto portfolio chart.

Replaces two pieces of ad-hoc logic that were behind reported bugs:

* ``int({"7d": 7, "30d": 30, "1y": 365}.get(time_range, 30))`` — an
  unrecognised dropdown value silently served 30 days with a 200, so the
  period selector looked inert instead of erroring;
* nothing anywhere accepted a start/end date, so a custom date range was
  impossible to express.

Both the fixed options and a custom range now resolve to the same ``Window``,
and the chart is drawn from ``snapshot_points`` regardless of which the caller
used. All of it is pure, and tested in ``tests/test_crypto_time_window.py``.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

# Exactly what the endpoint advertises to the frontend. Anything else is a 400,
# never a silent fallback.
SUPPORTED_TIME_RANGES = ("1h", "6h", "12h", "24h", "7d", "30d", "1y")

_RANGE_SPANS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "1y": timedelta(days=365),
}

# A span at or under this is drawn against a clock axis rather than a date axis.
INTRADAY_LIMIT = timedelta(hours=24)

# Every point costs a valuation lookup per asset, so a wide custom range is
# downsampled rather than walked day by day.
MAX_POINTS = 366
MIN_POINTS = 6


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @property
    def span(self) -> timedelta:
        return self.end - self.start

    @property
    def is_intraday(self) -> bool:
        return self.span <= INTRADAY_LIMIT


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes are treated as UTC. Comparing naive to aware raises
    TypeError and has caused real 500s elsewhere in this codebase."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def resolve_window(
    time_range: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Window:
    """Resolve a custom date range or a fixed dropdown option to a Window.

    An explicit date range wins over ``time_range`` — the picker is the more
    specific instruction. Raises ValueError on anything unrecognised or
    incoherent so the caller can turn it into a 400.
    """
    now = _as_utc(now or datetime.now(timezone.utc))

    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date must be supplied together")
        start, end = _as_utc(start_date), _as_utc(end_date)
        if start >= end:
            raise ValueError("start_date must be earlier than end_date")
        return Window(start=start, end=end)

    if not time_range:
        raise ValueError(
            "Provide time_range "
            f"({', '.join(SUPPORTED_TIME_RANGES)}) or a start_date/end_date pair"
        )

    span = _RANGE_SPANS.get(str(time_range).strip().lower())
    if span is None:
        raise ValueError(
            f"Unsupported time_range: {time_range}. "
            f"Supported: {', '.join(SUPPORTED_TIME_RANGES)}"
        )
    return Window(start=now - span, end=now)


def _interval_count(window: Window) -> int:
    """How many gaps between samples. One more point than this is emitted, so
    the cap is MAX_POINTS - 1. Intraday gets ~2/hour (a 24h range used to
    produce a single dot); longer ranges get one per day, capped."""
    ceiling = MAX_POINTS - 1
    if window.is_intraday:
        hours = window.span.total_seconds() / 3600
        return max(MIN_POINTS, min(ceiling, int(hours * 2)))
    return max(MIN_POINTS, min(ceiling, window.span.days))


def snapshot_points(window: Window) -> List[Tuple[datetime, str]]:
    """Evenly spaced (datetime, axis label) pairs, ascending, inclusive of both
    ends. Labels are clock times intraday and dates otherwise."""
    count = _interval_count(window)
    label_format = "%H:%M" if window.is_intraday else "%Y-%m-%d"
    step = window.span / count

    points: List[Tuple[datetime, str]] = []
    for index in range(count + 1):
        moment = window.start + step * index
        points.append((moment, moment.strftime(label_format)))
    return points
