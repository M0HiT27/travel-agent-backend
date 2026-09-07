class AppError(Exception):
    """Base class for handled, user-facing application errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, status_code=404)


class ConflictError(AppError):
    def __init__(self, message: str = "Resource already exists") -> None:
        super().__init__(message, status_code=409)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(message, status_code=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Not authorized") -> None:
        super().__init__(message, status_code=403)


class UpstreamError(AppError):
    """A third-party service we depend on failed. Our fault only in the sense that we
    chose to depend on it, so 502 rather than 500."""

    def __init__(self, message: str = "Upstream service error") -> None:
        super().__init__(message, status_code=502)


class UpstreamTimeoutError(AppError):
    def __init__(self, message: str = "Upstream service timed out") -> None:
        super().__init__(message, status_code=504)
