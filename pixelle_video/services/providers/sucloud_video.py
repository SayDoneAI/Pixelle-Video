"""
Sucloud unified video provider — async task submission + polling.

Protocol ("视频统一格式"):
  Submit: POST {base_url}/v1/video/create
  Poll:   GET  {base_url}/v1/video/query?id={task_id}

Supports VEO, Sora, and other models exposed via sucloud's unified video API.
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

_CREATE_PATH = "/v1/video/create"
_QUERY_PATH = "/v1/video/query"

# Terminal statuses that indicate the task is done (success or failure)
_SUCCESS_STATUSES = frozenset({"completed", "succeed", "success"})
_FAILURE_STATUSES = frozenset({"failed", "error", "cancelled"})


class SucloudVideoProvider(RetryHttpMixin):
    """Sucloud unified video generation provider (async submit + poll)."""

    _provider_name = "Sucloud"

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
        """Sucloud video provider does not support image generation."""
        raise NotImplementedError("SucloudVideoProvider does not support image generation")

    async def generate_video(self, prompt: str, **params) -> MediaResult:
        """Submit video task and poll until completion."""
        task_id = await self._submit_task(prompt, **params)
        video_url = await self._poll_task(task_id)
        return MediaResult(media_type="video", url=video_url)

    # ------------------------------------------------------------------
    # Internal: submit + poll
    # ------------------------------------------------------------------

    async def _submit_task(self, prompt: str, **params) -> str:
        """POST /v1/video/create — returns task id."""
        url = f"{self._base_url}{_CREATE_PATH}"
        headers = self._headers()
        aspect_ratio = params.pop("aspect_ratio", "16:9")
        body = {
            "model": self._model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            **params,
        }

        logger.info(f"Submitting sucloud video task: model={self._model}")
        data = await self._request_with_retry(url, headers, body)

        task_id = data.get("id")
        if not task_id:
            raise VideoGenerationError(f"Sucloud response missing task id: {data}")

        status = data.get("status", "")
        if status in _FAILURE_STATUSES:
            raise VideoGenerationError(f"Sucloud task failed immediately: {data}")

        logger.info(f"Sucloud video task submitted: id={task_id}, status={status}")
        return task_id

    async def _poll_task(self, task_id: str) -> str:
        """GET /v1/video/query?id={task_id} with exponential backoff."""
        url = f"{self._base_url}{_QUERY_PATH}"
        headers = self._headers()
        deadline = time.monotonic() + POLL_TIMEOUT
        interval = POLL_INITIAL_INTERVAL

        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            while time.monotonic() < deadline:
                await asyncio.sleep(interval)
                data = await self._request_with_retry(
                    url, headers, method="GET", client=client,
                    query_params={"id": task_id},
                )

                status = data.get("status", "")
                logger.debug(f"Sucloud poll id={task_id}: status={status}")

                if status in _SUCCESS_STATUSES:
                    return self._extract_video_url(data, task_id)
                if status in _FAILURE_STATUSES:
                    raise VideoGenerationError(
                        f"Sucloud task {task_id} failed: status={status}, data={data}"
                    )

                interval = min(interval * 2, POLL_MAX_INTERVAL)

        raise VideoGenerationTimeout(f"Sucloud task {task_id} timed out after {POLL_TIMEOUT}s")

    def _extract_video_url(self, data: dict, task_id: str) -> str:
        """Extract video URL from poll response."""
        video_url = data.get("video_url")
        if not video_url:
            raise VideoGenerationError(
                f"Sucloud task {task_id} completed but missing video_url: {data}"
            )
        logger.info(f"Sucloud video generated: {video_url[:80]}...")
        return video_url

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers["Accept"] = "application/json"
        return headers
