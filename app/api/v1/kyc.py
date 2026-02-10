from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
import httpx
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account, AccountType
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
    verification_url: Optional[str] = None  # Persona hosted verification page URL
    verification_level: Optional[str] = None
    verified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.post("/start", response_model=KYCResponse, status_code=status.HTTP_201_CREATED)
async def start_kyc(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start KYC verification process
    
    Requires email verification first before KYC can be started.
    """
    # Check if email is verified (required before KYC)
    if not current_user.email_verified_at and not current_user.is_verified:
        raise BadRequestException("Email verification required before starting KYC. Please verify your email first.")
    
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    # Auto-create account if it doesn't exist (for individual accounts)
    if not account:
        # Generate account name from user's name
        account_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()
        if not account_name:
            account_name = current_user.email.split("@")[0]  # Use email prefix as fallback
        
        account = Account(
            user_id=current_user.id,
            account_type=AccountType.INDIVIDUAL,
            account_name=account_name,
            is_joint=False
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        logger.info(f"Auto-created individual account for user {current_user.id}")
    
    # Check if KYC already exists
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if kyc and kyc.status == KYCStatus.APPROVED:
        raise BadRequestException("KYC already approved")
    
    # Create Persona inquiry (optional in development)
    from app.config import settings
    reference_id = generate_reference_id(f"KYC-{account.id}")
    inquiry_id = None
    persona_response = None
    
    try:
        persona_response = PersonaClient.create_inquiry(
            account_id=str(account.id),
            reference_id=reference_id
        )
        inquiry_id = persona_response.get("data", {}).get("id")
        if not inquiry_id:
            logger.error(f"Persona inquiry created but no inquiry ID returned: {persona_response}")
            if settings.APP_ENV != "development":
                raise BadRequestException("Failed to start KYC verification: No inquiry ID returned")
            else:
                logger.warning("Persona inquiry ID missing, continuing without Persona in development mode")
    except ValueError as e:
        # Template ID validation error
        logger.warning(f"Persona configuration error: {e}")
        if settings.APP_ENV != "development":
            raise BadRequestException(str(e))
        else:
            logger.warning("Persona template not configured, continuing without Persona in development mode")
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
        if settings.APP_ENV != "development":
            logger.error(f"Failed to create Persona inquiry: {error_msg}", exc_info=True)
            raise BadRequestException(f"Failed to start KYC verification: {error_msg}")
        else:
            logger.warning(f"Failed to create Persona inquiry, continuing without Persona in development mode: {error_msg}")
    except BadRequestException:
        if settings.APP_ENV != "development":
            raise
        else:
            logger.warning("Persona BadRequestException, continuing without Persona in development mode")
    except Exception as e:
        if settings.APP_ENV != "development":
            logger.error(f"Failed to create Persona inquiry: {e}", exc_info=True)
            raise BadRequestException(f"Failed to start KYC verification: {str(e)}")
        else:
            logger.warning(f"Failed to create Persona inquiry, continuing without Persona in development mode: {e}")
    
    # Create or update KYC verification
    if kyc:
        if inquiry_id:
            kyc.persona_inquiry_id = inquiry_id
        kyc.status = KYCStatus.IN_PROGRESS
        if persona_response:
            kyc.persona_response = persona_response
    else:
        kyc = KYCVerification(
            account_id=account.id,
            persona_inquiry_id=inquiry_id,
            status=KYCStatus.IN_PROGRESS,
            persona_response=persona_response,
        )
        db.add(kyc)
    
    # Ensure user is NOT verified when KYC is in progress
    account.user.is_verified = False
    
    await db.commit()
    await db.refresh(kyc)
    
    # Get verification URL for Persona hosted flow
    verification_url = None
    if inquiry_id:
        # Get redirect URI from settings or construct from CORS origins
        from app.config import settings
        if settings.PERSONA_REDIRECT_URI:
            redirect_uri = settings.PERSONA_REDIRECT_URI
        else:
            # Fallback to first CORS origin + default path
            base_url = settings.CORS_ORIGINS[0] if isinstance(settings.CORS_ORIGINS, list) and settings.CORS_ORIGINS else 'http://localhost:3000'
            redirect_uri = f"{base_url}/kyc/verification-complete"
        
        # Try to extract from response, otherwise construct it
        if persona_response:
            verification_url = PersonaClient.extract_verification_url_from_response(
                persona_response,
                redirect_uri=redirect_uri
            )
        else:
            # Construct verification URL directly if we have inquiry_id
            verification_url = PersonaClient.get_verification_url(inquiry_id, redirect_uri)
    
    logger.info(f"KYC started for account {account.id}, verification URL: {verification_url}")
    
    # Return response with verification URL
    return {
        "id": kyc.id,
        "status": kyc.status.value if hasattr(kyc.status, 'value') else str(kyc.status),
        "persona_inquiry_id": kyc.persona_inquiry_id,
        "verification_url": verification_url,
        "verification_level": kyc.verification_level,
        "verified_at": kyc.verified_at
    }


@router.get("/status")
async def get_kyc_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current KYC status"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    # If no account exists, return not_started status
    if not account:
        return {
            "id": None,
            "status": "not_started",
            "persona_inquiry_id": None,
            "verification_url": None,
            "verification_level": None,
            "verified_at": None
        }
    
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    # If KYC hasn't been started, return not_started status
    if not kyc:
        return {
            "id": None,
            "status": "not_started",
            "persona_inquiry_id": None,
            "verification_url": None,
            "verification_level": None,
            "verified_at": None
        }
    
    # Sync with Persona
    verification_url = None
    if kyc.persona_inquiry_id:
        try:
            logger.info(f"[KYC STATUS SYNC] Fetching Persona inquiry: {kyc.persona_inquiry_id}")
            persona_data = PersonaClient.get_inquiry(kyc.persona_inquiry_id)
            if persona_data:
                # Log full Persona response for debugging
                import json
                logger.info(f"[KYC STATUS SYNC] Full Persona API response: {json.dumps(persona_data, indent=2, default=str)}")
                
                attributes = persona_data.get("data", {}).get("attributes", {})
                logger.info(f"[KYC STATUS SYNC] Attributes keys: {list(attributes.keys()) if attributes else 'None'}")
                
                status_str = attributes.get("status")
                logger.info(f"[KYC STATUS SYNC] Persona status field value: '{status_str}'")
                
                # Check all possible status-related fields
                verification_status = attributes.get("verification-status")
                verification_state = attributes.get("verification_state")
                state = attributes.get("state")
                logger.info(f"[KYC STATUS SYNC] verification-status: '{verification_status}', verification_state: '{verification_state}', state: '{state}'")
                
                # Get account and user for is_verified updates
                account_result = await db.execute(
                    select(Account).where(Account.id == kyc.account_id)
                )
                account = account_result.scalar_one_or_none()
                
                # Properly map Persona statuses to KYC statuses
                if status_str == "approved":
                    # Persona returns "approved" directly when verification is complete and approved
                    logger.info(f"[KYC STATUS SYNC] Status is 'approved'. Setting to APPROVED")
                    kyc.status = KYCStatus.APPROVED
                    kyc.verified_at = datetime.utcnow()
                    # Update verification level if available
                    if attributes.get("verification-level"):
                        kyc.verification_level = attributes.get("verification-level")
                    # Set user as verified
                    if account:
                        account.user.is_verified = True
                elif status_str == "completed":
                    # Check verification status to determine if approved or pending review
                    verification_status = attributes.get("verification-status")
                    if verification_status == "approved":
                        kyc.status = KYCStatus.APPROVED
                        kyc.verified_at = datetime.utcnow()
                        # Update verification level if available
                        if attributes.get("verification-level"):
                            kyc.verification_level = attributes.get("verification-level")
                        # Set user as verified
                        if account:
                            account.user.is_verified = True
                    elif verification_status == "pending":
                        kyc.status = KYCStatus.PENDING_REVIEW
                        # Set user as NOT verified
                        if account:
                            account.user.is_verified = False
                    elif verification_status == "failed":
                        kyc.status = KYCStatus.REJECTED
                        kyc.rejection_reason = attributes.get("failure-reason", "Verification failed")
                        # Set user as NOT verified
                        if account:
                            account.user.is_verified = False
                    else:
                        # Default to approved if completed but no verification-status
                        logger.info(f"[KYC STATUS SYNC] Status is 'completed' but no verification-status found. Defaulting to APPROVED")
                        kyc.status = KYCStatus.APPROVED
                        kyc.verified_at = datetime.utcnow()
                        # Set user as verified
                        if account:
                            account.user.is_verified = True
                elif status_str == "failed":
                    logger.info(f"[KYC STATUS SYNC] Status is 'failed'. Setting to REJECTED")
                    kyc.status = KYCStatus.REJECTED
                    kyc.rejection_reason = attributes.get("failure-reason", "Verification failed")
                    # Set user as NOT verified
                    if account:
                        account.user.is_verified = False
                elif status_str == "pending":
                    logger.info(f"[KYC STATUS SYNC] Status is 'pending'. Setting to PENDING_REVIEW")
                    kyc.status = KYCStatus.PENDING_REVIEW
                    # Set user as NOT verified
                    if account:
                        account.user.is_verified = False
                elif status_str in ["processing", "waiting"]:
                    logger.info(f"[KYC STATUS SYNC] Status is '{status_str}'. Keeping as IN_PROGRESS")
                    kyc.status = KYCStatus.IN_PROGRESS
                    # Set user as NOT verified (KYC is still in progress)
                    if account:
                        account.user.is_verified = False
                else:
                    logger.warning(f"[KYC STATUS SYNC] Unknown status value: '{status_str}'. Keeping current status: {kyc.status}")
                    # For unknown statuses, set user as NOT verified to be safe
                    if account and kyc.status != KYCStatus.APPROVED:
                        account.user.is_verified = False
                
                # Update verification level if available
                verification_level = attributes.get("verification-level") or attributes.get("verification_level")
                if verification_level and not kyc.verification_level:
                    logger.info(f"[KYC STATUS SYNC] Updating verification_level to: {verification_level}")
                    kyc.verification_level = verification_level
                
                logger.info(f"[KYC STATUS SYNC] Final KYC status after sync: {kyc.status.value if hasattr(kyc.status, 'value') else kyc.status}")
                kyc.persona_response = persona_data
                await db.commit()
                logger.info(f"[KYC STATUS SYNC] Database updated successfully")
                
                # Get verification URL if inquiry is still in progress
                if kyc.status == KYCStatus.IN_PROGRESS:
                    from app.config import settings
                    if settings.PERSONA_REDIRECT_URI:
                        redirect_uri = settings.PERSONA_REDIRECT_URI
                    else:
                        base_url = settings.CORS_ORIGINS[0] if isinstance(settings.CORS_ORIGINS, list) and settings.CORS_ORIGINS else 'http://localhost:3000'
                        redirect_uri = f"{base_url}/kyc/verification-complete"
                    
                    verification_url = PersonaClient.get_verification_url(kyc.persona_inquiry_id, redirect_uri)
        except Exception as e:
            logger.error(f"[KYC STATUS SYNC] Failed to sync Persona status: {e}", exc_info=True)
    
    return {
        "id": kyc.id,
        "status": kyc.status.value if hasattr(kyc.status, 'value') else str(kyc.status),
        "persona_inquiry_id": kyc.persona_inquiry_id,
        "verification_url": verification_url,
        "verification_level": kyc.verification_level,
        "verified_at": kyc.verified_at
    }


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
    """Handle Persona webhook events
    
    CRITICAL: Preserves verification_level and verification_type when updating status.
    """
    logger.info("=== PERSONA WEBHOOK RECEIVED ===")
    
    try:
        # Get raw body for potential signature verification (read before JSON parsing)
        body = await request.body()
        
        # Parse webhook payload
        import json
        payload = json.loads(body.decode('utf-8'))
        
        logger.info(f"Webhook payload: {json.dumps(payload, indent=2)}")
        
        # Extract webhook data - CRITICAL FIX: inquiry_id is in data.id, not relationships
        event_type = payload.get("data", {}).get("attributes", {}).get("name")
        inquiry_id = payload.get("data", {}).get("id")  # FIXED: Was using relationships.inquiry.data.id
        
        logger.info(f"Webhook event: {event_type}, inquiry_id: {inquiry_id}")
        
        if not inquiry_id:
            logger.warning("Missing inquiry_id in webhook payload")
            # Log payload structure for debugging
            logger.warning(f"Payload structure: {list(payload.get('data', {}).keys())}")
            return {"status": "ignored", "message": "Missing inquiry_id"}
        
        # Find KYC by inquiry ID
        kyc_result = await db.execute(
            select(KYCVerification).where(KYCVerification.persona_inquiry_id == inquiry_id)
        )
        kyc = kyc_result.scalar_one_or_none()
        
        if not kyc:
            logger.warning(f"KYC not found for inquiry {inquiry_id}")
            # Log all existing inquiry IDs for debugging
            all_kyc_result = await db.execute(
                select(KYCVerification.persona_inquiry_id).where(
                    KYCVerification.persona_inquiry_id.isnot(None)
                )
            )
            existing_ids = [row[0] for row in all_kyc_result.fetchall()]
            logger.info(f"Existing persona_inquiry_ids in database: {existing_ids}")
            return {"status": "ignored", "message": "KYC not found"}
        
        logger.info(f"Found KYC record: id={kyc.id}, current_status={kyc.status.value if hasattr(kyc.status, 'value') else kyc.status}")
        
        # Get account and user for is_verified updates
        account_result = await db.execute(
            select(Account).where(Account.id == kyc.account_id)
        )
        account = account_result.scalar_one_or_none()
        
        # CRITICAL: Preserve verification_level and verification_type (if exists)
        old_verification_level = kyc.verification_level
        old_verification_type = getattr(kyc, 'verification_type', None)  # May not exist on KYC model
        
        logger.info(f"Preserving values: level={old_verification_level}, type={old_verification_type}")
        
        # Handle different event types
        if event_type == "inquiry.completed":
            # Check verification status to determine if approved or pending review
            attributes = payload.get("data", {}).get("attributes", {})
            verification_status = attributes.get("verification-status")
            
            if verification_status == "approved":
                logger.info("Updating status to approved")
                kyc.status = KYCStatus.APPROVED
                kyc.verified_at = datetime.utcnow()
                
                # Update verification level if available
                if attributes.get("verification-level"):
                    kyc.verification_level = attributes.get("verification-level")
                
                # Update user verification status - ONLY set to True when APPROVED
                if account:
                    account.user.is_verified = True
            elif verification_status == "pending":
                logger.info("Updating status to pending_review")
                kyc.status = KYCStatus.PENDING_REVIEW
                # Set user as NOT verified
                if account:
                    account.user.is_verified = False
            elif verification_status == "failed":
                logger.info("Updating status to rejected")
                kyc.status = KYCStatus.REJECTED
                kyc.rejection_reason = attributes.get("failure-reason", "Verification failed")
                # Set user as NOT verified
                if account:
                    account.user.is_verified = False
            else:
                # Default to approved if completed but no verification-status
                logger.info("Updating status to approved (default for completed)")
                kyc.status = KYCStatus.APPROVED
                kyc.verified_at = datetime.utcnow()
                
                # Update verification level if available
                if attributes.get("verification-level"):
                    kyc.verification_level = attributes.get("verification-level")
                # Set user as verified
                if account:
                    account.user.is_verified = True
        
        elif event_type == "inquiry.failed":
            logger.info("Updating status to rejected")
            kyc.status = KYCStatus.REJECTED
            attributes = payload.get("data", {}).get("attributes", {})
            kyc.rejection_reason = attributes.get("failure-reason", "Verification failed")
            # Set user as NOT verified
            if account:
                account.user.is_verified = False
        
        elif event_type == "inquiry.requires-attention":
            logger.info("Updating status to pending_review")
            kyc.status = KYCStatus.PENDING_REVIEW
            # Set user as NOT verified
            if account:
                account.user.is_verified = False
        
        # CRITICAL: Restore preserved values
        kyc.verification_level = old_verification_level
        if hasattr(kyc, 'verification_type'):
            kyc.verification_type = old_verification_type
        
        kyc.persona_response = payload
        await db.commit()
        await db.refresh(kyc)
        
        logger.info(f"KYC webhook processed successfully: event={event_type}, inquiry_id={inquiry_id}, new_status={kyc.status.value if hasattr(kyc.status, 'value') else kyc.status}")
        logger.info(f"Preserved values after update: level={kyc.verification_level}, type={getattr(kyc, 'verification_type', 'N/A')}")
        
        return {"status": "success", "message": "KYC status updated"}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse webhook JSON: {e}")
        return {"status": "error", "message": "Invalid JSON payload"}
    except Exception as e:
        logger.error(f"Failed to process Persona webhook: {e}", exc_info=True)
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
        
        # Set user as NOT verified when resubmitting (KYC is in progress again)
        account.user.is_verified = False
        
        await db.commit()
        await db.refresh(kyc)
        
        logger.info(f"KYC resubmitted for account {account.id}")
        return kyc
    except Exception as e:
        logger.error(f"Failed to resubmit KYC: {e}")
        raise BadRequestException("Failed to resubmit KYC verification")


@router.post("/sync-status")
async def sync_kyc_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Manually sync KYC status with Persona API"""
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
    
    # Query Persona API for latest status
    try:
        logger.info(f"[KYC SYNC-STATUS] Starting sync for inquiry: {kyc.persona_inquiry_id}")
        logger.info(f"[KYC SYNC-STATUS] Current database status: {kyc.status.value if hasattr(kyc.status, 'value') else kyc.status}")
        
        persona_data = PersonaClient.get_inquiry(kyc.persona_inquiry_id)
        if not persona_data:
            logger.error(f"[KYC SYNC-STATUS] Persona API returned None for inquiry: {kyc.persona_inquiry_id}")
            raise BadRequestException("Failed to fetch status from Persona")
        
        # Log full Persona response for debugging
        import json
        logger.info(f"[KYC SYNC-STATUS] Full Persona API response: {json.dumps(persona_data, indent=2, default=str)}")
        
        attributes = persona_data.get("data", {}).get("attributes", {})
        logger.info(f"[KYC SYNC-STATUS] Attributes keys: {list(attributes.keys()) if attributes else 'None'}")
        
        status_str = attributes.get("status")
        logger.info(f"[KYC SYNC-STATUS] Persona status field value: '{status_str}'")
        
        # Check all possible status-related fields
        verification_status = attributes.get("verification-status")
        verification_state = attributes.get("verification_state")
        state = attributes.get("state")
        logger.info(f"[KYC SYNC-STATUS] verification-status: '{verification_status}', verification_state: '{verification_state}', state: '{state}'")
        
        old_status = kyc.status
        
        # Properly map Persona statuses to KYC statuses
        # NOTE: Persona can return "approved" directly OR "completed" with verification-status
        if status_str == "approved":
            # Persona returns "approved" directly when verification is complete and approved
            logger.info(f"[KYC SYNC-STATUS] Status is 'approved'. Setting to APPROVED")
            kyc.status = KYCStatus.APPROVED
            kyc.verified_at = datetime.utcnow()
            # Update verification level if available
            verification_level = attributes.get("verification-level") or attributes.get("verification_level")
            if verification_level:
                logger.info(f"[KYC SYNC-STATUS] Updating verification_level to: {verification_level}")
                kyc.verification_level = verification_level
            
            # Update user verification status - ONLY set to True when APPROVED
            account.user.is_verified = True
        elif status_str == "completed":
            if verification_status == "approved":
                logger.info(f"[KYC SYNC-STATUS] verification-status is 'approved'. Setting to APPROVED")
                kyc.status = KYCStatus.APPROVED
                kyc.verified_at = datetime.utcnow()
                # Update verification level if available
                verification_level = attributes.get("verification-level") or attributes.get("verification_level")
                if verification_level:
                    logger.info(f"[KYC SYNC-STATUS] Updating verification_level to: {verification_level}")
                    kyc.verification_level = verification_level
                
                # Update user verification status - ONLY set to True when APPROVED
                account.user.is_verified = True
            elif verification_status == "pending":
                logger.info(f"[KYC SYNC-STATUS] verification-status is 'pending'. Setting to PENDING_REVIEW")
                kyc.status = KYCStatus.PENDING_REVIEW
                # Set user as NOT verified
                account.user.is_verified = False
            elif verification_status == "failed":
                logger.info(f"[KYC SYNC-STATUS] verification-status is 'failed'. Setting to REJECTED")
                kyc.status = KYCStatus.REJECTED
                kyc.rejection_reason = attributes.get("failure-reason", "Verification failed")
                # Set user as NOT verified
                account.user.is_verified = False
            else:
                # Default to approved if completed but no verification-status
                logger.info(f"[KYC SYNC-STATUS] Status is 'completed' but verification-status is '{verification_status}' (not found/unknown). Defaulting to APPROVED")
                kyc.status = KYCStatus.APPROVED
                kyc.verified_at = datetime.utcnow()
                verification_level = attributes.get("verification-level") or attributes.get("verification_level")
                if verification_level:
                    logger.info(f"[KYC SYNC-STATUS] Updating verification_level to: {verification_level}")
                    kyc.verification_level = verification_level
                # Set user as verified (defaulting to approved)
                account.user.is_verified = True
        elif status_str == "failed":
            logger.info(f"[KYC SYNC-STATUS] Status is 'failed'. Setting to REJECTED")
            kyc.status = KYCStatus.REJECTED
            kyc.rejection_reason = attributes.get("failure-reason", "Verification failed")
            # Set user as NOT verified
            account.user.is_verified = False
        elif status_str == "pending":
            logger.info(f"[KYC SYNC-STATUS] Status is 'pending'. Setting to PENDING_REVIEW")
            kyc.status = KYCStatus.PENDING_REVIEW
            # Set user as NOT verified
            account.user.is_verified = False
        elif status_str in ["processing", "waiting"]:
            logger.info(f"[KYC SYNC-STATUS] Status is '{status_str}'. Keeping as IN_PROGRESS")
            kyc.status = KYCStatus.IN_PROGRESS
            # Set user as NOT verified (KYC is still in progress)
            account.user.is_verified = False
        else:
            logger.warning(f"[KYC SYNC-STATUS] Unknown status value: '{status_str}'. Keeping current status: {kyc.status}")
            # For unknown statuses, set user as NOT verified to be safe (unless already approved)
            if kyc.status != KYCStatus.APPROVED:
                account.user.is_verified = False
        
        # Update verification level if available
        verification_level = attributes.get("verification-level") or attributes.get("verification_level")
        if verification_level and not kyc.verification_level:
            logger.info(f"[KYC SYNC-STATUS] Updating verification_level to: {verification_level}")
            kyc.verification_level = verification_level
        
        kyc.persona_response = persona_data
        await db.commit()
        await db.refresh(kyc)
        
        logger.info(f"[KYC SYNC-STATUS] Status synced successfully: {old_status.value if hasattr(old_status, 'value') else old_status} -> {kyc.status.value if hasattr(kyc.status, 'value') else kyc.status}")
        
        return {
            "status": kyc.status.value if hasattr(kyc.status, 'value') else str(kyc.status),
            "message": "Status synced successfully",
            "verification_level": kyc.verification_level,
            "verified_at": kyc.verified_at.isoformat() if kyc.verified_at else None
        }
    except Exception as e:
        logger.error(f"[KYC SYNC-STATUS] Failed to sync KYC status: {e}", exc_info=True)
        raise BadRequestException(f"Failed to sync status: {str(e)}")


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

