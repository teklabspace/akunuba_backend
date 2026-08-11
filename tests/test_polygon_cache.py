"""Negative-caching behavior of PolygonClient._cached_get (QA finding B9:
free-tier 429s re-fired on every page load and kept market cards empty)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.integrations.polygon_client as polygon_module
from app.integrations.polygon_client import PolygonClient


class _AlwaysFailClient:
    calls = 0

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        _AlwaysFailClient.calls += 1
        raise RuntimeError("simulated 429")


def test_failed_lookup_is_negative_cached(monkeypatch):
    monkeypatch.setattr(polygon_module.httpx, "Client", _AlwaysFailClient)
    PolygonClient._cache.clear()
    _AlwaysFailClient.calls = 0

    first = PolygonClient._cached_get("https://api.polygon.io/test/neg", {"apiKey": "x"}, ttl=300)
    second = PolygonClient._cached_get("https://api.polygon.io/test/neg", {"apiKey": "x"}, ttl=300)

    assert first is None and second is None
    assert _AlwaysFailClient.calls == 1  # second call served from negative cache


def test_stale_entry_served_on_failure(monkeypatch):
    PolygonClient._cache.clear()
    url = "https://api.polygon.io/test/stale"
    key = url + "?apiKey=x"
    PolygonClient._cache[key] = (0.0, {"results": [{"c": 42}]})  # expired entry

    monkeypatch.setattr(polygon_module.httpx, "Client", _AlwaysFailClient)
    _AlwaysFailClient.calls = 0

    result = PolygonClient._cached_get(url, {"apiKey": "x"}, ttl=300)
    assert result == {"results": [{"c": 42}]}
    assert _AlwaysFailClient.calls == 1


def test_has_cached_price_only_true_for_fresh_positive_entries():
    PolygonClient._cache.clear()
    assert PolygonClient.has_cached_price("AAPL") is False
