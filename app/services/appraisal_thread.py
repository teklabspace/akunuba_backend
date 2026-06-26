"""Shared helpers for the appraisal comment/document thread.

Used by both the staff concierge router and the investor-facing assets router
so visibility rules and author-name rendering stay in one place.

Visibility rules (single source of truth):
- Investors see only comments with is_internal == False.
- Investors see only documents with is_client_visible == True.
- Staff (admin/advisor) see everything.

Author-name rendering for the investor-facing view never exposes a staff
member's full internal identity — staff appear org-friendly as
"<first name> (Akunuba)".
"""
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.asset import AppraisalComment, AppraisalDocument, CommentType
from app.integrations.supabase_client import SupabaseClient

STAFF_ROLES = {"admin", "advisor"}
DOCUMENTS_BUCKET = "documents"


def display_author_name(user: Optional[User], role: str, *, for_investor: bool) -> str:
    """Render an author's display name.

    For the investor view, staff are shown org-friendly (first name + Akunuba)
    so internal identities are never leaked to the client.
    """
    first = (user.first_name or "").strip() if user else ""
    last = (user.last_name or "").strip() if user else ""
    if for_investor and role in STAFF_ROLES:
        return f"{first} (Akunuba)".strip() if first else "Akunuba Team"
    full = f"{first} {last}".strip()
    if full:
        return full
    return (user.email if user else None) or "Unknown"


async def author_map(db: AsyncSession, rows) -> Dict[UUID, User]:
    """Fetch the author Users for a set of comments/documents in one query."""
    ids = {r.author_user_id for r in rows} if rows else set()
    # documents use uploaded_by_user_id
    ids |= {getattr(r, "uploaded_by_user_id", None) for r in rows}
    ids.discard(None)
    if not ids:
        return {}
    users = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in users}


def document_url(doc: AppraisalDocument) -> str:
    """Directly-fetchable public Supabase URL (same bucket/pattern as asset docs)."""
    return SupabaseClient.get_file_url(DOCUMENTS_BUCKET, doc.storage_path)


def serialize_comment(c: AppraisalComment, author: Optional[User], *, for_investor: bool) -> dict:
    data = {
        "id": str(c.id),
        "appraisal_id": str(c.appraisal_id),
        "author_role": c.author_role,
        "author_name": display_author_name(author, c.author_role, for_investor=for_investor),
        "body": c.body,
        "comment_type": c.comment_type,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }
    if not for_investor:
        data["is_internal"] = c.is_internal
    return data


def serialize_document(doc: AppraisalDocument, author: Optional[User], *, for_investor: bool) -> dict:
    data = {
        "id": str(doc.id),
        "appraisal_id": str(doc.appraisal_id),
        "file_name": doc.file_name,
        "url": document_url(doc),
        "mime_type": doc.mime_type,
        "file_size": doc.file_size,
        "uploaded_by_role": doc.uploaded_by_role,
        "uploaded_by_name": display_author_name(author, doc.uploaded_by_role, for_investor=for_investor),
        "fulfills_comment_id": str(doc.fulfills_comment_id) if doc.fulfills_comment_id else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }
    if not for_investor:
        data["is_client_visible"] = doc.is_client_visible
    return data


async def create_appraisal_document(
    db: AsyncSession,
    appraisal_id: UUID,
    file,
    *,
    user_id: UUID,
    role: str,
    is_client_visible: bool,
    fulfills_comment_id: Optional[UUID] = None,
) -> Optional[AppraisalDocument]:
    """Validate, upload to Supabase, and persist one appraisal document.

    Returns the created (unflushed) AppraisalDocument, or None if the file was
    rejected (bad extension / too large / upload failure). Caller commits.
    """
    from app.config import settings

    filename = file.filename or "file"
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in settings.ALLOWED_FILE_TYPES:
        return None

    file_data = await file.read()
    file_size = len(file_data)
    if file_size > settings.MAX_UPLOAD_SIZE:
        return None

    storage_path = f"appraisals/{appraisal_id}/{user_id}_{filename}"
    try:
        SupabaseClient.upload_file(
            bucket=DOCUMENTS_BUCKET,
            file_path=storage_path,
            file_data=file_data,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as e:  # noqa: BLE001
        from app.utils.logger import logger
        logger.error("Failed to upload appraisal document: %s", e)
        return None

    doc = AppraisalDocument(
        appraisal_id=appraisal_id,
        uploaded_by_user_id=user_id,
        uploaded_by_role=role,
        file_name=filename,
        mime_type=file.content_type,
        file_size=file_size,
        storage_path=storage_path,
        is_client_visible=is_client_visible,
        fulfills_comment_id=fulfills_comment_id,
    )
    db.add(doc)
    return doc


def build_document_requests(comments: List[AppraisalComment], documents: List[AppraisalDocument]) -> List[dict]:
    """Project document_request comments into request rows with fulfillment state.

    A request is 'fulfilled' once any document links to it via
    fulfills_comment_id; we surface the first such document id.
    """
    by_request: Dict[UUID, AppraisalDocument] = {}
    for d in documents:
        if d.fulfills_comment_id and d.fulfills_comment_id not in by_request:
            by_request[d.fulfills_comment_id] = d

    requests = []
    for c in comments:
        if c.comment_type != CommentType.DOCUMENT_REQUEST.value:
            continue
        doc = by_request.get(c.id)
        requests.append({
            "id": str(c.id),
            "body": c.body,
            "status": "fulfilled" if doc else "open",
            "fulfilled_by_document_id": str(doc.id) if doc else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })
    return requests
