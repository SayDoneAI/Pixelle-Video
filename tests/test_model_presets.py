"""
Unit tests for model_presets — pure logic, no Streamlit dependency.

Covers: image model list, video model list, provider linkage,
        default resolution, and resolve_selection helper.
"""

import pytest

from web.components.model_presets import (
    CUSTOM_OPTION,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_VIDEO_MODELS,
    DEFAULT_VIDEO_PROVIDER,
    IMAGE_MODEL_PRESETS,
    VIDEO_MODEL_PRESETS,
    VIDEO_PROVIDER_PRESETS,
    ModelOption,
    format_model_label,
    get_default_video_model,
    get_image_model_ids,
    get_video_models_for_provider,
    get_video_provider_ids,
    resolve_selection,
)


class TestImageModelPresets:
    def test_has_entries(self):
        assert len(IMAGE_MODEL_PRESETS) >= 10

    def test_default_model_in_presets(self):
        ids = get_image_model_ids()
        assert DEFAULT_IMAGE_MODEL in ids

    def test_get_image_model_ids_returns_strings(self):
        ids = get_image_model_ids()
        assert all(isinstance(i, str) for i in ids)

    def test_dall_e_3_is_first(self):
        ids = get_image_model_ids()
        assert ids[0] == "dall-e-3"

    def test_includes_doubao_models(self):
        ids = get_image_model_ids()
        assert "doubao-seedream-5-0-260128" in ids
        assert "doubao-seedream-4-5-251128" in ids
        assert "doubao-seedream-4-0-250828" in ids

    def test_includes_flux_models(self):
        ids = get_image_model_ids()
        assert "flux-schnell" in ids
        assert "flux-dev" in ids
        assert "flux-pro" in ids

    def test_includes_gemini_models(self):
        ids = get_image_model_ids()
        assert "gemini-3.1-flash-image-preview" in ids
        assert "gemini-2.5-flash-image" in ids
        assert "gemini-3-pro-image-preview" in ids


class TestVideoProviderPresets:
    def test_has_entries(self):
        assert len(VIDEO_PROVIDER_PRESETS) >= 2

    def test_default_provider_in_presets(self):
        ids = get_video_provider_ids()
        assert DEFAULT_VIDEO_PROVIDER in ids

    def test_sucloud_is_first(self):
        ids = get_video_provider_ids()
        assert ids[0] == "sucloud_video"


class TestVideoModelLinkage:
    """Verify video models are correctly linked to providers."""

    def test_sucloud_provider_has_models(self):
        models = get_video_models_for_provider("sucloud_video")
        assert len(models) >= 10
        assert "veo3.1-fast" in models

    def test_kling_provider_has_models(self):
        models = get_video_models_for_provider("kling")
        assert len(models) >= 5
        assert "kling-video" in models

    def test_unknown_provider_returns_empty(self):
        models = get_video_models_for_provider("nonexistent_provider")
        assert models == []

    def test_default_video_model_sucloud(self):
        assert get_default_video_model("sucloud_video") == "veo3.1-fast"

    def test_default_video_model_kling(self):
        assert get_default_video_model("kling") == "kling-video"

    def test_default_video_model_unknown(self):
        assert get_default_video_model("unknown") == ""

    def test_switching_provider_changes_model_list(self):
        sucloud_models = get_video_models_for_provider("sucloud_video")
        kling_models = get_video_models_for_provider("kling")
        # The two lists should differ in at least one model
        assert set(sucloud_models) != set(kling_models)


class TestResolveSelection:
    """Verify the selectbox + custom input resolution logic."""

    def test_preset_selected(self):
        result = resolve_selection("dall-e-3", "")
        assert result == "dall-e-3"

    def test_custom_selected_with_value(self):
        result = resolve_selection(CUSTOM_OPTION, "my-custom-model")
        assert result == "my-custom-model"

    def test_custom_selected_strips_whitespace(self):
        result = resolve_selection(CUSTOM_OPTION, "  my-model  ")
        assert result == "my-model"

    def test_custom_selected_empty_value(self):
        result = resolve_selection(CUSTOM_OPTION, "")
        assert result == ""

    def test_custom_selected_whitespace_only(self):
        result = resolve_selection(CUSTOM_OPTION, "   ")
        assert result == ""


class TestConsistency:
    """Cross-check constants are consistent."""

    def test_all_providers_have_model_list(self):
        for prov in get_video_provider_ids():
            assert prov in VIDEO_MODEL_PRESETS, f"Provider {prov} missing from VIDEO_MODEL_PRESETS"

    def test_all_providers_have_default_model(self):
        for prov in get_video_provider_ids():
            default = get_default_video_model(prov)
            assert default, f"Provider {prov} has no default video model"
            models = get_video_models_for_provider(prov)
            assert default in models, f"Default model {default} not in {prov}'s model list"


class TestModelPrice:
    """Verify price field is populated on all preset models."""

    def test_image_models_have_price(self):
        for m in IMAGE_MODEL_PRESETS:
            assert m.price, f"Image model {m.id} missing price"

    def test_video_models_have_price(self):
        for provider, models in VIDEO_MODEL_PRESETS.items():
            for m in models:
                assert m.price, f"Video model {m.id} ({provider}) missing price"

    def test_price_format_contains_currency(self):
        for m in IMAGE_MODEL_PRESETS:
            assert "$" in m.price or "¥" in m.price, f"{m.id} price missing currency symbol"


class TestFormatModelLabel:
    """Verify format_model_label output."""

    def test_with_hint_and_price(self):
        m = ModelOption("test", "test", "fast", "$0.10/张")
        label = format_model_label(m)
        assert "test" in label
        assert "(fast)" in label
        assert "$0.10/张" in label

    def test_with_price_only(self):
        m = ModelOption("test", "test", "", "$0.50/次")
        label = format_model_label(m)
        assert "test" in label
        assert "$0.50/次" in label
        assert "()" not in label

    def test_no_hint_no_price(self):
        m = ModelOption("test", "test")
        label = format_model_label(m)
        assert label == "test"

    def test_real_image_model_label(self):
        m = IMAGE_MODEL_PRESETS[0]
        label = format_model_label(m)
        assert m.label in label
        assert m.price in label
