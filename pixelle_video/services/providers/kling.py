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
    VideoGenerationError,
    VideoGenerationTimeout,
    MAX_RETRIES,
    POLL_INITIAL_INTERVAL,
    POLL_MAX_INTERVAL,
    POLL_TIMEOUT,
    RETRYABLE_STATUS_CODES,
)

_KLING_SUBMIT_PATH = "/kling/v1/videos/text2video"


class KlingProvider:
    """Kling video generation provider (async submit + poll)."""

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

        timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
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

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _request_with_retry(
        self,
        url: str,
        headers: dict,
        body: Optional[dict] = None,
        method: str = "POST",
        client: Optional[httpx.AsyncClient] = None,
    ) -> dict:
        """HTTP request with retry on 429/5xx."""
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
        last_exc: Optional[Exception] = None
        owns_client = client is None

        async def _do_request(c: httpx.AsyncClient) -> Optional[dict]:
            nonlocal last_exc
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    if method == "GET":
                        resp = await c.get(url, headers=headers)
                    else:
                        resp = await c.post(url, json=body, headers=headers)
                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                            wait = POLL_INITIAL_INTERVAL * attempt
                            logger.warning(
                                f"Retryable {e.response.status_code} on {url}, "
                                f"retry {attempt}/{_MAX_RETRIES} in {wait}s"
                            )
                            last_exc = e
                            await asyncio.sleep(wait)
                            continue
                        raise RuntimeError(
                            f"Kling API request failed: url={url}, status={e.response.status_code}"
                        ) from e
                    return resp.json()
                except httpx.HTTPError as e:
                    if attempt < MAX_RETRIES:
                        last_exc = e
                        await asyncio.sleep(POLL_INITIAL_INTERVAL * attempt)
                        continue
                    raise RuntimeError(f"Kling API connection failed: url={url} — {e}") from e
            return None

        if owns_client:
            async with httpx.AsyncClient(timeout=timeout) as c:
                result = await _do_request(c)
        else:
            result = await _do_request(client)

        if result is not None:
            return result
        raise RuntimeError(f"Kling API request failed after {MAX_RETRIES} retries: url={url}") from last_exc
