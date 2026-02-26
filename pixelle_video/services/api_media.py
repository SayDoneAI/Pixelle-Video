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
API Media Service - image and async video generation

Image: OpenAI-compatible /v1/images/generations endpoint.
Video: Async task submission + exponential-backoff polling (Kling-compatible).
Returns URL-format MediaResult compatible with FrameProcessor._download_media.
"""

import asyncio
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from pixelle_video.models.media import MediaResult

# Polling constants
_POLL_INITIAL_INTERVAL = 2.0
_POLL_MAX_INTERVAL = 30.0
_POLL_TIMEOUT = 300.0
_MAX_RETRIES = 3
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class VideoGenerationError(RuntimeError):
    """Raised when async video generation fails."""


class VideoGenerationTimeout(VideoGenerationError):
    """Raised when video polling exceeds the timeout."""


class ApiMediaService:
    """
    API-based media generation service.

    Supports image (sync) and video (async polling) generation.
    Returns MediaResult with URL, compatible with FrameProcessor._download_media.
    """

    def __init__(self, config: dict):
        media_cfg = config.get("media", {})
        api_cfg = media_cfg.get("api", {})
        self.base_url = api_cfg.get("base_url", "")
        self.api_key = api_cfg.get("api_key", "")
        self.model = api_cfg.get("image_model", "")
        self.default_size = api_cfg.get("default_size", "1024x1024")
        self.video_base_url = api_cfg.get("video_base_url", "") or self.base_url
        self.video_api_key = api_cfg.get("video_api_key", "") or self.api_key
        self.video_model = api_cfg.get("video_model", "")

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
        """Generate media via API. Dispatches to image or video path."""
        if media_type == "video":
            return await self._generate_video(prompt, **params)
        if media_type != "image":
            raise ValueError(f"Unsupported media_type={media_type!r}")

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

    # ------------------------------------------------------------------
    # Video: async task submission + exponential-backoff polling
    # ------------------------------------------------------------------

    async def _generate_video(self, prompt: str, **params) -> MediaResult:
        """Submit video task and poll until completion."""
        task_id = await self._submit_video_task(prompt, **params)
        video_url, duration = await self._poll_video_task(task_id)
        return MediaResult(media_type="video", url=video_url, duration=duration)

    async def _submit_video_task(self, prompt: str, **params) -> str:
        """Submit async video generation task. Returns task_id."""
        url = self.video_base_url.rstrip("/") + "/v1/videos/generations"
        headers = {
            "Authorization": f"Bearer {self.video_api_key}",
            "Content-Type": "application/json",
        }
        body = {"model": self.video_model, "prompt": prompt, **params}

        logger.info(f"Submitting video task: model={self.video_model}")
        data = await self._request_with_retry(url, headers, body)

        task_id = data.get("task_id") or data.get("id") or (data.get("data", {}) or {}).get("task_id")
        if not task_id:
            raise VideoGenerationError(
                f"Video API did not return task_id: model={self.video_model}, response keys={list(data.keys())}"
            )
        logger.info(f"Video task submitted: task_id={task_id}")
        return task_id

    async def _poll_video_task(self, task_id: str) -> tuple[str, Optional[float]]:
        """Poll video task status with exponential backoff. Returns (video_url, duration)."""
        url = self.video_base_url.rstrip("/") + f"/v1/videos/generations/{task_id}"
        headers = {
            "Authorization": f"Bearer {self.video_api_key}",
            "Content-Type": "application/json",
        }

        elapsed = 0.0
        interval = _POLL_INITIAL_INTERVAL

        while elapsed < _POLL_TIMEOUT:
            await asyncio.sleep(interval)
            elapsed += interval

            data = await self._request_with_retry(url, headers, method="GET")
            status = data.get("status") or (data.get("data", {}) or {}).get("status") or ""
            status = status.lower()

            logger.debug(f"Poll task_id={task_id}: status={status}, elapsed={elapsed:.1f}s")

            if status in ("succeeded", "completed", "success", "complete"):
                return self._extract_video_url(data)
            if status in ("failed", "error", "cancelled"):
                msg = data.get("error") or data.get("message") or str(data)
                raise VideoGenerationError(f"Video task {task_id} failed: {msg}")

            interval = min(interval * 2, _POLL_MAX_INTERVAL)

        raise VideoGenerationTimeout(
            f"Video task {task_id} timed out after {_POLL_TIMEOUT}s"
        )

    def _extract_video_url(self, data: dict) -> tuple[str, Optional[float]]:
        """Extract video URL and optional duration from poll response."""
        # Try common response shapes
        video_url = None
        duration = None
        for container in (data, data.get("data", {}), data.get("output", {})):
            if not isinstance(container, dict):
                continue
            video_url = video_url or container.get("video_url") or container.get("url")
            results = container.get("results") or container.get("videos")
            if isinstance(results, list) and results:
                first = results[0] if isinstance(results[0], dict) else {}
                video_url = video_url or first.get("url") or first.get("video_url")
                duration = duration or first.get("duration")
            duration = duration or container.get("duration")
        if not video_url:
            raise VideoGenerationError(
                f"Video API response missing video URL: keys={list(data.keys())}"
            )
        logger.info(f"Video generated: {video_url[:80]}...")
        return video_url, duration

    async def _request_with_retry(
        self, url: str, headers: dict, body: Optional[dict] = None, method: str = "POST",
    ) -> dict:
        """HTTP request with retry on 429/5xx (max 3 attempts)."""
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
        last_exc: Optional[Exception] = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if method == "GET":
                        resp = await client.get(url, headers=headers)
                    else:
                        resp = await client.post(url, json=body, headers=headers)
                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                            wait = _POLL_INITIAL_INTERVAL * attempt
                            logger.warning(f"Retryable {e.response.status_code} on {url}, retry {attempt}/{_MAX_RETRIES} in {wait}s")
                            last_exc = e
                            await asyncio.sleep(wait)
                            continue
                        raise RuntimeError(
                            f"API request failed: url={url}, status={e.response.status_code}"
                        ) from e
                    return resp.json()
            except httpx.HTTPError as e:
                if attempt < _MAX_RETRIES:
                    last_exc = e
                    await asyncio.sleep(_POLL_INITIAL_INTERVAL * attempt)
                    continue
                raise RuntimeError(f"API connection failed: url={url} — {e}") from e

        raise RuntimeError(f"API request failed after {_MAX_RETRIES} retries: url={url}") from last_exc
