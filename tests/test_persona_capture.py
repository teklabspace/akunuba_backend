"""Tests for Persona KYC capture parsing.

`parse_inquiry` is a pure transform from a Persona inquiry(+verifications) payload
to {extracted_fields, checks, photos}. These tests pin its behavior against a
realistic payload and a few edge cases.

Runs under pytest *or* standalone:  python tests/test_persona_capture.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.persona_capture import parse_inquiry, _sniff_image, _safe_doc_type


SAMPLE = {
    "data": {"type": "inquiry", "id": "inq_ABC", "attributes": {"status": "approved"}},
    "included": [
        {
            "type": "verification/government-id",
            "id": "ver_1",
            "attributes": {
                "status": "passed",
                "name-first": "Jane",
                "name-last": "Investor",
                "birthdate": "1990-05-01",
                "identification-number": "X1234567",
                "expiration-date": "2030-01-01",
                "address-city": "Lagos",
                "country-code": "NG",
                "front-photo-url": "https://files.persona/front.jpg",
                "back-photo-url": "https://files.persona/back.jpg",
                "checks": [
                    {"name": "id_mrz_detection", "status": "passed", "reasons": []},
                    {"name": "id_expired_detection", "status": "passed"},
                ],
            },
        },
        {
            "type": "verification/selfie",
            "id": "ver_2",
            "attributes": {
                "status": "passed",
                "center-photo-url": "https://files.persona/selfie.jpg",
                "checks": [{"name": "selfie_face_match", "status": "passed"}],
            },
        },
        # Non-verification objects must be ignored.
        {"type": "account", "id": "acc_1", "attributes": {"name-first": "SHOULD_IGNORE"}},
    ],
}


def test_extracts_fields():
    out = parse_inquiry(SAMPLE)
    f = out["extracted_fields"]
    assert f["name_first"] == "Jane"
    assert f["name_last"] == "Investor"
    assert f["identification_number"] == "X1234567"
    assert f["country_code"] == "NG"
    # account object's name-first must not leak in
    assert f["name_first"] != "SHOULD_IGNORE"


def test_extracts_photos_with_types():
    out = parse_inquiry(SAMPLE)
    got = {p["document_type"]: p["url"] for p in out["photos"]}
    assert got["government_id_front"] == "https://files.persona/front.jpg"
    assert got["government_id_back"] == "https://files.persona/back.jpg"
    assert got["selfie_center"] == "https://files.persona/selfie.jpg"
    assert len(out["photos"]) == 3


def test_extracts_checks_with_verification_label():
    out = parse_inquiry(SAMPLE)
    names = {(c["verification"], c["name"]) for c in out["checks"]}
    assert ("government_id", "id_mrz_detection") in names
    assert ("selfie", "selfie_face_match") in names


def test_empty_and_missing_shapes():
    assert parse_inquiry({}) == {"extracted_fields": {}, "checks": [], "photos": []}
    assert parse_inquiry({"included": None}) == {"extracted_fields": {}, "checks": [], "photos": []}
    # verification with no attributes shouldn't crash
    out = parse_inquiry({"included": [{"type": "verification/selfie"}]})
    assert out["photos"] == []


def test_doc_type_sanitized_against_traversal():
    # A malicious/odd photo key must not produce a traversing storage path.
    payload = {"included": [{
        "type": "verification/government-id",
        "attributes": {"../../etc/passwd-photo-url": "https://files.persona/x.jpg"},
    }]}
    out = parse_inquiry(payload)
    dt = out["photos"][0]["document_type"]
    assert "/" not in dt and ".." not in dt, dt
    assert dt == "government_id_etc_passwd"


def test_safe_doc_type():
    assert _safe_doc_type("government_id_front") == "government_id_front"
    assert _safe_doc_type("../../x") == "x"
    assert _safe_doc_type("") == "document"
    assert _safe_doc_type("Selfie/Center") == "selfie_center"


def test_sniff_image():
    assert _sniff_image(b"\xff\xd8\xff\xe0rest") == ("jpg", "image/jpeg")
    assert _sniff_image(b"\x89PNG\r\n\x1a\n") == ("png", "image/png")
    assert _sniff_image(b"%PDF-1.7") == ("pdf", "application/pdf")
    assert _sniff_image(b"unknown") == ("jpg", "image/jpeg")  # default


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
