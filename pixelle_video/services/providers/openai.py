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
        reference_image: Optional[str] = None,
    ) -> MediaResult:
        """Call /v1/images/generations and return MediaResult.

        Args:
            prompt: Text prompt for image generation
            width: Image width
            height: Image height
            reference_image: URL or base64 of reference image for style/character consistency
        """
        import asyncio

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

        # Add reference image if provided
        if reference_image:
            body["image"] = reference_image
            if reference_image.startswith('http'):
                logger.info(f"Using reference image URL: {reference_image[:80]}...")
            else:
                # Log base64 format details
                logger.info(f"Using reference image: base64 data (length: {len(reference_image)} chars)")
                logger.debug(f"Base64 prefix: {reference_image[:100]}...")
                if not reference_image.startswith('data:image/'):
                    logger.warning(f"⚠️  Reference image may not have correct format. Expected 'data:image/...;base64,...', got: {reference_image[:50]}...")

        logger.info(f"Calling image API: model={self._model}, size={size}")
        logger.debug(f"API URL: {url}")

        timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

        # Retry logic for rate limiting
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                    response = await client.post(url, json=body, headers=headers)
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 429 and attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 5  # 5s, 10s, 15s
                            logger.warning(f"Rate limited (429), retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                            await asyncio.sleep(wait_time)
                            continue
                        raise RuntimeError(
                            f"Image API request failed: model={self._model}, size={size}, "
                            f"status_code={e.response.status_code}"
                        ) from e
                    data = response.json()
                    break  # Success, exit retry loop
            except httpx.HTTPError as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    logger.warning(f"Connection error, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
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
