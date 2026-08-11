"""Route-wiring guards for the QA work-order endpoints (Aug 2026).

The Goals Tracker and Strategies pages 405'd because only sub-routes existed
(`POST /goals/{id}/adjust` with no `GET /goals`). These tests pin the full
route set so a refactor can't silently drop a page's backing endpoint again.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.investment import router as investment_router
from app.api.v1.portfolio import router as portfolio_router


def _routes(router):
    table = {}
    for route in router.routes:
        for method in route.methods:
            table.setdefault(route.path, set()).add(method)
    return table


def test_goals_crud_routes_exist():
    routes = _routes(investment_router)
    assert "GET" in routes.get("/goals", set())
    assert "POST" in routes.get("/goals", set())
    assert "GET" in routes.get("/goals/{goal_id}", set())
    assert "DELETE" in routes.get("/goals/{goal_id}", set())
    assert "POST" in routes.get("/goals/{goal_id}/adjust", set())


def test_strategy_list_and_detail_routes_exist():
    routes = _routes(investment_router)
    assert "GET" in routes.get("/strategies", set())
    assert "POST" in routes.get("/strategies", set())  # create (frontend integration, 11 Aug)
    assert "GET" in routes.get("/strategies/{strategy_id}", set())
    assert "POST" in routes.get("/strategies/{strategy_id}/clone", set())


def test_transfer_routes_exist():
    routes = _routes(portfolio_router)
    assert "POST" in routes.get("/cash-flow/transfers", set())
    assert "GET" in routes.get("/cash-flow/transfers/{transfer_id}", set())


def test_batch_quotes_route_exists():
    routes = _routes(portfolio_router)
    assert "GET" in routes.get("/trade-engine/quotes", set())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
