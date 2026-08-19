"""Pure tests for app/services/ticket_scope.py.

An advisor's ticket list (GET /support/tickets) used to show every ticket
in the system while their analytics tab (GET /support/analytics) counted
only tickets assigned to them -- same account, same minute, disagreeing
numbers. Both endpoints now read scope from this single function.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.permissions import Role
from app.services.ticket_scope import ticket_scope_for_role


def test_admin_scope_is_all():
    assert ticket_scope_for_role(Role.ADMIN) == "all"


def test_advisor_scope_is_assigned():
    assert ticket_scope_for_role(Role.ADVISOR) == "assigned"


def test_investor_scope_is_own():
    assert ticket_scope_for_role(Role.INVESTOR) == "own"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[OK] {name}")
    print("All ticket scope tests passed.")
