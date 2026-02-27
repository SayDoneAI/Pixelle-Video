# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
API Media Service — provider-based media generation.

Routes image/video requests to the appropriate provider backend.
Returns URL-format MediaResult compatible with FrameProcessor._download_media.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from pixelle_video.models.media import MediaResult
from pixelle_video.services.providers import PROVIDER_REGISTRY
from pixelle_video.services.providers.base import MediaProvider
from pixelle_video.services.providers.errors import (  # noqa: F401 — re-export for backward compat
    VideoGenerationError,
    VideoGenerationTimeout,
)
from pixelle_video.services.providers.openai import OpenAIProvider


class ApiMediaService:
    """
    API-based media generation service.

    Routes requests to provider backends (OpenAI for images, Kling for video, etc.).
    Returns MediaResult with URL, compatible with FrameProcessor._download_media.
    """

    def __init__(self, config: dict):
        media_cfg = config.get("media", {})
        api_cfg = media_cfg.get("api", {})

        base_url = api_cfg.get("base_url", "")
        api_key = api_cfg.get("api_key", "")

        # Image provider — always OpenAI-compatible
        self._image_provider: MediaProvider = OpenAIProvider(
            base_url=base_url,
            api_key=api_key,
            model=api_cfg.get("image_model", ""),
            default_size=api_cfg.get("default_size", "1024x1024"),
        )

        # Video provider — resolved from config
        video_provider_name = api_cfg.get("video_provider", "kling")
        video_base_url = api_cfg.get("video_base_url", "") or base_url
        video_api_key = api_cfg.get("video_api_key", "") or api_key
        video_model = api_cfg.get("video_model", "")

        provider_cls = PROVIDER_REGISTRY.get(video_provider_name)
        if provider_cls is None:
            raise ValueError(
                f"Unknown video_provider={video_provider_name!r}. "
                f"Available: {list(PROVIDER_REGISTRY.keys())}"
            )
        self._video_provider: MediaProvider = provider_cls(
            base_url=video_base_url,
            api_key=video_api_key,
            model=video_model,
        )

        # Backward-compat attributes (used by tests)
        self.base_url = base_url
        self.api_key = api_key
        self.model = api_cfg.get("image_model", "")
        self.default_size = api_cfg.get("default_size", "1024x1024")
        self.video_base_url = video_base_url
        self.video_api_key = video_api_key
        self.video_model = video_model

        logger.info(
            f"ApiMediaService initialized: image=openai, video={video_provider_name}"
        )

    def list_workflows(self) -> List[Dict[str, Any]]:
        """Return empty list — API mode has no ComfyUI workflows."""
        return []

    async def __call__(
        self,
        prompt: str,
        media_type: str = "image",
        width: Optional[int] = None,
        height: Optional[int] = None,
        image_model: Optional[str] = None,
        reference_image: Optional[str] = None,
        **params,
    ) -> MediaResult:
        """Generate media via API. Dispatches to the appropriate provider.

        Args:
            prompt: Text prompt for generation
            media_type: "image" or "video"
            width: Image width (optional)
            height: Image height (optional)
            image_model: Override image model (optional, for per-request model selection)
            reference_image: Reference image URL or base64 for style/character consistency
            **params: Additional provider-specific parameters
        """
        if media_type == "video":
            return await self._video_provider.generate_video(prompt, **params)
        if media_type != "image":
            raise ValueError(f"Unsupported media_type={media_type!r}")

        # If image_model is provided, temporarily override the provider's model
        if image_model:
            original_model = self._image_provider._model
            self._image_provider._model = image_model
            logger.debug(f"Overriding image model: {original_model} -> {image_model}")
            try:
                return await self._image_provider.generate_image(prompt, width, height, reference_image)
            finally:
                self._image_provider._model = original_model
        else:
            return await self._image_provider.generate_image(prompt, width, height, reference_image)
