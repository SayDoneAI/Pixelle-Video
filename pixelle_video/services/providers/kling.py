"""
Kling video provider — async task submission + exponential-backoff polling.

Endpoint: /kling/v1/videos/text2video
Supports both image (delegated) and video generation.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx
from loguru import logger

from pixelle_video.models.media import MediaResult
from pixelle_video.services.providers.errors import (
    POLL_INITIAL_INTERVAL,
    POLL_MAX_INTERVAL,
    POLL_TIMEOUT,
    RetryHttpMixin,
    VideoGenerationError,
    VideoGenerationTimeout,
    _DEFAULT_TIMEOUT,
)

_KLING_SUBMIT_PATH = "/kling/v1/videos/text2video"


class KlingProvider(RetryHttpMixin):
    """Kling video generation provider (async submit + poll)."""

    _provider_name = "Kling"

    def __init__(self, base_url: str, api_key: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    async def generate_image(
        self,
        prompt: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> MediaResult:
        """Kling provider does not support image generation."""
        raise NotImplementedError("Kling provider does not support image generation")

    async def generate_video(self, prompt: str, **params) -> MediaResult:
        """Submit video task and poll until completion."""
        task_id = await self._submit_task(prompt, **params)
        video_url, duration = await self._poll_task(task_id)
        return MediaResult(media_type="video", url=video_url, duration=duration)

    # ------------------------------------------------------------------
    # Internal: submit + poll
    # ------------------------------------------------------------------

    async def _submit_task(self, prompt: str, **params) -> str:
        """POST /kling/v1/videos/text2video — returns task_id."""
        url = f"{self._base_url}{_KLING_SUBMIT_PATH}"
        headers = self._headers()
        duration = params.pop("duration", 5)
        body = {"model_name": self._model, "prompt": prompt, "duration": duration, **params}

        logger.info(f"Submitting Kling video task: model={self._model}")
        data = await self._request_with_retry(url, headers, body)

        # Kling response: {code: 0, data: {task_id: "..."}}
        code = data.get("code")
        if code != 0:
            msg = data.get("message", str(data))
            raise VideoGenerationError(f"Kling submit failed: code={code}, message={msg}")

        task_id = (data.get("data") or {}).get("task_id")
        if not task_id:
            raise VideoGenerationError(f"Kling response missing task_id: {data}")
        logger.info(f"Kling task submitted: task_id={task_id}")
        return task_id

    async def _poll_task(self, task_id: str) -> tuple[str, Optional[float]]:
        """GET /kling/v1/videos/text2video/{task_id} with exponential backoff."""
        url = f"{self._base_url}{_KLING_SUBMIT_PATH}/{task_id}"
        headers = self._headers()
        deadline = time.monotonic() + POLL_TIMEOUT
        interval = POLL_INITIAL_INTERVAL

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            while time.monotonic() < deadline:
                await asyncio.sleep(interval)
                data = await self._request_with_retry(
                    url, headers, method="GET", client=client,
                )

                status = (data.get("data") or {}).get("task_status", "")
                logger.debug(f"Kling poll task_id={task_id}: status={status}")

                if status == "succeed":
                    return self._extract_video_url(data)
                if status == "failed":
                    msg = (data.get("data") or {}).get("task_status_msg") or data.get("message") or str(data)
                    raise VideoGenerationError(f"Kling task {task_id} failed: {msg}")

                interval = min(interval * 2, POLL_MAX_INTERVAL)

        raise VideoGenerationTimeout(f"Kling task {task_id} timed out after {POLL_TIMEOUT}s")

    def _extract_video_url(self, data: dict) -> tuple[str, Optional[float]]:
        """Extract video URL and duration from Kling poll response.

        Expected shape: {data: {task_result: {videos: [{url, duration}]}}}
        """
        task_result = (data.get("data") or {}).get("task_result") or {}
        videos = task_result.get("videos") or []
        if not videos or not isinstance(videos[0], dict):
            raise VideoGenerationError(
                f"Kling response missing video result: keys={list(data.keys())}"
            )
        first = videos[0]
        video_url = first.get("url")
        if not video_url:
            raise VideoGenerationError("Kling video result missing 'url'")
        duration = first.get("duration")
        logger.info(f"Kling video generated: {video_url[:80]}...")
        return video_url, duration

