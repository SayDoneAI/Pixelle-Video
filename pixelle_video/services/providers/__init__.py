"""
Media provider abstraction layer.

Defines the MediaProvider protocol and provider registry.
"""

from pixelle_video.services.providers.base import MediaProvider
from pixelle_video.services.providers.kling import KlingProvider
from pixelle_video.services.providers.openai import OpenAIProvider
from pixelle_video.services.providers.sucloud_video import SucloudVideoProvider

PROVIDER_REGISTRY: dict[str, type[MediaProvider]] = {
    "openai": OpenAIProvider,
    "kling": KlingProvider,
    "sucloud_video": SucloudVideoProvider,
}

__all__ = [
    "MediaProvider",
    "OpenAIProvider",
    "KlingProvider",
    "SucloudVideoProvider",
    "PROVIDER_REGISTRY",
]
