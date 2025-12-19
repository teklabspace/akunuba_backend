import httpx
from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any


class PersonaClient:
    BASE_URL = "https://withpersona.com/api/v1"
    API_VERSION = "2024-01-01"  # Persona API version (YYYY-MM-DD format)

    @staticmethod
    def _get_headers() -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.PERSONA_API_KEY}",
            "Content-Type": "application/json",
            "Persona-Version": PersonaClient.API_VERSION,
            "Key-Inflection": "kebab",  # Use kebab-case for attribute keys
        }

    @staticmethod
    def create_inquiry(account_id: str, reference_id: str) -> Dict[str, Any]:
        # Validate template ID is set
        if not settings.PERSONA_TEMPLATE_ID:
            error_msg = "PERSONA_TEMPLATE_ID is not configured. Please set it in your environment variables."
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        try:
            with httpx.Client() as client:
                request_payload = {
                    "data": {
                        "type": "inquiry",
                        "attributes": {
                            "inquiry-template-id": settings.PERSONA_TEMPLATE_ID,
                            "reference-id": reference_id,
                        }
                    }
                }
                logger.debug(f"Creating Persona inquiry with payload: {request_payload}")
                
                response = client.post(
                    f"{PersonaClient.BASE_URL}/inquiries",
                    headers=PersonaClient._get_headers(),
                    json=request_payload,
                    timeout=30.0
                )
                
                # Capture error response before raising
                if response.status_code >= 400:
                    error_body = response.text
                    try:
                        error_json = response.json()
                        error_details = error_json
                    except:
                        error_details = error_body
                    
                    error_msg = f"Persona API error {response.status_code}: {error_details}"
                    logger.error(f"Failed to create Persona inquiry: {error_msg}")
                    raise httpx.HTTPStatusError(
                        message=error_msg,
                        request=response.request,
                        response=response
                    )
                
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            # Re-raise HTTP errors with better context
            raise
        except Exception as e:
            logger.error(f"Failed to create Persona inquiry: {e}", exc_info=True)
            raise

    @staticmethod
    def get_inquiry(inquiry_id: str) -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PersonaClient.BASE_URL}/inquiries/{inquiry_id}",
                    headers=PersonaClient._get_headers(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get Persona inquiry: {e}")
            return None

    @staticmethod
    def submit_inquiry(inquiry_id: str) -> Dict[str, Any]:
        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{PersonaClient.BASE_URL}/inquiries/{inquiry_id}/submit",
                    headers=PersonaClient._get_headers(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to submit Persona inquiry: {e}")
            raise

    @staticmethod
    def list_templates() -> Optional[Dict[str, Any]]:
        """List all inquiry templates available in your Persona account"""
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PersonaClient.BASE_URL}/inquiry-templates",
                    headers=PersonaClient._get_headers(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to list Persona templates: {e}")
            return None

    @staticmethod
    def upload_document(inquiry_id: str, file_data: bytes, file_name: str, document_type: str = "passport") -> Optional[Dict[str, Any]]:
        """Upload a document to an inquiry"""
        try:
            import base64
            file_base64 = base64.b64encode(file_data).decode('utf-8')
            
            with httpx.Client() as client:
                response = client.post(
                    f"{PersonaClient.BASE_URL}/inquiries/{inquiry_id}/documents",
                    headers=PersonaClient._get_headers(),
                    json={
                        "data": {
                            "type": "document",
                            "attributes": {
                                "document-type": document_type,
                                "file-name": file_name,
                                "file-content": file_base64
                            }
                        }
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to upload document to Persona: {e}")
            return None

    @staticmethod
    def list_documents(inquiry_id: str) -> Optional[Dict[str, Any]]:
        """List documents for an inquiry"""
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{PersonaClient.BASE_URL}/inquiries/{inquiry_id}/documents",
                    headers=PersonaClient._get_headers(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to list Persona documents: {e}")
            return None

    @staticmethod
    def redact_inquiry(inquiry_id: str) -> Optional[Dict[str, Any]]:
        """Redact an inquiry (GDPR compliance)"""
        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{PersonaClient.BASE_URL}/inquiries/{inquiry_id}/redact",
                    headers=PersonaClient._get_headers(),
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to redact Persona inquiry: {e}")
            return None

