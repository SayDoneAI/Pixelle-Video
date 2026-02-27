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
    # Verified models (keep at top)
    ModelOption("dall-e-3", "dall-e-3", "~10s, good compatibility", "$0.04/张"),
    ModelOption("doubao-seedream-3-0-t2i-250415", "doubao-seedream-3-0-t2i-250415", "~6.5s, cost-effective", "$0.10/张"),

    # Doubao Seedream series (豆包绘画系列)
    ModelOption("doubao-seedream-5-0-260128", "doubao-seedream-5-0-260128", "latest, best quality", "$0.22/张"),
    ModelOption("doubao-seedream-4-5-251128", "doubao-seedream-4-5-251128", "multi-image fusion", "$0.25/张"),
    ModelOption("doubao-seedream-4-0-250828", "doubao-seedream-4-0-250828", "multimodal generation", "$0.20/张"),
    ModelOption("doubao-seededit-3-0-i2i-250628", "doubao-seededit-3-0-i2i-250628", "image editing", "$0.10/张"),

    # FLUX series (高质量绘画)
    ModelOption("flux-schnell", "flux-schnell", "fastest, good quality", "$0.05/张"),
    ModelOption("flux.1-kontext-dev", "flux.1-kontext-dev", "dev version", "$0.06/张"),
    ModelOption("flux.1-dev", "flux.1-dev", "development", "$0.075/张"),
    ModelOption("flux-dev", "flux-dev", "standard dev", "$0.08/张"),
    ModelOption("flux.1-kontext-pro", "flux.1-kontext-pro", "pro context", "$0.12/张"),
    ModelOption("flux-pro", "flux-pro", "professional", "$0.15/张"),
    ModelOption("flux-kontext-pro", "flux-kontext-pro", "pro with context", "$0.24/张"),
    ModelOption("flux-pro-max", "flux-pro-max", "flagship quality", "$0.30/张"),
    ModelOption("flux.1.1-pro", "flux.1.1-pro", "latest pro", "$0.30/张"),
    ModelOption("flux-kontext-max", "flux-kontext-max", "max context", "$0.48/张"),
    ModelOption("flux-pro-1.1-ultra", "flux-pro-1.1-ultra", "ultra high-res", "$0.50/张"),

    # GPT Image series (OpenAI)
    ModelOption("sora_image", "sora_image", "cheapest, web version", "$0.03/张"),
    ModelOption("gpt-image-1-all", "gpt-image-1-all", "reverse proxy", "$0.08/张"),
    ModelOption("gpt-image-1", "gpt-image-1", "official, edit support", "$0.08/张"),

    # Gemini Image series (Google)
    ModelOption("gemini-3.1-flash-image-preview", "gemini-3.1-flash-image-preview", "4K output, 4-6s/张", "$0.067/张"),
    ModelOption("gemini-2.5-flash-image", "gemini-2.5-flash-image", "fast, conversational", "$0.09/张"),
    ModelOption("gemini-3-pro-image-preview", "gemini-3-pro-image-preview", "Nano Banana 2, 2K/4K", "$0.198/张"),

    # Qwen Image series (通义千问)
    ModelOption("qwen-image-edit-2509", "qwen-image-edit-2509", "image editing", "$0.12/张"),
    ModelOption("qwen-image-max", "qwen-image-max", "max quality", "$0.50/张"),

    # Ideogram (note: uses different API endpoint)
    ModelOption("ideogram-v3", "ideogram-v3", "Ideogram 3.0, separate API", "$0.08/张"),
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
        # Veo series (Google) — verified, fast & cheap
        ModelOption("veo3.1-fast", "veo3.1-fast", "~2.5min, fast", "$0.70/次"),
        ModelOption("veo_3_1-fast", "veo_3_1-fast", "fast, underscore variant", "$0.18/次"),
        ModelOption("veo_3_1", "veo_3_1", "high quality", "$0.438/次"),
        ModelOption("veo3.1", "veo3.1", "standard quality", "$0.70/次"),
        ModelOption("veo3.1-4k", "veo3.1-4k", "4K output", "$1.00/次"),
        ModelOption("veo3.1-pro", "veo3.1-pro", "pro quality", "$3.50/次"),
        ModelOption("veo3.1-pro-4k", "veo3.1-pro-4k", "pro 4K output", "$3.50/次"),
        ModelOption("veo_3_1-fast-4K", "veo_3_1-fast-4K", "fast 4K", "$0.258/次"),
        ModelOption("veo_3_1-4K", "veo_3_1-4K", "4K variant", "$0.51/次"),
        ModelOption("veo_3_1-components", "veo_3_1-components", "first-frame support", "$0.438/次"),
        ModelOption("veo_3_1-components-4K", "veo_3_1-components-4K", "first-frame 4K", "$0.51/次"),
        ModelOption("veo_3_1-fast-components-4K", "veo_3_1-fast-components-4K", "fast first-frame 4K", "$0.516/次"),
        ModelOption("veo3.1-components-4k", "veo3.1-components-4k", "first-frame 4K", "$1.00/次"),

        # Kling via sucloud unified protocol
        ModelOption("kling-v2-5-turbo", "kling-v2-5-turbo", "sucloud listed", "$1.70/次"),

        # Sora series (OpenAI, reverse proxy)
        ModelOption("sora-2-all", "sora-2-all", "10s/15s 720p, reverse", "$0.20/次"),
        ModelOption("sora-2-vip-all", "sora-2-vip-all", "10s, reverse", "$2.50/次"),
        ModelOption("sora-2-pro-all", "sora-2-pro-all", "15s/25s 1080p, reverse", "$3.60/次"),

        # Grok Video (xAI)
        ModelOption("grok-video-3-15s", "grok-video-3-15s", "720p/1080p 15s", "$0.50/次"),

        # Doubao Seedance (豆包视频)
        ModelOption("doubao-seedance-1-0-pro-fast-251015", "doubao-seedance-1-0-pro-fast-251015", "fast, cheapest", "$6.30/次"),
        ModelOption("doubao-seedance-1-0-lite-t2v-250428", "doubao-seedance-1-0-lite-t2v-250428", "lite text-to-video", "$15.00/次"),
        ModelOption("doubao-seedance-1-0-lite-i2v-250428", "doubao-seedance-1-0-lite-i2v-250428", "lite image-to-video", "$15.00/次"),
        ModelOption("doubao-seedance-1-0-pro-250528", "doubao-seedance-1-0-pro-250528", "pro quality", "$22.50/次"),
        ModelOption("doubao-seedance-1-5-pro-251215", "doubao-seedance-1-5-pro-251215", "latest pro 1.5", "$24.00/次"),

        # Wan (万相)
        ModelOption("wan2.6-i2v", "wan2.6-i2v", "image-to-video, multi-shot", "$1.00/s"),
    ),
    "kling": (
        ModelOption("kling-video", "kling-video", "text/image-to-video", "$1.70/次"),
        ModelOption("kling-v2-5-turbo", "kling-v2-5-turbo", "v2.5 turbo", "$1.70/次"),
        ModelOption("kling-omni-video", "kling-omni-video", "omni O1 video", "$1.70/次"),
        ModelOption("kling-multi-elements", "kling-multi-elements", "multi-element synthesis", "$1.70/次"),
        ModelOption("kling-video-extend", "kling-video-extend", "video extension", "$1.70/次"),
        ModelOption("kling-effects", "kling-effects", "136+ creative effects", "$3.40/次"),
        ModelOption("kling-avatar-image2video", "kling-avatar-image2video", "digital human", "$0.68/次"),
        ModelOption("kling-advanced-lip-sync", "kling-advanced-lip-sync", "lip sync", "$0.85/次"),
        ModelOption("kling-motion-control", "kling-motion-control", "motion transfer", "$0.85/s"),
    ),
}

DEFAULT_VIDEO_MODELS: dict[str, str] = {
    "sucloud_video": "veo3.1-fast",
    "kling": "kling-video",
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
