from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
import httpx
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.kyc import KYCVerification, KYCStatus
from app.integrations.persona_client import PersonaClient
from app.core.exceptions import NotFoundException, BadRequestException, UnauthorizedException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from app.utils.helpers import generate_reference_id
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()


class KYCResponse(BaseModel):
    id: UUID
    status: str
    persona_inquiry_id: Optional[str] = None
    verification_level: Optional[str] = None
    verified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.post("/start", response_model=KYCResponse, status_code=status.HTTP_201_CREATED)
async def start_kyc(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start KYC verification process"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Check if KYC already exists
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if kyc and kyc.status == KYCStatus.APPROVED:
        raise BadRequestException("KYC already approved")
    
    # Create Persona inquiry
    reference_id = generate_reference_id(f"KYC-{account.id}")
    try:
        persona_response = PersonaClient.create_inquiry(
            account_id=str(account.id),
            reference_id=reference_id
        )
        inquiry_id = persona_response.get("data", {}).get("id")
        if not inquiry_id:
            logger.error(f"Persona inquiry created but no inquiry ID returned: {persona_response}")
            raise BadRequestException("Failed to start KYC verification: No inquiry ID returned")
    except ValueError as e:
        # Template ID validation error
        logger.error(f"Persona configuration error: {e}")
        raise BadRequestException(str(e))
    except httpx.HTTPStatusError as e:
        # Persona API error - extract the actual error message
        error_msg = str(e)
        try:
            if hasattr(e, 'response') and e.response is not None:
                error_body = e.response.text
                try:
                    error_json = e.response.json()
                    # Try to extract meaningful error message from Persona response
                    if isinstance(error_json, dict):
                        errors = error_json.get("errors", [])
                        if errors:
                            error_details = "; ".join([err.get("detail", str(err)) for err in errors])
                            error_msg = f"Persona API error: {error_details}"
                        elif "detail" in error_json:
                            error_msg = f"Persona API error: {error_json['detail']}"
                except:
                    if error_body:
                        error_msg = f"Persona API error: {error_body[:500]}"  # Limit length
        except:
            pass
        logger.error(f"Failed to create Persona inquiry: {error_msg}", exc_info=True)
        raise BadRequestException(f"Failed to start KYC verification: {error_msg}")
    except BadRequestException:
        raise
    except Exception as e:
        logger.error(f"Failed to create Persona inquiry: {e}", exc_info=True)
        raise BadRequestException(f"Failed to start KYC verification: {str(e)}")
    
    if kyc:
        kyc.persona_inquiry_id = inquiry_id
        kyc.status = KYCStatus.IN_PROGRESS
        kyc.persona_response = persona_response
    else:
        kyc = KYCVerification(
            account_id=account.id,
            persona_inquiry_id=inquiry_id,
            status=KYCStatus.IN_PROGRESS,
            persona_response=persona_response,
        )
        db.add(kyc)
    
    await db.commit()
    await db.refresh(kyc)
    
    logger.info(f"KYC started for account {account.id}")
    return kyc


@router.get("/status", response_model=KYCResponse)
async def get_kyc_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current KYC status"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc:
        raise NotFoundException("KYC Verification", str(account.id))
    
    # Sync with Persona
    if kyc.persona_inquiry_id:
        try:
            persona_data = PersonaClient.get_inquiry(kyc.persona_inquiry_id)
            if persona_data:
                attributes = persona_data.get("data", {}).get("attributes", {})
                status_str = attributes.get("status")
                
                if status_str == "completed":
                    kyc.status = KYCStatus.APPROVED
                    kyc.verified_at = datetime.utcnow()
                elif status_str == "failed":
                    kyc.status = KYCStatus.REJECTED
                    kyc.rejection_reason = attributes.get("failure-reason", "Verification failed")
                
                kyc.persona_response = persona_data
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to sync Persona status: {e}")
    
    return kyc


@router.post("/submit")
async def submit_kyc(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Submit KYC inquiry to Persona"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc or not kyc.persona_inquiry_id:
        raise NotFoundException("KYC Verification", str(account.id))
    
    try:
        persona_response = PersonaClient.submit_inquiry(kyc.persona_inquiry_id)
        kyc.status = KYCStatus.PENDING_REVIEW
        kyc.persona_response = persona_response
        await db.commit()
        
        return {"message": "KYC submitted successfully", "status": "pending_review"}
    except httpx.HTTPStatusError as e:
        error_msg = str(e)
        try:
            if hasattr(e, 'response') and e.response is not None:
                error_body = e.response.text
                try:
                    error_json = e.response.json()
                    errors = error_json.get("errors", [])
                    if errors:
                        error_details = "; ".join([err.get("detail", str(err)) for err in errors])
                        error_msg = f"Persona API error: {error_details}"
                    elif "detail" in error_json:
                        error_msg = f"Persona API error: {error_json['detail']}"
                except:
                    if error_body:
                        error_msg = f"Persona API error: {error_body[:500]}"
        except:
            pass
        logger.error(f"Failed to submit KYC to Persona: {error_msg}", exc_info=True)
        raise BadRequestException(f"Failed to submit KYC verification: {error_msg}")
    except Exception as e:
        logger.error(f"Failed to submit KYC: {e}", exc_info=True)
        raise BadRequestException(f"Failed to submit KYC verification: {str(e)}")


@router.post("/upload-document")
async def upload_kyc_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload document for KYC verification"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc:
        raise NotFoundException("KYC Verification", str(account.id))
    
    # Upload to Supabase Storage
    try:
        file_data = await file.read()
        file_path = f"kyc/{account.id}/{file.filename}"
        
        from app.integrations.supabase_client import SupabaseClient
        SupabaseClient.upload_file(
            bucket="documents",
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type or "application/pdf"
        )
        
        kyc.documents_submitted = True
        await db.commit()
        
        return {"message": "Document uploaded successfully", "file_path": file_path}
    except Exception as e:
        logger.error(f"Failed to upload document: {e}")
        raise BadRequestException("Failed to upload document")


@router.post("/documents/{document_id}/attach-to-inquiry")
async def attach_document_to_inquiry(
    document_id: UUID,
    document_type: str = Body("passport"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Attach document to Persona inquiry"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc or not kyc.persona_inquiry_id:
        raise NotFoundException("KYC Verification", str(account.id))
    
    # Get document from Supabase
    from app.models.document import Document
    from app.integrations.supabase_client import SupabaseClient
    
    doc_result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.account_id == account.id
        )
    )
    document = doc_result.scalar_one_or_none()
    
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    try:
        # Download file from Supabase
        supabase = SupabaseClient.get_client()
        file_data = supabase.storage.from_("documents").download(document.supabase_storage_path)
        
        # Upload to Persona
        persona_response = PersonaClient.upload_document(
            inquiry_id=kyc.persona_inquiry_id,
            file_data=file_data,
            file_name=document.file_name,
            document_type=document_type
        )
        
        if persona_response:
            return {"message": "Document attached to inquiry successfully", "persona_response": persona_response}
        else:
            raise BadRequestException("Failed to attach document to Persona")
    except Exception as e:
        logger.error(f"Failed to attach document: {e}")
        raise BadRequestException("Failed to attach document to inquiry")


@router.get("/documents")
async def list_kyc_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List KYC documents"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc or not kyc.persona_inquiry_id:
        return {"documents": [], "persona_documents": []}
    
    # Get local documents
    from app.models.document import Document
    doc_result = await db.execute(
        select(Document).where(Document.account_id == account.id)
        .order_by(Document.created_at.desc())
    )
    local_documents = doc_result.scalars().all()
    
    # Get Persona documents
    persona_documents = []
    try:
        persona_docs_response = PersonaClient.list_documents(kyc.persona_inquiry_id)
        if persona_docs_response:
            persona_documents = persona_docs_response.get("data", [])
    except Exception as e:
        logger.error(f"Failed to list Persona documents: {e}")
    
    return {
        "local_documents": [
            {
                "id": str(doc.id),
                "file_name": doc.file_name,
                "document_type": doc.document_type.value if doc.document_type else None,
                "created_at": doc.created_at.isoformat()
            }
            for doc in local_documents
        ],
        "persona_documents": persona_documents
    }


@router.post("/webhook")
async def persona_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Persona webhook events"""
    try:
        payload = await request.json()
        event_type = payload.get("data", {}).get("attributes", {}).get("name")
        inquiry_id = payload.get("data", {}).get("relationships", {}).get("inquiry", {}).get("data", {}).get("id")
        
        if not inquiry_id:
            return {"status": "ignored"}
        
        # Find KYC by inquiry ID
        kyc_result = await db.execute(
            select(KYCVerification).where(KYCVerification.persona_inquiry_id == inquiry_id)
        )
        kyc = kyc_result.scalar_one_or_none()
        
        if not kyc:
            logger.warning(f"KYC not found for inquiry {inquiry_id}")
            return {"status": "ignored"}
        
        # Handle different event types
        if event_type == "inquiry.completed":
            kyc.status = KYCStatus.APPROVED
            kyc.verified_at = datetime.utcnow()
            # Update user verification status
            account_result = await db.execute(
                select(Account).where(Account.id == kyc.account_id)
            )
            account = account_result.scalar_one_or_none()
            if account:
                account.user.is_verified = True
        
        elif event_type == "inquiry.failed":
            kyc.status = KYCStatus.REJECTED
            attributes = payload.get("data", {}).get("attributes", {})
            kyc.rejection_reason = attributes.get("failure-reason", "Verification failed")
        
        elif event_type == "inquiry.requires-attention":
            kyc.status = KYCStatus.PENDING_REVIEW
        
        kyc.persona_response = payload
        await db.commit()
        
        logger.info(f"KYC webhook processed: {event_type} for inquiry {inquiry_id}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to process Persona webhook: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/resubmit", response_model=KYCResponse)
async def resubmit_kyc(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Resubmit failed KYC"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc:
        raise NotFoundException("KYC Verification", str(account.id))
    
    if kyc.status != KYCStatus.REJECTED:
        raise BadRequestException("Can only resubmit rejected KYC")
    
    # Create new inquiry
    reference_id = generate_reference_id(f"KYC-{account.id}")
    try:
        persona_response = PersonaClient.create_inquiry(
            account_id=str(account.id),
            reference_id=reference_id
        )
        inquiry_id = persona_response.get("data", {}).get("id")
        
        kyc.persona_inquiry_id = inquiry_id
        kyc.status = KYCStatus.IN_PROGRESS
        kyc.rejection_reason = None
        kyc.persona_response = persona_response
        
        await db.commit()
        await db.refresh(kyc)
        
        logger.info(f"KYC resubmitted for account {account.id}")
        return kyc
    except Exception as e:
        logger.error(f"Failed to resubmit KYC: {e}")
        raise BadRequestException("Failed to resubmit KYC verification")


@router.get("/rejection-reason")
async def get_rejection_reason(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed rejection reason"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc:
        raise NotFoundException("KYC Verification", str(account.id))
    
    if kyc.status != KYCStatus.REJECTED:
        raise BadRequestException("KYC is not rejected")
    
    # Parse Persona response for detailed reasons
    rejection_details = {
        "reason": kyc.rejection_reason,
        "status": kyc.status.value
    }
    
    if kyc.persona_response:
        attributes = kyc.persona_response.get("data", {}).get("attributes", {})
        rejection_details["persona_reason"] = attributes.get("failure-reason")
        rejection_details["persona_details"] = attributes.get("failure-details")
    
    return rejection_details


@router.get("/admin/kyc-queue", response_model=List[KYCResponse])
async def get_kyc_queue(
    status_filter: Optional[KYCStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get pending KYC verifications (admin only)"""
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
        raise UnauthorizedException("Insufficient permissions")
    
    query = select(KYCVerification)
    if status_filter:
        query = query.where(KYCVerification.status == status_filter)
    else:
        query = query.where(
            KYCVerification.status.in_([KYCStatus.PENDING_REVIEW, KYCStatus.IN_PROGRESS])
        )
    
    result = await db.execute(query.order_by(KYCVerification.created_at.desc()))
    kyc_list = result.scalars().all()
    
    return kyc_list


@router.post("/admin/kyc/{kyc_id}/approve", response_model=KYCResponse)
async def approve_kyc_manual(
    kyc_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Manually approve KYC (admin only)"""
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
        raise UnauthorizedException("Insufficient permissions")
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.id == kyc_id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc:
        raise NotFoundException("KYC Verification", str(kyc_id))
    
    kyc.status = KYCStatus.APPROVED
    kyc.verified_at = datetime.utcnow()
    
    # Update user verification status
    account_result = await db.execute(
        select(Account).where(Account.id == kyc.account_id)
    )
    account = account_result.scalar_one_or_none()
    if account:
        account.user.is_verified = True
    
    await db.commit()
    await db.refresh(kyc)
    
    logger.info(f"KYC manually approved: {kyc_id} by {current_user.id}")
    return kyc


@router.post("/admin/kyc/{kyc_id}/reject", response_model=KYCResponse)
async def reject_kyc_manual(
    kyc_id: UUID,
    reason: str = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Manually reject KYC (admin only)"""
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
        raise UnauthorizedException("Insufficient permissions")
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.id == kyc_id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc:
        raise NotFoundException("KYC Verification", str(kyc_id))
    
    kyc.status = KYCStatus.REJECTED
    kyc.rejection_reason = reason
    
    await db.commit()
    await db.refresh(kyc)
    
    logger.info(f"KYC manually rejected: {kyc_id} by {current_user.id}")
    return kyc

