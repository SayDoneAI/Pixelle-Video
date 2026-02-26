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
API Media Service - OpenAI-compatible image generation

Calls /v1/images/generations endpoint directly, no ComfyUI needed.
Returns URL-format MediaResult compatible with FrameProcessor._download_media.
"""

from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from pixelle_video.models.media import MediaResult


class ApiMediaService:
    """
    API-based media generation service.

    Uses OpenAI-compatible /v1/images/generations endpoint.
    Returns MediaResult with URL, compatible with FrameProcessor._download_media.
    """

    def __init__(self, config: dict):
        media_cfg = config.get("media", {})
        api_cfg = media_cfg.get("api", {})
        self.base_url = api_cfg.get("base_url", "")
        self.api_key = api_cfg.get("api_key", "")
        self.model = api_cfg.get("image_model", "")
        self.default_size = api_cfg.get("default_size", "1024x1024")

    def list_workflows(self) -> List[Dict[str, Any]]:
        """Return empty list — API mode has no ComfyUI workflows."""
        return []

    async def __call__(
        self,
        prompt: str,
        media_type: str = "image",
        width: Optional[int] = None,
        height: Optional[int] = None,
        **params,
    ) -> MediaResult:
        """
        Generate image via OpenAI-compatible API.

        Args:
            prompt: Image generation prompt
            media_type: Must be "image" for now (F001 scope)
            width: Image width (used to build size string)
            height: Image height (used to build size string)
            **params: Ignored (keeps interface compatible with MediaService)

        Returns:
            MediaResult with media_type="image" and url pointing to generated image
        """
        if media_type != "image":
            raise ValueError(
                f"ApiMediaService only supports image generation (got media_type={media_type!r}). "
                "Video generation via API is planned for F002."
            )

        size = f"{width}x{height}" if width and height else self.default_size

        url = self.base_url.rstrip("/") + "/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "url",
        }

        logger.info(f"Calling image API: model={self.model}, size={size}")
        logger.debug(f"API URL: {url}")

        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=body, headers=headers)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    raise RuntimeError(
                        f"Image API request failed: model={self.model}, size={size}, "
                        f"status_code={e.response.status_code}"
                    ) from e
                data = response.json()
        except httpx.HTTPError as e:
            raise RuntimeError(
                f"Image API connection failed: url={url}, model={self.model} — {e}"
            ) from e

        items = data.get("data") if isinstance(data, dict) else None
        if not items or not isinstance(items, list) or not isinstance(items[0], dict):
            raise RuntimeError(
                f"Image API returned unexpected response format: model={self.model}, size={size}"
            )
        image_url = items[0].get("url")
        if not image_url:
            raise RuntimeError(
                f"Image API response missing 'url' field: model={self.model}, size={size}"
            )
        logger.info(f"Image generated: {image_url[:80]}...")

        return MediaResult(media_type="image", url=image_url)
