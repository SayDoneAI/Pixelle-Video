"""
OpenAI-compatible provider — sync image generation via /v1/images/generations.

Video generation is not supported; raises NotImplementedError.
"""

from __future__ import annotations

from typing import Optional

import httpx
from loguru import logger

from pixelle_video.models.media import MediaResult


class OpenAIProvider:
    """OpenAI-compatible image generation provider."""

    def __init__(self, base_url: str, api_key: str, model: str, default_size: str = "1024x1024"):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._default_size = default_size

    async def generate_image(
        self,
        prompt: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> MediaResult:
        """Call /v1/images/generations and return MediaResult."""
        size = f"{width}x{height}" if width and height else self._default_size
        url = f"{self._base_url}/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "url",
        }

        logger.info(f"Calling image API: model={self._model}, size={size}")
        logger.debug(f"API URL: {url}")

        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=body, headers=headers)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    raise RuntimeError(
                        f"Image API request failed: model={self._model}, size={size}, "
                        f"status_code={e.response.status_code}"
                    ) from e
                data = response.json()
        except httpx.HTTPError as e:
            raise RuntimeError(
                f"Image API connection failed: url={url}, model={self._model} — {e}"
            ) from e

        items = data.get("data") if isinstance(data, dict) else None
        if not items or not isinstance(items, list) or not isinstance(items[0], dict):
            raise RuntimeError(
                f"Image API returned unexpected response format: model={self._model}, size={size}"
            )
        image_url = items[0].get("url")
        if not image_url:
            raise RuntimeError(
                f"Image API response missing 'url' field: model={self._model}, size={size}"
            )
        logger.info(f"Image generated: {image_url[:80]}...")
        return MediaResult(media_type="image", url=image_url)

    async def generate_video(self, prompt: str, **params) -> MediaResult:
        """Not supported by OpenAI provider."""
        raise NotImplementedError("OpenAI provider does not support video generation")
