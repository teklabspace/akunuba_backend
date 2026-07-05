"""Tests that rejected appraisal uploads fail loudly instead of silently.

`create_appraisal_document` used to return None for a bad extension, an
oversized file, or a storage failure — the endpoints then answered HTTP 200
with {"data": [], "count": 0}, which frontends read as a successful upload.
It must now raise DocumentRejected carrying the file name and reason.

Runs under pytest *or* standalone:  python tests/test_appraisal_document_rejection.py
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import appraisal_thread
from app.services.appraisal_thread import DocumentRejected, create_appraisal_document


class FakeUpload:
    def __init__(self, filename, data=b"x", content_type="application/pdf"):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def _create(file, *, db=None):
    return asyncio.run(create_appraisal_document(
        db if db is not None else FakeSession(),
        uuid4(), file,
        user_id=uuid4(),
        role="admin",
        is_client_visible=True,
    ))


def _expect_rejected(file, reason_fragment, db=None):
    try:
        _create(file, db=db)
    except DocumentRejected as e:
        assert reason_fragment in e.reason.lower(), f"reason {e.reason!r} lacks {reason_fragment!r}"
        assert e.file_name == (file.filename or "file")
        return
    raise AssertionError("DocumentRejected was not raised")


def test_bad_extension_raises():
    _expect_rejected(FakeUpload("report.xlsx"), "type")


def test_missing_extension_raises():
    # A raw Blob upload arrives with filename "blob" (no extension).
    _expect_rejected(FakeUpload("blob"), "type")


def test_oversized_file_raises(monkeypatch=None):
    from app.config import settings
    big = b"0" * (settings.MAX_UPLOAD_SIZE + 1)
    _expect_rejected(FakeUpload("report.pdf", data=big), "large")


def test_storage_failure_raises():
    original = appraisal_thread.SupabaseClient.upload_file

    def boom(**kwargs):
        raise RuntimeError("bucket unavailable")

    appraisal_thread.SupabaseClient.upload_file = staticmethod(boom)
    try:
        _expect_rejected(FakeUpload("report.pdf"), "storage")
    finally:
        appraisal_thread.SupabaseClient.upload_file = original


def test_accepted_file_still_persists():
    original_upload = appraisal_thread.SupabaseClient.upload_file
    original_url = appraisal_thread.SupabaseClient.get_file_url
    appraisal_thread.SupabaseClient.upload_file = staticmethod(lambda **kwargs: "ok")
    appraisal_thread.SupabaseClient.get_file_url = staticmethod(lambda bucket, path: f"https://x/{path}")
    try:
        db = FakeSession()
        doc = _create(FakeUpload("report.pdf"), db=db)
        assert doc is not None
        assert doc.file_name == "report.pdf"
        # client-visible + asset_id was not passed, so only the appraisal doc row
        assert doc in db.added
    finally:
        appraisal_thread.SupabaseClient.upload_file = original_upload
        appraisal_thread.SupabaseClient.get_file_url = original_url


def test_author_map_handles_document_rows():
    # GET .../documents used to 500: author_map read r.author_user_id directly,
    # but AppraisalDocument rows only carry uploaded_by_user_id.
    from app.models.asset import AppraisalDocument
    from app.services.appraisal_thread import author_map

    doc = AppraisalDocument(
        appraisal_id=uuid4(),
        uploaded_by_user_id=uuid4(),
        uploaded_by_role="admin",
        file_name="report.pdf",
        storage_path="appraisals/x/report.pdf",
        is_client_visible=True,
    )

    class NoQuerySession:
        async def execute(self, stmt):
            class R:
                def scalars(self):
                    return self

                def all(self):
                    return []
            return R()

    result = asyncio.run(author_map(NoQuerySession(), [doc]))
    assert result == {}


def _run_standalone():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
