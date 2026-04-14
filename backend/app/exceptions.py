"""Domain exceptions used across services. Mapped to HTTP responses by the API layer."""


class FastRecceError(Exception):
    """Base exception for all domain errors."""


class NotFoundError(FastRecceError):
    """Entity not found. Maps to HTTP 404."""


class ConflictError(FastRecceError):
    """Duplicate resource or invalid state transition. Maps to HTTP 409."""


class ValidationError(FastRecceError):
    """Business rule violation. Maps to HTTP 422."""


class UnauthorizedError(FastRecceError):
    """Authentication failed. Maps to HTTP 401."""


class ForbiddenError(FastRecceError):
    """Authenticated but insufficient permissions. Maps to HTTP 403."""


class ExternalServiceError(FastRecceError):
    """External service (Google, LLM, S3) failure. Maps to HTTP 502."""


class RateLimitError(FastRecceError):
    """Rate limit exceeded. Maps to HTTP 429."""
