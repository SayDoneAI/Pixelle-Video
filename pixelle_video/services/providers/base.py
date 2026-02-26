"""
MediaProvider protocol — contract for all media generation backends.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pixelle_video.models.media import MediaResult


@runtime_checkable
class MediaProvider(Protocol):
    """Protocol that every media provider must satisfy."""

    async def generate_image(
        self,
        prompt: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> MediaResult:
        """Generate an image and return a MediaResult with a URL."""
        ...

    async def generate_video(
        self,
        prompt: str,
        **params,
    ) -> MediaResult:
        """Generate a video and return a MediaResult with a URL."""
        ...
