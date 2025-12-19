from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Optional
from datetime import datetime
from app.database import get_db
from app.api.deps import get_current_user, get_account
from app.models.user import User
from app.models.account import Account, AccountType
from app.models.kyb import KYBVerification, KYBStatus
from app.models.document import Document, DocumentType
from app.core.exceptions import NotFoundException, BadRequestException
from app.integrations.supabase_client import SupabaseClient
from app.integrations.persona_client import PersonaClient
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel
import httpx

router = APIRouter()


class KYBStartRequest(BaseModel):
    business_name: str
    business_registration_number: Optional[str] = None
    business_address: Optional[str] = None


class KYBStatusResponse(BaseModel):
    id: UUID
    status: str
    verification_type: str
    business_name: Optional[str] = None
    documents_submitted: bool
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    class Config:
        from_attributes = True


@router.post("/start", response_model=KYBStatusResponse, status_code=status.HTTP_201_CREATED)
async def start_kyb_verification(
    kyb_data: KYBStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start KYB verification for corporate or trust account"""
    try:
        account = await get_account(current_user=current_user, db=db)
        
        if account.account_type not in [AccountType.CORPORATE, AccountType.TRUST]:
            raise BadRequestException("KYB verification is only required for Corporate and Trust accounts")
        
        existing_result = await db.execute(
            select(KYBVerification).where(KYBVerification.account_id == account.id)
        )
        existing = existing_result.scalar_one_or_none()
        
        if existing and existing.status == KYBStatus.APPROVED:
            raise BadRequestException("KYB verification already approved")
        
        verification_type = "corporate" if account.account_type == AccountType.CORPORATE else "trust"
        
        # Try to create Persona inquiry
        persona_inquiry_id = None
        try:
            reference_id = f"KYB-{account.id}-{verification_type}"
            persona_inquiry = PersonaClient.create_inquiry(
                account_id=str(account.id),
                reference_id=reference_id
            )
            persona_inquiry_id = persona_inquiry.get("data", {}).get("id") if persona_inquiry else None
            if persona_inquiry_id:
                logger.info(f"Persona KYB inquiry created: {persona_inquiry_id}")
        except ValueError as e:
            # Template ID validation error
            logger.warning(f"Persona template not configured, continuing without Persona: {e}")
            persona_inquiry_id = None
        except httpx.HTTPStatusError as e:
            # Persona API error - extract the actual error message
            error_msg = str(e)
            try:
                if hasattr(e, 'response') and e.response is not None:
                    error_body = e.response.text
                    try:
                        error_json = e.response.json()
                        if isinstance(error_json, dict):
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
            logger.warning(f"Failed to create Persona KYB inquiry, continuing without Persona: {error_msg}")
            persona_inquiry_id = None
        except Exception as e:
            logger.warning(f"Unexpected error creating Persona KYB inquiry, continuing without Persona: {e}")
            persona_inquiry_id = None
        
        # Update existing or create new KYB verification
        if existing:
            existing.status = KYBStatus.IN_PROGRESS
            existing.business_name = kyb_data.business_name
            existing.business_registration_number = kyb_data.business_registration_number
            existing.business_address = kyb_data.business_address
            if persona_inquiry_id:
                existing.persona_kyb_inquiry_id = persona_inquiry_id
            kyb = existing
        else:
            kyb = KYBVerification(
                account_id=account.id,
                verification_type=verification_type,
                business_name=kyb_data.business_name,
                business_registration_number=kyb_data.business_registration_number,
                business_address=kyb_data.business_address,
                persona_kyb_inquiry_id=persona_inquiry_id,
                status=KYBStatus.IN_PROGRESS
            )
            db.add(kyb)
        
        try:
            await db.commit()
            await db.refresh(kyb)
        except IntegrityError as e:
            await db.rollback()
            logger.error(f"Database integrity error during KYB creation: {e}")
            # Check if it's a unique constraint violation
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                # Try to get the existing record
                existing_result = await db.execute(
                    select(KYBVerification).where(KYBVerification.account_id == account.id)
                )
                existing = existing_result.scalar_one_or_none()
                if existing:
                    # Update the existing record
                    existing.status = KYBStatus.IN_PROGRESS
                    existing.business_name = kyb_data.business_name
                    existing.business_registration_number = kyb_data.business_registration_number
                    existing.business_address = kyb_data.business_address
                    if persona_inquiry_id:
                        existing.persona_kyb_inquiry_id = persona_inquiry_id
                    await db.commit()
                    await db.refresh(existing)
                    kyb = existing
                    logger.info(f"KYB verification updated for account {account.id}")
                else:
                    raise BadRequestException("Failed to create KYB verification due to database constraint")
            else:
                raise BadRequestException(f"Database error: {str(e)}")
        except Exception as e:
            await db.rollback()
            logger.error(f"Unexpected error during KYB creation: {e}", exc_info=True)
            raise BadRequestException(f"Failed to start KYB verification: {str(e)}")
        
        logger.info(f"KYB verification started for account {account.id}")
        
        # Ensure status is properly serialized as string
        try:
            return kyb
        except Exception as e:
            logger.error(f"Error serializing KYB response: {e}", exc_info=True)
            raise BadRequestException(f"Failed to serialize KYB response: {str(e)}")
    except (BadRequestException, NotFoundException):
        # Re-raise known exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in start_kyb_verification: {e}", exc_info=True)
        raise BadRequestException(f"Failed to start KYB verification: {str(e)}")


@router.post("/upload-document")
async def upload_kyb_document(
    file: UploadFile = File(...),
    document_type: str = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload KYB verification document"""
    account = await get_account(current_user=current_user, db=db)
    
    kyb_result = await db.execute(
        select(KYBVerification).where(KYBVerification.account_id == account.id)
    )
    kyb = kyb_result.scalar_one_or_none()
    
    if not kyb:
        raise NotFoundException("KYB Verification", str(account.id))
    
    if kyb.status not in [KYBStatus.IN_PROGRESS, KYBStatus.PENDING_REVIEW]:
        raise BadRequestException("KYB verification is not in progress")
    
    try:
        supabase = SupabaseClient.get_client()
        file_content = await file.read()
        file_path = f"kyb/{account.id}/{file.filename}"
        
        supabase.storage.from_("documents").upload(
            path=file_path,
            file=file_content,
            file_options={"content-type": file.content_type}
        )
        
        document = Document(
            account_id=account.id,
            document_type=DocumentType.KYC_DOCUMENT,
            file_name=file.filename,
            file_path=file_path,
            file_size=len(file_content),
            mime_type=file.content_type,
            supabase_storage_path=file_path,
            description=f"KYB document: {document_type}",
            metadata=f'{{"kyb_id": "{kyb.id}", "document_type": "{document_type}"}}'
        )
        
        db.add(document)
        kyb.documents_submitted = True
        await db.commit()
        await db.refresh(document)
        
        logger.info(f"KYB document uploaded: {document.id}")
        return {
            "message": "Document uploaded successfully",
            "document_id": str(document.id)
        }
    except Exception as e:
        logger.error(f"Failed to upload KYB document: {e}")
        raise BadRequestException("Failed to upload document")


@router.get("/status", response_model=KYBStatusResponse)
async def get_kyb_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get KYB verification status"""
    account = await get_account(current_user=current_user, db=db)
    
    result = await db.execute(
        select(KYBVerification).where(KYBVerification.account_id == account.id)
    )
    kyb = result.scalar_one_or_none()
    
    if not kyb:
        raise NotFoundException("KYB Verification", str(account.id))
    
    if kyb.persona_kyb_inquiry_id:
        try:
            persona_status = PersonaClient.get_inquiry(kyb.persona_kyb_inquiry_id)
            if persona_status:
                status_value = persona_status.get("data", {}).get("attributes", {}).get("status")
                if status_value == "completed":
                    kyb.status = KYBStatus.APPROVED
                    kyb.verified_at = datetime.utcnow()
                elif status_value == "failed":
                    kyb.status = KYBStatus.REJECTED
                    kyb.rejection_reason = persona_status.get("data", {}).get("attributes", {}).get("failure-reason", "Verification failed")
                await db.commit()
                await db.refresh(kyb)
        except Exception as e:
            logger.error(f"Failed to sync KYB status with Persona: {e}")
    
    return kyb


@router.post("/submit")
async def submit_kyb_verification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Submit KYB verification for review"""
    account = await get_account(current_user=current_user, db=db)
    
    result = await db.execute(
        select(KYBVerification).where(KYBVerification.account_id == account.id)
    )
    kyb = result.scalar_one_or_none()
    
    if not kyb:
        raise NotFoundException("KYB Verification", str(account.id))
    
    if not kyb.documents_submitted:
        raise BadRequestException("Please upload required documents before submitting")
    
    if kyb.status not in [KYBStatus.IN_PROGRESS]:
        raise BadRequestException(f"KYB verification is {kyb.status.value}, cannot submit")
    
    try:
        if kyb.persona_kyb_inquiry_id:
            PersonaClient.submit_inquiry(kyb.persona_kyb_inquiry_id)
        
        kyb.status = KYBStatus.PENDING_REVIEW
        await db.commit()
        await db.refresh(kyb)
        
        logger.info(f"KYB verification submitted for account {account.id}")
        return {"message": "KYB verification submitted successfully", "status": kyb.status.value}
    except Exception as e:
        logger.error(f"Failed to submit KYB verification: {e}")
        raise BadRequestException("Failed to submit KYB verification")


@router.post("/webhook")
async def kyb_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Persona KYB webhook events"""
    from fastapi import Request
    
    payload = await request.json()
    event_type = payload.get("data", {}).get("attributes", {}).get("name")
    inquiry_id = payload.get("data", {}).get("id")
    
    if not inquiry_id:
        raise BadRequestException("Missing inquiry ID")
    
    result = await db.execute(
        select(KYBVerification).where(KYBVerification.persona_kyb_inquiry_id == inquiry_id)
    )
    kyb = result.scalar_one_or_none()
    
    if not kyb:
        logger.warning(f"KYB verification not found for inquiry {inquiry_id}")
        return {"status": "ignored"}
    
    if event_type == "inquiry.completed":
        kyb.status = KYBStatus.APPROVED
        kyb.verified_at = datetime.utcnow()
        await db.commit()
        logger.info(f"KYB verification approved via webhook: {kyb.id}")
    
    elif event_type == "inquiry.failed":
        kyb.status = KYBStatus.REJECTED
        kyb.rejection_reason = payload.get("data", {}).get("attributes", {}).get("failure-reason", "Verification failed")
        await db.commit()
        logger.info(f"KYB verification rejected via webhook: {kyb.id}")
    
    return {"status": "success"}

