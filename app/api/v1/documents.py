from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.document import Document, DocumentType
from app.integrations.supabase_client import SupabaseClient
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from app.config import settings
from uuid import UUID
from pydantic import BaseModel
import io

router = APIRouter()


class DocumentResponse(BaseModel):
    id: UUID
    document_type: str
    file_name: str
    file_size: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    document_type: DocumentType = DocumentType.OTHER,
    description: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload a document"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Validate file type
    file_extension = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if file_extension not in settings.ALLOWED_FILE_TYPES:
        raise BadRequestException(f"File type not allowed. Allowed types: {settings.ALLOWED_FILE_TYPES}")
    
    # Read file
    file_data = await file.read()
    file_size = len(file_data)
    
    # Check file size
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise BadRequestException(f"File size exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE} bytes")
    
    # Upload to Supabase Storage
    try:
        file_path = f"documents/{account.id}/{file.filename}"
        SupabaseClient.upload_file(
            bucket="documents",
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type or "application/octet-stream"
        )
    except Exception as e:
        logger.error(f"Failed to upload document to Supabase: {e}")
        raise BadRequestException("Failed to upload document")
    
    # Create document record
    document = Document(
        account_id=account.id,
        document_type=document_type,
        file_name=file.filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
        supabase_storage_path=file_path,
        description=description,
    )
    
    db.add(document)
    await db.commit()
    await db.refresh(document)
    
    logger.info(f"Document uploaded: {document.id}")
    return document


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    document_type: Optional[DocumentType] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all documents"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Document).where(Document.account_id == account.id)
    if document_type:
        query = query.where(Document.document_type == document_type)
    
    result = await db.execute(query.order_by(Document.created_at.desc()))
    documents = result.scalars().all()
    
    return documents


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Download a document"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.account_id == account.id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    # Check access control (admin can access all)
    if not has_permission(current_user.role, Permission.READ_USERS):
        if document.account_id != account.id:
            raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        # Get file from Supabase Storage
        from app.integrations.supabase_client import SupabaseClient
        supabase = SupabaseClient.get_client()
        file_data = supabase.storage.from_("documents").download(document.supabase_storage_path)
        
        return StreamingResponse(
            io.BytesIO(file_data),
            media_type=document.mime_type or "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{document.file_name}"'}
        )
    except Exception as e:
        logger.error(f"Failed to download document: {e}")
        raise BadRequestException("Failed to download document")


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a document"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.account_id == account.id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    # Delete from Supabase Storage
    try:
        SupabaseClient.delete_file("documents", document.supabase_storage_path)
    except Exception as e:
        logger.error(f"Failed to delete document from storage: {e}")
    
    await db.delete(document)
    await db.commit()
    
    logger.info(f"Document deleted: {document_id}")
    return None


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get document details"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.account_id == account.id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        # Check if admin
        if has_permission(current_user.role, Permission.READ_USERS):
            result = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
        
        if not document:
            raise NotFoundException("Document", str(document_id))
    
    return document


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: UUID,
    description: Optional[str] = Body(None),
    document_type: Optional[DocumentType] = Body(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update document metadata"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.account_id == account.id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    if description is not None:
        document.description = description
    if document_type:
        document.document_type = document_type
    
    await db.commit()
    await db.refresh(document)
    
    logger.info(f"Document updated: {document_id}")
    return document


@router.get("/stats/summary")
async def get_document_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get document statistics"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Total documents
    total_result = await db.execute(
        select(func.count(Document.id)).where(Document.account_id == account.id)
    )
    total_documents = total_result.scalar() or 0
    
    # Total size
    size_result = await db.execute(
        select(func.sum(Document.file_size)).where(Document.account_id == account.id)
    )
    total_size = size_result.scalar() or 0
    
    # By type
    type_result = await db.execute(
        select(
            Document.document_type,
            func.count(Document.id).label("count")
        ).where(
            Document.account_id == account.id
        ).group_by(Document.document_type)
    )
    by_type = {
        row.document_type.value: row.count
        for row in type_result.all()
    }
    
    return {
        "total_documents": total_documents,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "by_type": by_type
    }


@router.post("/{document_id}/share", response_model=Dict[str, Any])
async def share_document(
    document_id: UUID,
    user_ids: Optional[List[UUID]] = Body(None),
    permissions: str = Body("view"),
    expiry_date: Optional[str] = Body(None),
    generate_link: bool = Body(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Share a document with other users or generate a shareable link"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.account_id == account.id
        )
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    from app.models.document_share import DocumentShare, SharePermission
    import secrets
    
    shares_created = []
    
    # Share with specific users
    if user_ids:
        for user_id in user_ids:
            # Verify user exists
            user_result = await db.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                continue
            
            # Check if share already exists
            existing_share = await db.execute(
                select(DocumentShare).where(
                    DocumentShare.document_id == document_id,
                    DocumentShare.shared_with_user_id == user_id,
                    DocumentShare.is_active == True
                )
            )
            if existing_share.scalar_one_or_none():
                continue
            
            # Create share
            share = DocumentShare(
                document_id=document_id,
                shared_with_user_id=user_id,
                permission=SharePermission(permissions.lower()),
                expiry_date=datetime.fromisoformat(expiry_date.replace('Z', '+00:00')) if expiry_date else None
            )
            db.add(share)
            shares_created.append({
                "user_id": str(user_id),
                "user_name": user.email,
                "permission": permissions
            })
    
    # Generate shareable link
    share_link = None
    share_token = None
    if generate_link:
        share_token = secrets.token_urlsafe(32)
        share_link = f"/api/v1/documents/shared/{share_token}"
        
        share = DocumentShare(
            document_id=document_id,
            share_link=share_link,
            share_token=share_token,
            permission=SharePermission(permissions.lower()),
            expiry_date=datetime.fromisoformat(expiry_date.replace('Z', '+00:00')) if expiry_date else None
        )
        db.add(share)
    
    await db.commit()
    
    return {
        "message": "Document shared successfully",
        "shares": shares_created,
        "share_link": share_link,
        "share_token": share_token
    }


@router.get("/{document_id}/preview")
async def preview_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a preview URL or thumbnail for a document"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.account_id == account.id
        )
    )
    document = result.scalar_one_or_none()
    
    # Check if shared with user
    if not document:
        from app.models.document_share import DocumentShare
        share_result = await db.execute(
            select(DocumentShare).where(
                DocumentShare.document_id == document_id,
                DocumentShare.shared_with_user_id == current_user.id,
                DocumentShare.is_active == True
            )
        )
        share = share_result.scalar_one_or_none()
        if not share:
            raise NotFoundException("Document", str(document_id))
        document_result = await db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = document_result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    # Generate signed URL for preview (expires in 1 hour)
    from app.integrations.supabase_client import SupabaseClient
    try:
        # For images, return direct URL
        if document.mime_type and document.mime_type.startswith('image/'):
            preview_url = SupabaseClient.get_file_url("documents", document.supabase_storage_path)
        else:
            # For other files, return download URL (preview not supported)
            preview_url = SupabaseClient.get_file_url("documents", document.supabase_storage_path)
        
        return {
            "preview_url": preview_url,
            "file_name": document.file_name,
            "mime_type": document.mime_type,
            "file_size": document.file_size
        }
    except Exception as e:
        logger.error(f"Failed to generate preview URL: {e}")
        raise BadRequestException("Failed to generate preview URL")

