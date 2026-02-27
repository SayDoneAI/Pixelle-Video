"""
Unit tests for config schema video_enabled field.

Verifies that video_enabled field has correct default value,
serializes/deserializes properly, and maintains backward compatibility.
"""

import pytest

from pixelle_video.config.schema import MediaApiConfig, MediaConfig, PixelleVideoConfig


class TestVideoEnabledField:
    """Verify video_enabled field behavior in MediaApiConfig."""

    def test_video_enabled_default_false(self):
        """Default value should be False for backward compatibility."""
        cfg = PixelleVideoConfig()
        assert cfg.media.api.video_enabled is False

    def test_video_enabled_explicit_true(self):
        """Should accept explicit True value."""
        cfg = PixelleVideoConfig(
            media=MediaConfig(
                mode="api",
                api=MediaApiConfig(video_enabled=True)
            )
        )
        assert cfg.media.api.video_enabled is True

    def test_video_enabled_explicit_false(self):
        """Should accept explicit False value."""
        cfg = PixelleVideoConfig(
            media=MediaConfig(
                mode="api",
                api=MediaApiConfig(video_enabled=False)
            )
        )
        assert cfg.media.api.video_enabled is False

    def test_video_enabled_serialization(self):
        """Should serialize video_enabled to dict."""
        cfg = PixelleVideoConfig(
            media=MediaConfig(
                mode="api",
                api=MediaApiConfig(video_enabled=True)
            )
        )
        d = cfg.to_dict()
        assert d["media"]["api"]["video_enabled"] is True

    def test_video_enabled_serialization_default(self):
        """Should serialize default False value."""
        cfg = PixelleVideoConfig()
        d = cfg.to_dict()
        assert d["media"]["api"]["video_enabled"] is False

    def test_video_enabled_deserialization(self):
        """Should deserialize video_enabled from dict."""
        d = {
            "media": {
                "mode": "api",
                "api": {
                    "video_enabled": True,
                    "base_url": "http://test.com",
                    "api_key": "key"
                }
            }
        }
        cfg = PixelleVideoConfig(**d)
        assert cfg.media.api.video_enabled is True

    def test_video_enabled_roundtrip(self):
        """Should preserve video_enabled through serialize/deserialize cycle."""
        cfg1 = PixelleVideoConfig(
            media=MediaConfig(
                mode="api",
                api=MediaApiConfig(
                    video_enabled=True,
                    base_url="http://example.com",
                    api_key="test-key"
                )
            )
        )
        d = cfg1.to_dict()
        cfg2 = PixelleVideoConfig(**d)
        assert cfg2.media.api.video_enabled is True
        assert cfg2.media.api.video_enabled == cfg1.media.api.video_enabled

    def test_video_enabled_with_full_config(self):
        """Should work alongside other video configuration fields."""
        cfg = PixelleVideoConfig(
            media=MediaConfig(
                mode="api",
                api=MediaApiConfig(
                    base_url="http://api.example.com",
                    api_key="key123",
                    image_model="dall-e-3",
                    video_enabled=True,
                    video_model="kling-v1",
                    video_provider="kling",
                    video_base_url="http://video.example.com",
                    video_api_key="video-key"
                )
            )
        )
        assert cfg.media.api.video_enabled is True
        assert cfg.media.api.video_model == "kling-v1"
        assert cfg.media.api.video_provider == "kling"
