"""
Shared exceptions, constants, and HTTP retry mixin for API media providers.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx
from loguru import logger

# Polling constants
POLL_INITIAL_INTERVAL = 2.0
POLL_MAX_INTERVAL = 30.0
POLL_TIMEOUT = 300.0
MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)


class VideoGenerationError(RuntimeError):
    """Raised when async video generation fails."""


class VideoGenerationTimeout(VideoGenerationError):
    """Raised when video polling exceeds the timeout."""


class RetryHttpMixin:
    """Shared HTTP request-with-retry logic for video providers."""

    _base_url: str
    _api_key: str
    _provider_name: str = "Provider"

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
        query_params: Optional[dict] = None,
    ) -> dict:
        """HTTP request with retry on 429/5xx."""
        last_exc: Optional[Exception] = None
        owns_client = client is None
        name = self._provider_name

        async def _do(c: httpx.AsyncClient) -> Optional[dict]:
            nonlocal last_exc
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    if method == "GET":
                        resp = await c.get(url, headers=headers, params=query_params)
                    else:
                        resp = await c.post(url, json=body, headers=headers)
                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                            wait = POLL_INITIAL_INTERVAL * attempt
                            logger.warning(
                                f"Retryable {e.response.status_code} on {url}, "
                                f"retry {attempt}/{MAX_RETRIES} in {wait}s"
                            )
                            last_exc = e
                            await asyncio.sleep(wait)
                            continue
                        raise RuntimeError(
                            f"{name} API request failed: url={url}, status={e.response.status_code}"
                        ) from e
                    return resp.json()
                except httpx.HTTPError as e:
                    if attempt < MAX_RETRIES:
                        last_exc = e
                        await asyncio.sleep(POLL_INITIAL_INTERVAL * attempt)
                        continue
                    raise RuntimeError(f"{name} API connection failed: url={url} — {e}") from e
            return None

        if owns_client:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
                result = await _do(c)
        else:
            result = await _do(client)

        if result is not None:
            return result
        raise RuntimeError(f"{name} API request failed after {MAX_RETRIES} retries: url={url}") from last_exc
