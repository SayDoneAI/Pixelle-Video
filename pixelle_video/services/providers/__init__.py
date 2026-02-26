"""
Media provider abstraction layer.

Defines the MediaProvider protocol and provider registry.
"""

from pixelle_video.services.providers.base import MediaProvider
from pixelle_video.services.providers.openai import OpenAIProvider
from pixelle_video.services.providers.kling import KlingProvider

PROVIDER_REGISTRY: dict[str, type[MediaProvider]] = {
    "openai": OpenAIProvider,
    "kling": KlingProvider,
}

__all__ = [
    "MediaProvider",
    "OpenAIProvider",
    "KlingProvider",
    "PROVIDER_REGISTRY",
]
