"""Pure tests for app/services/ticket_aggregation.py.

Documents link to a support ticket via a raw JSON-in-text meta_data string
(no real foreign key). count_documents_by_ticket does the substring
matching in Python over one bulk-fetched column, instead of an N+1
GET /tickets/{id}/documents call per row in a ticket list.
"""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ticket_aggregation import count_documents_by_ticket


def test_counts_only_documents_matching_their_own_ticket_id():
    t1, t2 = uuid4(), uuid4()
    rows = [
        f'{{"ticket_id": "{t1}"}}',
        f'{{"ticket_id": "{t2}"}}',
        f'{{"ticket_id": "{t1}"}}',
    ]
    counts = count_documents_by_ticket(rows, [t1, t2])
    assert counts[t1] == 2
    assert counts[t2] == 1


def test_ticket_with_no_documents_counts_zero():
    t1, t2 = uuid4(), uuid4()
    counts = count_documents_by_ticket([], [t1, t2])
    assert counts == {t1: 0, t2: 0}


def test_none_and_unrelated_meta_data_values_are_skipped():
    t1 = uuid4()
    other = uuid4()
    rows = [None, "", f'{{"ticket_id": "{other}"}}']
    counts = count_documents_by_ticket(rows, [t1])
    assert counts[t1] == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[OK] {name}")
    print("All ticket aggregation tests passed.")
