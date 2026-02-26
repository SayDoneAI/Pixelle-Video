"""
Shared exceptions and constants for API media providers.
"""

# Polling constants
POLL_INITIAL_INTERVAL = 2.0
POLL_MAX_INTERVAL = 30.0
POLL_TIMEOUT = 300.0
MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class VideoGenerationError(RuntimeError):
    """Raised when async video generation fails."""


class VideoGenerationTimeout(VideoGenerationError):
    """Raised when video polling exceeds the timeout."""
