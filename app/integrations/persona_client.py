import httpx
from urllib.parse import urlencode
from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any


class PersonaClient:
    BASE_URL = "https://api.withpersona.com/api/v1"
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
            logger.info(f"[PERSONA CLIENT] Fetching inquiry: {inquiry_id}")
            with httpx.Client() as client:
                response = client.get(
                    f"{PersonaClient.BASE_URL}/inquiries/{inquiry_id}",
                    headers=PersonaClient._get_headers(),
                    timeout=30.0
                )
                logger.info(f"[PERSONA CLIENT] Response status code: {response.status_code}")
                response.raise_for_status()
                response_data = response.json()
                logger.info(f"[PERSONA CLIENT] Successfully fetched inquiry. Response structure: data={bool(response_data.get('data'))}, attributes={bool(response_data.get('data', {}).get('attributes'))}")
                return response_data
        except httpx.HTTPStatusError as e:
            logger.error(f"[PERSONA CLIENT] HTTP error fetching inquiry {inquiry_id}: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"[PERSONA CLIENT] Failed to get Persona inquiry {inquiry_id}: {e}", exc_info=True)
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

    @staticmethod
    def kyc_reference_id(account_id: str) -> str:
        """Stable reference ID for linking Persona inquiries to an account."""
        return f"KYC-{account_id}"

    @staticmethod
    def get_redirect_uri() -> Optional[str]:
        """Only return redirect URI when explicitly enabled and configured in Persona."""
        if not settings.PERSONA_USE_REDIRECT_URI:
            return None
        if settings.PERSONA_REDIRECT_URI:
            return settings.PERSONA_REDIRECT_URI.strip()
        return None

    @staticmethod
    def _hosted_flow_environment_param() -> Dict[str, str]:
        if settings.PERSONA_ENVIRONMENT_ID:
            return {"environment-id": settings.PERSONA_ENVIRONMENT_ID}
        if settings.PERSONA_API_KEY.startswith("persona_sandbox_"):
            return {"environment": "sandbox"}
        if settings.PERSONA_API_KEY.startswith("persona_production_"):
            return {"environment": "production"}
        return {}

    @staticmethod
    def parse_http_error(error: httpx.HTTPStatusError) -> str:
        try:
            if error.response is not None:
                error_json = error.response.json()
                if isinstance(error_json, dict):
                    errors = error_json.get("errors", [])
                    if errors:
                        parts = []
                        for err in errors:
                            detail = err.get("details") or err.get("detail") or str(err)
                            parts.append(str(detail))
                        return f"Persona API error: {'; '.join(parts)}"
                    if "detail" in error_json:
                        return f"Persona API error: {error_json['detail']}"
                return f"Persona API error: {error.response.text[:500]}"
        except Exception:
            pass
        return str(error)

    @staticmethod
    def is_inquiry_create_disabled(error: httpx.HTTPStatusError) -> bool:
        if error.response is None:
            return False
        if error.response.status_code == 403:
            return True
        return "inquiries.create" in error.response.text.lower()

    @staticmethod
    def get_hosted_flow_url(reference_id: str, redirect_uri: Optional[str] = None) -> str:
        """
        Build a Persona Hosted Flow URL that creates an inquiry client-side.
        Does not require inquiries.create.api permission on the server API key.
        """
        params = {
            "inquiry-template-id": settings.PERSONA_TEMPLATE_ID,
            "reference-id": reference_id,
            **PersonaClient._hosted_flow_environment_param(),
        }
        if redirect_uri:
            params["redirect-uri"] = redirect_uri
        return f"https://inquiry.withpersona.com/verify?{urlencode(params)}"

    @staticmethod
    def start_verification(
        account_id: str,
        reference_id: str,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start KYC verification via API when permitted, otherwise fall back to
        Persona's template-based Hosted Flow (no server-side create permission needed).
        """
        redirect_uri = redirect_uri or PersonaClient.get_redirect_uri()

        try:
            persona_response = PersonaClient.create_inquiry(account_id, reference_id)
            inquiry_id = persona_response.get("data", {}).get("id")
            verification_url = PersonaClient.extract_verification_url_from_response(
                persona_response, redirect_uri
            )
            return {
                "inquiry_id": inquiry_id,
                "persona_response": persona_response,
                "verification_url": verification_url,
                "flow_mode": "api",
            }
        except httpx.HTTPStatusError as e:
            if PersonaClient.is_inquiry_create_disabled(e):
                logger.warning(
                    "Persona inquiries.create.api not enabled; using hosted template flow"
                )
                verification_url = PersonaClient.get_hosted_flow_url(reference_id, redirect_uri)
                return {
                    "inquiry_id": None,
                    "persona_response": {
                        "flow_mode": "hosted_template",
                        "reference_id": reference_id,
                        "verification_url": verification_url,
                    },
                    "verification_url": verification_url,
                    "flow_mode": "hosted_template",
                }
            raise

    @staticmethod
    def get_verification_url(inquiry_id: str, redirect_uri: Optional[str] = None) -> str:
        """
        Get the Persona hosted verification URL for an inquiry.
        
        Args:
            inquiry_id: The Persona inquiry ID
            redirect_uri: Optional redirect URI after verification completes
            
        Returns:
            The verification URL to redirect users to
        """
        base_url = f"https://inquiry.withpersona.com/verify?inquiry-id={inquiry_id}"
        
        if redirect_uri:
            base_url += f"&redirect-uri={redirect_uri}"
        
        return base_url

    @staticmethod
    def extract_verification_url_from_response(inquiry_response: Dict[str, Any], redirect_uri: Optional[str] = None) -> Optional[str]:
        """
        Extract verification URL from Persona inquiry response.
        
        Persona may return the verification URL in the response, or we construct it.
        
        Args:
            inquiry_response: The response from create_inquiry
            redirect_uri: Optional redirect URI after verification completes
            
        Returns:
            The verification URL or None if inquiry_id is missing
        """
        inquiry_id = inquiry_response.get("data", {}).get("id")
        if not inquiry_id:
            return None
        
        # Check if Persona provided a verification URL in the response
        verification_url = inquiry_response.get("data", {}).get("attributes", {}).get("verification-url")
        if verification_url:
            if redirect_uri:
                # Append redirect URI if provided
                separator = "&" if "?" in verification_url else "?"
                return f"{verification_url}{separator}redirect-uri={redirect_uri}"
            return verification_url
        
        # Construct the verification URL if not provided
        return PersonaClient.get_verification_url(inquiry_id, redirect_uri)

