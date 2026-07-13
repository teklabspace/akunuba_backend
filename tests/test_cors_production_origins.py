"""Pin the production CORS allowlist to every first-party frontend host.

Real production bug: the Cloudflare Pages deployments (akunuba-production /
akunuba-preview .pages.dev) were missing from the hardcoded production origins
and the Render CORS_ORIGINS env still held render.yaml's placeholder domains —
so every preflight from pages.dev got 400 and users saw "network error".

Runs under pytest *or* standalone:  python tests/test_cors_production_origins.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAIN_SRC = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

REQUIRED_PRODUCTION_ORIGINS = [
    "https://akunuba.io",
    "https://www.akunuba.io",
    "https://akunuba.vercel.app",
    "https://akunuba-production.pages.dev",
    "https://akunuba-preview.pages.dev",
]


def test_all_first_party_frontends_are_allowed():
    for origin in REQUIRED_PRODUCTION_ORIGINS:
        assert f'"{origin}"' in MAIN_SRC, (
            f"{origin} missing from production_origins in app/main.py - "
            "preflights from that host will 400 and the frontend shows 'network error'"
        )


def test_no_trailing_slashes_in_origins():
    # An origin with a trailing slash never matches the browser's Origin header.
    for origin in REQUIRED_PRODUCTION_ORIGINS:
        assert f'"{origin}/"' not in MAIN_SRC, f"{origin}/ has a trailing slash"


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
