"""
Tests for ApiMediaService with provider abstraction layer.

Unit tests (mocked): verify provider routing, config parsing, backward compat.
Integration tests (real API): verify end-to-end contract.

Requires env vars for integration tests:
  MEDIA_API_BASE_URL  - OpenAI-compatible base URL
  MEDIA_API_KEY       - API key
  MEDIA_IMAGE_MODEL   - Image model name (e.g. "dall-e-3")
  MEDIA_VIDEO_BASE_URL - Video API base URL (optional, falls back to MEDIA_API_BASE_URL)
  MEDIA_VIDEO_API_KEY  - Video API key (optional, falls back to MEDIA_API_KEY)
  MEDIA_VIDEO_MODEL    - Video model name (e.g. "kling-v2-5-turbo")
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from pixelle_video.config.schema import MediaApiConfig, MediaConfig, PixelleVideoConfig
from pixelle_video.models.media import MediaResult
from pixelle_video.services.api_media import (
    ApiMediaService,
    VideoGenerationError,
    VideoGenerationTimeout,
)
from pixelle_video.services.providers import PROVIDER_REGISTRY
from pixelle_video.services.providers.kling import KlingProvider
from pixelle_video.services.providers.openai import OpenAIProvider
from pixelle_video.services.providers.sucloud_video import SucloudVideoProvider

_needs_api = pytest.mark.skipif(
    not os.environ.get("MEDIA_API_BASE_URL"),
    reason="MEDIA_API_BASE_URL not set — skipping real API tests",
)

_needs_video_api = pytest.mark.skipif(
    not os.environ.get("MEDIA_VIDEO_MODEL"),
    reason="MEDIA_VIDEO_MODEL not set — skipping real video API tests",
)


def _make_config(**overrides) -> dict:
    """Build config dict from env vars."""
    api_kwargs = dict(
        base_url=os.environ.get("MEDIA_API_BASE_URL", ""),
        api_key=os.environ.get("MEDIA_API_KEY", ""),
        image_model=os.environ.get("MEDIA_IMAGE_MODEL", ""),
        video_base_url=os.environ.get("MEDIA_VIDEO_BASE_URL", ""),
        video_api_key=os.environ.get("MEDIA_VIDEO_API_KEY", ""),
        video_model=os.environ.get("MEDIA_VIDEO_MODEL", ""),
    )
    api_kwargs.update(overrides)
    return PixelleVideoConfig(
        media=MediaConfig(mode="api", api=MediaApiConfig(**api_kwargs)),
    ).to_dict()


def _make_service(**overrides) -> ApiMediaService:
    return ApiMediaService(_make_config(**overrides))


# ======================================================================
# Unit tests — provider routing and config
# ======================================================================


class TestProviderRegistry:
    """Verify provider registry contains expected providers."""

    def test_openai_registered(self):
        assert "openai" in PROVIDER_REGISTRY
        assert PROVIDER_REGISTRY["openai"] is OpenAIProvider

    def test_kling_registered(self):
        assert "kling" in PROVIDER_REGISTRY
        assert PROVIDER_REGISTRY["kling"] is KlingProvider

    def test_sucloud_video_registered(self):
        assert "sucloud_video" in PROVIDER_REGISTRY
        assert PROVIDER_REGISTRY["sucloud_video"] is SucloudVideoProvider


class TestApiMediaServiceInit:
    """Verify ApiMediaService initializes providers correctly."""

    def test_default_video_provider_is_sucloud(self):
        svc = _make_service(base_url="http://test.com", api_key="k")
        assert isinstance(svc._video_provider, SucloudVideoProvider)
        assert isinstance(svc._image_provider, OpenAIProvider)

    def test_explicit_kling_provider(self):
        svc = _make_service(
            base_url="http://test.com", api_key="k", video_provider="kling",
        )
        assert isinstance(svc._video_provider, KlingProvider)

    def test_explicit_sucloud_video_provider(self):
        svc = _make_service(
            base_url="http://test.com", api_key="k", video_provider="sucloud_video",
        )
        assert isinstance(svc._video_provider, SucloudVideoProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown video_provider"):
            _make_service(
                base_url="http://test.com", api_key="k", video_provider="nonexistent",
            )

    def test_list_workflows_empty(self):
        svc = _make_service(base_url="http://test.com", api_key="k")
        assert svc.list_workflows() == []

    def test_backward_compat_attributes(self):
        svc = _make_service(
            base_url="http://shared.com", api_key="shared_key",
            video_base_url="http://video.com", video_api_key="vk",
        )
        assert svc.base_url == "http://shared.com"
        assert svc.api_key == "shared_key"
        assert svc.video_base_url == "http://video.com"
        assert svc.video_api_key == "vk"

    def test_video_config_falls_back_to_base(self):
        svc = _make_service(base_url="http://shared.com", api_key="shared_key")
        assert svc.video_base_url == "http://shared.com"
        assert svc.video_api_key == "shared_key"


class TestApiMediaServiceRouting:
    """Verify __call__ routes to the correct provider."""

    @pytest.mark.asyncio
    async def test_image_routes_to_image_provider(self):
        svc = _make_service(base_url="http://test.com", api_key="k")
        mock_result = MediaResult(media_type="image", url="http://img.png")
        svc._image_provider = AsyncMock()
        svc._image_provider.generate_image = AsyncMock(return_value=mock_result)

        result = await svc(prompt="test", media_type="image", width=512, height=512)
        assert result.media_type == "image"
        svc._image_provider.generate_image.assert_awaited_once_with("test", 512, 512, None)

    @pytest.mark.asyncio
    async def test_video_routes_to_video_provider(self):
        svc = _make_service(base_url="http://test.com", api_key="k")
        mock_result = MediaResult(media_type="video", url="http://vid.mp4", duration=5.0)
        svc._video_provider = AsyncMock()
        svc._video_provider.generate_video = AsyncMock(return_value=mock_result)

        result = await svc(prompt="test", media_type="video", duration=5)
        assert result.media_type == "video"
        svc._video_provider.generate_video.assert_awaited_once_with("test", duration=5)

    @pytest.mark.asyncio
    async def test_unsupported_media_type_raises(self):
        svc = _make_service(base_url="http://test.com", api_key="k")
        with pytest.raises(ValueError, match="Unsupported media_type"):
            await svc(prompt="test", media_type="audio")


class TestOpenAIProviderUnit:
    """Unit tests for OpenAIProvider."""

    def test_video_not_supported(self):
        provider = OpenAIProvider("http://test.com", "k", "model")
        with pytest.raises(NotImplementedError):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                provider.generate_video("test")
            )


class TestKlingProviderUnit:
    """Unit tests for KlingProvider."""

    def test_image_not_supported(self):
        provider = KlingProvider("http://test.com", "k", "model")
        with pytest.raises(NotImplementedError):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                provider.generate_image("test")
            )


class TestSucloudVideoProviderUnit:
    """Unit tests for SucloudVideoProvider."""

    def test_image_not_supported(self):
        provider = SucloudVideoProvider("http://test.com", "k", "veo3.1-fast")
        with pytest.raises(NotImplementedError):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                provider.generate_image("test")
            )

    def test_init_stores_config(self):
        provider = SucloudVideoProvider("http://test.com/", "key", "veo3.1-fast")
        assert provider._base_url == "http://test.com"
        assert provider._api_key == "key"
        assert provider._model == "veo3.1-fast"


# ======================================================================
# Config schema tests
# ======================================================================


class TestConfigSchema:
    """Verify config schema supports provider fields."""

    def test_default_mode_is_comfyui(self):
        cfg = PixelleVideoConfig()
        assert cfg.media.mode == "comfyui"

    def test_video_fields_default_empty(self):
        cfg = PixelleVideoConfig()
        assert cfg.media.api.video_model == ""
        assert cfg.media.api.video_base_url == ""
        assert cfg.media.api.video_api_key == ""

    def test_video_provider_default_is_sucloud(self):
        cfg = PixelleVideoConfig()
        assert cfg.media.api.video_provider == "sucloud_video"

    def test_media_config_roundtrip(self):
        cfg = PixelleVideoConfig(
            media=MediaConfig(
                mode="api",
                api=MediaApiConfig(
                    base_url="http://example.com", api_key="k", image_model="m",
                    video_base_url="http://video.example.com", video_api_key="vk",
                    video_model="kling-v1", video_provider="kling",
                ),
            )
        )
        d = cfg.to_dict()
        assert d["media"]["mode"] == "api"
        assert d["media"]["api"]["base_url"] == "http://example.com"
        assert d["media"]["api"]["video_model"] == "kling-v1"
        assert d["media"]["api"]["video_provider"] == "kling"

        cfg2 = PixelleVideoConfig(**d)
        assert cfg2.media.api.video_model == "kling-v1"
        assert cfg2.media.api.video_provider == "kling"

    def test_media_config_sucloud_video_provider(self):
        cfg = PixelleVideoConfig(
            media=MediaConfig(
                mode="api",
                api=MediaApiConfig(
                    base_url="http://sucloud.vip", api_key="sk-test",
                    image_model="doubao-seedream-5-0-260128",
                    video_model="veo3.1-fast", video_provider="sucloud_video",
                ),
            )
        )
        d = cfg.to_dict()
        assert d["media"]["api"]["video_provider"] == "sucloud_video"
        assert d["media"]["api"]["video_model"] == "veo3.1-fast"

        cfg2 = PixelleVideoConfig(**d)
        assert cfg2.media.api.video_provider == "sucloud_video"


# ======================================================================
# Integration tests — real API (skipped without env vars)
# ======================================================================


@_needs_api
class TestApiMediaServiceImageContract:
    """Verify image generation returns MediaResult compatible with FrameProcessor."""

    @pytest.mark.asyncio
    async def test_returns_media_result_with_url(self):
        svc = _make_service()
        result = await svc(prompt="a simple red circle on white background", media_type="image")

        assert isinstance(result, MediaResult)
        assert result.media_type == "image"
        assert result.is_image is True
        assert result.is_video is False
        assert isinstance(result.url, str)
        assert result.url.startswith("http")

    @pytest.mark.asyncio
    async def test_custom_size_accepted(self):
        svc = _make_service()
        result = await svc(
            prompt="a simple blue square",
            media_type="image",
            width=512,
            height=512,
        )
        assert isinstance(result, MediaResult)
        assert result.url.startswith("http")


@_needs_api
@_needs_video_api
class TestApiMediaServiceVideoContract:
    """Verify video generation returns MediaResult via Kling provider."""

    @pytest.mark.asyncio
    async def test_returns_video_media_result(self):
        svc = _make_service()
        result = await svc(prompt="a cat walking slowly", media_type="video")

        assert isinstance(result, MediaResult)
        assert result.media_type == "video"
        assert result.is_video is True
        assert isinstance(result.url, str)
        assert result.url.startswith("http")
