"""
Preset model definitions for API mode.

Contains verified model lists for sucloud and pure-logic helper functions
for provider-model linkage. No UI code here — testable without Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass

# Sentinel used by UI to indicate "enter a custom model name"
CUSTOM_OPTION = "__custom__"


@dataclass(frozen=True)
class ModelOption:
    """A single model entry in a dropdown list."""
    id: str
    label: str
    hint: str = ""
    price: str = ""


# ======================================================================
# Image models (sucloud verified)
# ======================================================================

IMAGE_MODEL_PRESETS: tuple[ModelOption, ...] = (
    ModelOption("dall-e-3", "dall-e-3", "~10s, good compatibility", "$0.04/张"),
    ModelOption("doubao-seedream-3-0-t2i-250415", "doubao-seedream-3-0-t2i-250415", "~6.5s, cost-effective", "$0.10/张"),
    ModelOption("doubao-seedream-4-0-250828", "doubao-seedream-4-0-250828", "sucloud listed, untested", "$0.20/张"),
    ModelOption("gpt-image-1", "gpt-image-1", "429 rate-limited, reserved", "$0.08/张"),
)

DEFAULT_IMAGE_MODEL = "dall-e-3"

# ======================================================================
# Video providers
# ======================================================================

@dataclass(frozen=True)
class ProviderOption:
    """A video provider entry."""
    id: str
    label: str
    hint: str = ""


VIDEO_PROVIDER_PRESETS: tuple[ProviderOption, ...] = (
    ProviderOption("sucloud_video", "sucloud_video", "sucloud unified video protocol"),
    ProviderOption("kling", "kling", "Kling official protocol"),
)

DEFAULT_VIDEO_PROVIDER = "sucloud_video"

# ======================================================================
# Video models — keyed by provider
# ======================================================================

VIDEO_MODEL_PRESETS: dict[str, tuple[ModelOption, ...]] = {
    "sucloud_video": (
        ModelOption("veo3.1-fast", "veo3.1-fast", "~2.5min, fast", "$0.70/次"),
        ModelOption("veo3", "veo3", "standard", "$0.90/次"),
        ModelOption("kling-v2-5-turbo", "kling-v2-5-turbo", "sucloud listed", "$1.70/次"),
    ),
    "kling": (
        ModelOption("kling-v2-5-turbo", "kling-v2-5-turbo", "", "$1.70/次"),
    ),
}

DEFAULT_VIDEO_MODELS: dict[str, str] = {
    "sucloud_video": "veo3.1-fast",
    "kling": "kling-v2-5-turbo",
}


# ======================================================================
# Pure-logic helpers (unit-testable)
# ======================================================================


def get_image_model_ids() -> list[str]:
    """Return ordered list of preset image model IDs."""
    return [m.id for m in IMAGE_MODEL_PRESETS]


def get_video_provider_ids() -> list[str]:
    """Return ordered list of preset video provider IDs."""
    return [p.id for p in VIDEO_PROVIDER_PRESETS]


def get_video_models_for_provider(provider: str) -> list[str]:
    """Return ordered list of video model IDs for a given provider.

    Falls back to an empty list for unknown providers.
    """
    return [m.id for m in VIDEO_MODEL_PRESETS.get(provider, ())]


def get_default_video_model(provider: str) -> str:
    """Return the default video model for a provider, or empty string."""
    return DEFAULT_VIDEO_MODELS.get(provider, "")


def resolve_selection(
    selected: str,
    custom_value: str,
) -> str:
    """Resolve a selectbox + custom-input pair to a final model string.

    Args:
        selected: The selectbox value (may be CUSTOM_OPTION).
        custom_value: The text_input value (used when selected == CUSTOM_OPTION).

    Returns:
        The resolved model ID string.
    """
    if selected == CUSTOM_OPTION:
        return custom_value.strip()
    return selected


def format_model_label(model: ModelOption) -> str:
    """Format a model option as a display label with price.

    Example: "dall-e-3  (~10s, good compatibility) $0.04/张"
    """
    parts = [model.label]
    if model.hint:
        parts.append(f"({model.hint})")
    if model.price:
        parts.append(model.price)
    return "  ".join(parts)
