from fastapi import APIRouter, Depends, status, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user, get_account
from app.models.user import User
from app.integrations.supabase_client import SupabaseClient
from app.core.exceptions import BadRequestException
from app.utils.logger import logger
from app.config import settings

router = APIRouter()


@router.post("/upload", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form(..., description="File type: photo or document"),
    asset_id: Optional[UUID] = Form(None, description="Asset ID if uploading for specific asset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """General file upload endpoint"""
    account = await get_account(current_user=current_user, db=db)
    
    # Validate file type
    if file_type not in ["photo", "document"]:
        raise BadRequestException("file_type must be 'photo' or 'document'")
    
    # Read file
    file_data = await file.read()
    file_size = len(file_data)
    
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise BadRequestException(f"File size exceeds maximum allowed size")
    
    # Upload to Supabase - generate unique filename to avoid duplicates
    import uuid
    from datetime import datetime, timezone
    
    # Generate unique filename with UUID to ensure uniqueness
    file_extension = file.filename.split('.')[-1] if '.' in file.filename else ''
    base_name = file.filename.rsplit('.', 1)[0] if '.' in file.filename else file.filename
    # Sanitize base_name (remove special characters that might cause issues)
    base_name = "".join(c for c in base_name if c.isalnum() or c in (' ', '-', '_')).strip()
    base_name = base_name.replace(' ', '_')[:50]  # Limit length
    
    # Use UUID for guaranteed uniqueness
    unique_id = str(uuid.uuid4())[:8]
    unique_filename = f"{base_name}_{unique_id}.{file_extension}" if file_extension else f"{base_name}_{unique_id}"
    
    # Use appropriate bucket based on file type
    # Photos go to 'images' bucket, documents go to 'documents' bucket
    bucket_name = "images" if file_type == "photo" else "documents"
    folder = "assets" if asset_id else "general"
    file_path = f"{folder}/{account.id}/{unique_filename}"
    
    try:
        # Upload to Supabase Storage - photos to images bucket, documents to documents bucket
        upload_result = SupabaseClient.upload_file(
            bucket=bucket_name,
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type or "application/octet-stream"
        )
        logger.info(f"File uploaded successfully. Path: {file_path}, Bucket: {bucket_name}, Result: {upload_result}")
        
        # Get public URL for the uploaded file from the correct bucket
        url = SupabaseClient.get_file_url(bucket_name, file_path)
        logger.info(f"Generated public URL: {url}")
        thumbnail_url = url if file_type == "photo" else None
    except Exception as e:
        logger.error(f"Failed to upload file to Supabase Storage: {e}")
        # If duplicate error (shouldn't happen with UUID, but handle it)
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            # Generate new UUID and retry
            unique_id = str(uuid.uuid4())[:8]
            unique_filename = f"{base_name}_{unique_id}.{file_extension}" if file_extension else f"{base_name}_{unique_id}"
            file_path = f"{folder}/{account.id}/{unique_filename}"
            try:
                SupabaseClient.upload_file(
                    bucket=bucket_name,
                    file_path=file_path,
                    file_data=file_data,
                    content_type=file.content_type or "application/octet-stream"
                )
                url = SupabaseClient.get_file_url(bucket_name, file_path)
                thumbnail_url = url if file_type == "photo" else None
            except Exception as retry_error:
                logger.error(f"Failed to upload file after retry: {retry_error}")
                raise BadRequestException(f"Failed to upload file: {str(retry_error)}")
        else:
            raise BadRequestException(f"Failed to upload file: {str(e)}")
    
    # Create asset photo/document record (even if asset_id is not provided)
    # This allows frontend to upload files before creating asset, then link them later
    from app.models.asset import AssetPhoto, AssetDocument
    from sqlalchemy import select, and_
    
    file_id = None
    if file_type == "photo":
        photo = AssetPhoto(
            asset_id=asset_id,  # Can be None if asset doesn't exist yet
            file_name=file.filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=file.content_type,
            url=url,
            supabase_storage_path=file_path,
            is_primary=False
        )
        db.add(photo)
        await db.commit()
        await db.refresh(photo)
        file_id = photo.id
    else:  # document
        document = AssetDocument(
            asset_id=asset_id,  # Can be None if asset doesn't exist yet
            name=file.filename,
            file_name=file.filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=file.content_type,
            url=url,
            supabase_storage_path=file_path,
            date=datetime.now(timezone.utc) if file_type == "document" else None
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        file_id = document.id
    
    # If asset_id was provided, verify asset exists (already done above if needed)
    # The linking is already done by setting asset_id in the record
    
    # Return public URL as primary identifier - accessible from anywhere
    # ID is included for internal linking, but URL is the primary access method
    return {
        "data": {
            "url": url,  # PRIMARY: Public URL - accessible from anywhere without authentication
            "thumbnail_url": thumbnail_url,  # For images: same as url
            "id": str(file_id) if file_id else None,  # Optional: For internal linking only
            "file_name": file.filename,
            "file_size": file_size,
            "file_type": file_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat()
        }
    }
