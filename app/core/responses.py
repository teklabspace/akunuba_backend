"""Standard API response envelope.

Every JSON response the API returns to a client follows one predictable shape so
the frontend can use a single parser. See ``doc/SUBSCRIPTION_CONTRACT.md`` for the
agreed contract.

Success:
    {"success": true,  "status_code": 200, "message": "...", "data": {...}}
No data:
    {"success": true,  "status_code": 200, "message": "...", "data": null}
Error:
    {"success": false, "status_code": 404, "message": "...",
     "error": {"code": "SUBSCRIPTION_NOT_FOUND", "details": []}}
"""
from typing import Any, List, Optional

# Map plain HTTP status codes to a stable machine-readable error code. Used when an
# exception does not carry its own ``code`` (e.g. a raw ``HTTPException``).
STATUS_TO_CODE = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    402: "PAYMENT_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

# Generic, user-safe fallback messages keyed by status code. Never leak internals.
STATUS_TO_MESSAGE = {
    400: "The request could not be processed. Please check your input and try again.",
    401: "You need to sign in to continue.",
    402: "Payment is required to complete this action.",
    403: "You don't have permission to perform this action.",
    404: "We couldn't find what you were looking for.",
    405: "That action isn't allowed here.",
    409: "This action conflicts with the current state. Please refresh and try again.",
    422: "Some of the information provided is invalid. Please check the highlighted fields.",
    429: "Too many requests. Please slow down and try again shortly.",
    500: "Something went wrong on our end. Please try again.",
    503: "The service is temporarily unavailable. Please try again shortly.",
}


def error_code_for(status_code: int) -> str:
    return STATUS_TO_CODE.get(status_code, "ERROR")


def default_message_for(status_code: int) -> str:
    return STATUS_TO_MESSAGE.get(status_code, "Request failed.")


def success_envelope(
    data: Any = None,
    message: str = "Request successful.",
    status_code: int = 200,
) -> dict:
    """Build a success envelope body."""
    return {
        "success": True,
        "status_code": status_code,
        "message": message,
        "data": data,
    }


def error_envelope(
    status_code: int,
    message: Optional[str] = None,
    code: Optional[str] = None,
    details: Optional[List[dict]] = None,
) -> dict:
    """Build an error envelope body."""
    return {
        "success": False,
        "status_code": status_code,
        "message": message or default_message_for(status_code),
        "error": {
            "code": code or error_code_for(status_code),
            "details": details or [],
        },
    }


def flatten_validation_errors(errors: List[dict]) -> List[dict]:
    """Flatten FastAPI/Pydantic ``exc.errors()`` into ``[{field, message}]``.

    Pydantic ``loc`` looks like ``("body", "billing_cycle")`` or
    ``("query", "page")``. We drop the leading source segment ("body"/"query"/
    "path"/"header") and join the rest with dots so nested fields read naturally
    (e.g. ``items.0.price``).
    """
    flattened: List[dict] = []
    for err in errors:
        loc = err.get("loc", ())
        parts = [str(p) for p in loc]
        if parts and parts[0] in ("body", "query", "path", "header", "cookie"):
            parts = parts[1:]
        field = ".".join(parts) if parts else "body"
        flattened.append({"field": field, "message": err.get("msg", "Invalid value")})
    return flattened
