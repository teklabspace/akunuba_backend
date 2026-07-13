"""Tests for profile-picture (avatar) support.

Pure-helper tests, no DB — run via pytest or `python tests/test_avatar_support.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.upload_helpers import storage_bucket_for_file_type, validate_image_content_type
from app.schemas.user import UserUpdate


def test_avatar_uploads_go_to_public_images_bucket():
    # Avatars must land in the public images bucket so the returned URL is a
    # permanent, publicly loadable <img> src (not a signed/expiring one).
    assert storage_bucket_for_file_type("avatar") == "images"
    assert storage_bucket_for_file_type("photo") == "images"
    assert storage_bucket_for_file_type("document") == "documents"


def test_avatar_content_type_validation_is_image_only():
    assert validate_image_content_type("me.png", None) == "image/png"
    assert validate_image_content_type("me.jpg", None) == "image/jpeg"
    try:
        validate_image_content_type("resume.pdf", None)
        assert False, "PDF must be rejected as an avatar/photo"
    except ValueError:
        pass


def test_user_update_accepts_avatar_url():
    u = UserUpdate(avatar_url="https://cdn.example.com/avatars/x.png")
    assert u.avatar_url == "https://cdn.example.com/avatars/x.png"
    assert "avatar_url" in u.model_fields_set


def test_user_update_null_clears_vs_omitted_leaves_unchanged():
    # Explicit null = "remove the picture": the field IS in model_fields_set.
    cleared = UserUpdate.model_validate({"avatar_url": None})
    assert cleared.avatar_url is None
    assert "avatar_url" in cleared.model_fields_set

    # Omitted = "don't touch": the field is NOT in model_fields_set, which is
    # what PUT /users/me checks before writing.
    untouched = UserUpdate.model_validate({"first_name": "A"})
    assert "avatar_url" not in untouched.model_fields_set


def test_user_update_avatar_url_max_length():
    try:
        UserUpdate(avatar_url="https://x/" + "a" * 500)
        assert False, "avatar_url longer than 500 chars must be rejected"
    except Exception:
        pass


def test_storage_path_from_public_url_accepts_only_our_urls():
    from app.utils.upload_helpers import storage_path_from_public_url

    base = "https://proj.supabase.co"
    ours = f"{base}/storage/v1/object/public/images/avatars/acc-1/me_ab12.png"
    assert storage_path_from_public_url(ours, base) == "avatars/acc-1/me_ab12.png"
    # Trailing slash on the configured URL and query strings are tolerated.
    assert storage_path_from_public_url(ours + "?", base + "/") == "avatars/acc-1/me_ab12.png"

    # Everything else is rejected: foreign hosts, private-bucket URLs,
    # javascript: — this backs the PUT /users/me lockdown.
    assert storage_path_from_public_url("https://evil.example/x.png", base) is None
    assert storage_path_from_public_url(f"{base}/storage/v1/object/sign/images/x.png", base) is None
    assert storage_path_from_public_url("javascript:alert(1)", base) is None
    assert storage_path_from_public_url(None, base) is None
    # Wrong bucket = not an avatar-eligible URL.
    assert storage_path_from_public_url(
        f"{base}/storage/v1/object/public/documents/x.pdf", base
    ) is None


def test_referral_response_carries_avatar_url():
    from app.api.v1.referrals import ReferralResponse

    assert "avatar_url" in ReferralResponse.model_fields


def test_user_facing_payload_schemas_carry_avatar_fields():
    from app.schemas.user import UserResponse
    from app.api.v1.chat_conversations import ParticipantInfo, MessageResponse
    from app.api.v1.support import TicketReplyResponse

    assert "avatar_url" in UserResponse.model_fields
    assert "userAvatar" in ParticipantInfo.model_fields
    assert "senderAvatar" in MessageResponse.model_fields
    assert "avatar_url" in TicketReplyResponse.model_fields
    assert "user_name" in TicketReplyResponse.model_fields


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[OK] {name}")
    print("All avatar tests passed.")
