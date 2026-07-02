"""Tests for the KYC verification-URL freshness guard.

`_hosted_url_matches_config` decides whether a cached Persona verification URL is
still safe to reuse under the current template/environment config. A stale URL
(old template or environment) must be rejected so the status endpoint regenerates
it instead of stranding the user on Persona's "application misconfigured" page.

Runs under pytest *or* standalone:  python tests/test_kyc_url_freshness.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.kyc import _hosted_url_matches_config

TMPL = "itmpl_APMUzRxiZTmnsDVRXkxvBXofxW6L6c"       # current template
ENV = "env_APMUzRxjeKHHXD4j5X5dAfrueaxJhp"          # current environment
OLD_TMPL = "itmpl_nJCXseZraPCGx4exkGnLKigUQ7Gh"     # old account template
OLD_ENV = "env_YGxmjRPetG7WQbChN725wZFqTocN"        # old account environment

HOSTED = "https://inquiry.withpersona.com/verify?inquiry-template-id={t}&reference-id=KYC-x&environment-id={e}"
API = "https://inquiry.withpersona.com/verify?inquiry-id=inq_APMUzRx4JXDpCniSb1LAPpra2zi1Xx"


def test_current_hosted_url_is_reusable():
    url = HOSTED.format(t=TMPL, e=ENV)
    assert _hosted_url_matches_config(url, TMPL, ENV) is True


def test_stale_template_is_rejected():
    # This is the exact bug we hit: old template cached, current config differs.
    url = HOSTED.format(t=OLD_TMPL, e=OLD_ENV)
    assert _hosted_url_matches_config(url, TMPL, ENV) is False


def test_stale_environment_is_rejected():
    # Template matches but environment is the old one -> still stale.
    url = HOSTED.format(t=TMPL, e=OLD_ENV)
    assert _hosted_url_matches_config(url, TMPL, ENV) is False


def test_api_inquiry_url_is_always_reusable():
    # An inquiry-id URL points at a concrete inquiry; template/env don't apply.
    assert _hosted_url_matches_config(API, TMPL, ENV) is True
    # Even if config somehow differs, an inquiry-id URL is still valid to resume.
    assert _hosted_url_matches_config(API, OLD_TMPL, OLD_ENV) is True


def test_empty_or_none_url_is_not_reusable():
    assert _hosted_url_matches_config(None, TMPL, ENV) is False
    assert _hosted_url_matches_config("", TMPL, ENV) is False


def test_no_config_set_does_not_reject():
    # If settings are unset (None), we can't prove staleness -> don't reject.
    url = HOSTED.format(t=OLD_TMPL, e=OLD_ENV)
    assert _hosted_url_matches_config(url, None, None) is True


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
