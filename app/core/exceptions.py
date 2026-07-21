from fastapi import HTTPException, status


class AkunubaException(HTTPException):
    """Base API exception.

    Carries a stable, machine-readable ``code`` (surfaced as ``error.code`` in the
    response envelope) so the frontend can branch on specific cases without parsing
    the human-readable ``detail`` message.
    """

    def __init__(self, status_code: int, detail: str, code: str = "ERROR"):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


class NotFoundException(AkunubaException):
    def __init__(self, resource: str, identifier: str, code: str = "NOT_FOUND"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} with id {identifier} not found",
            code=code,
        )


class UnauthorizedException(AkunubaException):
    def __init__(self, detail: str = "Unauthorized", code: str = "UNAUTHORIZED"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            code=code,
        )


class ForbiddenException(AkunubaException):
    def __init__(self, detail: str = "Forbidden", code: str = "FORBIDDEN"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            code=code,
        )


class ValidationException(AkunubaException):
    def __init__(self, detail: str, code: str = "VALIDATION_ERROR"):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
            code=code,
        )


class ConflictException(AkunubaException):
    def __init__(self, detail: str, code: str = "CONFLICT"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            code=code,
        )


class GoneException(AkunubaException):
    """The resource existed but is permanently unavailable (e.g. an expired
    share link) — 410 so clients can distinguish it from a plain 404."""

    def __init__(self, detail: str, code: str = "GONE"):
        super().__init__(
            status_code=status.HTTP_410_GONE,
            detail=detail,
            code=code,
        )


class BadRequestException(AkunubaException):
    def __init__(self, detail: str, code: str = "BAD_REQUEST"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            code=code,
        )


class ServiceUnavailableException(AkunubaException):
    def __init__(
        self,
        detail: str = "Service temporarily unavailable",
        code: str = "SERVICE_UNAVAILABLE",
    ):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
            code=code,
        )
