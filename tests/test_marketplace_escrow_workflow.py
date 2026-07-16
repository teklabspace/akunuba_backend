"""Marketplace & escrow workflow: state machines, guards, and money math.

QA requirement: "Marketplace and escrow workflow testing". The trade flow is
listing → offer → accept → escrow(PENDING) → fund(FUNDED) → release(RELEASED)
with refund/dispute branches. This suite pins the status vocabularies, the
guards that keep the flow safe (staff can't buy, owners can't bid on their own
listing, offers only acceptable on open listings, escrow only releasable once
funded), and the commission arithmetic.

Runs under pytest *or* standalone:  python tests/test_marketplace_escrow_workflow.py
"""
import inspect
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.marketplace import EscrowStatus, ListingStatus, OfferStatus
from app.utils.helpers import calculate_commission, calculate_listing_fee


# ------------------------------------------------------- status vocabularies

def test_listing_status_vocabulary_exact():
    # 8 statuses including SUSPENDED (appraisal-driven pull from marketplace).
    expected = {
        "draft", "pending_approval", "approved", "rejected",
        "active", "suspended", "sold", "cancelled",
    }
    assert {s.value for s in ListingStatus} == expected, (
        "ListingStatus vocabulary drifted — frontend filters and the "
        "suspension workflow key off these exact values"
    )


def test_offer_status_vocabulary_exact():
    expected = {"pending", "accepted", "rejected", "countered", "expired", "withdrawn"}
    assert {s.value for s in OfferStatus} == expected


def test_escrow_status_vocabulary_exact():
    expected = {"pending", "funded", "released", "refunded", "disputed"}
    assert {s.value for s in EscrowStatus} == expected


# ------------------------------------------------------------- offer guards

def _create_offer_source():
    from app.api.v1.marketplace import create_offer
    return inspect.getsource(create_offer)


def test_staff_cannot_buy_guard_present():
    # Reported QA bug: staff got a raw error after filling the whole offer
    # form. Backend contract: admins/advisors are refused with a machine-
    # readable 403 STAFF_CANNOT_BUY the frontend can act on up-front.
    src = _create_offer_source()
    assert 'code="STAFF_CANNOT_BUY"' in src, "staff purchase block lost its error code"
    assert "admin" in src and "advisor" in src, "staff role check removed from create_offer"

    from app.core.exceptions import ForbiddenException
    exc = ForbiddenException("staff cannot buy", code="STAFF_CANNOT_BUY")
    assert exc.status_code == 403, "staff block must surface as 403, not 500"


def test_offer_guards_cover_subscription_limit_and_self_purchase():
    src = _create_offer_source()
    assert 'code="SUBSCRIPTION_REQUIRED"' in src, "plan gate removed from offers"
    assert 'code="OFFER_LIMIT_REACHED"' in src, "per-plan offer cap removed"
    assert 'code="OWN_LISTING"' in src, "self-purchase guard removed"


def test_offers_only_on_buyable_listing_statuses():
    src = _create_offer_source()
    assert "ListingStatus.APPROVED" in src and "ListingStatus.ACTIVE" in src, (
        "buyable statuses changed — offers must be limited to APPROVED/ACTIVE "
        "(never draft/pending/suspended/sold listings)"
    )


def test_offer_expiry_is_seven_days():
    src = _create_offer_source()
    assert "timedelta(days=7)" in src, "offer expiry window changed from 7 days"


# ------------------------------------------------------- accept → escrow leg

def _accept_offer_source():
    from app.api.v1.marketplace import accept_offer
    return inspect.getsource(accept_offer)


def test_accept_requires_open_listing():
    # Regression pin: accepting an offer on a suspended/sold listing must 409
    # LISTING_NOT_OPEN (appraisal suspension semantics).
    src = _accept_offer_source()
    assert 'code="LISTING_NOT_OPEN"' in src, "LISTING_NOT_OPEN guard removed from accept"

    from app.core.exceptions import ConflictException
    exc = ConflictException("listing not open", code="LISTING_NOT_OPEN")
    assert exc.status_code == 409


def test_accept_transitions_offer_and_listing_and_creates_escrow():
    src = _accept_offer_source()
    assert "OfferStatus.ACCEPTED" in src, "accepted offer no longer marked ACCEPTED"
    assert "ListingStatus.SOLD" in src, "listing no longer marked SOLD on acceptance"
    assert "EscrowStatus.PENDING" in src, "escrow must start life as PENDING"
    assert "EscrowTransaction(" in src, "accept no longer opens an escrow transaction"
    assert "create_payment_intent" in src, "Stripe payment intent creation removed"


def test_accept_only_for_pending_offers_by_listing_owner():
    src = _accept_offer_source()
    assert "OfferStatus.PENDING" in src, "non-pending offers must not be acceptable"
    assert "listing.account_id != account.id" in src, "owner-only acceptance check removed"


# --------------------------------------------------------------- escrow legs

def test_release_requires_funded_escrow():
    from app.api.v1.marketplace import release_escrow
    src = inspect.getsource(release_escrow)
    assert "EscrowStatus.FUNDED" in src, (
        "release no longer requires FUNDED — funds could be released before payment"
    )
    assert "seller_id" in src, "seller-only release check removed"


def test_escrow_transaction_model_supports_audit_and_stripe():
    from app.models.marketplace import EscrowTransaction
    cols = {c.name for c in EscrowTransaction.__table__.columns}
    for required in (
        "buyer_id", "seller_id", "amount", "commission", "status",
        "stripe_payment_intent_id", "released_at", "resolved_by", "resolution_reason",
    ):
        assert required in cols, f"escrow_transactions.{required} column missing"


# ------------------------------------------------------------ marketplace fees

def test_commission_rates_standard_and_premium():
    assert calculate_commission(Decimal("1000")) == Decimal("200.00"), "standard rate is 20%"
    assert calculate_commission(Decimal("1000"), is_premium=True) == Decimal("100.00"), (
        "premium rate is 10%"
    )


def test_listing_fee_is_two_percent():
    assert calculate_listing_fee(Decimal("50000")) == Decimal("1000.00")


def test_offer_limits_scale_with_plan():
    from app.core.features import check_usage_limit, get_limit
    from app.models.payment import SubscriptionPlan

    assert get_limit(SubscriptionPlan.FREE, "offers") == 3
    assert get_limit(SubscriptionPlan.MONTHLY, "offers") == 20
    assert get_limit(SubscriptionPlan.ANNUAL, "offers") is None  # unlimited

    assert check_usage_limit(SubscriptionPlan.FREE, "offers", 2)
    assert not check_usage_limit(SubscriptionPlan.FREE, "offers", 3)
    assert check_usage_limit(SubscriptionPlan.ANNUAL, "offers", 10_000)


def _run_standalone():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
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
