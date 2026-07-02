"""Tests for Persona webhook event parsing.

Persona wraps the affected resource under data.attributes.payload.data, and the
top-level data.id is the EVENT id (evt_...), not the inquiry id (inq_...). The old
parser read the top-level id and so never matched a KYC row. These tests pin the
correct extraction against realistic event envelopes.

Runs under pytest *or* standalone:  python tests/test_persona_webhook_parse.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.webhooks import _parse_persona_event


# Realistic Persona "inquiry.approved" webhook envelope.
APPROVED_EVENT = {
    "data": {
        "type": "event",
        "id": "evt_APMUzRxEVENTIDshouldNOTbeUsed",
        "attributes": {
            "name": "inquiry.approved",
            "payload": {
                "data": {
                    "type": "inquiry",
                    "id": "inq_APMUzRx4JXDpCniSb1LAPpra2zi1Xx",
                    "attributes": {
                        "status": "approved",
                        "reference-id": "KYC-70405d16",
                    },
                }
            },
        },
    }
}


def test_extracts_inquiry_id_not_event_id():
    out = _parse_persona_event(APPROVED_EVENT)
    # Must be the inquiry id, never the top-level event id.
    assert out["inquiry_id"] == "inq_APMUzRx4JXDpCniSb1LAPpra2zi1Xx"
    assert not out["inquiry_id"].startswith("evt_")


def test_extracts_status_from_nested_payload():
    out = _parse_persona_event(APPROVED_EVENT)
    assert out["status"] == "approved"
    assert out["event_type"] == "inquiry.approved"


def test_status_derived_from_event_name_when_missing():
    # Event with no explicit status on the resource -> derive from the event name.
    event = {
        "data": {
            "type": "event",
            "id": "evt_x",
            "attributes": {
                "name": "inquiry.declined",
                "payload": {"data": {"type": "inquiry", "id": "inq_abc", "attributes": {}}},
            },
        }
    }
    out = _parse_persona_event(event)
    assert out["inquiry_id"] == "inq_abc"
    assert out["status"] == "declined"


def test_flat_shape_fallback():
    # Defensive: a non-nested body (e.g. a manual/test post) still yields the id.
    flat = {"data": {"type": "inquiry", "id": "inq_flat", "attributes": {"status": "completed"}}}
    out = _parse_persona_event(flat)
    assert out["inquiry_id"] == "inq_flat"
    assert out["status"] == "completed"


def test_empty_body_is_safe():
    out = _parse_persona_event({})
    assert out["inquiry_id"] is None
    assert out["status"] == ""


def _run_standalone():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
