"""Tests for PUT /assets/{id} edit semantics (partial update, review re-queue, lock).

Pure-helper tests, no DB — run via pytest or `python tests/test_asset_edit_semantics.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.asset import AIReviewStatus
from app.api.v1.assets import review_status_after_investor_edit
from app.schemas.asset import AssetUpdate


def test_rejected_asset_requeues_on_edit():
    # The whole point of editing a rejected asset is fix-and-resubmit.
    assert review_status_after_investor_edit(AIReviewStatus.REJECTED) == AIReviewStatus.NOT_REVIEWED
    assert review_status_after_investor_edit(AIReviewStatus.NEEDS_REVIEW) == AIReviewStatus.NOT_REVIEWED


def test_pending_and_unset_are_noops():
    assert review_status_after_investor_edit(AIReviewStatus.NOT_REVIEWED) == AIReviewStatus.NOT_REVIEWED
    assert review_status_after_investor_edit(None) is None
    # APPROVED can't reach the helper (the ASSET_LOCKED guard rejects the PUT
    # first), but the helper must never silently un-approve.
    assert review_status_after_investor_edit(AIReviewStatus.APPROVED) == AIReviewStatus.APPROVED


def test_asset_update_is_fully_partial():
    # Every field optional: an empty payload is valid and touches nothing.
    empty = AssetUpdate()
    assert empty.model_dump(exclude_unset=True) == {}

    # Omitted fields stay unset — the endpoint's `is not None` guards then
    # leave the stored values untouched (incl. photos/documents, which the
    # endpoint ignores entirely even when sent).
    partial = AssetUpdate(name="New name")
    assert partial.model_dump(exclude_unset=True) == {"name": "New name"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[OK] {name}")
    print("All asset-edit tests passed.")
