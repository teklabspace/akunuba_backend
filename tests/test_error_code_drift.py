"""Drift guard: backend error codes must match the shared frontend contract.

The frontend imports ``doc/api_error_codes.js`` verbatim to branch on ``error.code``.
If the backend emits a code that isn't in that file, the frontend can't handle it;
if the file lists a code the backend never emits, the contract is lying. This test
fails CI on either, enforcing the "same PR" rule from doc/API_ERROR_CODES.md.

Runs under pytest *or* standalone:  python tests/test_error_code_drift.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_CONTRACT = ROOT / "doc" / "api_error_codes.js"
APP_DIR = ROOT / "app"

# Ensure the repo root is importable when run as a standalone script
# (python tests/test_error_code_drift.py), not just under pytest.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def js_contract_codes() -> set:
    """Codes declared in the shared JS contract (object keys + the fallback)."""
    text = JS_CONTRACT.read_text(encoding="utf-8")
    # Keys inside API_ERROR_CODES, e.g.  `BAD_REQUEST: 400,`
    codes = set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*\d+", text, re.MULTILINE))
    # The string fallback, e.g.  `const FALLBACK_ERROR_CODE = "ERROR";`
    codes |= set(re.findall(r'FALLBACK_ERROR_CODE\s*=\s*["\']([A-Z0-9_]+)["\']', text))
    return codes


def backend_emitted_codes() -> set:
    """Every code the backend can actually put in error.code."""
    codes = set()

    # 1. Generic, status-derived codes + the ultimate fallback.
    from app.core.responses import STATUS_TO_CODE, error_code_for
    codes |= set(STATUS_TO_CODE.values())
    codes.add(error_code_for(599))  # unmapped status -> fallback ("ERROR")

    # 2. Per-exception default codes  (e.g.  `code: str = "NOT_FOUND"`).
    exc_text = (APP_DIR / "core" / "exceptions.py").read_text(encoding="utf-8")
    codes |= set(re.findall(r'code\s*:\s*str\s*=\s*["\']([A-Z0-9_]+)["\']', exc_text))

    # 3. Explicit domain codes passed at raise sites  (`code="PLAN_INVALID"`).
    for py in APP_DIR.rglob("*.py"):
        codes |= set(re.findall(r'code\s*=\s*["\']([A-Z0-9_]+)["\']', py.read_text(encoding="utf-8")))

    return codes


def test_no_backend_code_missing_from_contract():
    """Every code the backend emits must exist in the JS contract."""
    missing = backend_emitted_codes() - js_contract_codes()
    assert not missing, (
        f"Backend emits codes absent from doc/api_error_codes.js: {sorted(missing)}. "
        "Add them to the JS file and the table in doc/API_ERROR_CODES.md."
    )


def test_no_contract_code_unused_by_backend():
    """Every code in the JS contract must be emitted somewhere in the backend."""
    unused = js_contract_codes() - backend_emitted_codes()
    assert not unused, (
        f"doc/api_error_codes.js lists codes the backend never emits: {sorted(unused)}. "
        "Wire them at a raise site or remove them from the contract."
    )


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failures else 0)
