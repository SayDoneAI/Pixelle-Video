"""
Tests for F007 character feature — core logic only, no mocks.

Covers:
- build_image_prompt_prompt: curly braces in character_description don't crash .format()
- character_description / reference_image: API param overrides config fallback
- config manager: file path → base64 data URL conversion
"""

import base64
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from pixelle_video.config.schema import (
    CharacterConfig,
    MediaApiConfig,
    MediaConfig,
    PixelleVideoConfig,
)
from pixelle_video.prompts.image_generation import build_image_prompt_prompt


@contextmanager
def _patch_config_manager(mock_cm):
    """Patch config_manager singleton so _resolve_* reads our test config."""
    with patch("pixelle_video.config.config_manager", mock_cm):
        yield


# ======================================================================
# 1. build_image_prompt_prompt — curly braces safety
# ======================================================================


class TestBuildImagePromptCurlyBraces:
    """character_description containing { or } must not break .format()."""

    def test_curly_braces_in_description_no_error(self):
        desc = "a character wearing {armor} with {shield}"
        result = build_image_prompt_prompt(
            narrations=["Hello world"],
            min_words=10,
            max_words=50,
            character_description=desc,
        )
        assert "{armor}" in result
        assert "{shield}" in result

    def test_without_character_description(self):
        result = build_image_prompt_prompt(
            narrations=["Test narration"],
            min_words=10,
            max_words=50,
        )
        assert "Character Consistency" not in result

    def test_with_normal_character_description(self):
        result = build_image_prompt_prompt(
            narrations=["Scene one"],
            min_words=10,
            max_words=50,
            character_description="a cute yellow flame character named Xingbao",
        )
        assert "Character Consistency Requirement" in result
        assert "Xingbao" in result


# ======================================================================
# 2. Resolve logic — API param overrides config fallback
# ======================================================================


def _make_config_with_character(
    description: str = "",
    reference_image: str = "",
) -> PixelleVideoConfig:
    """Build a PixelleVideoConfig with character settings."""
    return PixelleVideoConfig(
        media=MediaConfig(
            mode="api",
            api=MediaApiConfig(
                character=CharacterConfig(
                    description=description,
                    reference_image=reference_image,
                ),
            ),
        ),
    )


def _make_pipeline_and_ctx(params: dict, config: PixelleVideoConfig):
    """Create a StandardPipeline + PipelineContext for testing resolve methods.

    Uses unittest.mock.patch to inject the given config into config_manager
    so that _resolve_* reads from it instead of the real singleton.
    """
    from unittest.mock import patch, MagicMock
    from pixelle_video.pipelines.standard import StandardPipeline
    from pixelle_video.pipelines.linear import PipelineContext

    pipeline = StandardPipeline.__new__(StandardPipeline)
    ctx = PipelineContext(input_text="", params=params)

    # Patch config_manager inside the standard module so _resolve_* reads our config
    mock_cm = MagicMock()
    mock_cm.config = config
    return pipeline, ctx, mock_cm


class TestResolveCharacterDescription:
    """API param takes priority over config fallback."""

    def test_param_present_overrides_config(self):
        config = _make_config_with_character(description="config-char")
        pipeline, ctx, mock_cm = _make_pipeline_and_ctx(
            {"character_description": "api-char"}, config
        )
        with _patch_config_manager(mock_cm):
            result = pipeline._resolve_character_description(ctx)
        assert result == "api-char"

    def test_param_empty_string_disables(self):
        """Empty string in params means explicitly disabled → None."""
        config = _make_config_with_character(description="config-char")
        pipeline, ctx, mock_cm = _make_pipeline_and_ctx(
            {"character_description": ""}, config
        )
        with _patch_config_manager(mock_cm):
            result = pipeline._resolve_character_description(ctx)
        assert result is None

    def test_param_absent_falls_back_to_config(self):
        config = _make_config_with_character(description="config-char")
        pipeline, ctx, mock_cm = _make_pipeline_and_ctx({}, config)
        with _patch_config_manager(mock_cm):
            result = pipeline._resolve_character_description(ctx)
        assert result == "config-char"

    def test_param_absent_config_empty_returns_none(self):
        config = _make_config_with_character(description="")
        pipeline, ctx, mock_cm = _make_pipeline_and_ctx({}, config)
        with _patch_config_manager(mock_cm):
            result = pipeline._resolve_character_description(ctx)
        assert result is None


class TestResolveReferenceImage:
    """API param takes priority over config fallback."""

    def test_param_present_overrides_config(self):
        config = _make_config_with_character(reference_image="data:image/png;base64,config")
        pipeline, ctx, mock_cm = _make_pipeline_and_ctx(
            {"reference_image": "data:image/png;base64,api"}, config
        )
        with _patch_config_manager(mock_cm):
            result = pipeline._resolve_reference_image(ctx)
        assert result == "data:image/png;base64,api"

    def test_param_empty_string_disables(self):
        """Empty string in params means explicitly disabled → None."""
        config = _make_config_with_character(reference_image="https://example.com/char.png")
        pipeline, ctx, mock_cm = _make_pipeline_and_ctx(
            {"reference_image": ""}, config
        )
        with _patch_config_manager(mock_cm):
            result = pipeline._resolve_reference_image(ctx)
        assert result is None

    def test_param_absent_falls_back_to_config(self):
        config = _make_config_with_character(reference_image="https://example.com/char.png")
        pipeline, ctx, mock_cm = _make_pipeline_and_ctx({}, config)
        with _patch_config_manager(mock_cm):
            result = pipeline._resolve_reference_image(ctx)
        assert result == "https://example.com/char.png"

    def test_param_absent_config_empty_returns_none(self):
        config = _make_config_with_character(reference_image="")
        pipeline, ctx, mock_cm = _make_pipeline_and_ctx({}, config)
        with _patch_config_manager(mock_cm):
            result = pipeline._resolve_reference_image(ctx)
        assert result is None


# ======================================================================
# 3. Config manager — file path → base64 data URL
# ======================================================================


class TestResolveCharacterReferenceImage:
    """ConfigManager._resolve_character_reference_image converts file paths to data URLs."""

    def test_file_path_converted_to_data_url(self, tmp_path: Path):
        # Create a real tiny file to act as an image
        img_file = tmp_path / "char.png"
        img_bytes = b"\x89PNG\r\n\x1a\nfake-png-data"
        img_file.write_bytes(img_bytes)

        config = _make_config_with_character(reference_image=str(img_file))

        from pixelle_video.config.manager import ConfigManager
        manager = ConfigManager.__new__(ConfigManager)
        manager.config_path = tmp_path / "config.yaml"
        manager._resolve_character_reference_image(config)

        result = config.media.api.character.reference_image
        assert result.startswith("data:image/png;base64,")
        # Verify round-trip
        b64_part = result.split(",", 1)[1]
        assert base64.b64decode(b64_part) == img_bytes

    def test_relative_path_resolved_against_config_dir(self, tmp_path: Path):
        img_file = tmp_path / "assets" / "char.jpg"
        img_file.parent.mkdir()
        img_bytes = b"\xff\xd8\xff\xe0fake-jpg"
        img_file.write_bytes(img_bytes)

        config = _make_config_with_character(reference_image="assets/char.jpg")

        from pixelle_video.config.manager import ConfigManager
        manager = ConfigManager.__new__(ConfigManager)
        manager.config_path = tmp_path / "config.yaml"
        manager._resolve_character_reference_image(config)

        result = config.media.api.character.reference_image
        assert result.startswith("data:image/jpeg;base64,")

    def test_http_url_kept_as_is(self):
        config = _make_config_with_character(reference_image="https://example.com/char.png")

        from pixelle_video.config.manager import ConfigManager
        manager = ConfigManager.__new__(ConfigManager)
        manager.config_path = Path("/tmp/config.yaml")
        manager._resolve_character_reference_image(config)

        assert config.media.api.character.reference_image == "https://example.com/char.png"

    def test_data_url_kept_as_is(self):
        data_url = "data:image/png;base64,iVBORw0KGgo="
        config = _make_config_with_character(reference_image=data_url)

        from pixelle_video.config.manager import ConfigManager
        manager = ConfigManager.__new__(ConfigManager)
        manager.config_path = Path("/tmp/config.yaml")
        manager._resolve_character_reference_image(config)

        assert config.media.api.character.reference_image == data_url

    def test_missing_file_disables_reference_image(self, tmp_path: Path):
        config = _make_config_with_character(reference_image="/nonexistent/char.png")

        from pixelle_video.config.manager import ConfigManager
        manager = ConfigManager.__new__(ConfigManager)
        manager.config_path = tmp_path / "config.yaml"
        manager._resolve_character_reference_image(config)

        # File not found — reference_image disabled (set to empty string)
        assert config.media.api.character.reference_image == ""
