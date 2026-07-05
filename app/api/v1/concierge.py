from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import (
    Asset, AssetAppraisal, AppraisalStatus, AppraisalType,
    AppraisalComment, AppraisalDocument, CommentType,
)
from app.models.document import Document, DocumentType
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Permission, has_permission
from app.utils.logger import logger
from app.services import appraisal_thread
from app.integrations.supabase_client import SupabaseClient
from app.config import settings
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class AppraisalStatusUpdate(BaseModel):
    status: AppraisalStatus
    notes: Optional[str] = None


class AppraisalAssignRequest(BaseModel):
    user_id: UUID
    user_name: Optional[str] = None
    provider: Optional[str] = None
    internal_note: Optional[str] = None


class AppraisalCommentCreate(BaseModel):
    comment: str
    from_field: Optional[str] = None  # "from" is a Python keyword, using from_field


class StaffCommentCreate(BaseModel):
    body: str
    comment_type: CommentType = CommentType.MESSAGE
    is_internal: bool = False


class DocumentRequestCreate(BaseModel):
    description: str


class AppraisalCommentResponse(BaseModel):
    id: UUID
    comment: str
    from_field: Optional[str] = None
    user_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class AppraisalValuationUpdate(BaseModel):
    appraised_value: Decimal
    valuation_date: str  # YYYY-MM-DD
    currency: str = "USD"


class AppraisalResponse(BaseModel):
    id: UUID
    asset_id: UUID
    asset_name: Optional[str] = None
    appraisal_type: str
    status: str
    estimated_value: Optional[Decimal] = None
    requested_at: datetime
    completed_at: Optional[datetime] = None
    estimated_completion_date: Optional[datetime] = None
    notes: Optional[str] = None
    assigned_to: Optional[UUID] = None
    provider: Optional[str] = None

    class Config:
        from_attributes = True


def _asset_images(asset) -> tuple:
    """Return (primary_image_url, [all_image_urls]) for an asset's photos.

    Resolves relative paths to public Supabase URLs in the images bucket.
    Requires asset.photos to be eager-loaded.
    """
    if asset is None or not getattr(asset, "photos", None):
        return None, []
    urls = []
    primary = None
    for photo in asset.photos:
        url = photo.url
        if url and not url.startswith(("http://", "https://")) and photo.supabase_storage_path:
            try:
                url = SupabaseClient.get_file_url("images", photo.supabase_storage_path)
            except Exception:  # noqa: BLE001
                continue
        if not url:
            continue
        urls.append(url)
        if photo.is_primary or primary is None:
            primary = url
    return primary, urls


async def _appraisals_with_open_document_requests(db: AsyncSession, appraisal_ids: list) -> set:
    """Return the set of appraisal ids that have at least one unfulfilled
    document_request comment (used for the documents_requested flag)."""
    if not appraisal_ids:
        return set()

    req_rows = (await db.execute(
        select(AppraisalComment.id, AppraisalComment.appraisal_id).where(and_(
            AppraisalComment.appraisal_id.in_(appraisal_ids),
            AppraisalComment.comment_type == CommentType.DOCUMENT_REQUEST.value,
        ))
    )).all()
    if not req_rows:
        return set()

    req_ids = [r.id for r in req_rows]
    fulfilled = set((await db.execute(
        select(AppraisalDocument.fulfills_comment_id).where(
            AppraisalDocument.fulfills_comment_id.in_(req_ids)
        )
    )).scalars().all())

    return {r.appraisal_id for r in req_rows if r.id not in fulfilled}


@router.get("/appraisals", response_model=Dict[str, Any])
async def list_appraisals(
    status_filter: Optional[AppraisalStatus] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a list of appraisal requests.

    Staff (admins/advisors) see every request; an investor sees only the
    requests on assets they own.
    """
    is_staff = has_permission(current_user.role, Permission.MANAGE_SUPPORT)

    # An investor is scoped to their own account; no account => no requests.
    owner_account_id = None
    if not is_staff:
        account = (await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )).scalar_one_or_none()
        if not account:
            return {
                "data": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "pages": 0},
            }
        owner_account_id = account.id

    # Concierge queue is human appraisals only; API (instant AI) appraisals
    # complete immediately and must never appear here.
    query = select(AssetAppraisal).options(
        selectinload(AssetAppraisal.asset).options(
            selectinload(Asset.photos),
            selectinload(Asset.category),
        )
    ).where(AssetAppraisal.appraisal_type != AppraisalType.API)
    count_query = select(func.count(AssetAppraisal.id)).where(
        AssetAppraisal.appraisal_type != AppraisalType.API
    )

    # A single Asset join covers both investor scoping and category filtering.
    if owner_account_id is not None or category:
        query = query.join(Asset, Asset.id == AssetAppraisal.asset_id)
        count_query = count_query.join(Asset, Asset.id == AssetAppraisal.asset_id)
    if owner_account_id is not None:
        query = query.where(Asset.account_id == owner_account_id)
        count_query = count_query.where(Asset.account_id == owner_account_id)
    if category:
        query = query.where(Asset.category_group == category)
        count_query = count_query.where(Asset.category_group == category)

    if status_filter:
        query = query.where(AssetAppraisal.status == status_filter)
        count_query = count_query.where(AssetAppraisal.status == status_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    offset = (page - 1) * limit
    query = query.order_by(desc(AssetAppraisal.requested_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    appraisals = result.scalars().all()

    # Bulk-compute which appraisals have an OPEN document request (point 4).
    documents_requested_ids = await _appraisals_with_open_document_requests(
        db, [a.id for a in appraisals]
    )

    # Build response
    appraisal_list = []
    for appraisal in appraisals:
        asset = appraisal.asset
        asset_name = asset.name if asset else None
        asset_code = asset.asset_code if asset else None
        category = asset.category.name if asset and asset.category else None
        category_group = (
            asset.category_group.value if asset and asset.category_group else None
        )
        primary_image, images = _asset_images(asset)

        appraisal_data = {
            "id": appraisal.id,
            "asset_id": appraisal.asset_id,
            "asset_code": asset_code,
            "asset_name": asset_name,
            "asset_image": primary_image,   # single URL for the card
            "image": primary_image,         # alias
            "images": images,               # all image URLs
            "category": category,
            "category_group": category_group,
            "appraisal_type": appraisal.appraisal_type.value if appraisal.appraisal_type else None,
            "status": appraisal.status.value if appraisal.status else None,
            "estimated_value": float(appraisal.estimated_value) if appraisal.estimated_value else None,
            "requested_at": appraisal.requested_at.isoformat() if appraisal.requested_at else None,
            "completed_at": appraisal.completed_at.isoformat() if appraisal.completed_at else None,
            "estimated_completion_date": appraisal.estimated_completion_date.isoformat() if appraisal.estimated_completion_date else None,
            "notes": appraisal.notes,
            "documents_requested": appraisal.id in documents_requested_ids,
        }
        appraisal_list.append(appraisal_data)

    return {
        "data": appraisal_list,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit if total > 0 else 0
        }
    }


@router.get("/appraisals/{appraisal_id}", response_model=Dict[str, AppraisalResponse])
async def get_appraisal_details(
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific appraisal"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).options(
            selectinload(AssetAppraisal.asset)
        ).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    asset_name = None
    if appraisal.asset:
        asset_name = appraisal.asset.name
    
    return {
        "data": {
            "id": appraisal.id,
            "asset_id": appraisal.asset_id,
            "asset_name": asset_name,
            "appraisal_type": appraisal.appraisal_type.value if appraisal.appraisal_type else None,
            "status": appraisal.status.value if appraisal.status else None,
            "estimated_value": float(appraisal.estimated_value) if appraisal.estimated_value else None,
            "requested_at": appraisal.requested_at.isoformat() if appraisal.requested_at else None,
            "completed_at": appraisal.completed_at.isoformat() if appraisal.completed_at else None,
            "estimated_completion_date": appraisal.estimated_completion_date.isoformat() if appraisal.estimated_completion_date else None,
            "notes": appraisal.notes,
        }
    }


@router.patch("/appraisals/{appraisal_id}/status", response_model=Dict[str, AppraisalResponse])
async def update_appraisal_status(
    appraisal_id: UUID,
    status_data: AppraisalStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update the status of an appraisal request"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    # Update status
    appraisal.status = status_data.status
    
    # Update notes if provided
    if status_data.notes:
        existing_notes = appraisal.notes or ""
        appraisal.notes = f"{existing_notes}\n[{datetime.now(timezone.utc).isoformat()}] {status_data.notes}".strip()
    
    # Set completed_at if status is COMPLETED
    if status_data.status == AppraisalStatus.COMPLETED:
        appraisal.completed_at = datetime.now(timezone.utc)
    
    await db.commit()
    await db.refresh(appraisal)
    
    logger.info(f"Appraisal status updated: {appraisal_id} -> {status_data.status.value}")
    
    return {
        "data": {
            "id": appraisal.id,
            "asset_id": appraisal.asset_id,
            "appraisal_type": appraisal.appraisal_type.value if appraisal.appraisal_type else None,
            "status": appraisal.status.value if appraisal.status else None,
            "estimated_value": float(appraisal.estimated_value) if appraisal.estimated_value else None,
            "requested_at": appraisal.requested_at.isoformat() if appraisal.requested_at else None,
            "completed_at": appraisal.completed_at.isoformat() if appraisal.completed_at else None,
            "notes": appraisal.notes,
        }
    }


@router.post("/appraisals/{appraisal_id}/assign", response_model=Dict[str, Any])
async def assign_appraisal(
    appraisal_id: UUID,
    assign_data: AppraisalAssignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Assign an appraisal to a CRM user or provider"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    # Verify user exists
    user_result = await db.execute(
        select(User).where(User.id == assign_data.user_id)
    )
    user = user_result.scalar_one_or_none()
    
    if not user:
        raise NotFoundException("User", str(assign_data.user_id))
    
    # Note: AssetAppraisal model doesn't have assigned_to field yet
    # For now, we'll store assignment info in notes
    assignment_note = f"[ASSIGNED] User: {assign_data.user_name or user.email}"
    if assign_data.provider:
        assignment_note += f", Provider: {assign_data.provider}"
    if assign_data.internal_note:
        assignment_note += f"\nNote: {assign_data.internal_note}"
    
    existing_notes = appraisal.notes or ""
    appraisal.notes = f"{existing_notes}\n[{datetime.now(timezone.utc).isoformat()}] {assignment_note}".strip()
    
    await db.commit()
    await db.refresh(appraisal)
    
    logger.info(f"Appraisal assigned: {appraisal_id} -> {assign_data.user_id}")
    
    return {
        "message": "Appraisal assigned successfully",
        "appraisal_id": str(appraisal_id),
        "assigned_to": str(assign_data.user_id),
        "user_name": assign_data.user_name or user.email
    }


@router.post("/appraisals/{appraisal_id}/documents", response_model=Dict[str, Any])
async def upload_appraisal_documents(
    appraisal_id: UUID,
    files: List[UploadFile] = File(...),
    is_client_visible: bool = Query(True, description="Staff only: if false, the document is staff-internal and hidden from the investor"),
    fulfills_comment_id: Optional[UUID] = Query(None, description="Optional document_request comment id this upload fulfills"),
    document_type: Optional[str] = Query(None, description="Optional category, e.g. 'valuation' (staff only). A staff 'valuation' doc + a saved amount auto-publishes the asset to the marketplace."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload one or more documents to an appraisal.

    Staff may set is_client_visible=false to keep a document staff-internal.
    The owning investor may also upload (always client-visible). Client-visible
    uploads are mirrored onto the asset's document list.
    """
    appraisal, is_staff, is_owner = await _appraisal_with_access(db, appraisal_id, current_user)

    # Investors can never upload staff-internal documents.
    effective_visible = is_client_visible if is_staff else True

    # Only staff may tag a document as the "valuation" doc (it's a trigger for
    # auto-publishing the asset to the marketplace). Aliases like "Valuation
    # Report" are collapsed to the canonical tag first.
    from app.services.asset_listing_service import normalize_document_type
    effective_doc_type = normalize_document_type(document_type)
    if effective_doc_type == "valuation" and not is_staff:
        effective_doc_type = None

    # If fulfilling a request, validate it's a document_request on this appraisal.
    if fulfills_comment_id is not None:
        req = (await db.execute(
            select(AppraisalComment).where(and_(
                AppraisalComment.id == fulfills_comment_id,
                AppraisalComment.appraisal_id == appraisal_id,
                AppraisalComment.comment_type == CommentType.DOCUMENT_REQUEST.value,
            ))
        )).scalar_one_or_none()
        if not req:
            raise BadRequestException("fulfills_comment_id is not a document request on this appraisal")

    created = []
    rejected = []
    for file in files:
        try:
            doc = await appraisal_thread.create_appraisal_document(
                db, appraisal_id, file,
                user_id=current_user.id,
                role=current_user.role.value,
                is_client_visible=effective_visible,
                fulfills_comment_id=fulfills_comment_id,
                asset_id=appraisal.asset_id,
                document_type=effective_doc_type,
            )
            created.append(doc)
        except appraisal_thread.DocumentRejected as e:
            rejected.append({"file_name": e.file_name, "reason": e.reason})

    if not created and rejected:
        raise BadRequestException(
            "No documents were saved: "
            + "; ".join(f"{r['file_name']} ({r['reason']})" for r in rejected)
        )

    await db.commit()
    for doc in created:
        await db.refresh(doc)

    logger.info(f"User {current_user.id} uploaded {len(created)} document(s) to appraisal {appraisal_id}")

    # If staff just attached the valuation document, and the amount is already
    # set, this auto-publishes the asset to the marketplace (idempotent).
    if is_staff and effective_doc_type == "valuation":
        from app.services.asset_listing_service import maybe_publish_valued_asset
        await maybe_publish_valued_asset(db, appraisal, current_user)
    return {
        "data": [appraisal_thread.serialize_document(d, current_user, for_investor=not is_staff) for d in created],
        "count": len(created),
        "rejected": rejected,
    }


@router.get("/appraisals/{appraisal_id}/documents", response_model=Dict[str, Any])
async def get_appraisal_documents(
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Staff: list all documents on an appraisal (including staff-internal)."""
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")

    appraisal = (await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )).scalar_one_or_none()
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))

    documents = (await db.execute(
        select(AppraisalDocument)
        .where(AppraisalDocument.appraisal_id == appraisal_id)
        .order_by(desc(AppraisalDocument.created_at))
    )).scalars().all()

    authors = await appraisal_thread.author_map(db, documents)
    return {
        "data": [
            appraisal_thread.serialize_document(d, authors.get(d.uploaded_by_user_id), for_investor=False)
            for d in documents
        ],
        "count": len(documents),
    }


async def _load_appraisal_or_404(db: AsyncSession, appraisal_id: UUID) -> AssetAppraisal:
    appraisal = (await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )).scalar_one_or_none()
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    return appraisal


async def _appraisal_with_access(db: AsyncSession, appraisal_id: UUID, current_user: User):
    """Load an appraisal and authorize the caller.

    Staff (MANAGE_SUPPORT) get full access; otherwise the caller must own the
    asset the appraisal belongs to. Returns (appraisal, is_staff, is_owner).
    """
    appraisal = (await db.execute(
        select(AssetAppraisal)
        .options(selectinload(AssetAppraisal.asset))
        .where(AssetAppraisal.id == appraisal_id)
    )).scalar_one_or_none()
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))

    is_staff = has_permission(current_user.role, Permission.MANAGE_SUPPORT)
    is_owner = False
    if not is_staff and appraisal.asset is not None:
        owner = (await db.execute(
            select(Account.id).where(and_(
                Account.id == appraisal.asset.account_id,
                Account.user_id == current_user.id,
            ))
        )).scalar_one_or_none()
        is_owner = owner is not None

    if not is_staff and not is_owner:
        raise HTTPException(status_code=403, detail="Access denied")
    return appraisal, is_staff, is_owner


@router.post("/appraisals/{appraisal_id}/comments", response_model=Dict[str, Any])
async def add_appraisal_comment(
    appraisal_id: UUID,
    comment_data: StaffCommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Post a comment on an appraisal.

    Staff may set is_internal=true (staff-only) and comment_type 'message'/'system'.
    The owning investor may also reply; their comment is always a client-visible
    message. Use the dedicated /document-requests endpoint for document requests.
    """
    appraisal, is_staff, is_owner = await _appraisal_with_access(db, appraisal_id, current_user)

    if is_staff:
        comment_type = comment_data.comment_type.value
        is_internal = comment_data.is_internal
    else:
        # Investors can only post visible messages, never internal/system notes.
        comment_type = CommentType.MESSAGE.value
        is_internal = False

    comment = AppraisalComment(
        appraisal_id=appraisal_id,
        author_user_id=current_user.id,
        author_role=current_user.role.value,
        body=comment_data.body,
        comment_type=comment_type,
        is_internal=is_internal,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    if appraisal.asset is not None:
        from app.services.appraisal_notifications import dispatch_appraisal_message
        await dispatch_appraisal_message(db, appraisal, appraisal.asset, comment, current_user)

    logger.info(f"Comment added to appraisal {appraisal_id} by {current_user.id} (staff={is_staff}, internal={is_internal})")
    return {"data": appraisal_thread.serialize_comment(comment, current_user, for_investor=not is_staff)}


@router.post("/appraisals/{appraisal_id}/document-requests", response_model=Dict[str, Any])
async def request_appraisal_document(
    appraisal_id: UUID,
    request_data: DocumentRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Staff: ask the asset owner to upload a document.

    Stored as a client-visible comment of type document_request; the investor
    fulfils it by uploading a document that links back via fulfills_comment_id.
    """
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    appraisal = (await db.execute(
        select(AssetAppraisal)
        .options(selectinload(AssetAppraisal.asset))
        .where(AssetAppraisal.id == appraisal_id)
    )).scalar_one_or_none()
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))

    comment = AppraisalComment(
        appraisal_id=appraisal_id,
        author_user_id=current_user.id,
        author_role=current_user.role.value,
        body=request_data.description,
        comment_type=CommentType.DOCUMENT_REQUEST.value,
        is_internal=False,  # a document request must be visible to the client
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    if appraisal.asset is not None:
        from app.services.appraisal_notifications import dispatch_appraisal_message
        await dispatch_appraisal_message(db, appraisal, appraisal.asset, comment, current_user)

    logger.info(f"Document requested on appraisal {appraisal_id}")
    return {
        "data": {
            "id": str(comment.id),
            "body": comment.body,
            "status": "open",
            "fulfilled_by_document_id": None,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
        }
    }


@router.get("/appraisals/{appraisal_id}/comments", response_model=Dict[str, Any])
async def get_appraisal_comments(
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List comments on an appraisal.

    Staff see everything (including staff-internal). The owning investor sees
    only client-visible comments. Each item carries `author_kind`
    (investor | staff | system) and a matching `from` label for chat alignment.

    Legacy free-text from asset_appraisals.notes is returned separately under
    `legacy_notes` so historical appraisals can still be shown read-only.
    """
    appraisal, is_staff, is_owner = await _appraisal_with_access(db, appraisal_id, current_user)

    comment_query = select(AppraisalComment).where(AppraisalComment.appraisal_id == appraisal_id)
    if not is_staff:
        # Investors never see staff-internal comments.
        comment_query = comment_query.where(AppraisalComment.is_internal.is_(False))
    comment_query = comment_query.order_by(AppraisalComment.created_at)

    comments = (await db.execute(comment_query)).scalars().all()

    authors = await appraisal_thread.author_map(db, comments)
    return {
        "data": [
            appraisal_thread.serialize_comment(c, authors.get(c.author_user_id), for_investor=not is_staff)
            for c in comments
        ],
        "count": len(comments),
        # Legacy notes are staff-internal context; hide from investors.
        "legacy_notes": appraisal.notes if is_staff else None,
    }


@router.get("/appraisals/{appraisal_id}/document-requests", response_model=Dict[str, Any])
async def list_appraisal_document_requests(
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Staff: list document requests on an appraisal with fulfillment state."""
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    await _load_appraisal_or_404(db, appraisal_id)

    comments = (await db.execute(
        select(AppraisalComment)
        .where(AppraisalComment.appraisal_id == appraisal_id)
        .order_by(AppraisalComment.created_at)
    )).scalars().all()
    documents = (await db.execute(
        select(AppraisalDocument).where(AppraisalDocument.appraisal_id == appraisal_id)
    )).scalars().all()

    requests = appraisal_thread.build_document_requests(comments, documents)
    return {"data": requests, "count": len(requests)}


@router.put("/appraisals/{appraisal_id}/valuation", response_model=Dict[str, AppraisalResponse])
async def update_appraisal_valuation(
    appraisal_id: UUID,
    valuation_data: AppraisalValuationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update the appraised value and valuation date"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).options(
            selectinload(AssetAppraisal.asset)
        ).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    # Parse valuation date
    try:
        valuation_date = datetime.fromisoformat(valuation_data.valuation_date.replace('Z', '+00:00'))
    except:
        valuation_date = datetime.now(timezone.utc)
    
    # Update appraisal
    appraisal.estimated_value = valuation_data.appraised_value
    appraisal.completed_at = valuation_date
    
    # Update asset's current value and last appraisal date
    if appraisal.asset:
        appraisal.asset.current_value = valuation_data.appraised_value
        appraisal.asset.last_appraisal_date = valuation_date
        appraisal.asset.currency = valuation_data.currency
    
    # Create valuation record
    from app.models.asset import AssetValuation
    valuation = AssetValuation(
        asset_id=appraisal.asset_id,
        value=valuation_data.appraised_value,
        currency=valuation_data.currency,
        valuation_method="appraisal",
        valuation_date=valuation_date,
        notes=f"From appraisal {appraisal_id}"
    )
    db.add(valuation)
    
    # Mark appraisal as completed
    appraisal.status = AppraisalStatus.COMPLETED

    await db.commit()
    await db.refresh(appraisal)

    logger.info(f"Appraisal valuation updated: {appraisal_id}")

    # Amount is now saved; if a valuation document is already attached this
    # auto-publishes the asset to the marketplace (idempotent, never raises).
    from app.services.asset_listing_service import maybe_publish_valued_asset
    await maybe_publish_valued_asset(db, appraisal, current_user)
    
    asset_name = None
    if appraisal.asset:
        asset_name = appraisal.asset.name
    
    return {
        "data": {
            "id": appraisal.id,
            "asset_id": appraisal.asset_id,
            "asset_name": asset_name,
            "appraisal_type": appraisal.appraisal_type.value if appraisal.appraisal_type else None,
            "status": appraisal.status.value if appraisal.status else None,
            "estimated_value": float(appraisal.estimated_value) if appraisal.estimated_value else None,
            "requested_at": appraisal.requested_at.isoformat() if appraisal.requested_at else None,
            "completed_at": appraisal.completed_at.isoformat() if appraisal.completed_at else None,
            "notes": appraisal.notes,
        }
    }


@router.get("/appraisals/{appraisal_id}/report")
async def download_valuation_report(
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Download the valuation report for a completed appraisal"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    if appraisal.status != AppraisalStatus.COMPLETED:
        raise BadRequestException("Appraisal is not completed yet")
    
    # Check if report_url exists
    if not appraisal.report_url:
        raise NotFoundException("Report", "No report available for this appraisal")
    
    # For now, return the report URL
    # In a full implementation, you'd generate and return the PDF
    return {
        "report_url": appraisal.report_url,
        "message": "Report URL retrieved. Full PDF generation not yet implemented."
    }


@router.get("/statistics", response_model=Dict[str, Any])
async def get_appraisal_statistics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for concierge (human) appraisals.

    Staff see totals across all requests; an investor sees only their own.
    Excludes API (instant AI) appraisals to match the concierge queue.
    """
    is_staff = has_permission(current_user.role, Permission.MANAGE_SUPPORT)

    # Base scope: human appraisals only (exclude instant AI).
    base_filters = [AssetAppraisal.appraisal_type != AppraisalType.API]

    if not is_staff:
        account = (await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )).scalar_one_or_none()
        if not account:
            empty = {
                "total_requests": 0, "totalRequests": 0,
                "pending": 0,
                "in_progress": 0, "inProgress": 0,
                "completed": 0,
                "awaiting_info": 0, "awaitingInfo": 0,
                "by_status": {},
            }
            return empty
        base_filters.append(Asset.account_id == account.id)

    # By status (single grouped query); join Asset only when investor-scoped.
    status_query = select(
        AssetAppraisal.status,
        func.count(AssetAppraisal.id).label("count"),
    )
    if not is_staff:
        status_query = status_query.join(Asset, Asset.id == AssetAppraisal.asset_id)
    status_query = status_query.where(and_(*base_filters)).group_by(AssetAppraisal.status)

    by_status = {
        row.status.value: row.count
        for row in (await db.execute(status_query)).all()
    }

    total_requests = sum(by_status.values())
    in_progress = by_status.get(AppraisalStatus.IN_PROGRESS.value, 0)
    completed = by_status.get(AppraisalStatus.COMPLETED.value, 0)
    pending = by_status.get(AppraisalStatus.PENDING.value, 0)
    # "Awaiting Info" maps to the NEEDS_MORE_INFORMATION status.
    awaiting_info = by_status.get(AppraisalStatus.NEEDS_MORE_INFORMATION.value, 0)

    return {
        # snake_case (existing) + camelCase (frontend) keys, both populated.
        "total_requests": total_requests,
        "totalRequests": total_requests,
        "pending": pending,
        "in_progress": in_progress,
        "inProgress": in_progress,
        "completed": completed,
        "awaiting_info": awaiting_info,
        "awaitingInfo": awaiting_info,
        "by_status": by_status,
    }
