"""Custom exception classes for LostFilm client."""


class LostFilmError(Exception):
    """Base exception for all LostFilm-related errors."""

    pass


class AuthenticationError(LostFilmError):
    """Raised when authentication fails (HTTP 403)."""

    def __init__(
        self, message: str = "Authentication failed. Session tokens may have expired."
    ):
        self.message = message
        super().__init__(self.message)


class ServerError(LostFilmError):
    """Raised when the server returns an error (HTTP 503 or other server errors)."""

    def __init__(
        self,
        message: str = "Server error. The service may be temporarily unavailable. Please try again later.",
    ):
        self.message = message
        super().__init__(self.message)


class RateLimitError(LostFilmError):
    """Raised when requests are made too frequently."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please wait at least 15 minutes between requests.",
    ):
        self.message = message
        super().__init__(self.message)


class ParseError(LostFilmError):
    """Raised when RSS feed parsing fails."""

    def __init__(
        self, message: str = "Failed to parse RSS feed. The feed may be malformed."
    ):
        self.message = message
        super().__init__(self.message)
