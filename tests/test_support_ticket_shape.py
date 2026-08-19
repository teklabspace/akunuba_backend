"""Structural tests for the support ticket endpoints.

No DB needed -- these inspect the FastAPI route table and Pydantic models
directly, matching the pattern in tests/test_security_permissions.py and
tests/test_avatar_support.py.

Backs a frontend change request: GET /support/tickets and .../{id} used to
return a 7-field subset (id, ticket_number, subject, status, priority,
created_at, requester) so the ticket body, last-updated date, category,
assignee and CSAT state were all missing from the UI, and admins got a 404
on the list because the account lookup happened before the staff check.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inspect

from fastapi.routing import APIRoute

from app.api.v1.support import TicketAssignee, TicketRequester, TicketResponse, list_tickets
from app.main import app


def _support_ticket_routes():
    return [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/v1/support/tickets")]


def test_stats_route_is_registered_before_the_dynamic_ticket_id_route():
    routes = _support_ticket_routes()
    stats_index = next(i for i, r in enumerate(routes) if r.path == "/api/v1/support/tickets/stats")
    dynamic_index = next(i for i, r in enumerate(routes) if r.path == "/api/v1/support/tickets/{ticket_id}" and "GET" in r.methods)
    assert stats_index < dynamic_index, (
        "/tickets/stats must be declared before /tickets/{ticket_id} or FastAPI "
        "tries to parse 'stats' as a ticket UUID and 422s"
    )


def test_ticket_response_carries_every_field_the_ui_needs():
    required = {
        "description", "updated_at", "category", "resolved_at",
        "assignee", "satisfaction_rating", "documents_count", "replies_count",
    }
    missing = required - set(TicketResponse.model_fields)
    assert not missing, f"TicketResponse is missing {missing}"


def test_requester_and_assignee_carry_avatar_url():
    assert "avatar_url" in TicketRequester.model_fields
    assert "avatar_url" in TicketAssignee.model_fields


def test_list_tickets_accepts_pagination_and_priority_filter():
    params = inspect.signature(list_tickets).parameters
    assert "page" in params
    assert "limit" in params
    assert "priority" in params


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[OK] {name}")
    print("All support ticket shape tests passed.")
