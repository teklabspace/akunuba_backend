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
from app.models.asset import Asset, AssetAppraisal, AppraisalStatus, AppraisalType
from app.models.document import Document, DocumentType
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Permission, has_permission
from app.utils.logger import logger
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


@router.get("/appraisals", response_model=Dict[str, Any])
async def list_appraisals(
    status_filter: Optional[AppraisalStatus] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a list of all appraisal requests"""
    # Check permissions - only admins and advisors can see all appraisals
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    query = select(AssetAppraisal).options(
        selectinload(AssetAppraisal.asset)
    )
    
    if status_filter:
        query = query.where(AssetAppraisal.status == status_filter)
    
    # Filter by category if provided (via asset category)
    if category:
        query = query.join(Asset).where(Asset.category_group == category)
    
    # Get total count
    count_query = select(func.count(AssetAppraisal.id))
    if status_filter:
        count_query = count_query.where(AssetAppraisal.status == status_filter)
    if category:
        count_query = count_query.join(Asset).where(Asset.category_group == category)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    offset = (page - 1) * limit
    query = query.order_by(desc(AssetAppraisal.requested_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    appraisals = result.scalars().all()
    
    # Build response
    appraisal_list = []
    for appraisal in appraisals:
        asset_name = None
        if appraisal.asset:
            asset_name = appraisal.asset.name
        
        appraisal_data = {
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload documents related to an appraisal request"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    # Get account
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    uploaded_documents = []
    from app.integrations.supabase_client import SupabaseClient
    from app.config import settings
    
    for file in files:
        # Validate file type
        file_extension = file.filename.split(".")[-1].lower() if "." in file.filename else ""
        if file_extension not in settings.ALLOWED_FILE_TYPES:
            continue  # Skip invalid files
        
        # Read file
        file_data = await file.read()
        file_size = len(file_data)
        
        # Check file size
        if file_size > settings.MAX_UPLOAD_SIZE:
            continue  # Skip oversized files
        
        # Upload to Supabase Storage
        try:
            file_path = f"appraisals/{appraisal_id}/{file.filename}"
            SupabaseClient.upload_file(
                bucket="documents",
                file_path=file_path,
                file_data=file_data,
                content_type=file.content_type or "application/octet-stream"
            )
        except Exception as e:
            logger.error(f"Failed to upload document: {e}")
            continue
        
        # Create document record linked to appraisal
        document = Document(
            account_id=account.id,
            document_type=DocumentType.OTHER,
            file_name=file.filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=file.content_type,
            supabase_storage_path=file_path,
            description=f"Appraisal document for appraisal {appraisal_id}",
            meta_data=f'{{"appraisal_id": "{appraisal_id}"}}'
        )
        
        db.add(document)
        uploaded_documents.append({
            "id": str(document.id),
            "file_name": file.filename,
            "file_size": file_size
        })
    
    await db.commit()
    
    logger.info(f"Documents uploaded for appraisal {appraisal_id}: {len(uploaded_documents)} files")
    
    return {
        "message": f"Uploaded {len(uploaded_documents)} document(s)",
        "documents": uploaded_documents
    }


@router.get("/appraisals/{appraisal_id}/documents", response_model=Dict[str, Any])
async def get_appraisal_documents(
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all documents associated with an appraisal"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    # Find documents linked to this appraisal via metadata
    documents_result = await db.execute(
        select(Document).where(
            Document.meta_data.contains(f'"appraisal_id": "{appraisal_id}"')
        )
    )
    documents = documents_result.scalars().all()
    
    document_list = []
    for doc in documents:
        document_list.append({
            "id": str(doc.id),
            "file_name": doc.file_name,
            "file_size": doc.file_size,
            "mime_type": doc.mime_type,
            "created_at": doc.created_at.isoformat() if doc.created_at else None
        })
    
    return {
        "data": document_list,
        "count": len(document_list)
    }


# Note: Comments system for appraisals would require a new model
# For now, we'll use the notes field in AssetAppraisal
@router.post("/appraisals/{appraisal_id}/comments", response_model=Dict[str, Any])
async def add_appraisal_comment(
    appraisal_id: UUID,
    comment_data: AppraisalCommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a comment or note to an appraisal"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    # Add comment to notes
    from_field = comment_data.from_field or current_user.email
    comment_text = f"[{from_field}] {comment_data.comment}"
    existing_notes = appraisal.notes or ""
    appraisal.notes = f"{existing_notes}\n[{datetime.now(timezone.utc).isoformat()}] {comment_text}".strip()
    
    await db.commit()
    await db.refresh(appraisal)
    
    logger.info(f"Comment added to appraisal {appraisal_id}")
    
    return {
        "message": "Comment added successfully",
        "comment": comment_data.comment,
        "from": from_field,
        "created_at": datetime.now(timezone.utc).isoformat()
    }


@router.get("/appraisals/{appraisal_id}/comments", response_model=Dict[str, Any])
async def get_appraisal_comments(
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all comments and notes for an appraisal"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.id == appraisal_id)
    )
    appraisal = result.scalar_one_or_none()
    
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    # Parse notes into comments (simple implementation)
    # In a real system, you'd have a separate comments table
    comments = []
    if appraisal.notes:
        # Split by lines that start with timestamp
        import re
        lines = appraisal.notes.split('\n')
        current_comment = None
        
        for line in lines:
            # Check if line starts with timestamp pattern [YYYY-MM-DD...]
            timestamp_match = re.match(r'\[(\d{4}-\d{2}-\d{2}[^\]]+)\]\s*(.+)', line)
            if timestamp_match:
                if current_comment:
                    comments.append(current_comment)
                current_comment = {
                    "comment": timestamp_match.group(2),
                    "created_at": timestamp_match.group(1),
                    "from": None  # Would need to parse from comment text
                }
            elif current_comment:
                current_comment["comment"] += "\n" + line
        
        if current_comment:
            comments.append(current_comment)
    
    return {
        "data": comments,
        "count": len(comments)
    }


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
    """Get statistics for concierge appraisals"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Total requests
    total_result = await db.execute(
        select(func.count(AssetAppraisal.id))
    )
    total_requests = total_result.scalar() or 0
    
    # By status
    status_result = await db.execute(
        select(
            AssetAppraisal.status,
            func.count(AssetAppraisal.id).label("count")
        ).group_by(AssetAppraisal.status)
    )
    by_status = {
        row.status.value: row.count
        for row in status_result.all()
    }
    
    return {
        "total_requests": total_requests,
        "in_progress": by_status.get(AppraisalStatus.IN_PROGRESS.value, 0),
        "completed": by_status.get(AppraisalStatus.COMPLETED.value, 0),
        "pending": by_status.get(AppraisalStatus.PENDING.value, 0),
        "awaiting_info": 0,  # Not a status in current enum, but frontend expects it
        "by_status": by_status
    }
