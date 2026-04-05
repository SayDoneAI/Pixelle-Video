from __future__ import annotations

import base64
import json
import re
from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Literal

import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup, Tag
from loguru import logger

from pixelle_video.services.frame_html import HTMLFrameGenerator
from pixelle_video.utils.template_util import parse_template_size, resolve_template_path
from web.i18n import get_language, tr
from web.utils.async_helpers import run_async

ElementKind = Literal["StaticText", "DynamicField", "Decoration"]
BindingSource = Literal["preview", "param"]


@dataclass(frozen=True)
class TemplateElement:
    id: str
    label: str
    kind: ElementKind
    selector: str
    description: str
    field_name: str | None = None
    role: str | None = None
    param_names: tuple[str, ...] = ()
    z_index: int = 1
    binding_name: str | None = None
    binding_source: BindingSource | None = None
    binding_attribute: str | None = None
    slot_name: str | None = None


@dataclass(frozen=True)
class TemplateProtocolSlot:
    node_name: str
    slot_name: str
    selector: str
    label: str
    kind: ElementKind
    description: str
    field_name: str | None = None
    role: str | None = None
    param_names: tuple[str, ...] = ()
    z_index: int = 1
    binding_source: BindingSource | None = None
    binding_attribute: str | None = None


@dataclass(frozen=True)
class TemplateProtocol:
    template_path: str
    slots: tuple[TemplateProtocolSlot, ...]
    edit_strategy: Literal["mapped", "protocol"] = "protocol"


def _build_protocol_elements(protocol: TemplateProtocol) -> tuple[TemplateElement, ...]:
    return tuple(
        TemplateElement(
            id=slot.slot_name,
            label=slot.label,
            kind=slot.kind,
            selector=f'[data-studio-node="{slot.node_name}"]',
            description=slot.description,
            field_name=slot.field_name,
            role=slot.role,
            param_names=slot.param_names,
            z_index=slot.z_index,
            binding_name=slot.field_name or slot.slot_name,
            binding_source=slot.binding_source,
            binding_attribute=slot.binding_attribute,
            slot_name=slot.slot_name,
        )
        for slot in protocol.slots
    )


LIVE_PREVIEW_FIELDS = frozenset({"title", "text", "image"})

PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-z]+))?(?:=([^}]+))?\}\}")

TEMPLATE_KIND_LABELS = {
    "asset": "素材模板",
    "image": "图文模板",
    "static": "纯文模板",
    "video": "视频模板",
}

TEMPLATE_NAME_BY_STEM = {
    "blur_card": "模糊卡片",
    "book": "书摘卡片",
    "cartoon": "卡通插画",
    "default": "默认版式",
    "elegant": "优雅版式",
    "excerpt": "摘录版式",
    "fashion_vintage": "时尚复古",
    "film": "电影感",
    "full": "全幅图文",
    "health_preservation": "养生图文",
    "healing": "疗愈风格",
    "life_insights": "人生感悟",
    "life_insights_light": "人生感悟·轻色",
    "long_text": "长文图文",
    "minimal_framed": "极简边框",
    "modern": "现代风格",
    "neon": "霓虹风格",
    "psychology_card": "心理卡片",
    "purple": "紫调版式",
    "satirical_cartoon": "讽刺漫画",
    "simple_black": "极简黑白",
    "simple_line_drawing": "简笔线稿",
    "sketch_card": "手绘卡片",
    "ultrawide_minimal": "超宽极简",
    "wide_darktech": "宽屏暗科技",
}

GENERIC_ELEMENT_LABELS = {
    "author": "作者",
    "background": "背景图",
    "brand": "品牌",
    "describe": "描述文案",
    "image": "图片",
    "logo": "Logo",
    "quote": "引文",
    "subtitle": "副标题",
    "tagline": "标语",
    "text": "正文",
    "title": "标题",
}

PROTOCOL_TEMPLATE_COPY = {
    "1080x1440/image_sketch_card.html": {
        "label_key": "studio.template.sketch_card.name",
        "description_key": "studio.template.sketch_card.description",
    },
    "1080x1920/image_default.html": {},
    "1080x1080/image_minimal_framed.html": {},
}

def _preview_slot(
    *,
    node_name: str,
    slot_name: str,
    selector: str,
    label: str,
    description: str,
    role: str | None = None,
    param_names: tuple[str, ...] = (),
    z_index: int = 4,
    binding_attribute: str | None = None,
) -> TemplateProtocolSlot:
    return TemplateProtocolSlot(
        node_name=node_name,
        slot_name=slot_name,
        selector=selector,
        label=label,
        kind="DynamicField",
        description=description,
        field_name=slot_name,
        role=role or slot_name,
        param_names=param_names,
        z_index=z_index,
        binding_source="preview",
        binding_attribute=binding_attribute,
    )


def _param_slot(
    *,
    node_name: str,
    slot_name: str,
    selector: str,
    label: str,
    description: str,
    param_names: tuple[str, ...] | None = None,
    role: str | None = None,
    z_index: int = 4,
) -> TemplateProtocolSlot:
    return TemplateProtocolSlot(
        node_name=node_name,
        slot_name=slot_name,
        selector=selector,
        label=label,
        kind="StaticText",
        description=description,
        role=role or slot_name,
        param_names=param_names or (slot_name,),
        z_index=z_index,
        binding_source="param",
    )


def _decoration_slot(
    *,
    node_name: str,
    slot_name: str,
    selector: str,
    label: str,
    description: str,
    param_names: tuple[str, ...] = (),
    z_index: int = 1,
) -> TemplateProtocolSlot:
    return TemplateProtocolSlot(
        node_name=node_name,
        slot_name=slot_name,
        selector=selector,
        label=label,
        kind="Decoration",
        description=description,
        param_names=param_names,
        z_index=z_index,
    )


PROTOCOL_TEMPLATE_ORDER = (
    "1080x1440/image_sketch_card.html",
    "1080x1920/asset_default.html",
    "1080x1920/image_default.html",
    "1080x1920/image_psychology_card.html",
    "1080x1920/image_elegant.html",
    "1080x1920/image_fashion_vintage.html",
    "1080x1920/image_blur_card.html",
    "1080x1920/image_book.html",
    "1080x1920/image_excerpt.html",
    "1080x1920/image_life_insights.html",
    "1080x1920/image_life_insights_light.html",
    "1080x1920/image_modern.html",
    "1080x1920/image_neon.html",
    "1080x1920/image_purple.html",
    "1080x1920/image_cartoon.html",
    "1080x1920/image_full.html",
    "1080x1920/image_healing.html",
    "1080x1920/image_health_preservation.html",
    "1080x1920/image_long_text.html",
    "1080x1920/image_satirical_cartoon.html",
    "1080x1920/image_simple_black.html",
    "1080x1920/image_simple_line_drawing.html",
    "1080x1920/static_default.html",
    "1080x1920/static_excerpt.html",
    "1080x1920/video_default.html",
    "1080x1920/video_healing.html",
    "1080x1080/image_minimal_framed.html",
    "1920x1080/image_book.html",
    "1920x1080/image_film.html",
    "1920x1080/image_full.html",
    "1920x1080/image_ultrawide_minimal.html",
    "1920x1080/image_wide_darktech.html",
)

SKETCH_CARD_PROTOCOL = TemplateProtocol(
    template_path="1080x1440/image_sketch_card.html",
    edit_strategy="mapped",
    slots=(
        _decoration_slot(
            node_name="title_bar",
            slot_name="title_bar",
            selector='[data-studio-node="title_bar"]',
            label="标题栏背景",
            description="标题栏背景",
            param_names=("title_bar_height", "title_bar_padding_x", "title_bar_bg", "title_bar_border_color"),
        ),
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector='[data-studio-node="title"]',
            label="标题",
            description="标题内容",
            param_names=("title_bar_height", "title_bar_padding_x", "title_font_size", "title_color"),
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector='[data-studio-node="illustration_card"]',
            label="插图卡片",
            description="插图外框",
            param_names=(
                "illustration_bottom",
                "illustration_padding_x",
                "illustration_top_padding",
                "illustration_bottom_padding",
                "illustration_card_padding",
                "illustration_frame_color",
            ),
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector='[data-studio-node="image"]',
            label="插图槽位",
            description="插图内容",
            param_names=(
                "illustration_bottom",
                "illustration_padding_x",
                "illustration_top_padding",
                "illustration_bottom_padding",
                "illustration_card_padding",
                "illustration_fill_mode",
            ),
            z_index=3,
            binding_attribute="src",
        ),
        _decoration_slot(
            node_name="caption_divider",
            slot_name="caption_divider",
            selector='[data-studio-node="caption_divider"]',
            label="分隔线",
            description="正文分隔线",
            param_names=("divider_height", "divider_inset", "divider_color"),
            z_index=2,
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector='[data-studio-node="caption"]',
            label="字幕槽位",
            description="字幕槽位",
            role="subtitle",
            param_names=(
                "caption_section_height",
                "caption_padding_top",
                "caption_padding_x",
                "caption_padding_bottom",
                "caption_font_size",
                "caption_text_color",
                "caption_text_align",
            ),
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector='[data-studio-node="author"]',
            label="作者文案",
            description="作者文案",
            param_names=("author", "author_font_size", "footer_text_color"),
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector='[data-studio-node="brand"]',
            label="品牌文案",
            description="品牌文案",
            param_names=("brand", "author_font_size", "footer_text_color"),
        ),
        _param_slot(
            node_name="tagline",
            slot_name="tagline",
            selector='[data-studio-node="tagline"]',
            label="标语",
            description="底部标语",
            param_names=("tagline", "tagline_font_size", "footer_text_color"),
        ),
    ),
)

MINIMAL_FRAMED_PROTOCOL = TemplateProtocol(
    template_path="1080x1080/image_minimal_framed.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector='[data-studio-node="title"]',
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector='[data-studio-node="image_frame"]',
            label="边框容器",
            description="图片边框容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector='[data-studio-node="image"]',
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector='[data-studio-node="text"]',
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
    ),
)

IMAGE_DEFAULT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_default.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector='[data-studio-node="title"]',
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector='[data-studio-node="image_frame"]',
            label="图片框",
            description="主图边框与角标",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector='[data-studio-node="image"]',
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector='[data-studio-node="text"]',
            label="正文",
            description="正文内容",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector='[data-studio-node="author"]',
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector='[data-studio-node="describe"]',
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector='[data-studio-node="brand"]',
            label="品牌",
            description="底部品牌",
        ),
    ),
)

PSYCHOLOGY_CARD_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_psychology_card.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".media",
            label="图片区",
            description="主图容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".media img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".caption",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
    ),
)

ELEGANT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_elegant.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".topic",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".image-wrapper",
            label="图片框",
            description="主图外框与装饰容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-container img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
    ),
)

BLUR_CARD_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_blur_card.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".image-center",
            label="图片区",
            description="主图容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-box img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".caption",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-section > .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

ASSET_DEFAULT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/asset_default.html",
    slots=(
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".background-layer",
            label="背景媒体层",
            description="背景媒体容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".background-layer img",
            label="图片",
            description="背景图片槽位",
            z_index=1,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".video-title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
    ),
)

BOOK_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_book.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector="body",
            label="背景图",
            description="整页背景图片",
            z_index=1,
            binding_attribute="background-image",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".main-text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="subtitle",
            slot_name="subtitle",
            selector=".subtitle",
            label="副标题",
            description="标题下方副标题",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author",
            label="作者",
            description="底部作者",
        ),
    ),
)

EXCERPT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_excerpt.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image",
            label="图片",
            description="背景图片",
            z_index=1,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".excerpt",
            label="正文",
            description="正文摘录",
            role="subtitle",
        ),
        _param_slot(
            node_name="signature",
            slot_name="signature",
            selector=".signature",
            label="署名",
            description="底部署名",
        ),
    ),
)

LIFE_INSIGHTS_LIGHT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_life_insights_light.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".content",
            label="图片区",
            description="中部图片区",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".content img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".content-text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author",
            label="作者",
            description="底部作者",
        ),
    ),
)

NEON_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_neon.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".media",
            label="图片区",
            description="主图容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".media img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".caption p",
            label="正文",
            description="正文内容",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".cta .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

PURPLE_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_purple.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".image-wrapper",
            label="图片框",
            description="主图外框与装饰容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-container img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="正文内容",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-wrapper .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

CARTOON_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_cartoon.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title-container h1",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".image-container",
            label="图片区",
            description="主图容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-container img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".caption-container p",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
    ),
)

FULL_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_full.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="主标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".bg",
            label="背景图",
            description="全幅背景图",
            z_index=1,
            binding_attribute="background-image",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-section > .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

HEALING_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_healing.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title-content",
            label="标题",
            description="右侧标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector="body",
            label="背景图",
            description="整页背景图片",
            z_index=1,
            binding_attribute="background-image",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="signature",
            slot_name="signature",
            selector=".signature",
            label="署名",
            description="底部署名",
        ),
    ),
)

HEALTH_PRESERVATION_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_health_preservation.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".content",
            label="背景图",
            description="内容区背景图",
            z_index=1,
            binding_attribute="background-image",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="正文内容",
            role="subtitle",
        ),
        _param_slot(
            node_name="signature",
            slot_name="signature",
            selector=".signature",
            label="署名",
            description="底部署名",
        ),
    ),
)

LONG_TEXT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_long_text.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector="body",
            label="背景图",
            description="整页背景图片",
            z_index=1,
            binding_attribute="background-image",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".content",
            label="正文",
            description="长文正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author",
            label="作者",
            description="底部作者",
        ),
    ),
)

SATIRICAL_CARTOON_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_satirical_cartoon.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="主标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".bg",
            label="背景图",
            description="全幅背景图",
            z_index=1,
            binding_attribute="background-image",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-section > .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

SIMPLE_BLACK_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_simple_black.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="主标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-center",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-section > .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

SIMPLE_LINE_DRAWING_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_simple_line_drawing.html",
    slots=(
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".title",
            label="正文",
            description="标题样式正文",
            role="subtitle",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-center",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-section > .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

STATIC_DEFAULT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/static_default.html",
    slots=(
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".background-image",
            label="背景层",
            description="背景图片容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".background-image img",
            label="背景图",
            description="背景图片",
            z_index=1,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".video-title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="正文内容",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

STATIC_EXCERPT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/static_excerpt.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".excerpt",
            label="正文",
            description="正文摘录",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="signature",
            slot_name="signature",
            selector=".signature",
            label="署名",
            description="底部署名",
        ),
    ),
)

VIDEO_DEFAULT_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/video_default.html",
    slots=(
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".background-image",
            label="背景图",
            description="整页背景图",
            z_index=1,
            binding_attribute="background-image",
        ),
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".video-title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

VIDEO_HEALING_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/video_healing.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title-content",
            label="标题",
            description="右侧标题",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="signature",
            slot_name="signature",
            selector=".signature",
            label="署名",
            description="底部署名",
        ),
    ),
)

WIDE_BOOK_PROTOCOL = TemplateProtocol(
    template_path="1920x1080/image_book.html",
    slots=(
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector="body",
            label="背景图",
            description="整页背景图",
            z_index=1,
            binding_attribute="background-image",
        ),
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="右上标题",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".content",
            label="正文",
            description="主内容文案",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author",
            label="作者",
            description="底部作者",
        ),
    ),
)

FILM_PROTOCOL = TemplateProtocol(
    template_path="1920x1080/image_film.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".middle",
            label="图片区",
            description="中部图片容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".middle img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-section > .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

WIDE_FULL_PROTOCOL = TemplateProtocol(
    template_path="1920x1080/image_full.html",
    slots=(
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector="body",
            label="背景图",
            description="整页背景图",
            z_index=1,
            binding_attribute="background-image",
        ),
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".title",
            label="标题",
            description="主标题",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text",
            label="正文",
            description="底部正文",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-section > .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

ULTRAWIDE_MINIMAL_PROTOCOL = TemplateProtocol(
    template_path="1920x1080/image_ultrawide_minimal.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".main-title",
            label="标题",
            description="左侧标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".image-container",
            label="图片区",
            description="中部图片容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-container img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text-content",
            label="正文",
            description="右侧正文",
            role="subtitle",
        ),
    ),
)

WIDE_DARKTECH_PROTOCOL = TemplateProtocol(
    template_path="1920x1080/image_wide_darktech.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".main-title",
            label="标题",
            description="左侧标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".image-wrapper",
            label="图片区",
            description="右侧图片容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-container img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".description",
            label="正文",
            description="左侧正文",
            role="subtitle",
        ),
    ),
)

LIFE_INSIGHTS_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_life_insights.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".top-title-text",
            label="标题",
            description="顶部标题",
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".image-frame",
            label="图框",
            description="中部图框",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-container img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".highlight-text",
            label="正文",
            description="底部感悟文案",
            role="subtitle",
        ),
    ),
)

FASHION_VINTAGE_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_fashion_vintage.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".main-title",
            label="标题",
            description="顶部标题",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-container img",
            label="图片",
            description="中部图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".bottom-text",
            label="正文",
            description="底部手写文案",
            role="subtitle",
        ),
    ),
)

MODERN_PROTOCOL = TemplateProtocol(
    template_path="1080x1920/image_modern.html",
    slots=(
        _preview_slot(
            node_name="title",
            slot_name="title",
            selector=".video-title",
            label="标题",
            description="顶部标题",
            param_names=("title_font_size",),
        ),
        _decoration_slot(
            node_name="image_frame",
            slot_name="image_frame",
            selector=".image-wrapper",
            label="图片区",
            description="主图外围容器",
        ),
        _preview_slot(
            node_name="image",
            slot_name="image",
            selector=".image-container img",
            label="图片",
            description="主图片槽位",
            z_index=3,
            binding_attribute="src",
        ),
        _preview_slot(
            node_name="text",
            slot_name="text",
            selector=".text-wrapper .text",
            label="正文",
            description="正文内容",
            role="subtitle",
        ),
        _param_slot(
            node_name="author",
            slot_name="author",
            selector=".author-name .logo",
            label="作者",
            description="作者标识",
        ),
        _param_slot(
            node_name="describe",
            slot_name="describe",
            selector=".author-desc",
            label="说明文案",
            description="作者说明",
        ),
        _param_slot(
            node_name="brand",
            slot_name="brand",
            selector=".logo-wrapper .logo",
            label="品牌",
            description="底部品牌",
        ),
    ),
)

TEMPLATE_PROTOCOLS = {
    protocol.template_path: protocol
    for protocol in (
        SKETCH_CARD_PROTOCOL,
        ASSET_DEFAULT_PROTOCOL,
        IMAGE_DEFAULT_PROTOCOL,
        PSYCHOLOGY_CARD_PROTOCOL,
        ELEGANT_PROTOCOL,
        BLUR_CARD_PROTOCOL,
        BOOK_PROTOCOL,
        EXCERPT_PROTOCOL,
        LIFE_INSIGHTS_LIGHT_PROTOCOL,
        NEON_PROTOCOL,
        PURPLE_PROTOCOL,
        CARTOON_PROTOCOL,
        FULL_PROTOCOL,
        HEALING_PROTOCOL,
        HEALTH_PRESERVATION_PROTOCOL,
        LONG_TEXT_PROTOCOL,
        SATIRICAL_CARTOON_PROTOCOL,
        SIMPLE_BLACK_PROTOCOL,
        SIMPLE_LINE_DRAWING_PROTOCOL,
        STATIC_DEFAULT_PROTOCOL,
        STATIC_EXCERPT_PROTOCOL,
        VIDEO_DEFAULT_PROTOCOL,
        VIDEO_HEALING_PROTOCOL,
        MINIMAL_FRAMED_PROTOCOL,
        WIDE_BOOK_PROTOCOL,
        FILM_PROTOCOL,
        WIDE_FULL_PROTOCOL,
        ULTRAWIDE_MINIMAL_PROTOCOL,
        WIDE_DARKTECH_PROTOCOL,
        LIFE_INSIGHTS_PROTOCOL,
        FASHION_VINTAGE_PROTOCOL,
        MODERN_PROTOCOL,
    )
}

PREVIEW_DATASETS = {
    "short": {
        "label": "短字幕",
        "title": "真正的判断力",
        "text": "先想清楚，再动手。",
        "image": "resources/example.png",
    },
    "medium": {
        "label": "中字幕",
        "title": "真正的判断力",
        "text": "判断力不是知道更多信息，而是知道哪些信息值得你认真对待。",
        "image": "resources/example.png",
    },
    "long": {
        "label": "长字幕",
        "title": "真正的判断力",
        "text": (
            "判断力真正拉开差距的时刻，往往不是你会不会做，"
            "而是你能不能在信息混乱、情绪拉扯和时间紧迫的时候，"
            "依然抓住最重要的那个变量。"
        ),
        "image": "resources/example.png",
    },
}

TEMPLATE_SAMPLE_TEXT_RULES: tuple[tuple[tuple[str, ...], dict[str, str]], ...] = (
    (
        ("极简", "minimal", "simple", "边框"),
        {
            "short": "少一点，重点会更清楚。",
            "medium": "少一点信息，重点会更清楚。",
            "long": "当画面只留下真正重要的部分，注意力反而更容易落在最该被看见的地方。",
        },
    ),
    (
        ("手绘", "sketch", "cartoon", "线稿"),
        {
            "short": "先有画面感，再放重点。",
            "medium": "先有画面感，再把重点慢慢放下。",
            "long": "画面先把情绪接住，再让真正重要的一句话慢慢落下来，信息才不会显得生硬。",
        },
    ),
    (
        ("优雅", "elegant", "healing", "vintage", "purple"),
        {
            "short": "情绪慢下来，内容才会被看见。",
            "medium": "情绪放慢一点，内容会更容易被看见。",
            "long": "节奏慢一点、留白多一点，真正重要的内容反而更容易被观众安静地接住。",
        },
    ),
    (
        ("书", "书摘", "摘录", "excerpt", "book", "long_text", "长文"),
        {
            "short": "把值得重读的一段留下。",
            "medium": "把值得重读的一段，安静地留在画面里。",
            "long": "有些内容不需要被讲得很满，只要把最值得停留的那一段留在画面里，就已经足够。",
        },
    ),
    (
        ("心理", "psychology", "life_insights", "人生", "养生", "health"),
        {
            "short": "有力量的话，不必很大声。",
            "medium": "真正有力量的话，往往不需要很大声。",
            "long": "真正能留下来的表达，通常都不是最用力的那一句，而是最贴近人心、最不急着证明自己的那一句。",
        },
    ),
    (
        ("modern", "modern", "neon", "darktech", "film", "科技", "电影"),
        {
            "short": "结构清楚，信息才有力量。",
            "medium": "结构清楚，信息就会更有力量。",
            "long": "当画面层次、节奏和重点都被清楚地组织起来，观众会更快抓到你真正想传达的那个结论。",
        },
    ),
)

TEMPLATE_SAMPLE_IMAGE_THEME_RULES: tuple[tuple[tuple[str, ...], dict[str, str]], ...] = (
    (
        ("极简", "minimal", "simple", "边框"),
        {
            "start": "#f8fafc",
            "end": "#e2e8f0",
            "accent": "#475569",
            "secondary": "#cbd5e1",
            "text": "#0f172a",
        },
    ),
    (
        ("手绘", "sketch", "cartoon", "线稿"),
        {
            "start": "#fff7ed",
            "end": "#fde68a",
            "accent": "#ea580c",
            "secondary": "#fdba74",
            "text": "#7c2d12",
        },
    ),
    (
        ("优雅", "elegant", "healing", "vintage", "purple"),
        {
            "start": "#fdf2f8",
            "end": "#ede9fe",
            "accent": "#9333ea",
            "secondary": "#f5d0fe",
            "text": "#4a044e",
        },
    ),
    (
        ("书", "书摘", "摘录", "excerpt", "book", "long_text", "长文"),
        {
            "start": "#fef3c7",
            "end": "#fde68a",
            "accent": "#92400e",
            "secondary": "#fcd34d",
            "text": "#78350f",
        },
    ),
    (
        ("心理", "psychology", "life_insights", "人生", "养生", "health"),
        {
            "start": "#ecfeff",
            "end": "#cffafe",
            "accent": "#0f766e",
            "secondary": "#99f6e4",
            "text": "#134e4a",
        },
    ),
    (
        ("modern", "modern", "neon", "darktech", "film", "科技", "电影"),
        {
            "start": "#0f172a",
            "end": "#1d4ed8",
            "accent": "#38bdf8",
            "secondary": "#0ea5e9",
            "text": "#e0f2fe",
        },
    ),
)

PARAM_LABELS = {
    "accent_color": "主色",
    "author": "作者文案",
    "author_font_size": "作者字号",
    "brand": "品牌文案",
    "caption_font_size": "字幕字号",
    "caption_padding_bottom": "字幕区下内边距",
    "caption_padding_top": "字幕区上内边距",
    "caption_padding_x": "字幕区左右内边距",
    "caption_section_height": "字幕区高度",
    "caption_text_align": "字幕对齐",
    "caption_text_color": "字幕颜色",
    "divider_color": "分隔线颜色",
    "divider_height": "分隔线高度",
    "divider_inset": "分隔线左右留白",
    "describe": "说明文案",
    "footer_text_color": "底部文字颜色",
    "illustration_bottom": "插图区底部位置",
    "illustration_bottom_padding": "插图区下内边距",
    "illustration_card_padding": "插图卡片内边距",
    "illustration_fill_mode": "插图填充方式",
    "illustration_frame_color": "插图外框颜色",
    "illustration_padding_x": "插图区左右留白",
    "illustration_top_padding": "插图区上内边距",
    "page_background": "页面背景",
    "subtitle": "副标题",
    "tagline": "标语文案",
    "tagline_font_size": "标语字号",
    "title_bar_bg": "标题栏背景",
    "title_bar_border_color": "标题栏边线",
    "title_bar_height": "标题栏高度",
    "title_bar_padding_x": "标题栏左右留白",
    "title_color": "标题颜色",
    "title_font_size": "标题字号",
}

PARAM_OPTIONS = {
    "caption_text_align": ("left", "center", "right"),
    "illustration_fill_mode": ("contain", "cover"),
}

PARAM_OPTION_LABELS = {
    "caption_text_align": {
        "left": "左对齐",
        "center": "居中",
        "right": "右对齐",
    },
    "illustration_fill_mode": {
        "contain": "完整显示",
        "cover": "铺满裁切",
    },
}

DEFAULT_SELECTED_ELEMENT_ID = "text"


def render_template_studio() -> None:
    """Render the live WYSIWYG template editor."""
    template_options = _get_template_options()
    selected_template = _resolve_selected_template(template_options)
    selected_template = _render_page_header(template_options, selected_template)
    template_path = selected_template["template_path"]
    current_query_template = _read_query_param("studio_template")
    if current_query_template != template_path:
        st.query_params["studio_template"] = template_path
    resolved_template_path = resolve_template_path(template_path)

    generator = HTMLFrameGenerator(resolved_template_path)
    custom_params = generator.parse_template_parameters()
    template_width, template_height = parse_template_size(template_path)
    payload = _build_live_editor_payload(
        selected_template=selected_template,
        template_path=template_path,
        generator=generator,
        custom_params=custom_params,
        template_width=template_width,
        template_height=template_height,
    )
    components.html(_build_live_editor_html(payload), height=2000, scrolling=False)


def _inject_editor_styles() -> None:
    st.markdown(
        """
        <style>
        .studio-canvas-shell {
            display: flex;
            justify-content: center;
            padding: 12px 0 4px;
        }
        .studio-canvas {
            position: relative;
            width: min(100%, 520px);
            aspect-ratio: 1080 / 1440;
            background:
                radial-gradient(circle at top left, rgba(0, 0, 0, 0.06), transparent 28%),
                linear-gradient(180deg, #f7f7f7 0%, #ececec 100%);
            border-radius: 28px;
            padding: 18px;
            box-shadow: 0 24px 50px rgba(0, 0, 0, 0.12);
        }
        .studio-phone {
            position: relative;
            width: 100%;
            height: 100%;
            overflow: hidden;
            border-radius: 22px;
            background: #ffffff;
            box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08);
        }
        .studio-preview-image {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .studio-element {
            position: absolute;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            overflow: hidden;
            gap: 4px;
            padding: 6px 7px;
            border-radius: 14px;
            border: 1px solid transparent;
            text-decoration: none !important;
            transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
            color: inherit !important;
        }
        .studio-element:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.12);
        }
        .studio-element.is-selected {
            border-width: 2px;
            box-shadow: 0 16px 30px rgba(0, 0, 0, 0.18);
        }
        .studio-element:not(.is-selected) .studio-element-body {
            display: none;
        }
        .studio-element:not(.is-selected) .studio-element-title {
            font-size: 12px;
        }
        .studio-element-kind {
            width: fit-content;
            max-width: 100%;
            border-radius: 999px;
            padding: 3px 8px;
            font-size: 11px;
            font-weight: 700;
            line-height: 1.1;
            letter-spacing: 0.02em;
            background: rgba(255, 255, 255, 0.88);
            backdrop-filter: blur(8px);
            color: #111827;
        }
        .studio-element-title {
            font-size: 15px;
            font-weight: 700;
            line-height: 1.25;
            word-break: break-word;
        }
        .studio-element-body {
            font-size: 12px;
            line-height: 1.4;
            opacity: 0.82;
            word-break: break-word;
        }
        .studio-kind-dynamic {
            background: rgba(14, 165, 233, 0.16);
            border-color: rgba(14, 165, 233, 0.44);
        }
        .studio-kind-dynamic.is-selected {
            border-color: #0284c7;
        }
        .studio-kind-static {
            background: rgba(34, 197, 94, 0.16);
            border-color: rgba(34, 197, 94, 0.42);
        }
        .studio-kind-static.is-selected {
            border-color: #15803d;
        }
        .studio-kind-decoration {
            background: rgba(107, 114, 128, 0.16);
            border-color: rgba(107, 114, 128, 0.34);
        }
        .studio-kind-decoration.is-selected {
            border-color: #374151;
        }
        .studio-divider-chip {
            align-items: center;
            justify-content: center;
            padding-top: 4px;
            padding-bottom: 4px;
        }
        .studio-toolbar-note {
            font-size: 12px;
            color: #64748b;
            margin-top: 8px;
        }
        .studio-panel-label {
            font-size: 12px;
            color: #6b7280;
            margin-bottom: 4px;
        }
        .studio-panel-code {
            font-family: "SFMono-Regular", "SF Mono", Consolas, monospace;
            font-size: 12px;
            background: rgba(15, 23, 42, 0.05);
            border-radius: 10px;
            padding: 6px 8px;
        }
        .studio-note {
            font-size: 12px;
            color: #64748b;
            line-height: 1.5;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_page_header(
    template_options: list[dict[str, Any]],
    selected_template: dict[str, Any],
) -> dict[str, Any]:
    current_path = selected_template["template_path"]

    title_col, action_col = st.columns([1.0, 0.46])
    with title_col:
        st.markdown(f"## {tr('studio.title', '模板工作台')}")
    with action_col:
        selected_path = _render_template_picker(template_options, current_path)
    return next(item for item in template_options if item["template_path"] == selected_path)


def _get_template_options() -> list[dict[str, Any]]:
    template_root = Path("templates")
    requested_path = _read_query_param("studio_template")
    candidate_paths = _discover_template_paths(template_root)
    if requested_path and requested_path not in candidate_paths and (template_root / requested_path).is_file():
        candidate_paths.append(requested_path)

    options: list[dict[str, Any]] = []
    for relative_path in candidate_paths:
        path = template_root / relative_path
        if not path.is_file():
            continue
        template_source = path.read_text(encoding="utf-8")
        size_label = _format_size_label(path.parent.name)
        kind_label, stem_name = _template_kind_and_name(path.stem)
        protocol = TEMPLATE_PROTOCOLS.get(relative_path)
        protocol_ready = bool(protocol and _protocol_matches_template(protocol, template_source))
        edit_strategy = protocol.edit_strategy if protocol_ready and protocol else "preview"
        status_label = (
            "精细编辑"
            if edit_strategy == "mapped"
            else "协议编辑"
            if protocol_ready
            else "仅预览"
        )
        copy = PROTOCOL_TEMPLATE_COPY.get(relative_path, {})
        label_fallback = f"{stem_name} / {size_label}"
        description_fallback = (
            f"{kind_label} · 已接入所见即所得编辑。"
            if edit_strategy == "mapped"
            else f"{kind_label} · 已接入统一槽位协议，可进入直接编辑。"
            if protocol_ready
            else f"{kind_label} · 当前仅保留预览，待适配后再开放编辑。"
        )
        options.append(
            {
                "id": relative_path.replace("/", "__").removesuffix(".html"),
                "template_path": relative_path,
                "label": (
                    tr(copy["label_key"], label_fallback)
                    if copy.get("label_key")
                    else label_fallback
                ),
                "description": (
                    tr(copy["description_key"], description_fallback)
                    if copy.get("description_key")
                    else description_fallback
                ),
                "display_name": stem_name,
                "kind_label": kind_label,
                "size_label": size_label,
                "status": edit_strategy if protocol_ready else "preview-only",
                "status_label": status_label,
                "editable": protocol_ready,
                "mapped": protocol_ready,
                "protocol_slots": len(protocol.slots) if protocol else 0,
            }
        )
    options.sort(key=_template_sort_key)
    _apply_template_display_labels(options)
    return options


def _discover_template_paths(template_root: Path) -> list[str]:
    if not template_root.is_dir():
        return []
    return sorted(
        path.relative_to(template_root).as_posix()
        for path in template_root.rglob("*.html")
        if path.is_file()
    )


def _protocol_matches_template(protocol: TemplateProtocol, template_source: str) -> bool:
    soup = BeautifulSoup(template_source, "html.parser")
    return all(bool(soup.select(slot.selector)) for slot in protocol.slots)


def _read_query_param(name: str) -> str | None:
    value = st.query_params.get(name)
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return str(value)


def _resolve_selected_template(template_options: list[dict[str, Any]]) -> dict[str, Any]:
    requested_path = _read_query_param("studio_template")
    if requested_path:
        match = next((item for item in template_options if item["template_path"] == requested_path), None)
        if match:
            return match
    return next((item for item in template_options if item["editable"]), template_options[0])


def _format_size_label(raw_value: str) -> str:
    if re.fullmatch(r"\d+x\d+", raw_value):
        return raw_value.replace("x", "×")
    return raw_value


def _template_kind_and_name(stem: str) -> tuple[str, str]:
    prefix, _, raw_name = stem.partition("_")
    kind_label = TEMPLATE_KIND_LABELS.get(prefix, "HTML 模板")
    if raw_name == "default":
        kind_name = kind_label.removesuffix("模板") or kind_label
        return kind_label, f"{kind_name}默认"
    template_name = TEMPLATE_NAME_BY_STEM.get(raw_name or prefix)
    if template_name:
        return kind_label, template_name

    fallback_source = raw_name or stem
    fallback_label = fallback_source.replace("_", " ").strip().title() or stem
    return kind_label, fallback_label


def _apply_template_display_labels(template_options: list[dict[str, Any]]) -> None:
    label_counts = Counter(str(option["label"]) for option in template_options)
    display_counts: Counter[str] = Counter()

    for option in template_options:
        display_label = str(option["label"])
        if label_counts[display_label] > 1:
            display_label = f"{display_label} · {option['kind_label']}"
        option["display_label"] = display_label
        display_counts[display_label] += 1

    for option in template_options:
        display_label = str(option["display_label"])
        if display_counts[display_label] > 1:
            option["display_label"] = f"{display_label} · {option['template_path']}"


def _render_template_picker(
    template_options: list[dict[str, Any]],
    current_path: str,
) -> str:
    option_by_path = {item["template_path"]: item for item in template_options}
    current_option = option_by_path[current_path]
    popover_label = current_option.get("display_label", current_option["label"])

    with st.popover(popover_label, use_container_width=True):
        search_query = st.text_input(
            tr("studio.template_search", "搜索模板"),
            value=st.session_state.get("studio_template_search", ""),
            placeholder=tr("studio.template_search_placeholder", "输入模板名、类型或尺寸"),
            key="studio_template_search",
        )
        filtered_options = [
            item
            for item in template_options
            if _template_picker_matches(item, search_query)
        ]
        if not filtered_options:
            st.caption(tr("studio.template_search_empty", "没有匹配的模板。"))
        for item in filtered_options:
            is_current = item["template_path"] == current_path
            button_label = item.get("display_label", item["label"])
            if st.button(
                button_label,
                key=f"studio_pick_{item['id']}",
                type="primary" if is_current else "secondary",
                use_container_width=True,
                disabled=is_current,
            ):
                st.query_params["studio_template"] = item["template_path"]
                st.rerun()
            st.caption(f"{item['status_label']} · {item['template_path']}")

    return current_path


def _template_picker_matches(item: dict[str, Any], query: str | None) -> bool:
    normalized_query = (query or "").strip().lower()
    if not normalized_query:
        return True
    haystack = " ".join(
        str(
            item.get(key, "")
        )
        for key in ("display_label", "label", "display_name", "kind_label", "size_label", "status_label", "template_path")
    ).lower()
    return normalized_query in haystack


def _template_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    if item["template_path"] in PROTOCOL_TEMPLATE_ORDER:
        return (0, PROTOCOL_TEMPLATE_ORDER.index(item["template_path"]), item["template_path"])
    return (1 if item["mapped"] else 2, 0, item["template_path"])


def _render_template_sidebar(template_options: list[dict[str, Any]]) -> dict[str, Any]:
    option_labels = [option.get("display_label", option["label"]) for option in template_options]
    selected_label = st.radio(
        tr("studio.template_list", "模板列表"),
        option_labels,
        key="studio_selected_template_label",
        label_visibility="collapsed",
    )
    return next(
        option
        for option in template_options
        if option.get("display_label", option["label"]) == selected_label
    )


def _render_template_overview(
    selected_template: dict[str, Any],
    template_width: int,
    template_height: int,
    media_width: int,
    media_height: int,
) -> None:
    with st.container(border=True):
        st.markdown(f"### {selected_template.get('display_label', selected_template['label'])}")


def _render_layer_list(template_elements: tuple[TemplateElement, ...], selected_element_id: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{tr('studio.layers', '图层列表')}**")
        st.caption(
            tr(
                "studio.layers_hint",
                "优先点内容层，装饰层折叠到下面；中间画布也能直接点。",
            )
        )
        dynamic_elements = [element for element in template_elements if element.kind == "DynamicField"]
        static_elements = [element for element in template_elements if element.kind == "StaticText"]
        decoration_elements = [element for element in template_elements if element.kind == "Decoration"]

        _render_layer_group(tr("studio.layer_group_content", "内容层"), dynamic_elements, selected_element_id)
        _render_layer_group(tr("studio.layer_group_static", "固定文案"), static_elements, selected_element_id)
        with st.expander(tr("studio.layer_group_decoration", "装饰层"), expanded=False):
            _render_layer_group(tr("studio.layer_group_decoration", "装饰层"), decoration_elements, selected_element_id, show_heading=False)


def _render_layer_group(
    title: str,
    elements: list[TemplateElement],
    selected_element_id: str,
    *,
    show_heading: bool = True,
) -> None:
    if not elements:
        return
    if show_heading:
        st.caption(title)
    for element in elements:
        button_type = "primary" if element.id == selected_element_id else "secondary"
        button_label = f"{_kind_badge(element.kind)} {element.label}"
        if st.button(button_label, key=f"studio_select_{element.id}", use_container_width=True, type=button_type):
            _set_selected_element(element.id)
            st.rerun()


def _render_draft_panel(template_path: str, custom_params: dict[str, dict[str, Any]]) -> None:
    drafts = _list_saved_drafts()
    with st.container(border=True):
        st.markdown(f"**{tr('studio.drafts', '草稿')}**")
        st.caption(tr("studio.drafts_hint", "保存当前参数和样例数据，之后可以重新载入继续微调。"))
        st.text_input(tr("studio.draft_name", "草稿名"), key="studio_draft_name")
        selected_draft = st.selectbox(
            tr("studio.saved_drafts", "已保存草稿"),
            options=[""] + drafts,
            format_func=lambda item: "选择一个草稿" if not item else item,
            key="studio_saved_draft",
        )
        save_col, load_col = st.columns(2)
        with save_col:
            if st.button(tr("studio.save_draft", "保存草稿"), use_container_width=True):
                saved_path = _save_current_draft(template_path)
                st.success(f"{tr('studio.save_draft', '保存草稿')} · {saved_path.name}")
                st.rerun()
        with load_col:
            if st.button(tr("studio.load_draft", "载入草稿"), use_container_width=True, disabled=not selected_draft):
                _load_draft(Path(selected_draft), custom_params)
                st.success(tr("studio.load_draft_success", "草稿已载入"))
                st.rerun()


def _render_editor_toolbar() -> tuple[bool, bool]:
    left_action, right_action = st.columns(2)
    with left_action:
        refresh_requested = st.button(
            tr("studio.refresh_preview", "🖼️ 立即刷新"),
            type="primary",
            key="studio_refresh_preview",
            use_container_width=True,
        )
    with right_action:
        reset_requested = st.button(
            tr("studio.reset_defaults", "↺ 恢复默认"),
            key="studio_reset_defaults",
            use_container_width=True,
        )
    st.caption(
        tr(
            "studio.auto_preview_hint",
            "自动预览已开启：参数或样例数据发生变化后，画布会重新生成。",
        )
    )
    return refresh_requested, reset_requested


def _render_editor_canvas(
    template_path: str,
    template_width: int,
    template_height: int,
    template_elements: tuple[TemplateElement, ...],
    element_views: dict[str, dict[str, Any]],
    selected_element_id: str,
    preview_path: str,
    preview_error: str,
) -> None:
    with st.container(border=True):
        st.markdown(f"**{tr('studio.canvas', '编辑画布')} · {tr('template.preview_title', '模板预览')}**")
        st.caption(
            tr(
                "studio.canvas_hint",
                "真实预览和编辑热点已经合在同一块画布里。未选中元素只保留轻量标签，减少遮挡。",
            )
        )
        if preview_error:
            st.error(preview_error)
        elif preview_path and Path(preview_path).exists():
            st.caption(
                tr("template.preview_caption", "模板预览：{template}", template=template_path)
                + f" · {tr('studio.preview_ready', '已同步')} · {_truncate_path(preview_path)}"
            )
        else:
            st.info(tr("studio.no_preview", "点击“刷新预览”后，这里会显示当前模板的最新效果。"))

        canvas_html = _build_canvas_markup(
            template_width=template_width,
            template_height=template_height,
            template_elements=template_elements,
            element_views=element_views,
            selected_element_id=selected_element_id,
            preview_data_uri=_image_data_uri(preview_path),
        )
        st.markdown(canvas_html, unsafe_allow_html=True)


def _render_selected_element_panel(
    selected_element: TemplateElement,
    custom_params: dict[str, dict[str, Any]],
    element_view: dict[str, Any],
) -> None:
    with st.container(border=True):
        st.markdown(f"**{tr('studio.properties', '属性面板')}**")
        st.markdown(f"### {selected_element.label}")
        st.caption(selected_element.description)

        _render_contextual_preview_controls(selected_element)

        meta_col, binding_col = st.columns(2)
        with meta_col:
            st.markdown(
                "<div class='studio-panel-label'>"
                + tr("studio.element_kind", "元素类型")
                + "</div><div class='studio-panel-code'>"
                + _kind_label(selected_element.kind)
                + "</div>",
                unsafe_allow_html=True,
            )
        with binding_col:
            binding_value = selected_element.field_name or tr("studio.not_applicable", "不适用")
            st.markdown(
                "<div class='studio-panel-label'>"
                + tr("studio.field_binding", "字段绑定")
                + "</div><div class='studio-panel-code'>"
                + escape(binding_value)
                + "</div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<div class='studio-panel-label'>"
            + tr("studio.selector", "模板节点选择器")
            + "</div><div class='studio-panel-code'>"
            + escape(selected_element.selector)
            + "</div>",
            unsafe_allow_html=True,
        )
        _render_element_geometry_metrics(element_view)
        _render_element_specific_controls(selected_element, custom_params, element_view)


def _render_element_geometry_metrics(element_view: dict[str, Any]) -> None:
    st.markdown(f"**{tr('studio.geometry', '画布几何')}**")
    metric_col_1, metric_col_2 = st.columns(2)
    with metric_col_1:
        st.metric("X", f"{round(element_view['x'])} px")
        st.metric("W", f"{round(element_view['width'])} px")
    with metric_col_2:
        st.metric("Y", f"{round(element_view['y'])} px")
        st.metric("H", f"{round(element_view['height'])} px")


def _render_element_specific_controls(
    element: TemplateElement,
    custom_params: dict[str, dict[str, Any]],
    element_view: dict[str, Any],
) -> None:
    if element.kind == "DynamicField":
        st.markdown(f"**{tr('studio.dynamic_field', '动态字段')}**")
        _render_dynamic_field_help(element, element_view)
    st.markdown(f"**{tr('studio.param_controls', '可调参数')}**")
    for param_name in element.param_names:
        _render_param_control(param_name, custom_params)


def _render_contextual_preview_controls(selected_element: TemplateElement) -> None:
    if selected_element.field_name is None:
        return

    st.markdown(f"**{tr('studio.preview_content', '预览数据')}**")
    if selected_element.field_name == "title":
        st.caption(tr("studio.title_preview_hint", "标题槽位只需要当前标题样例。"))
        st.text_input(tr("template.preview_param_title", "标题"), key="studio_preview_title")
        return

    if selected_element.field_name == "image":
        st.caption(tr("studio.image_preview_hint", "插图槽位只需要当前图片样例。"))
        st.text_input(
            tr("template.preview_param_image", "图片路径"),
            key="studio_preview_image",
            help=tr("template.preview_image_help", "支持本地路径或 URL"),
        )
        return

    if selected_element.field_name == "text":
        st.caption(tr("studio.preview_content_hint", "先切换短/中/长样例，再观察字幕容器是否稳定。"))
        dataset_choice = st.radio(
            tr("studio.sample_data", "字幕样例"),
            list(PREVIEW_DATASETS.keys()),
            format_func=lambda key: PREVIEW_DATASETS[key]["label"],
            horizontal=True,
            key="studio_preview_dataset",
            label_visibility="collapsed",
        )
        _apply_preview_dataset_choice(dataset_choice)
        st.text_area(
            tr("template.preview_param_text", "文本"),
            key="studio_preview_text",
            height=140,
        )


def _render_dynamic_field_help(element: TemplateElement, element_view: dict[str, Any]) -> None:
    if element.field_name == "title":
        st.info(
            tr(
                "studio.dynamic_title_hint",
                "标题槽位绑定 `title`。这里编辑的是标题条高度、左右留白、字号和颜色。",
            )
        )
        return

    if element.field_name == "image":
        st.info(
            tr(
                "studio.dynamic_image_hint",
                "插图槽位绑定 `image`。这里编辑的是插图容器和填充策略，不是某一张固定图片。",
            )
        )
        return

    if element.field_name == "text":
        st.info(
            tr(
                "studio.dynamic_text_hint",
                "字幕槽位绑定 `text`。这里改的是字幕容器和排版规则，不是把样例文案写死进模板。",
            )
        )
        sample_preview = _truncate_text_for_panel(st.session_state["studio_preview_text"])
        st.caption(tr("studio.dynamic_text_sample", "当前字幕样例"))
        st.code(sample_preview)
        info_col_1, info_col_2 = st.columns(2)
        with info_col_1:
            st.metric(tr("studio.sample_chars", "样例字数"), str(len(st.session_state["studio_preview_text"])))
        with info_col_2:
            st.metric(tr("studio.sample_lines", "样例行数"), str(st.session_state["studio_preview_text"].count("\n") + 1))
        field_label = element_view.get("field_label", "[字幕]")
        st.caption(f"{tr('studio.slot_label', '槽位标签')}: {field_label}")


def _apply_preview_dataset_choice(dataset_choice: str) -> None:
    if st.session_state.get("studio_preview_dataset_applied") == dataset_choice:
        return
    dataset = PREVIEW_DATASETS[dataset_choice]
    st.session_state["studio_preview_title"] = dataset["title"]
    st.session_state["studio_preview_text"] = dataset["text"]
    st.session_state["studio_preview_image"] = dataset["image"]
    st.session_state["studio_preview_dataset_applied"] = dataset_choice


def _render_param_control(param_name: str, custom_params: dict[str, dict[str, Any]]) -> None:
    config = custom_params.get(param_name, {"type": "text", "default": ""})
    widget_key = _param_key(param_name)
    label = PARAM_LABELS.get(param_name, config.get("label", param_name))
    param_type = config.get("type", "text")

    if param_name in PARAM_OPTIONS:
        options = list(PARAM_OPTIONS[param_name])
        current_value = str(st.session_state.get(widget_key, options[0]))
        index = options.index(current_value) if current_value in options else 0
        st.selectbox(label, options, index=index, key=widget_key)
        return

    if param_type == "text":
        st.text_input(label, key=widget_key)
        return

    if param_type == "number":
        current_value = st.session_state.get(widget_key, config.get("default", 0))
        if not isinstance(current_value, bool) and isinstance(current_value, (int, float)):
            st.session_state[widget_key] = float(current_value)
        step = 1.0
        st.number_input(label, step=step, key=widget_key)
        return

    if param_type == "color":
        st.color_picker(label, key=widget_key)
        return

    if param_type == "bool":
        st.checkbox(label, key=widget_key)
        return

    st.text_input(label, key=widget_key)


def _build_canvas_markup(
    template_width: int,
    template_height: int,
    template_elements: tuple[TemplateElement, ...],
    element_views: dict[str, dict[str, Any]],
    selected_element_id: str,
    preview_data_uri: str | None,
) -> str:
    canvas_html = [
        "<div class='studio-canvas-shell'><div class='studio-canvas'><div class='studio-phone'>"
    ]
    if preview_data_uri:
        canvas_html.append(f"<img class='studio-preview-image' src='{preview_data_uri}' alt='template preview'>")
    for element in sorted(template_elements, key=lambda item: item.z_index):
        view = element_views[element.id]
        class_name = _kind_css_class(element.kind)
        selected_class = " is-selected" if element.id == selected_element_id else ""
        divider_class = " studio-divider-chip" if element.id == "caption_divider" else ""
        href = f"?studio_selected={element.id}"
        canvas_html.extend(
            [
                f"<a class='studio-element {class_name}{selected_class}{divider_class}' "
                f"href='{href}' target='_self' style='{_build_element_style(view)}'>",
                f"<span class='studio-element-kind'>{escape(_kind_label(element.kind))}</span>",
                f"<div class='studio-element-title' style='color: {view['title_color']};'>{view['title_html']}</div>",
                f"<div class='studio-element-body' style='color: {view['body_color']};'>{view['body_html']}</div>",
                "</a>",
            ]
        )
    canvas_html.extend(["</div></div></div>"])
    return "".join(canvas_html)


def _build_element_style(view: dict[str, Any]) -> str:
    left = _to_percent(view["x"], view["canvas_width"])
    top = _to_percent(view["y"], view["canvas_height"])
    width = _to_percent(view["width"], view["canvas_width"])
    height = _to_percent(view["height"], view["canvas_height"])
    background = view["background"]
    border_color = view["border_color"]
    return (
        f"left: {left}; top: {top}; width: {width}; height: {height}; "
        f"background: {background}; border-color: {border_color}; z-index: {view['z_index']};"
    )


def _build_sketch_card_element_views(
    template_width: int,
    template_height: int,
    current_values: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    width = float(template_width)
    height = float(template_height)

    title_bar_height = _number_value(current_values, "title_bar_height")
    title_bar_padding_x = _number_value(current_values, "title_bar_padding_x")
    illustration_bottom = _number_value(current_values, "illustration_bottom")
    illustration_padding_x = _number_value(current_values, "illustration_padding_x")
    illustration_top_padding = _number_value(current_values, "illustration_top_padding")
    illustration_bottom_padding = _number_value(current_values, "illustration_bottom_padding")
    illustration_card_padding = _number_value(current_values, "illustration_card_padding")
    divider_height = max(2.0, _number_value(current_values, "divider_height"))
    divider_inset = _number_value(current_values, "divider_inset")
    caption_section_height = _number_value(current_values, "caption_section_height")
    caption_padding_top = _number_value(current_values, "caption_padding_top")
    caption_padding_x = _number_value(current_values, "caption_padding_x")
    caption_padding_bottom = _number_value(current_values, "caption_padding_bottom")
    author_font_size = _number_value(current_values, "author_font_size")
    tagline_font_size = _number_value(current_values, "tagline_font_size")

    title_bar_bg = _color_value(current_values, "title_bar_bg")
    title_bar_border_color = _color_value(current_values, "title_bar_border_color")
    title_color = _color_value(current_values, "title_color")
    illustration_frame_color = _color_value(current_values, "illustration_frame_color")
    divider_color = _color_value(current_values, "divider_color")
    caption_text_color = _color_value(current_values, "caption_text_color")
    footer_text_color = _color_value(current_values, "footer_text_color")

    preview_title = st.session_state["studio_preview_title"]
    preview_text = st.session_state["studio_preview_text"]
    preview_image = st.session_state["studio_preview_image"]

    illustration_card_x = illustration_padding_x
    illustration_card_y = title_bar_height + illustration_top_padding
    illustration_card_width = width - illustration_padding_x * 2
    illustration_card_height = (
        height
        - illustration_bottom
        - title_bar_height
        - illustration_top_padding
        - illustration_bottom_padding
    )

    image_x = illustration_card_x + illustration_card_padding
    image_y = illustration_card_y + illustration_card_padding
    image_width = max(80.0, illustration_card_width - illustration_card_padding * 2)
    image_height = max(80.0, illustration_card_height - illustration_card_padding * 2)

    caption_section_y = height - caption_section_height
    meta_top_height = max(32.0, author_font_size * 1.4)
    tagline_height = max(28.0, tagline_font_size * 1.45)
    meta_block_height = meta_top_height + tagline_height + 22.0
    caption_text_height = max(
        120.0,
        caption_section_height - caption_padding_top - caption_padding_bottom - meta_block_height - 24.0,
    )

    author_brand_y = height - caption_padding_bottom - meta_block_height
    tagline_y = height - caption_padding_bottom - tagline_height
    author_width = max(180.0, (width - caption_padding_x * 2) * 0.56)
    brand_width = max(150.0, (width - caption_padding_x * 2) * 0.3)

    return {
        "title_bar": {
            "x": 0.0,
            "y": 0.0,
            "width": width,
            "height": title_bar_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 1,
            "background": title_bar_bg,
            "border_color": title_bar_border_color,
            "title_color": "#111827",
            "body_color": "#374151",
            "title_html": escape("标题栏背景"),
            "body_html": escape(f"高度 {round(title_bar_height)}px"),
        },
        "title": {
            "x": title_bar_padding_x,
            "y": 0.0,
            "width": max(120.0, width - title_bar_padding_x * 2),
            "height": title_bar_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 4,
            "background": "rgba(255, 255, 255, 0.48)",
            "border_color": "rgba(2, 132, 199, 0.40)",
            "title_color": title_color,
            "body_color": "#0f172a",
            "title_html": escape(_truncate_text(preview_title, 32)),
            "body_html": escape("[DynamicField] title"),
            "field_label": "[标题]",
        },
        "image_frame": {
            "x": illustration_card_x,
            "y": illustration_card_y,
            "width": illustration_card_width,
            "height": illustration_card_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 1,
            "background": "linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(250,250,250,0.92) 100%)",
            "border_color": illustration_frame_color,
            "title_color": "#111827",
            "body_color": "#374151",
            "title_html": escape("插图卡片"),
            "body_html": escape("外框 / 留白"),
        },
        "image": {
            "x": image_x,
            "y": image_y,
            "width": image_width,
            "height": image_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 3,
            "background": (
                "radial-gradient(circle at top, rgba(14,165,233,0.16), transparent 46%), "
                "linear-gradient(180deg, rgba(255,255,255,0.82) 0%, rgba(240,249,255,0.82) 100%)"
            ),
            "border_color": "rgba(2, 132, 199, 0.38)",
            "title_color": "#0f172a",
            "body_color": "#0f172a",
            "title_html": escape("[插图]"),
            "body_html": escape(f"{current_values.get('illustration_fill_mode', 'contain')} · {_truncate_path(preview_image)}"),
            "field_label": "[插图]",
        },
        "caption_divider": {
            "x": divider_inset,
            "y": height - caption_section_height,
            "width": max(60.0, width - divider_inset * 2),
            "height": divider_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 2,
            "background": divider_color,
            "border_color": divider_color,
            "title_color": "#111827",
            "body_color": "#111827",
            "title_html": escape("分隔线"),
            "body_html": escape("Decoration"),
        },
        "text": {
            "x": caption_padding_x,
            "y": caption_section_y + caption_padding_top,
            "width": max(120.0, width - caption_padding_x * 2),
            "height": caption_text_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 4,
            "background": "rgba(14, 165, 233, 0.12)",
            "border_color": "rgba(2, 132, 199, 0.42)",
            "title_color": caption_text_color,
            "body_color": "#0f172a",
            "title_html": escape("[字幕]"),
            "body_html": _multiline_preview_html(preview_text),
            "field_label": "[字幕]",
        },
        "author": {
            "x": caption_padding_x,
            "y": author_brand_y,
            "width": author_width,
            "height": meta_top_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 4,
            "background": "rgba(34, 197, 94, 0.10)",
            "border_color": "rgba(34, 197, 94, 0.32)",
            "title_color": footer_text_color,
            "body_color": footer_text_color,
            "title_html": escape(_truncate_text(str(current_values["author"]), 48)),
            "body_html": escape("StaticText"),
        },
        "brand": {
            "x": width - caption_padding_x - brand_width,
            "y": author_brand_y,
            "width": brand_width,
            "height": meta_top_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 4,
            "background": "rgba(34, 197, 94, 0.10)",
            "border_color": "rgba(34, 197, 94, 0.32)",
            "title_color": footer_text_color,
            "body_color": footer_text_color,
            "title_html": escape(_truncate_text(str(current_values["brand"]), 28)),
            "body_html": escape("StaticText"),
        },
        "tagline": {
            "x": caption_padding_x,
            "y": tagline_y,
            "width": max(120.0, width - caption_padding_x * 2),
            "height": tagline_height,
            "canvas_width": width,
            "canvas_height": height,
            "z_index": 4,
            "background": "rgba(34, 197, 94, 0.10)",
            "border_color": "rgba(34, 197, 94, 0.32)",
            "title_color": footer_text_color,
            "body_color": footer_text_color,
            "title_html": escape(_truncate_text(str(current_values["tagline"]), 72)),
            "body_html": escape("StaticText"),
        },
    }


def _render_preview_panel(template_path: str, template_width: int, template_height: int) -> None:
    with st.container(border=True):
        st.markdown(f"**{tr('template.preview_title', '模板预览')}**")
        st.caption(f"{tr('template.size_info', '模板尺寸')}: {template_width} × {template_height}")

        preview_error = st.session_state.get("studio_preview_error")
        preview_path = st.session_state.get("studio_preview_path")

        if preview_error:
            st.error(preview_error)
            return

        if preview_path and Path(preview_path).exists():
            st.image(preview_path, caption=tr("template.preview_caption", "模板预览：{template}", template=template_path))
            st.caption(f"📁 {preview_path}")
            return

        st.info(tr("studio.no_preview", "点击“刷新预览”后，这里会显示当前模板的最新效果。"))


def _image_data_uri(preview_path: str) -> str | None:
    if not preview_path:
        return None

    path = Path(preview_path)
    if not path.exists():
        return None

    suffix = path.suffix.lower()
    if suffix == ".png":
        mime_type = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    else:
        return None

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _ensure_template_state(template_path: str, custom_params: dict[str, dict[str, Any]]) -> None:
    st.session_state.setdefault("studio_selected_template_path", template_path)
    st.session_state.setdefault("studio_preview_path", "")
    st.session_state.setdefault("studio_preview_error", "")
    st.session_state.setdefault("studio_selected_element_id", DEFAULT_SELECTED_ELEMENT_ID)
    st.session_state.setdefault("studio_preview_dataset", "medium")
    st.session_state.setdefault("studio_preview_dataset_applied", "")
    st.session_state.setdefault("studio_preview_title", PREVIEW_DATASETS["medium"]["title"])
    st.session_state.setdefault("studio_preview_text", PREVIEW_DATASETS["medium"]["text"])
    st.session_state.setdefault("studio_preview_image", PREVIEW_DATASETS["medium"]["image"])
    st.session_state.setdefault("studio_draft_name", "sketch_card")

    for param_name, config in custom_params.items():
        key = _param_key(param_name)
        st.session_state.setdefault(key, config.get("default"))


def _sync_selected_element_state(template_elements: tuple[TemplateElement, ...]) -> None:
    valid_ids = {element.id for element in template_elements}
    requested_element_id = st.query_params.get("studio_selected")
    if isinstance(requested_element_id, list):
        requested_element_id = requested_element_id[0] if requested_element_id else None
    if requested_element_id in valid_ids:
        st.session_state["studio_selected_element_id"] = requested_element_id
        return

    current_element_id = st.session_state.get("studio_selected_element_id", DEFAULT_SELECTED_ELEMENT_ID)
    if current_element_id not in valid_ids:
        st.session_state["studio_selected_element_id"] = DEFAULT_SELECTED_ELEMENT_ID


def _get_selected_element(template_elements: tuple[TemplateElement, ...]) -> TemplateElement:
    selected_id = st.session_state.get("studio_selected_element_id", DEFAULT_SELECTED_ELEMENT_ID)
    return next((element for element in template_elements if element.id == selected_id), template_elements[0])


def _set_selected_element(element_id: str) -> None:
    st.session_state["studio_selected_element_id"] = element_id
    st.query_params["studio_selected"] = element_id


def _get_template_elements(
    template_path: str,
    template_source: str | None = None,
    custom_params: dict[str, dict[str, Any]] | None = None,
) -> tuple[TemplateElement, ...]:
    protocol = TEMPLATE_PROTOCOLS.get(template_path)
    if not protocol:
        return ()
    return _build_protocol_elements(protocol)


def _prepare_live_template(
    template_path: str,
    template_source: str,
    custom_params: dict[str, dict[str, Any]],
) -> tuple[str, tuple[TemplateElement, ...], str]:
    protocol = TEMPLATE_PROTOCOLS.get(template_path)
    if not protocol:
        return template_source, (), "preview"
    instrumented_source, elements = _build_protocol_template_document(protocol, template_source, custom_params)
    return instrumented_source, elements, protocol.edit_strategy


def _build_protocol_template_document(
    protocol: TemplateProtocol,
    template_source: str,
    custom_params: dict[str, dict[str, Any]],
) -> tuple[str, tuple[TemplateElement, ...]]:
    soup = BeautifulSoup(template_source, "html.parser")
    body = soup.body or soup
    if not body.get("data-studio-node"):
        body["data-studio-node"] = "template_canvas"
    body["data-studio-slot"] = "template_canvas"

    assigned_params: set[str] = set()
    for slot in protocol.slots:
        matches = soup.select(slot.selector)
        if not matches:
            raise ValueError(f"Template protocol slot missing: {protocol.template_path} -> {slot.selector}")
        tag = matches[0]
        tag["data-studio-node"] = slot.node_name
        tag["data-studio-slot"] = slot.slot_name
        assigned_params.update(slot.param_names)

    elements = list(_build_protocol_elements(protocol))
    remaining_params = tuple(name for name in custom_params if name not in assigned_params)
    if remaining_params:
        elements.append(
            TemplateElement(
                id="template_canvas",
                label="版式参数",
                kind="Decoration",
                selector='[data-studio-node="template_canvas"]',
                description="未映射到具体槽位的模板参数",
                param_names=remaining_params,
                z_index=1,
                slot_name="template_canvas",
            )
        )
    return str(soup), tuple(elements)


def _reset_studio_defaults(custom_params: dict[str, dict[str, Any]]) -> None:
    for param_name, config in custom_params.items():
        st.session_state[_param_key(param_name)] = config.get("default")
    st.session_state["studio_preview_dataset"] = "medium"
    st.session_state["studio_preview_dataset_applied"] = ""
    st.session_state["studio_preview_title"] = PREVIEW_DATASETS["medium"]["title"]
    st.session_state["studio_preview_text"] = PREVIEW_DATASETS["medium"]["text"]
    st.session_state["studio_preview_image"] = PREVIEW_DATASETS["medium"]["image"]
    st.session_state["studio_preview_path"] = ""
    st.session_state["studio_preview_error"] = ""
    st.session_state["studio_selected_element_id"] = DEFAULT_SELECTED_ELEMENT_ID
    st.query_params["studio_selected"] = DEFAULT_SELECTED_ELEMENT_ID


def _generate_preview(template_path: str) -> None:
    _generate_preview(template_path, None)


def _generate_preview(template_path: str, preview_signature: str | None) -> None:
    custom_values = _get_current_param_values()
    with st.spinner(tr("template.preview_generating", "正在生成模板预览...")):
        try:
            generator = HTMLFrameGenerator(resolve_template_path(template_path))
            preview_path = run_async(
                generator.generate_frame(
                    title=st.session_state["studio_preview_title"],
                    text=st.session_state["studio_preview_text"],
                    image=st.session_state["studio_preview_image"],
                    ext={"index": 1, **custom_values},
                )
            )
            st.session_state["studio_preview_path"] = preview_path
            st.session_state["studio_preview_error"] = ""
            if preview_signature is None:
                preview_signature = _build_preview_signature(template_path)
            st.session_state["studio_preview_signature"] = preview_signature
        except Exception as exc:
            logger.exception(exc)
            st.session_state["studio_preview_error"] = tr(
                "template.preview_failed",
                "❌ 预览失败：{error}",
                error=str(exc),
            )


def _get_current_param_values() -> dict[str, Any]:
    prefix = "studio_param_"
    values: dict[str, Any] = {}
    for key, value in st.session_state.items():
        if key.startswith(prefix):
            values[key.removeprefix(prefix)] = value
    return values


def _build_preview_signature(template_path: str) -> str:
    payload = {
        "template_path": template_path,
        "preview_title": st.session_state.get("studio_preview_title", ""),
        "preview_text": st.session_state.get("studio_preview_text", ""),
        "preview_image": st.session_state.get("studio_preview_image", ""),
        "params": _get_current_param_values(),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _param_key(param_name: str) -> str:
    return f"studio_param_{param_name}"


def _kind_badge(kind: ElementKind) -> str:
    if kind == "StaticText":
        return "T"
    if kind == "DynamicField":
        return "D"
    return "•"


def _kind_label(kind: ElementKind) -> str:
    if kind == "StaticText":
        return "StaticText"
    if kind == "DynamicField":
        return "DynamicField"
    return "Decoration"


def _kind_css_class(kind: ElementKind) -> str:
    if kind == "StaticText":
        return "studio-kind-static"
    if kind == "DynamicField":
        return "studio-kind-dynamic"
    return "studio-kind-decoration"


def _number_value(values: dict[str, Any], key: str) -> float:
    value = values.get(key, 0)
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (float, int)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _color_value(values: dict[str, Any], key: str) -> str:
    value = str(values.get(key, "#000000")).strip()
    return value if value else "#000000"


def _to_percent(value: float, total: float) -> str:
    if total <= 0:
        return "0%"
    return f"{max(0.0, min(100.0, value / total * 100)):.4f}%"


def _truncate_text(value: str, limit: int) -> str:
    stripped = " ".join(value.split())
    if len(stripped) <= limit:
        return stripped
    return stripped[: max(limit - 1, 0)] + "…"


def _truncate_text_for_panel(value: str) -> str:
    lines = value.splitlines()
    clipped = "\n".join(lines[:4]).strip()
    if len(lines) > 4:
        return clipped + "\n..."
    return clipped


def _multiline_preview_html(value: str) -> str:
    lines = [escape(line) for line in value.splitlines() if line.strip()]
    if not lines:
        return "等待字幕样例"
    preview = lines[:4]
    if len(lines) > 4:
        preview.append("…")
    return "<br>".join(preview)


def _truncate_path(value: str) -> str:
    path = Path(value)
    name = path.name
    if len(name) <= 24:
        return name
    return name[:21] + "..."


def _build_live_editor_payload(
    *,
    selected_template: dict[str, Any],
    template_path: str,
    generator: HTMLFrameGenerator,
    custom_params: dict[str, dict[str, Any]],
    template_width: int,
    template_height: int,
) -> dict[str, Any]:
    live_template_source, elements, edit_strategy = _prepare_live_template(
        template_path,
        generator.template,
        custom_params,
    )
    if not selected_template["editable"]:
        elements = ()
        edit_strategy = "preview"
    default_selected_element_id = next(
        (element.id for element in elements if element.id == DEFAULT_SELECTED_ELEMENT_ID),
        None,
    )
    if default_selected_element_id is None:
        default_selected_element_id = next(
            (element.id for element in elements if element.field_name == "title"),
            None,
        )
    if default_selected_element_id is None:
        default_selected_element_id = elements[0].id if elements else ""
    params = {
        param_name: config.get("default")
        for param_name, config in custom_params.items()
    }
    rendered_default_html = generator._replace_parameters(
        live_template_source,
        {
            "index": 1,
            **params,
        },
    )
    preview_datasets = _build_template_preview_datasets(
        selected_template=selected_template,
        template_source=live_template_source,
        rendered_default_html=rendered_default_html,
    )
    preview_dataset_key = "medium"
    preview_dataset = dict(preview_datasets[preview_dataset_key])
    preview_image_source = _resolve_live_image_source(preview_dataset["image"])
    render_context = {
        "index": 1,
        **params,
        "title": preview_dataset["title"],
        "text": preview_dataset["text"],
        "image": preview_image_source,
    }
    rendered_html = generator._replace_parameters(live_template_source, render_context)
    official_preview_path = _get_template_preview_image_path(template_path)
    official_preview_source = _resolve_live_image_source(official_preview_path) if official_preview_path else ""
    if not selected_template["editable"] and official_preview_source:
        rendered_html = _build_official_preview_html(
            image_source=official_preview_source,
            label=selected_template.get("display_label", selected_template["label"]),
        )

    return {
        "template": {
            "label": selected_template.get("display_label", selected_template["label"]),
            "templatePath": template_path,
            "templateWidth": template_width,
            "templateHeight": template_height,
            "sizeLabel": selected_template["size_label"],
            "kindLabel": selected_template["kind_label"],
            "status": selected_template["status"],
            "statusLabel": selected_template["status_label"],
            "editable": bool(selected_template["editable"]),
            "mapped": bool(selected_template["mapped"]),
            "editStrategy": edit_strategy,
        },
        "elements": [
            {
                "id": element.id,
                "label": element.label,
                "kind": element.kind,
                "selector": element.selector,
                "description": element.description,
                "fieldName": element.field_name,
                "role": element.role,
                "paramNames": list(element.param_names),
                "zIndex": element.z_index,
                "bindingName": element.binding_name,
                "bindingSource": element.binding_source,
                "bindingAttribute": element.binding_attribute,
                "slotName": element.slot_name,
            }
            for element in elements
        ],
        "customParams": custom_params,
        "paramLabels": PARAM_LABELS,
        "paramOptions": {key: list(values) for key, values in PARAM_OPTIONS.items()},
        "paramOptionLabels": PARAM_OPTION_LABELS,
        "previewDatasets": preview_datasets,
        "previewDatasetKey": preview_dataset_key,
        "preview": {
            "title": preview_dataset["title"],
            "text": preview_dataset["text"],
            "image": preview_dataset["image"],
            "imageSrc": preview_image_source,
        },
        "params": params,
        "templateSourceHtml": live_template_source,
        "renderedHtml": rendered_html,
        "defaultSelectedElementId": default_selected_element_id,
        "officialPreviewSource": official_preview_source,
    }


def _build_initial_preview_dataset(
    *,
    selected_template: dict[str, Any],
    template_source: str,
) -> dict[str, str]:
    return dict(
        _build_template_preview_datasets(
            selected_template=selected_template,
            template_source=template_source,
        )["medium"]
    )


def _build_template_preview_datasets(
    *,
    selected_template: dict[str, Any],
    template_source: str,
    rendered_default_html: str | None = None,
) -> dict[str, dict[str, str]]:
    preview_defaults = _extract_preview_field_defaults(
        template_source,
        rendered_default_html=rendered_default_html,
    )
    display_name = str(selected_template.get("display_name") or selected_template.get("label") or "模板").strip()
    template_path = selected_template["template_path"]
    base_title = preview_defaults.get("title") or display_name
    base_image = preview_defaults.get("image") or _template_sample_image(display_name, template_path)

    datasets: dict[str, dict[str, str]] = {}
    for dataset_key, dataset in PREVIEW_DATASETS.items():
        dataset_text = _template_sample_text(display_name, template_path, dataset_key)
        datasets[dataset_key] = {
            "label": dataset["label"],
            "title": base_title,
            "text": dataset_text,
            "image": base_image,
        }

    default_text = preview_defaults.get("text")
    if default_text:
        datasets["medium"]["text"] = default_text

    return datasets


def _extract_preview_field_defaults(
    template_source: str,
    *,
    rendered_default_html: str | None = None,
) -> dict[str, str]:
    defaults: dict[str, str] = {}
    placeholder_fields: set[str] = set()
    for match in PLACEHOLDER_PATTERN.finditer(template_source):
        binding_name = match.group(1)
        default_value = match.group(3)
        if binding_name not in LIVE_PREVIEW_FIELDS:
            continue
        placeholder_fields.add(binding_name)
        if not default_value:
            continue
        defaults.setdefault(binding_name, default_value.strip())

    if not rendered_default_html:
        return defaults

    if "title" not in defaults and "title" not in placeholder_fields:
        title_default = _extract_visible_text_default(
            rendered_default_html,
            include_tokens=("title", "headline", "heading", "topic"),
            exclude_tokens=("accent", "author", "brand", "desc", "description", "logo", "mark", "meta", "quote", "subtitle", "tagline"),
            min_length=2,
            max_length=80,
        )
        if title_default:
            defaults["title"] = title_default

    if "text" not in defaults and "text" not in placeholder_fields:
        text_default = _extract_visible_text_default(
            rendered_default_html,
            include_tokens=("caption", "content", "excerpt", "quote", "story", "summary", "text"),
            exclude_tokens=("author", "brand", "headline", "logo", "subtitle", "tagline", "title", "topic"),
            min_length=6,
            max_length=420,
        )
        if text_default:
            defaults["text"] = text_default

    if "image" not in defaults and "image" not in placeholder_fields:
        image_default = _extract_visible_image_default(rendered_default_html)
        if image_default:
            defaults["image"] = image_default

    return defaults


def _extract_visible_text_default(
    rendered_default_html: str,
    *,
    include_tokens: tuple[str, ...],
    exclude_tokens: tuple[str, ...],
    min_length: int,
    max_length: int,
) -> str:
    soup = BeautifulSoup(rendered_default_html, "html.parser")
    best_value = ""
    best_score = float("-inf")

    for order, tag in enumerate(soup.find_all(["h1", "h2", "h3", "div", "p", "span"])):
        text = " ".join(tag.stripped_strings)
        if not text or "{{" in text or "}}" in text:
            continue
        if len(text) < min_length or len(text) > max_length:
            continue

        hint_text = _preview_hint_text(tag)
        if not any(token in hint_text for token in include_tokens):
            continue
        if any(token in hint_text for token in exclude_tokens):
            continue

        score = _visible_text_candidate_score(tag, hint_text, text)
        score -= order * 0.01
        if score > best_score:
            best_score = score
            best_value = text

    return best_value


def _extract_visible_image_default(rendered_default_html: str) -> str:
    soup = BeautifulSoup(rendered_default_html, "html.parser")
    best_value = ""
    best_score = float("-inf")

    for order, tag in enumerate(soup.find_all(["img", "image"])):
        source = str(tag.get("src") or tag.get("href") or "").strip()
        if not source or "{{" in source or "}}" in source or source in {"#", "about:blank"}:
            continue

        hint_text = _preview_hint_text(tag)
        if any(token in hint_text for token in ("avatar", "badge", "icon", "logo", "mark")):
            continue

        score = 120 if tag.name == "img" else 100
        if any(token in hint_text for token in ("cover", "hero", "image", "illustration", "media", "photo", "poster")):
            score += 24
        score -= order * 0.01
        if score > best_score:
            best_score = score
            best_value = source

    if best_value:
        return best_value

    background_pattern = re.compile(r"background-image\s*:\s*url\((['\"]?)([^)\"']+)\1\)", re.IGNORECASE)
    for match in background_pattern.finditer(rendered_default_html):
        source = match.group(2).strip()
        if source and "{{" not in source and "}}" not in source:
            return source
    return ""


def _preview_hint_text(tag: Tag) -> str:
    parts = [tag.name]
    for attr_name in ("class", "id", "data-studio-node", "role", "aria-label"):
        value = tag.get(attr_name)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _visible_text_candidate_score(tag: Tag, hint_text: str, text: str) -> float:
    score = 0.0
    tag_weight = {
        "h1": 80.0,
        "h2": 64.0,
        "h3": 52.0,
        "p": 38.0,
        "div": 30.0,
        "span": 20.0,
    }
    score += tag_weight.get(tag.name, 0.0)
    score += min(len(text), 160) / 6
    for token in ("title", "headline", "heading", "topic", "caption", "content", "excerpt", "quote", "story", "summary", "text"):
        if token in hint_text:
            score += 18.0
    return score


def _template_sample_text(display_name: str, template_path: str, dataset_key: str = "medium") -> str:
    normalized = f"{display_name} {template_path}".lower()
    for keywords, sample_texts in TEMPLATE_SAMPLE_TEXT_RULES:
        if any(keyword.lower() in normalized for keyword in keywords):
            return sample_texts.get(dataset_key, sample_texts["medium"])
    return {
        "short": "先放进去，再看版式。",
        "medium": "把你的内容放进来，再看版式是否合适。",
        "long": "先把内容放进画面里，再确认版式、留白和节奏是否真的在帮你表达重点。",
    }.get(dataset_key, "把你的内容放进来，再看版式是否合适。")


def _template_sample_image(display_name: str, template_path: str) -> str:
    width, height = parse_template_size(template_path)
    normalized = f"{display_name} {template_path}".lower()
    theme = {
        "start": "#f8fafc",
        "end": "#dbeafe",
        "accent": "#2563eb",
        "secondary": "#93c5fd",
        "text": "#0f172a",
    }
    for keywords, candidate in TEMPLATE_SAMPLE_IMAGE_THEME_RULES:
        if any(keyword.lower() in normalized for keyword in keywords):
            theme = candidate
            break

    title = escape(_truncate_text(display_name, 18))
    subtitle = escape(Path(template_path).stem.replace("_", " ").upper())
    size_label = escape(_format_size_label(Path(template_path).parent.name))
    illustration_width = max(int(width * 0.52), 240)
    illustration_height = max(int(height * 0.42), 220)
    illustration_x = width - illustration_width - max(int(width * 0.08), 48)
    illustration_y = max(int(height * 0.14), 72)
    card_x = max(int(width * 0.08), 48)
    card_y = max(int(height * 0.16), 96)
    card_width = max(int(width * 0.42), 260)
    card_height = max(int(height * 0.24), 180)
    radius = max(int(min(width, height) * 0.04), 28)

    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="{theme['start']}"/>
          <stop offset="100%" stop-color="{theme['end']}"/>
        </linearGradient>
        <linearGradient id="glow" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="{theme['secondary']}" stop-opacity="0.92"/>
          <stop offset="100%" stop-color="{theme['accent']}" stop-opacity="0.76"/>
        </linearGradient>
      </defs>
      <rect width="{width}" height="{height}" rx="{radius}" fill="url(#bg)"/>
      <circle cx="{int(width * 0.18)}" cy="{int(height * 0.2)}" r="{int(min(width, height) * 0.12)}" fill="{theme['secondary']}" fill-opacity="0.45"/>
      <rect x="{illustration_x}" y="{illustration_y}" width="{illustration_width}" height="{illustration_height}" rx="{radius}" fill="url(#glow)"/>
      <rect x="{illustration_x + 24}" y="{illustration_y + 24}" width="{illustration_width - 48}" height="{illustration_height - 48}" rx="{max(radius - 12, 16)}" fill="none" stroke="{theme['text']}" stroke-opacity="0.22" stroke-width="6"/>
      <rect x="{card_x}" y="{card_y}" width="{card_width}" height="{card_height}" rx="{radius}" fill="#ffffff" fill-opacity="0.78"/>
      <text x="{card_x + 32}" y="{card_y + 70}" fill="{theme['text']}" font-family="Arial, sans-serif" font-size="{max(int(width * 0.038), 26)}" font-weight="700">{title}</text>
      <text x="{card_x + 32}" y="{card_y + 124}" fill="{theme['text']}" fill-opacity="0.72" font-family="Arial, sans-serif" font-size="{max(int(width * 0.018), 15)}">{size_label}</text>
      <text x="{card_x + 32}" y="{card_y + 162}" fill="{theme['text']}" fill-opacity="0.54" font-family="Arial, sans-serif" font-size="{max(int(width * 0.014), 12)}" letter-spacing="2">{subtitle}</text>
    </svg>
    """.strip()
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _get_template_preview_image_path(template_path: str) -> str:
    path_parts = template_path.split("/")
    if len(path_parts) < 2:
        return ""

    size = path_parts[0]
    template_name = path_parts[1].removesuffix(".html")
    suffix = "" if get_language() == "zh_CN" else "_en"

    for ext in (".jpg", ".png"):
        preview_path = Path("docs/images") / size / f"{template_name}{suffix}{ext}"
        if preview_path.exists():
            return str(preview_path)

    for ext in (".jpg", ".png"):
        preview_path = Path("docs/images") / size / f"{template_name}{ext}"
        if preview_path.exists():
            return str(preview_path)

    return ""


def _build_official_preview_html(*, image_source: str, label: str) -> str:
    safe_src = image_source.replace("&", "&amp;").replace('"', "&quot;")
    safe_label = escape(label)
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      background: #ffffff;
      overflow: hidden;
    }}
    body {{
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    img {{
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
      background: #ffffff;
    }}
  </style>
</head>
<body>
  <img src="{safe_src}" alt="{safe_label}">
</body>
</html>
"""


def _resolve_live_image_source(value: str) -> str:
    if value.startswith(("http://", "https://", "data:")):
        return value

    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / value

    if not path.exists():
        return _placeholder_image_data_uri()

    suffix = path.suffix.lower()
    if suffix == ".png":
        mime_type = "image/png"
    elif suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    elif suffix == ".webp":
        mime_type = "image/webp"
    else:
        return _placeholder_image_data_uri()

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _placeholder_image_data_uri() -> str:
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
      <defs>
        <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#f8fafc"/>
          <stop offset="100%" stop-color="#dbeafe"/>
        </linearGradient>
      </defs>
      <rect width="1024" height="1024" rx="48" fill="url(#g)"/>
      <g fill="none" stroke="#94a3b8" stroke-width="24" stroke-linecap="round">
        <rect x="180" y="180" width="664" height="664" rx="36"/>
        <path d="M252 692l164-164 116 116 128-128 112 112"/>
        <circle cx="382" cy="374" r="46" fill="#cbd5e1" stroke="none"/>
      </g>
      <text x="512" y="910" text-anchor="middle" fill="#475569" font-family="Arial, sans-serif" font-size="42">Preview Image</text>
    </svg>
    """.strip()
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _build_live_editor_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4efe7;
      --panel: rgba(255,255,255,0.84);
      --panel-border: rgba(148, 163, 184, 0.22);
      --muted: #667085;
      --text: #111827;
      --accent: #ff5a36;
      --accent-soft: rgba(255, 90, 54, 0.14);
      --shadow: 0 18px 48px rgba(15, 23, 42, 0.10);
      --radius: 24px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "SF Pro Display", "SF Pro Text", "PingFang SC", "Noto Sans SC", sans-serif;
      background: #ffffff;
      color: var(--text);
    }}
    .studio-app {{
      padding: 4px 0 10px;
    }}
    .studio-shell {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 360px);
      grid-template-areas: "canvas inspector";
      gap: 18px;
      align-items: start;
    }}
    .panel {{
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--panel-border);
      border-radius: 18px;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
      backdrop-filter: blur(10px);
      padding: 14px;
      min-width: 0;
    }}
    .panel-inspector {{
      grid-area: inspector;
      background: transparent;
      border: 1px solid rgba(148, 163, 184, 0.14);
      border-radius: 16px;
      box-shadow: none;
      padding: 14px 14px 16px;
      min-width: 0;
    }}
    .panel h2, .panel h3, .panel h4, .panel p {{
      margin: 0;
    }}
    .meta-stack {{
      display: grid;
      gap: 9px;
    }}
    .eyebrow {{
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .template-title {{
      font-size: 20px;
      line-height: 1.08;
      font-weight: 700;
      margin-bottom: 4px;
    }}
    .template-title.is-compact {{
      font-size: 20px;
      line-height: 1.12;
      margin-bottom: 0;
    }}
    .template-desc {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 8px;
    }}
    .metric {{
      padding: 8px 10px;
      border-radius: 15px;
      background: rgba(255,255,255,0.75);
      border: 1px solid rgba(226, 232, 240, 0.9);
    }}
    .metric-label {{
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 4px;
    }}
    .metric-value {{
      font-size: 15px;
      font-weight: 700;
      line-height: 1.3;
      letter-spacing: -0.02em;
    }}
    .layer-section {{
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid rgba(148, 163, 184, 0.18);
    }}
    .template-list {{
      display: grid;
      gap: 8px;
      margin-top: 8px;
    }}
    .template-list-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
    }}
    .template-list-title {{
      font-size: 14px;
      font-weight: 800;
      color: var(--text);
      letter-spacing: -0.01em;
    }}
    .template-list-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 24px;
      height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: rgba(255, 90, 54, 0.14);
      color: #c2410c;
      font-size: 12px;
      font-weight: 800;
    }}
    .template-option {{
      width: 100%;
      appearance: none;
      border: 1px solid rgba(148, 163, 184, 0.2);
      background: rgba(255,255,255,0.86);
      border-radius: 16px;
      padding: 12px;
      text-align: left;
      cursor: pointer;
      transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
    }}
    .template-option:hover {{
      transform: translateY(-1px);
      box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
    }}
    .template-option.is-selected {{
      border-color: rgba(255, 90, 54, 0.78);
      background: linear-gradient(180deg, rgba(255, 90, 54, 0.12), rgba(255, 255, 255, 0.92));
      box-shadow: 0 10px 24px rgba(255, 90, 54, 0.12);
    }}
    .template-option[disabled] {{
      cursor: default;
      opacity: 1;
      transform: none;
    }}
    .template-option-top {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
    }}
    .template-option-title {{
      font-size: 14px;
      font-weight: 700;
      color: var(--text);
      line-height: 1.35;
    }}
    .template-option-meta {{
      margin-top: 4px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
    }}
    .template-option-note {{
      margin-top: 6px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
    }}
    .template-option-path {{
      margin-top: 8px;
      font-size: 11px;
      color: var(--muted);
      word-break: break-all;
    }}
    .template-option-size {{
      white-space: nowrap;
      font-size: 11px;
      font-weight: 700;
      color: var(--muted);
      padding-top: 2px;
    }}
    .template-option-tags {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .template-option-status {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 800;
    }}
    .template-option-status.is-editable {{
      background: rgba(34, 197, 94, 0.14);
      color: #15803d;
    }}
    .template-option-status.is-preview-only {{
      background: rgba(71, 85, 105, 0.12);
      color: #475569;
    }}
    .template-option-status.is-current {{
      background: rgba(255, 90, 54, 0.14);
      color: #c2410c;
    }}
    .template-chip {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      background: rgba(15, 23, 42, 0.06);
      color: var(--muted);
    }}
    .preset-section {{
      margin-top: 10px;
      padding-top: 12px;
      border-top: 1px solid rgba(148, 163, 184, 0.18);
    }}
    .preset-actions {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }}
    .preset-grid {{
      display: grid;
      gap: 10px;
    }}
    .preset-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }}
    .preset-item {{
      width: auto;
      border: 1px solid rgba(148, 163, 184, 0.18);
      background: rgba(255,255,255,0.62);
      border-radius: 999px;
      padding: 8px 11px;
      text-align: left;
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      color: var(--text);
      transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
    }}
    .preset-item:hover {{
      transform: translateY(-1px);
      border-color: rgba(255, 90, 54, 0.34);
    }}
    .preset-item.is-active {{
      border-color: rgba(255, 90, 54, 0.72);
      background: rgba(255, 90, 54, 0.12);
      color: #c2410c;
    }}
    .preset-status {{
      min-height: 18px;
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.4;
    }}
    .preset-status.is-error {{
      color: #b42318;
    }}
    .layer-group-title {{
      font-size: 12px;
      color: var(--muted);
      margin: 0;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .layer-group-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }}
    .layer-count {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 24px;
      height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.06);
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }}
    .layer-list {{
      display: grid;
      gap: 8px;
    }}
    .layer-button {{
      width: 100%;
      border: 1px solid rgba(148, 163, 184, 0.18);
      background: rgba(255,255,255,0.76);
      border-radius: 16px;
      padding: 10px 12px;
      text-align: left;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
      transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
      min-width: 0;
    }}
    .layer-button:hover {{
      transform: translateY(-1px);
      border-color: rgba(255, 90, 54, 0.34);
    }}
    .layer-button.is-selected {{
      border-color: rgba(255, 90, 54, 0.7);
      background: rgba(255, 90, 54, 0.12);
    }}
    .layer-chip {{
      min-width: 24px;
      height: 24px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 700;
      background: rgba(15, 23, 42, 0.06);
    }}
    .layer-label {{
      font-size: 13px;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .center-panel {{
      grid-area: canvas;
      padding: 0;
      min-width: 0;
    }}
    .inspector-topbar {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 6px;
    }}
    .inspector-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .reference-toggle.is-active {{
      background: rgba(255, 90, 54, 0.14);
      color: #c2410c;
    }}
    .reference-panel {{
      display: grid;
      gap: 10px;
      padding: 12px;
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.68);
    }}
    .reference-panel[hidden] {{
      display: none;
    }}
    .reference-caption {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      color: var(--muted);
    }}
    .reference-frame {{
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid rgba(148, 163, 184, 0.14);
      background: #ffffff;
    }}
    .reference-frame img {{
      display: block;
      width: 100%;
      max-height: 280px;
      object-fit: contain;
      background: #ffffff;
    }}
    .btn {{
      appearance: none;
      border: none;
      border-radius: 999px;
      cursor: pointer;
      padding: 11px 16px;
      font-size: 13px;
      font-weight: 700;
      transition: transform 120ms ease, opacity 120ms ease, background 120ms ease;
    }}
    .btn:hover {{ transform: translateY(-1px); }}
    .btn-primary {{
      background: var(--accent);
      color: white;
    }}
    .btn-secondary {{
      background: rgba(15, 23, 42, 0.06);
      color: var(--text);
    }}
    .preview-stage {{
      display: flex;
      justify-content: center;
      padding: 0;
    }}
    .preview-wrapper {{
      position: relative;
      width: min(100%, 720px);
      max-width: 100%;
      margin: 0;
      border-radius: 0;
      overflow: visible;
      background: transparent;
      min-height: 380px;
    }}
    .add-menu-layer {{
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 30;
    }}
    .add-menu {{
      position: absolute;
      width: 172px;
      border: 1px solid rgba(148, 163, 184, 0.24);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.96);
      box-shadow: 0 14px 36px rgba(15, 23, 42, 0.18);
      padding: 10px;
      pointer-events: auto;
      backdrop-filter: blur(10px);
    }}
    .add-menu-title {{
      font-size: 12px;
      font-weight: 700;
      color: #475569;
      margin-bottom: 8px;
    }}
    .add-menu-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
    }}
    .add-menu-button {{
      width: 100%;
      border: 1px solid rgba(148, 163, 184, 0.16);
      background: rgba(248, 250, 252, 0.96);
      color: #0f172a;
      border-radius: 12px;
      padding: 8px 10px;
      text-align: left;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: background 120ms ease, transform 120ms ease;
    }}
    .add-menu-button:hover {{
      background: rgba(241, 245, 249, 1);
      transform: translateY(-1px);
    }}
    .preview-frame {{
      position: absolute;
      left: 50%;
      top: 0;
      border: 1px solid rgba(148, 163, 184, 0.22);
      background: white;
      transform-origin: top center;
      box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
      border-radius: 12px;
      overflow: hidden;
    }}
    .panel-title {{
      font-size: 15px;
      font-weight: 700;
      margin-bottom: 2px;
    }}
    .panel-desc {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      margin-bottom: 0;
    }}
    .field-grid {{
      display: grid;
      gap: 12px;
    }}
    .micro-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .subsection-title {{
      font-size: 11px;
      color: var(--muted);
      margin: 2px 0 0;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .micro-actions {{
      display: flex;
      justify-content: flex-end;
      margin-bottom: 8px;
    }}
    .btn-small {{
      padding: 8px 12px;
      font-size: 12px;
    }}
    .field {{
      display: grid;
      gap: 6px;
    }}
    .field label {{
      font-size: 12px;
      color: var(--muted);
      font-weight: 600;
    }}
    .field input, .field textarea, .field select {{
      width: 100%;
      border: 1px solid rgba(148, 163, 184, 0.24);
      background: rgba(255,255,255,0.78);
      border-radius: 12px;
      padding: 10px 12px;
      min-height: 42px;
      font-size: 14px;
      color: var(--text);
      outline: none;
    }}
    .field input:focus, .field textarea:focus, .field select:focus {{
      border-color: rgba(255, 90, 54, 0.68);
      box-shadow: 0 0 0 3px rgba(255, 90, 54, 0.12);
    }}
    .checkbox-field {{
      gap: 8px;
    }}
    .checkbox-row {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
      font-weight: 600;
      color: var(--text);
      cursor: pointer;
    }}
    .checkbox-row input[type="checkbox"] {{
      width: 18px;
      height: 18px;
      margin: 0;
      padding: 0;
      border-radius: 6px;
      accent-color: var(--accent);
      box-shadow: none;
      flex: 0 0 auto;
    }}
    .checkbox-row span {{
      color: var(--text);
      line-height: 1.3;
    }}
    .field textarea {{
      min-height: 128px;
      resize: vertical;
      line-height: 1.55;
    }}
    .readonly-value {{
      min-height: 40px;
      border: 1px solid rgba(148, 163, 184, 0.16);
      background: rgba(255,255,255,0.48);
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 13px;
      color: var(--text);
      display: flex;
      align-items: center;
    }}
    .inline-note {{
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
      margin-top: 6px;
    }}
    .segment {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }}
    .segment button {{
      border: 1px solid rgba(148, 163, 184, 0.24);
      background: rgba(255,255,255,0.72);
      color: var(--text);
      padding: 9px 8px;
      border-radius: 12px;
      cursor: pointer;
      font-size: 12px;
      font-weight: 700;
    }}
    .segment button.is-active {{
      border-color: rgba(255, 90, 54, 0.72);
      background: rgba(255, 90, 54, 0.12);
      color: #c2410c;
    }}
    .property-block {{
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid rgba(148, 163, 184, 0.12);
      display: grid;
      gap: 8px;
    }}
    .property-block-first {{
      margin-top: 8px;
      padding-top: 0;
      border-top: none;
    }}
    .property-title {{
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 0;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .selection-head {{
      display: grid;
      gap: 1px;
      margin-top: 0;
    }}
    .selection-label {{
      font-size: 17px;
      font-weight: 700;
      line-height: 1.2;
      letter-spacing: -0.02em;
    }}
    .selection-summary {{
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
    }}
    .selection-inline {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      align-items: baseline;
      gap: 6px 12px;
      margin-top: 6px;
      padding-top: 10px;
      border-top: 1px solid rgba(148, 163, 184, 0.14);
      font-size: 12px;
      color: var(--muted);
    }}
    .selection-key {{
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .selection-value {{
      color: var(--text);
      font-weight: 700;
    }}
    .selection-separator {{
      display: none;
    }}
    .advanced-details {{
      margin-top: 2px;
      border-top: 1px solid rgba(148, 163, 184, 0.16);
      padding-top: 8px;
    }}
    .advanced-summary {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      cursor: pointer;
      list-style: none;
      font-size: 12px;
      font-weight: 700;
      color: var(--text);
    }}
    .advanced-summary::-webkit-details-marker {{
      display: none;
    }}
    .advanced-summary::after {{
      content: "▾";
      font-size: 12px;
      color: var(--muted);
      font-weight: 700;
      transition: transform 120ms ease;
    }}
    .advanced-details[open] .advanced-summary::after {{
      transform: rotate(180deg);
    }}
    .advanced-panel {{
      display: grid;
      gap: 8px;
      margin-top: 8px;
    }}
    .property-count {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 22px;
      height: 22px;
      padding: 0 8px;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.06);
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }}
    .empty-state {{
      padding: 4px 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}
    .layer-details summary {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      cursor: pointer;
      font-size: 12px;
      color: var(--muted);
      list-style: none;
      margin-bottom: 8px;
    }}
    .layer-details summary::-webkit-details-marker {{
      display: none;
    }}
    @media (max-width: 1180px) {{
      .studio-shell {{
        grid-template-columns: minmax(0, 1fr) minmax(300px, 332px);
      }}
      .panel-inspector {{
        position: static;
        max-height: none;
        overflow: visible;
      }}
    }}
    @media (max-width: 960px) {{
      .studio-shell {{
        grid-template-columns: 1fr;
        grid-template-areas:
          "canvas"
          "inspector";
      }}
      .panel-inspector {{
        position: static;
        max-height: none;
        overflow: visible;
      }}
      .preview-wrapper {{
        max-width: 100%;
      }}
      .inspector-topbar {{
        flex-direction: column;
        align-items: flex-start;
      }}
      .inspector-actions {{
        width: 100%;
        justify-content: flex-start;
      }}
    }}
    @media (max-width: 720px) {{
      .studio-app {{
        padding: 8px;
      }}
      .panel {{
        padding: 12px;
        border-radius: 18px;
      }}
      .panel-inspector {{
        padding: 12px;
      }}
      .meta-grid,
      .micro-grid {{
        grid-template-columns: 1fr;
      }}
      .segment {{
        grid-template-columns: 1fr;
      }}
      .preset-actions {{
        grid-template-columns: 1fr;
      }}
      .preview-wrapper {{
        width: 100%;
      }}
    }}
  </style>
</head>
<body>
  <div id="app" class="studio-app"></div>
  <script>
    const INITIAL = {payload_json};
    const STATE = JSON.parse(JSON.stringify(INITIAL));
    const APP = document.getElementById("app");
    let previewReady = false;
    let previewResizeHandler = null;
    let dragState = null;
    const STORAGE_PREFIX = "pixelle-template-studio:v2";
    const TRANSPARENT_BG_CACHE = new Map();
    const TRANSPARENT_BG_PENDING = new Map();

    if (!STATE.expandedGroups) {{
      STATE.expandedGroups = {{ decoration: false }};
    }}
    if (!STATE.elementOverrides) {{
      STATE.elementOverrides = {{}};
    }}
    if (!STATE.elementMetrics) {{
      STATE.elementMetrics = {{}};
    }}
    if (!STATE.advancedParamsOpen) {{
      STATE.advancedParamsOpen = {{}};
    }}
    if (!STATE.userElements) {{
      STATE.userElements = [];
    }}
    STATE.userElementCounter = Number(STATE.userElementCounter || 0);
    STATE.addMenu = {{ open: false, frameX: 0, frameY: 0, x: 0, y: 0 }};
    STATE.selectedElementId = STATE.selectedElementId || STATE.defaultSelectedElementId || ((STATE.elements[0] || STATE.userElements[0]) && (STATE.elements[0] || STATE.userElements[0]).id) || "";
    STATE.saveName = STATE.saveName || defaultPresetName();
    STATE.activePresetName = STATE.activePresetName || "";
    STATE.saveStatus = STATE.saveStatus || "";
    STATE.saveStatusError = false;
    STATE.savedPresets = readSavedPresets();
    STATE.officialPreviewOpen = Boolean(STATE.officialPreviewSource && STATE.officialPreviewOpen);

    function paramToCssVar(paramName) {{
      return `--${{paramName.replace(/_/g, "-")}}`;
    }}

    function selectorNodeName(selector) {{
      const match = selector.match(/\\[data-studio-node="([^"]+)"\\]/);
      return match ? match[1] : null;
    }}

    function liveImageSource(value) {{
      if (value.startsWith("http://") || value.startsWith("https://") || value.startsWith("data:")) {{
        return value;
      }}
      if (value === STATE.preview.image) {{
        return STATE.preview.imageSrc;
      }}
      return STATE.preview.imageSrc;
    }}

    function cssValue(name, config, value) {{
      if (config.type === "number") return `${{value}}px`;
      return `${{value}}`;
    }}

    function allElements() {{
      return [...(STATE.elements || []), ...(STATE.userElements || [])];
    }}

    function elementById(elementId) {{
      return allElements().find((item) => item.id === elementId) || null;
    }}

    function selectedElement() {{
      return elementById(STATE.selectedElementId) || allElements()[0] || null;
    }}

    function layerGroups() {{
      return [
        {{ id: "content", title: "内容层", items: allElements().filter((item) => item.kind === "DynamicField"), collapsible: false }},
        {{ id: "static", title: "固定文案", items: allElements().filter((item) => item.kind === "StaticText"), collapsible: false }},
        {{ id: "decoration", title: "装饰层", items: allElements().filter((item) => item.kind === "Decoration"), collapsible: true }},
      ];
    }}

    function kindBadge(kind) {{
      if (kind === "DynamicField") return "D";
      if (kind === "StaticText") return "T";
      return "•";
    }}

    function kindLabel(kind) {{
      if (kind === "DynamicField") return "动态字段";
      if (kind === "StaticText") return "固定文案";
      return "装饰元素";
    }}

    function selectionSummary(element) {{
      if (!element) return "";
      if (element.isUserElement && element.kind === "StaticText") return "新增静态文案";
      if (element.isUserElement) return "新增装饰元素";
      if (element.fieldName === "title") return "标题内容与样式";
      if (element.fieldName === "text") return "字幕内容与排版";
      if (element.fieldName === "image") return "图片内容与容器";
      if (element.kind === "StaticText") return "固定文案";
      return "装饰与版式";
    }}

    function defaultElementOverride() {{
      return {{
        offsetX: 0,
        offsetY: 0,
        scale: 1,
        fontSize: null,
        color: "",
        textAlign: "",
        objectFit: "",
        removeBackground: false,
        bgThreshold: 244,
        bgSoftness: 18,
      }};
    }}

    function ensureElementOverride(elementId) {{
      if (!STATE.elementOverrides[elementId]) {{
        STATE.elementOverrides[elementId] = defaultElementOverride();
      }}
      return STATE.elementOverrides[elementId];
    }}

    function getElementOverride(elementId) {{
      return STATE.elementOverrides[elementId] || null;
    }}

    function isTextElement(element) {{
      return Boolean(element) && (
        element.fieldName === "title"
        || element.fieldName === "text"
        || element.kind === "StaticText"
        || (element.kind === "DynamicField" && element.fieldName !== "image")
      );
    }}

    function isImageElement(element) {{
      return Boolean(element) && (
        element.bindingAttribute === "src"
        || (!element.bindingAttribute && element.fieldName === "image")
      );
    }}

    function isUserElement(element) {{
      return Boolean(element && element.isUserElement);
    }}

    function isUserTextElement(element) {{
      return isUserElement(element) && element.kind === "StaticText";
    }}

    function defaultUserElementConfig(type, frameX, frameY) {{
      const presets = {{
        static_title: {{
          kind: "StaticText",
          label: "静态标题",
          description: "新增静态标题",
          width: 360,
          height: 84,
          text: "输入标题",
          fontSize: 42,
          fontWeight: "700",
          textColor: "#111827",
          background: "rgba(255, 255, 255, 0.78)",
          borderColor: "rgba(148, 163, 184, 0.18)",
          borderWidth: 1,
          borderRadius: 22,
          textAlign: "center",
          paddingX: 18,
          paddingY: 12,
          zIndex: 5,
        }},
        static_text: {{
          kind: "StaticText",
          label: "静态正文",
          description: "新增静态正文",
          width: 420,
          height: 128,
          text: "输入正文",
          fontSize: 28,
          fontWeight: "500",
          textColor: "#0f172a",
          background: "rgba(255, 255, 255, 0.72)",
          borderColor: "rgba(148, 163, 184, 0.12)",
          borderWidth: 1,
          borderRadius: 22,
          textAlign: "left",
          paddingX: 18,
          paddingY: 16,
          zIndex: 5,
        }},
        static_tag: {{
          kind: "StaticText",
          label: "静态标签",
          description: "新增静态标签",
          width: 220,
          height: 56,
          text: "标签",
          fontSize: 22,
          fontWeight: "700",
          textColor: "#ffffff",
          background: "#111827",
          borderColor: "#111827",
          borderWidth: 0,
          borderRadius: 999,
          textAlign: "center",
          paddingX: 18,
          paddingY: 8,
          zIndex: 6,
        }},
        divider: {{
          kind: "Decoration",
          label: "分隔线",
          description: "新增分隔线",
          width: 260,
          height: 6,
          text: "",
          fontSize: 0,
          fontWeight: "400",
          textColor: "#111827",
          background: "#111827",
          borderColor: "transparent",
          borderWidth: 0,
          borderRadius: 999,
          textAlign: "center",
          paddingX: 0,
          paddingY: 0,
          zIndex: 3,
        }},
        background_block: {{
          kind: "Decoration",
          label: "背景块",
          description: "新增背景块",
          width: 360,
          height: 180,
          text: "",
          fontSize: 0,
          fontWeight: "400",
          textColor: "#111827",
          background: "rgba(15, 23, 42, 0.08)",
          borderColor: "rgba(148, 163, 184, 0.18)",
          borderWidth: 1,
          borderRadius: 28,
          textAlign: "center",
          paddingX: 0,
          paddingY: 0,
          zIndex: 1,
        }},
        border_box: {{
          kind: "Decoration",
          label: "边框",
          description: "新增边框容器",
          width: 360,
          height: 220,
          text: "",
          fontSize: 0,
          fontWeight: "400",
          textColor: "#111827",
          background: "transparent",
          borderColor: "#111827",
          borderWidth: 2,
          borderRadius: 28,
          textAlign: "center",
          paddingX: 0,
          paddingY: 0,
          zIndex: 2,
        }},
      }};
      const config = presets[type];
      if (!config) return null;
      const width = Number(config.width);
      const height = Number(config.height);
      return {{
        ...config,
        x: clampNumber(frameX - width / 2, 0, Math.max(0, STATE.template.templateWidth - width), 0),
        y: clampNumber(frameY - height / 2, 0, Math.max(0, STATE.template.templateHeight - height), 0),
      }};
    }}

    function createUserElement(type, frameX, frameY) {{
      const config = defaultUserElementConfig(type, frameX, frameY);
      if (!config) return null;
      STATE.userElementCounter += 1;
      const id = `user_${{type}}_${{STATE.userElementCounter}}`;
      return {{
        id,
        label: config.label,
        kind: config.kind,
        selector: `[data-studio-node="${{id}}"]`,
        description: config.description,
        fieldName: null,
        role: type,
        paramNames: [],
        zIndex: config.zIndex,
        bindingName: type,
        bindingSource: "param",
        bindingAttribute: null,
        slotName: id,
        isUserElement: true,
        userType: type,
        userConfig: config,
      }};
    }}

    function removeUserElement(elementId) {{
      STATE.userElements = (STATE.userElements || []).filter((item) => item.id !== elementId);
      delete STATE.elementOverrides[elementId];
      delete STATE.elementMetrics[elementId];
      delete STATE.advancedParamsOpen[elementId];
      if (STATE.selectedElementId === elementId) {{
        const fallback = allElements()[0];
        STATE.selectedElementId = fallback ? fallback.id : "";
      }}
      hideAddMenu();
      syncSelectionUI(true);
    }}

    function selectedPreviewDoc() {{
      const frame = APP.querySelector("#preview-frame");
      return previewReady && frame ? frame.contentDocument : null;
    }}

    function colorToHex(value) {{
      if (!value) return "#111827";
      if (value.startsWith("#")) return value.slice(0, 7);
      const match = value.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
      if (!match) return "#111827";
      return `#${{[match[1], match[2], match[3]].map((item) => Number(item).toString(16).padStart(2, "0")).join("")}}`;
    }}

    function elementMetrics(element) {{
      if (!element) return null;
      const doc = selectedPreviewDoc();
      if (!doc) return STATE.elementMetrics[element.id] || null;
      const node = doc.querySelector(element.selector);
      if (!node) return STATE.elementMetrics[element.id] || null;
      const rect = node.getBoundingClientRect();
      const bodyRect = doc.body.getBoundingClientRect();
      const styles = doc.defaultView.getComputedStyle(node);
      const metrics = {{
        x: Math.round(rect.left - bodyRect.left),
        y: Math.round(rect.top - bodyRect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        fontSize: Math.round(parseFloat(styles.fontSize) || 0),
        color: colorToHex(styles.color),
        textAlign: styles.textAlign || "left",
        objectFit: styles.objectFit || "cover",
      }};
      STATE.elementMetrics[element.id] = metrics;
      return metrics;
    }}

    function canEditCurrentTemplate() {{
      return Boolean(STATE.template && STATE.template.editable && allElements().length);
    }}

    function isMappedTemplate() {{
      return STATE.template && STATE.template.editStrategy === "mapped";
    }}

    function isProtocolTemplate() {{
      return STATE.template && STATE.template.editStrategy === "protocol";
    }}

    function usesLiveDomPreview() {{
      return Boolean(STATE.template) && (isMappedTemplate() || isProtocolTemplate());
    }}

    function hasOfficialPreview() {{
      return Boolean(STATE.officialPreviewSource);
    }}

    function escapeHtml(value) {{
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }}

    function defaultPresetName() {{
      const raw = (STATE.template.label || "模板方案").split("/")[0].trim();
      return raw || "模板方案";
    }}

    function currentRenderContext() {{
      return {{
        index: 1,
        ...STATE.params,
        title: STATE.preview.title,
        text: STATE.preview.text,
        image: liveImageSource(STATE.preview.image),
      }};
    }}

    function renderTemplateHtml() {{
      if (!canEditCurrentTemplate()) {{
        return String(STATE.renderedHtml || STATE.templateSourceHtml || "");
      }}
      const context = currentRenderContext();
      const source = String(STATE.templateSourceHtml || "");
      let output = "";
      let cursor = 0;

      while (cursor < source.length) {{
        const start = source.indexOf("{{{{", cursor);
        if (start === -1) {{
          output += source.slice(cursor);
          break;
        }}
        const end = source.indexOf("}}}}", start + 2);
        if (end === -1) {{
          output += source.slice(cursor);
          break;
        }}

        output += source.slice(cursor, start);
        const token = source.slice(start + 2, end);
        const name = token.split("=")[0].split(":")[0].trim();
        const value = context[name];
        output += value === undefined || value === null ? "" : String(value);
        cursor = end + 2;
      }}

      return output;
    }}

    function templateStoragePrefix() {{
      return `${{STORAGE_PREFIX}}:${{STATE.template.templatePath}}:`;
    }}

    function presetStorageKey(name) {{
      return `${{templateStoragePrefix()}}${{name}}`;
    }}

    function readSavedPresets() {{
      try {{
        const prefix = templateStoragePrefix();
        return Object.keys(localStorage)
          .filter((key) => key.startsWith(prefix))
          .map((key) => {{
            const name = key.slice(prefix.length);
            let savedAt = 0;
            try {{
              const payload = JSON.parse(localStorage.getItem(key) || "{{}}");
              savedAt = Number(payload.savedAt || 0);
            }} catch (error) {{
              savedAt = 0;
            }}
            return {{ name, savedAt }};
          }})
          .sort((left, right) => right.savedAt - left.savedAt || left.name.localeCompare(right.name, "zh-Hans-CN"));
      }} catch (error) {{
        return [];
      }}
    }}

    function setSaveStatus(message, isError = false) {{
      STATE.saveStatus = message;
      STATE.saveStatusError = isError;
      const node = APP.querySelector("#preset-status");
      if (!node) return;
      node.textContent = message;
      node.classList.toggle("is-error", isError);
    }}

    function renderSavePanel() {{
      const container = APP.querySelector("#preset-panel");
      if (!container) return;
      if (!canEditCurrentTemplate()) {{
        container.innerHTML = `<div class="empty-state">暂不支持保存</div>`;
        return;
      }}

      container.innerHTML = `
        <div class="preset-grid">
          <div class="field">
            <label for="preset-name">方案名</label>
            <input id="preset-name" type="text" value="${{String(STATE.saveName || "").replace(/"/g, "&quot;")}}" placeholder="例如：品牌版">
          </div>
          <div class="field">
            <label for="preset-select">已存方案</label>
            <select id="preset-select">
              <option value="">${{STATE.savedPresets.length ? "选择方案" : "暂无方案"}}</option>
              ${{STATE.savedPresets.map((item) => `<option value="${{item.name}}" ${{item.name === STATE.activePresetName ? "selected" : ""}}>${{item.name}}</option>`).join("")}}
            </select>
          </div>
        </div>
        <div class="preset-actions">
          <button class="btn btn-primary" id="save-preset">保存方案</button>
          <button class="btn btn-secondary" id="load-preset" ${{STATE.activePresetName ? "" : "disabled"}}>载入方案</button>
          <button class="btn btn-secondary" id="delete-preset" ${{STATE.activePresetName ? "" : "disabled"}}>删除</button>
        </div>
        <div class="preset-status${{STATE.saveStatusError ? " is-error" : ""}}" id="preset-status">${{STATE.saveStatus || ""}}</div>
      `;

      const nameInput = container.querySelector("#preset-name");

      nameInput.addEventListener("input", (event) => {{
        STATE.saveName = event.target.value;
      }});

      container.querySelector("#preset-select").addEventListener("change", (event) => {{
        const name = event.target.value;
        STATE.activePresetName = name;
        if (name) {{
          STATE.saveName = name;
          setSaveStatus(`已选中：${{name}}`);
        }} else {{
          setSaveStatus("");
        }}
        renderSavePanel();
      }});

      container.querySelector("#save-preset").addEventListener("click", () => {{
        saveCurrentPreset();
      }});
      container.querySelector("#load-preset").addEventListener("click", () => {{
        loadPresetByName(STATE.activePresetName);
      }});
      container.querySelector("#delete-preset").addEventListener("click", () => {{
        deleteCurrentPreset();
      }});
    }}

    function saveCurrentPreset() {{
      const name = String(STATE.saveName || "").trim();
      if (!name) {{
        setSaveStatus("请先输入方案名。", true);
        return;
      }}

      const payload = {{
        version: 2,
        templatePath: STATE.template.templatePath,
        savedAt: Date.now(),
        selectedElementId: STATE.selectedElementId,
        previewDatasetKey: STATE.previewDatasetKey,
        preview: JSON.parse(JSON.stringify(STATE.preview)),
        params: JSON.parse(JSON.stringify(STATE.params)),
        elementOverrides: JSON.parse(JSON.stringify(STATE.elementOverrides)),
        userElements: JSON.parse(JSON.stringify(STATE.userElements || [])),
        userElementCounter: Number(STATE.userElementCounter || 0),
        expandedGroups: JSON.parse(JSON.stringify(STATE.expandedGroups)),
      }};

      try {{
        localStorage.setItem(presetStorageKey(name), JSON.stringify(payload));
        STATE.activePresetName = name;
        STATE.saveName = name;
        STATE.savedPresets = readSavedPresets();
        renderSavePanel();
        setSaveStatus(`已保存方案：${{name}}`);
      }} catch (error) {{
        setSaveStatus("保存失败，请检查浏览器存储权限。", true);
      }}
    }}

    function applyPresetPayload(payload) {{
      if (!payload || payload.templatePath !== STATE.template.templatePath) return false;

      if (payload.selectedElementId) {{
        STATE.selectedElementId = payload.selectedElementId;
      }}
      if (payload.previewDatasetKey) {{
        STATE.previewDatasetKey = payload.previewDatasetKey;
      }}
      if (payload.preview) {{
        STATE.preview = JSON.parse(JSON.stringify(payload.preview));
      }}
      if (payload.params) {{
        STATE.params = JSON.parse(JSON.stringify(payload.params));
      }}
      if (payload.elementOverrides) {{
        STATE.elementOverrides = JSON.parse(JSON.stringify(payload.elementOverrides));
      }}
      STATE.userElements = Array.isArray(payload.userElements)
        ? JSON.parse(JSON.stringify(payload.userElements))
        : [];
      STATE.userElementCounter = Number(payload.userElementCounter || 0);
      if (payload.expandedGroups) {{
        STATE.expandedGroups = JSON.parse(JSON.stringify(payload.expandedGroups));
      }}
      hideAddMenu();
      return true;
    }}

    function loadPresetByName(name) {{
      if (!name) {{
        setSaveStatus("请先选择要载入的方案。", true);
        return;
      }}

      try {{
        const payload = JSON.parse(localStorage.getItem(presetStorageKey(name)) || "null");
        if (!applyPresetPayload(payload)) {{
          setSaveStatus("载入失败：方案与当前模板不匹配。", true);
          return;
        }}
        STATE.activePresetName = name;
        STATE.saveName = name;
        syncSelectionUI(true);
        renderSavePanel();
        setSaveStatus(`已载入方案：${{name}}`);
      }} catch (error) {{
        setSaveStatus("载入失败，保存数据可能已损坏。", true);
      }}
    }}

    function deleteCurrentPreset() {{
      const name = STATE.activePresetName;
      if (!name) {{
        setSaveStatus("请先选择要删除的方案。", true);
        return;
      }}

      if (!window.confirm(`删除保存方案「${{name}}」？`)) {{
        return;
      }}

      try {{
        localStorage.removeItem(presetStorageKey(name));
        STATE.savedPresets = readSavedPresets();
        STATE.activePresetName = "";
        if (STATE.saveName === name) {{
          STATE.saveName = defaultPresetName();
        }}
        renderSavePanel();
        setSaveStatus(`已删除方案：${{name}}`);
      }} catch (error) {{
        setSaveStatus("删除失败，请稍后重试。", true);
      }}
    }}

    function renderLayerGroupHeading(group, useSummary = false) {{
      if (useSummary) {{
        return `
          <summary>
            <span>${{group.title}}</span>
            <span class="layer-count">${{group.items.length}}</span>
          </summary>
        `;
      }}
      return `
        <div class="layer-group-head">
          <div class="layer-group-title">${{group.title}}</div>
          <span class="layer-count">${{group.items.length}}</span>
        </div>
      `;
    }}

    function isGroupExpanded(group) {{
      return Boolean(STATE.expandedGroups[group.id]);
    }}

    function renderOfficialPreviewPanel() {{
      const panel = APP.querySelector("#official-preview-panel");
      const toggle = APP.querySelector("#toggle-official-preview");

      if (toggle) {{
        toggle.hidden = !hasOfficialPreview();
        toggle.textContent = STATE.officialPreviewOpen ? "收起参考图" : "参考图";
        toggle.classList.toggle("is-active", Boolean(STATE.officialPreviewOpen));
        toggle.setAttribute("aria-expanded", STATE.officialPreviewOpen ? "true" : "false");
      }}

      if (!panel) return;
      if (!hasOfficialPreview() || !STATE.officialPreviewOpen) {{
        panel.hidden = true;
        panel.innerHTML = "";
        return;
      }}

      panel.hidden = false;
      panel.innerHTML = `
        <div class="reference-panel">
          <div class="reference-caption">README / docs 官方参考图</div>
          <div class="reference-frame">
            <img
              src="${{escapeHtml(STATE.officialPreviewSource)}}"
              alt="${{escapeHtml(`${{STATE.template.label}} 官方参考图`)}}"
              loading="lazy"
              decoding="async"
            >
          </div>
        </div>
      `;
    }}

    function renderShell() {{
      APP.innerHTML = `
        <div class="studio-shell">
          <main class="center-panel">
            <div class="preview-stage">
              <div class="preview-wrapper" id="preview-wrapper">
                <iframe id="preview-frame" class="preview-frame" title="模板预览"></iframe>
                <div id="add-menu-layer" class="add-menu-layer"></div>
              </div>
            </div>
          </main>
          <aside class="panel-inspector">
            <div class="inspector-topbar">
              <div>
                <div class="eyebrow">模板</div>
                <div class="template-title is-compact">${{STATE.template.label}}</div>
              </div>
              <div class="inspector-actions">
                ${{hasOfficialPreview() ? '<button class="btn btn-secondary btn-small reference-toggle" id="toggle-official-preview" type="button">参考图</button>' : ""}}
                <button class="btn btn-secondary btn-small" id="reset-live" ${{canEditCurrentTemplate() ? "" : "disabled"}}>恢复默认</button>
              </div>
            </div>
            <div id="official-preview-panel" hidden></div>
            <div class="property-block property-block-first">
              <div class="property-title">方案</div>
              <div id="preset-panel"></div>
            </div>
            <div class="property-block">
              <div class="selection-head">
                <div class="selection-label" id="selected-label"></div>
                <p class="selection-summary" id="selected-description"></p>
              </div>
              <div class="selection-inline">
                <span class="selection-key">类型</span>
                <span class="selection-value" id="selected-kind"></span>
                <span class="selection-separator"></span>
                <span class="selection-key">绑定</span>
                <span class="selection-value" id="selected-field"></span>
              </div>
            </div>
            <div class="property-block">
              <div class="property-title">内容</div>
              <div id="context-panel"></div>
            </div>
            <div class="property-block">
              <div class="property-title">微调</div>
              <div class="field-grid" id="property-panel"></div>
            </div>
          </aside>
        </div>
      `;

      APP.querySelector("#reset-live").addEventListener("click", () => {{
        resetState();
        syncSelectionUI(true);
      }});
      const officialPreviewToggle = APP.querySelector("#toggle-official-preview");
      if (officialPreviewToggle) {{
        officialPreviewToggle.addEventListener("click", () => {{
          STATE.officialPreviewOpen = !STATE.officialPreviewOpen;
          renderOfficialPreviewPanel();
        }});
      }}

      APP.addEventListener("click", (event) => {{
        if (!STATE.addMenu.open) return;
        if (event.target.closest(".add-menu")) return;
        hideAddMenu();
      }});

      mountPreview();
      renderOfficialPreviewPanel();
      renderSavePanel();
      syncSelectionUI();
    }}

    function syncSelectionUI(forceRerender = false) {{
      const selected = selectedElement();

      if (!selected) {{
        APP.querySelector("#selected-label").textContent = canEditCurrentTemplate() ? "选择元素" : "暂无元素";
        APP.querySelector("#selected-description").textContent = canEditCurrentTemplate()
          ? "点预览开始编辑。"
          : "当前模板仅保留预览。";
        APP.querySelector("#selected-kind").textContent = canEditCurrentTemplate() ? "未选中" : "待识别";
        APP.querySelector("#selected-field").textContent = "无";
        renderContextPanel(null);
        renderPropertyPanel(null);
        if (forceRerender) {{
          rerenderPreview();
        }} else {{
          applyPreviewState();
        }}
        return;
      }}

      APP.querySelector("#selected-label").textContent = selected.label;
      APP.querySelector("#selected-description").textContent = selectionSummary(selected);
      APP.querySelector("#selected-kind").textContent = kindLabel(selected.kind);
      APP.querySelector("#selected-field").textContent = selected.slotName || selected.fieldName || "无";

      renderContextPanel(selected);
      renderPropertyPanel(selected);
      if (forceRerender) {{
        rerenderPreview();
      }} else {{
        applyPreviewState();
      }}
    }}

    function resetState() {{
      const preservedSaveName = STATE.saveName;
      const preservedActivePresetName = STATE.activePresetName;
      const preservedSavedPresets = STATE.savedPresets;
      const preservedOfficialPreviewOpen = STATE.officialPreviewOpen;
      const fresh = JSON.parse(JSON.stringify(INITIAL));
      Object.keys(STATE).forEach((key) => delete STATE[key]);
      Object.assign(STATE, fresh);
      STATE.expandedGroups = {{ decoration: false }};
      STATE.userElements = [];
      STATE.userElementCounter = 0;
      STATE.addMenu = {{ open: false, frameX: 0, frameY: 0, x: 0, y: 0 }};
      STATE.selectedElementId = STATE.defaultSelectedElementId || ((STATE.elements[0] || STATE.userElements[0]) && (STATE.elements[0] || STATE.userElements[0]).id) || "";
      STATE.saveName = preservedSaveName || defaultPresetName();
      STATE.activePresetName = preservedActivePresetName || "";
      STATE.savedPresets = preservedSavedPresets || readSavedPresets();
      STATE.officialPreviewOpen = Boolean(STATE.officialPreviewSource && preservedOfficialPreviewOpen);
      STATE.elementOverrides = {{}};
      STATE.elementMetrics = {{}};
      STATE.advancedParamsOpen = {{}};
      STATE.saveStatus = "已恢复默认。";
      STATE.saveStatusError = false;
      renderOfficialPreviewPanel();
      renderSavePanel();
    }}

    function renderLayerButton(item) {{
      return `
        <button class="layer-button ${{item.id === STATE.selectedElementId ? "is-selected" : ""}}" data-element-id="${{item.id}}">
          <span class="layer-chip">${{kindBadge(item.kind)}}</span>
          <span class="layer-label">${{item.label}}</span>
        </button>
      `;
    }}

    function renderContextPanel(element) {{
      const container = APP.querySelector("#context-panel");
      if (!element) {{
        container.innerHTML = `<div class="empty-state">${{canEditCurrentTemplate() ? "选中文字或图片后编辑内容。" : "暂无运行时字段。"}}</div>`;
        return;
      }}
      if (isUserTextElement(element)) {{
        const config = element.userConfig || {{}};
        const multiline = element.userType === "static_text";
        container.innerHTML = multiline
          ? textareaHTML("文字内容", "live-user-text", config.text || "")
          : fieldHTML("文字内容", "live-user-text", config.text || "");
        const editor = container.querySelector(multiline ? "textarea" : "input");
        editor.addEventListener("input", (event) => {{
          element.userConfig = {{ ...(element.userConfig || {{}}), text: event.target.value }};
          refreshPreviewFromState();
        }});
        return;
      }}
      if (!element.fieldName) {{
        container.innerHTML = `<div class="empty-state">${{isUserElement(element) ? "当前装饰元素没有文案输入。可在右侧继续调整尺寸与样式。" : "当前元素没有内容输入。"}}</div>`;
        return;
      }}

      if (element.fieldName === "title") {{
        container.innerHTML = fieldHTML("标题", "live-preview-title", STATE.preview.title);
        container.querySelector("input").addEventListener("input", (event) => {{
          STATE.preview.title = event.target.value;
          refreshPreviewFromState();
        }});
        return;
      }}

      if (element.fieldName === "image") {{
        container.innerHTML = `
          ${{fieldHTML("图片路径 / URL", "live-preview-image", STATE.preview.image)}}
          <div class="inline-note">支持 URL；本地路径沿用当前图片。</div>
        `;
        container.querySelector("input").addEventListener("input", (event) => {{
          STATE.preview.image = event.target.value;
          refreshPreviewFromState();
        }});
        return;
      }}

      if (element.fieldName === "text") {{
        container.innerHTML = `
          <div class="segment">
            ${{Object.entries(STATE.previewDatasets).map(([key, dataset]) => `
              <button class="${{STATE.previewDatasetKey === key ? "is-active" : ""}}" data-dataset-key="${{key}}">${{dataset.label}}</button>
            `).join("")}}
          </div>
          ${{textareaHTML("字幕文本", "live-preview-text", STATE.preview.text)}}
        `;
        container.querySelectorAll("[data-dataset-key]").forEach((button) => {{
          button.addEventListener("click", () => {{
            const key = button.dataset.datasetKey;
            STATE.previewDatasetKey = key;
            STATE.preview.title = STATE.previewDatasets[key].title;
            STATE.preview.text = STATE.previewDatasets[key].text;
            STATE.preview.image = STATE.previewDatasets[key].image;
            syncSelectionUI(true);
          }});
        }});
        container.querySelector("textarea").addEventListener("input", (event) => {{
          STATE.preview.text = event.target.value;
          refreshPreviewFromState();
        }});
      }}
    }}

    function renderDirectTuneFields(element) {{
      const metrics = elementMetrics(element) || {{}};
      const override = ensureElementOverride(element.id);
      const userConfig = element.userConfig || {{}};
      const fontSize = override.fontSize ?? metrics.fontSize ?? "";
      const color = override.color || metrics.color || "#111827";
      const textAlign = override.textAlign || metrics.textAlign || "left";
      const objectFit = override.objectFit || metrics.objectFit || "cover";
      const removeBackground = Boolean(override.removeBackground);
      const bgThreshold = clampNumber(override.bgThreshold, 0, 255, 244);
      const bgSoftness = clampNumber(override.bgSoftness, 0, 64, 18);

      const blocks = [
        `<div class="subsection-title">位置</div>`,
        `<div class="micro-grid">
          <div class="field">
            <label>偏移 X</label>
            <input data-override="offsetX" type="number" step="1" value="${{Number(override.offsetX || 0)}}">
          </div>
          <div class="field">
            <label>偏移 Y</label>
            <input data-override="offsetY" type="number" step="1" value="${{Number(override.offsetY || 0)}}">
          </div>
          <div class="field">
            <label>缩放</label>
            <input data-override="scale" type="number" min="0.2" max="3" step="0.05" value="${{Number(override.scale || 1)}}">
          </div>
        </div>`,
      ];

      if (isUserElement(element)) {{
        blocks.push(`
          <div class="subsection-title">尺寸</div>
          <div class="micro-grid">
            <div class="field">
              <label>宽度</label>
              <input data-user-config="width" type="number" min="24" step="1" value="${{Number(userConfig.width || metrics.width || 160)}}">
            </div>
            <div class="field">
              <label>高度</label>
              <input data-user-config="height" type="number" min="12" step="1" value="${{Number(userConfig.height || metrics.height || 48)}}">
            </div>
            <div class="field">
              <label>圆角</label>
              <input data-user-config="borderRadius" type="number" min="0" step="1" value="${{Number(userConfig.borderRadius || 0)}}">
            </div>
          </div>
          <div class="subsection-title">形状</div>
          <div class="micro-grid">
            <div class="field">
              <label>填充</label>
              <input data-user-config="background" type="color" value="${{colorToHex(userConfig.background || "#ffffff")}}">
            </div>
            <div class="field">
              <label>描边</label>
              <input data-user-config="borderColor" type="color" value="${{colorToHex(userConfig.borderColor || "#111827")}}">
            </div>
            <div class="field">
              <label>描边宽度</label>
              <input data-user-config="borderWidth" type="number" min="0" step="1" value="${{Number(userConfig.borderWidth || 0)}}">
            </div>
          </div>
        `);
      }}

      if (isTextElement(element)) {{
        blocks.push(`
          <div class="subsection-title">文字</div>
          <div class="micro-grid">
            <div class="field">
              <label>字号</label>
              <input data-override="fontSize" type="number" min="8" step="1" value="${{fontSize}}">
            </div>
            <div class="field">
              <label>颜色</label>
              <input data-override="color" type="color" value="${{color}}">
            </div>
            <div class="field">
              <label>对齐</label>
              <select data-override="textAlign">
                ${{["left", "center", "right"].map((option) => `<option value="${{option}}" ${{option === textAlign ? "selected" : ""}}>${{option === "left" ? "左对齐" : option === "center" ? "居中" : "右对齐"}}</option>`).join("")}}
              </select>
            </div>
            <div class="field">
              <label>当前尺寸</label>
              <div class="readonly-value">${{metrics.width || 0}} × ${{metrics.height || 0}}</div>
            </div>
          </div>
        `);
      }}

      if (isImageElement(element)) {{
        blocks.push(`
          <div class="subsection-title">图片</div>
          <div class="micro-grid">
            <div class="field">
              <label>填充</label>
              <select data-override="objectFit">
                <option value="contain" ${{objectFit === "contain" ? "selected" : ""}}>完整显示</option>
                <option value="cover" ${{objectFit === "cover" ? "selected" : ""}}>铺满裁切</option>
              </select>
            </div>
            <div class="field">
              <label>当前尺寸</label>
              <div class="readonly-value">${{metrics.width || 0}} × ${{metrics.height || 0}}</div>
            </div>
          </div>
          <div class="field checkbox-field">
            <label class="checkbox-row">
              <input data-override="removeBackground" type="checkbox" ${{removeBackground ? "checked" : ""}}>
              <span>透明底预览</span>
            </label>
            <div class="inline-note">仅作用于当前预览；适合白底 / 浅底插图，远程 URL 若不支持跨域会自动回退原图。</div>
          </div>
          ${{removeBackground ? `
            <div class="micro-grid">
              <div class="field">
                <label>白底阈值</label>
                <input data-override="bgThreshold" type="number" min="0" max="255" step="1" value="${{bgThreshold}}">
              </div>
              <div class="field">
                <label>边缘柔化</label>
                <input data-override="bgSoftness" type="number" min="0" max="64" step="1" value="${{bgSoftness}}">
              </div>
            </div>
            <div class="inline-note">阈值越低，抠除范围越大；柔化越高，边缘过渡越软。</div>
          ` : ""}}
        `);
      }}

      return `
        <div class="micro-actions">
          <button class="btn btn-secondary btn-small" id="reset-element-tune">重置微调</button>
          ${{isUserElement(element) ? '<button class="btn btn-secondary btn-small" id="delete-user-element">删除元素</button>' : ""}}
        </div>
        ${{blocks.join("")}}
      `;
    }}

    function bindDirectTuneControls(panel, element) {{
      const resetButton = panel.querySelector("#reset-element-tune");
      if (resetButton) {{
        resetButton.addEventListener("click", () => {{
          delete STATE.elementOverrides[element.id];
          delete STATE.elementMetrics[element.id];
          applyPreviewState();
          renderPropertyPanel(element);
        }});
      }}

      const deleteButton = panel.querySelector("#delete-user-element");
      if (deleteButton) {{
        deleteButton.addEventListener("click", () => {{
          removeUserElement(element.id);
        }});
      }}

      panel.querySelectorAll("[data-override]").forEach((control) => {{
        const name = control.dataset.override;
        const eventName = control.tagName === "SELECT" || control.type === "color" || control.type === "checkbox" ? "change" : "input";
        control.addEventListener(eventName, (event) => {{
          const override = ensureElementOverride(element.id);
          let value = event.target.value;
          if (event.target.type === "checkbox") {{
            value = event.target.checked;
          }}
          if (["offsetX", "offsetY", "scale", "fontSize", "bgThreshold", "bgSoftness"].includes(name)) {{
            value = Number(value || (name === "scale" ? 1 : 0));
          }}
          if (name === "fontSize" && !value) {{
            override[name] = null;
          }} else if (name === "bgThreshold") {{
            override[name] = clampNumber(value, 0, 255, 244);
          }} else if (name === "bgSoftness") {{
            override[name] = clampNumber(value, 0, 64, 18);
          }} else {{
            override[name] = value;
          }}
          applyPreviewState();
          renderPropertyPanel(element);
        }});
      }});

      panel.querySelectorAll("[data-user-config]").forEach((control) => {{
        const name = control.dataset.userConfig;
        const eventName = control.tagName === "SELECT" || control.type === "color" ? "change" : "input";
        control.addEventListener(eventName, (event) => {{
          const next = {{ ...(element.userConfig || {{}}) }};
          let value = event.target.value;
          if (["width", "height", "borderWidth", "borderRadius"].includes(name)) {{
            value = Number(value || 0);
          }}
          if (name === "width") {{
            value = clampNumber(value, 24, STATE.template.templateWidth, next.width || 160);
          }}
          if (name === "height") {{
            value = clampNumber(value, 12, STATE.template.templateHeight, next.height || 48);
          }}
          if (name === "borderWidth") {{
            value = clampNumber(value, 0, 24, next.borderWidth || 0);
          }}
          if (name === "borderRadius") {{
            value = clampNumber(value, 0, 240, next.borderRadius || 0);
          }}
          next[name] = value;
          element.userConfig = next;
          applyPreviewState();
          renderPropertyPanel(element);
        }});
      }});
    }}

    function renderPropertyPanel(element) {{
      const panel = APP.querySelector("#property-panel");
      if (!element) {{
        panel.innerHTML = `<div class="empty-state">${{canEditCurrentTemplate() ? "点预览里的元素后开始微调。" : "暂无参数。"}}</div>`;
        return;
      }}

      const advancedOpen = Boolean(STATE.advancedParamsOpen[element.id]);
      const advancedSection = element.paramNames.length
        ? `
          <details class="advanced-details" id="advanced-param-details" ${{advancedOpen ? "open" : ""}}>
            <summary class="advanced-summary">
              <span>高级参数</span>
              <span class="property-count">${{element.paramNames.length}}</span>
            </summary>
            <div class="advanced-panel">
              ${{element.paramNames.map((paramName) => renderParamField(paramName)).join("")}}
            </div>
          </details>
        `
        : "";

      panel.innerHTML = `
        ${{renderDirectTuneFields(element)}}
        ${{advancedSection}}
      `;

      bindDirectTuneControls(panel, element);

      const advancedDetails = panel.querySelector("#advanced-param-details");
      if (advancedDetails) {{
        advancedDetails.addEventListener("toggle", () => {{
          STATE.advancedParamsOpen[element.id] = advancedDetails.open;
        }});
      }}

      element.paramNames.forEach((paramName) => {{
        const config = STATE.customParams[paramName] || {{ type: "text" }};
        const controls = panel.querySelectorAll(`[data-param="${{paramName}}"]`);
        if (!controls.length) return;
        const handler = (event) => {{
          const target = event.target;
          let value = target.value;
          if (config.type === "number") {{
            value = Number(value || 0);
          }} else if (config.type === "bool") {{
            value = target.checked;
          }}
          STATE.params[paramName] = value;
          refreshPreviewFromState();
        }};
        const eventName = config.type === "bool" || Boolean(STATE.paramOptions[paramName]) ? "change" : "input";
        controls.forEach((control) => {{
          control.addEventListener(eventName, handler);
        }});
      }});
    }}

    function renderParamField(paramName) {{
      const config = STATE.customParams[paramName] || {{ type: "text" }};
      const label = STATE.paramLabels[paramName] || paramName;
      const value = STATE.params[paramName];
      if (STATE.paramOptions[paramName]) {{
        return `
          <div class="field">
            <label>${{label}}</label>
            <select data-param="${{paramName}}">
              ${{STATE.paramOptions[paramName].map((option) => `<option value="${{option}}" ${{option === value ? "selected" : ""}}>${{(STATE.paramOptionLabels[paramName] && STATE.paramOptionLabels[paramName][option]) || option}}</option>`).join("")}}
            </select>
          </div>
        `;
      }}
      if (config.type === "color") {{
        return `
          <div class="field">
            <label>${{label}}</label>
            <input data-param="${{paramName}}" type="color" value="${{value}}">
          </div>
        `;
      }}
      if (config.type === "number") {{
        return `
          <div class="field">
            <label>${{label}}</label>
            <input data-param="${{paramName}}" type="number" min="0" step="1" value="${{Number(value)}}" inputmode="numeric">
          </div>
        `;
      }}
      if (config.type === "bool") {{
        return `
          <div class="field">
            <label>${{label}}</label>
            <input data-param="${{paramName}}" type="checkbox" ${{value ? "checked" : ""}}>
          </div>
        `;
      }}
      return `
        <div class="field">
          <label>${{label}}</label>
          <input data-param="${{paramName}}" type="text" value="${{String(value ?? "").replace(/"/g, "&quot;")}}">
        </div>
      `;
    }}

    function fieldHTML(label, id, value) {{
      return `
        <div class="field">
          <label for="${{id}}">${{label}}</label>
          <input id="${{id}}" type="text" value="${{String(value ?? "").replace(/"/g, "&quot;")}}">
        </div>
      `;
    }}

    function textareaHTML(label, id, value) {{
      return `
        <div class="field">
          <label for="${{id}}">${{label}}</label>
          <textarea id="${{id}}">${{value ?? ""}}</textarea>
        </div>
      `;
    }}

    function previewLayout() {{
      const wrapper = APP.querySelector("#preview-wrapper");
      const scale = wrapper ? Math.min(wrapper.clientWidth / STATE.template.templateWidth, 1) : 1;
      const frameWidth = STATE.template.templateWidth * scale;
      return {{
        wrapper,
        scale,
        offsetX: wrapper ? Math.max(0, (wrapper.clientWidth - frameWidth) / 2) : 0,
      }};
    }}

    function hideAddMenu() {{
      STATE.addMenu = {{ open: false, frameX: 0, frameY: 0, x: 0, y: 0 }};
      renderAddMenu();
    }}

    function showAddMenu(frameX, frameY) {{
      const layout = previewLayout();
      STATE.addMenu = {{
        open: true,
        frameX,
        frameY,
        x: layout.offsetX + frameX * layout.scale,
        y: frameY * layout.scale,
      }};
      renderAddMenu();
    }}

    function addMenuOptions() {{
      return [
        {{ type: "static_title", label: "静态标题" }},
        {{ type: "static_text", label: "静态正文" }},
        {{ type: "static_tag", label: "静态标签" }},
        {{ type: "divider", label: "分隔线" }},
        {{ type: "background_block", label: "背景块" }},
        {{ type: "border_box", label: "边框" }},
      ];
    }}

    function renderAddMenu() {{
      const layer = APP.querySelector("#add-menu-layer");
      if (!layer) return;
      if (!STATE.addMenu.open || !canEditCurrentTemplate() || !usesLiveDomPreview()) {{
        layer.innerHTML = "";
        return;
      }}

      const layout = previewLayout();
      const menuWidth = 172;
      const maxLeft = Math.max(8, (layout.wrapper?.clientWidth || menuWidth) - menuWidth - 8);
      const maxTop = Math.max(8, (layout.wrapper?.clientHeight || 240) - 228);
      const left = clampNumber(STATE.addMenu.x, 8, maxLeft, 8);
      const top = clampNumber(STATE.addMenu.y, 8, maxTop, 8);

      layer.innerHTML = `
        <div class="add-menu" style="left:${{left}}px; top:${{top}}px;">
          <div class="add-menu-title">添加元素</div>
          <div class="add-menu-grid">
            ${{addMenuOptions().map((item) => `
              <button class="add-menu-button" data-add-type="${{item.type}}">${{item.label}}</button>
            `).join("")}}
          </div>
        </div>
      `;

      layer.querySelectorAll("[data-add-type]").forEach((button) => {{
        button.addEventListener("click", (event) => {{
          event.preventDefault();
          event.stopPropagation();
          const type = button.dataset.addType;
          const element = createUserElement(type, STATE.addMenu.frameX, STATE.addMenu.frameY);
          if (!element) return;
          STATE.userElements = [...(STATE.userElements || []), element];
          STATE.selectedElementId = element.id;
          hideAddMenu();
          syncSelectionUI(true);
        }});
      }});
    }}

    function editableRootNode(doc) {{
      return doc.querySelector('[data-studio-node="template_canvas"]') || doc.body;
    }}

    function applyUserElementNode(node, element) {{
      const config = element.userConfig || {{}};
      const width = clampNumber(config.width, 24, STATE.template.templateWidth, 160);
      const height = clampNumber(config.height, 12, STATE.template.templateHeight, 48);
      const x = clampNumber(config.x, 0, Math.max(0, STATE.template.templateWidth - width), 0);
      const y = clampNumber(config.y, 0, Math.max(0, STATE.template.templateHeight - height), 0);
      const textAlign = config.textAlign || "left";
      const justifyContent = textAlign === "center" ? "center" : textAlign === "right" ? "flex-end" : "flex-start";

      node.setAttribute("data-studio-node", element.id);
      node.setAttribute("data-studio-user", "1");
      node.setAttribute("data-user-type", element.userType || "custom");
      node.style.position = "absolute";
      node.style.left = `${{x}}px`;
      node.style.top = `${{y}}px`;
      node.style.width = `${{width}}px`;
      node.style.height = `${{height}}px`;
      node.style.zIndex = String(config.zIndex || element.zIndex || 4);
      node.style.boxSizing = "border-box";
      node.style.display = "flex";
      node.style.alignItems = "center";
      node.style.justifyContent = justifyContent;
      node.style.padding = `${{Number(config.paddingY || 0)}}px ${{Number(config.paddingX || 0)}}px`;
      node.style.background = config.background || "transparent";
      node.style.borderStyle = Number(config.borderWidth || 0) > 0 ? "solid" : "none";
      node.style.borderWidth = `${{Number(config.borderWidth || 0)}}px`;
      node.style.borderColor = config.borderColor || "transparent";
      node.style.borderRadius = `${{Number(config.borderRadius || 0)}}px`;
      node.style.color = config.textColor || "#111827";
      node.style.fontSize = `${{Number(config.fontSize || 16)}}px`;
      node.style.fontWeight = config.fontWeight || "500";
      node.style.lineHeight = "1.35";
      node.style.textAlign = textAlign;
      node.style.whiteSpace = "pre-wrap";
      node.style.wordBreak = "break-word";
      node.style.overflow = "hidden";
      node.textContent = config.text || "";
      element.userConfig = {{ ...config, width, height, x, y }};
    }}

    function syncUserElements(doc) {{
      const root = editableRootNode(doc);
      const activeIds = new Set((STATE.userElements || []).map((item) => item.id));
      doc.querySelectorAll('[data-studio-user="1"]').forEach((node) => {{
        const nodeId = node.getAttribute("data-studio-node");
        if (!activeIds.has(nodeId)) {{
          node.remove();
        }}
      }});

      (STATE.userElements || []).forEach((element) => {{
        let node = doc.querySelector(element.selector);
        if (!node) {{
          node = doc.createElement("div");
          root.appendChild(node);
        }}
        applyUserElementNode(node, element);
      }});
    }}

    function clampNumber(value, min, max, fallback) {{
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return fallback;
      return Math.min(max, Math.max(min, numeric));
    }}

    function clearTransparentImageState(node) {{
      delete node.dataset.studioProcessedKey;
      delete node.dataset.studioProcessingKey;
    }}

    function setNodeTextValue(node, value) {{
      const nextValue = value === undefined || value === null ? "" : String(value);
      const elementChildren = Array.from(node.children || []);
      if (!elementChildren.length) {{
        if (node.textContent !== nextValue) {{
          node.textContent = nextValue;
        }}
        return;
      }}

      const textNodes = Array.from(node.childNodes).filter((child) => child.nodeType === Node.TEXT_NODE);
      const targetNode = [...textNodes].reverse().find((child) => child.textContent.trim().length) || textNodes[textNodes.length - 1] || null;
      if (!targetNode) {{
        if (nextValue) {{
          node.appendChild(node.ownerDocument.createTextNode(` ${{nextValue}}`));
        }}
        return;
      }}

      const prefix = targetNode.textContent.match(/^\\s*/)?.[0] || " ";
      const suffix = targetNode.textContent.match(/\\s*$/)?.[0] || "";
      targetNode.textContent = `${{prefix}}${{nextValue}}${{suffix}}`;
    }}

    function setOriginalImageSource(node, source) {{
      if (!source) return;
      if (node.dataset.studioOriginalSrc !== source) {{
        node.dataset.studioOriginalSrc = source;
        clearTransparentImageState(node);
      }}
      if (node.getAttribute("src") !== source) {{
        node.setAttribute("src", source);
      }}
    }}

    function setOriginalBackgroundImageSource(node, source) {{
      if (!source) {{
        node.style.removeProperty("background-image");
        delete node.dataset.studioOriginalBackgroundSrc;
        return;
      }}
      if (node.dataset.studioOriginalBackgroundSrc !== source) {{
        node.dataset.studioOriginalBackgroundSrc = source;
      }}
      const backgroundValue = `url("${{source}}")`;
      if (node.style.backgroundImage !== backgroundValue) {{
        node.style.backgroundImage = backgroundValue;
      }}
    }}

    function setBoundImageSource(node, source, bindingAttribute) {{
      if (bindingAttribute === "background-image") {{
        setOriginalBackgroundImageSource(node, source);
        return true;
      }}
      if (bindingAttribute === "src" || node.tagName === "IMG") {{
        setOriginalImageSource(node, source);
        return true;
      }}
      return false;
    }}

    function syncBlurCardBackgroundImage(doc, source) {{
      if (STATE.template.templatePath !== "1080x1920/image_blur_card.html") return;
      doc.querySelectorAll(".bg").forEach((node) => {{
        if (!source) {{
          node.style.removeProperty("background-image");
          delete node.dataset.studioOriginalBackgroundSrc;
          return;
        }}
        node.dataset.studioOriginalBackgroundSrc = source;
        node.style.backgroundImage = `url("${{source}}")`;
      }});
    }}

    function restoreOriginalImage(node) {{
      const originalSrc = node.dataset.studioOriginalSrc || node.getAttribute("src") || "";
      if (!originalSrc) return;
      if (node.getAttribute("src") !== originalSrc) {{
        node.setAttribute("src", originalSrc);
      }}
      clearTransparentImageState(node);
    }}

    function transparentBgCacheKey(source, threshold, softness) {{
      return `${{threshold}}::${{softness}}::${{source}}`;
    }}

    function createTransparentImageSource(source, threshold, softness) {{
      const cacheKey = transparentBgCacheKey(source, threshold, softness);
      if (TRANSPARENT_BG_CACHE.has(cacheKey)) {{
        const cached = TRANSPARENT_BG_CACHE.get(cacheKey);
        return Promise.resolve(typeof cached === "string" ? cached : null);
      }}
      if (TRANSPARENT_BG_PENDING.has(cacheKey)) {{
        return TRANSPARENT_BG_PENDING.get(cacheKey);
      }}

      const task = new Promise((resolve) => {{
        const image = new Image();
        if (source.startsWith("http://") || source.startsWith("https://")) {{
          image.crossOrigin = "anonymous";
        }}
        image.onload = () => {{
          try {{
            const canvas = document.createElement("canvas");
            canvas.width = image.naturalWidth || image.width;
            canvas.height = image.naturalHeight || image.height;
            const context = canvas.getContext("2d", {{ willReadFrequently: true }});
            if (!context) {{
              TRANSPARENT_BG_CACHE.set(cacheKey, false);
              resolve(null);
              return;
            }}

            context.drawImage(image, 0, 0);
            const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
            const data = imageData.data;
            const feather = Math.max(softness, 1);
            const varianceLimit = Math.max(18, feather * 2);

            for (let index = 0; index < data.length; index += 4) {{
              const alpha = data[index + 3];
              if (!alpha) continue;

              const red = data[index];
              const green = data[index + 1];
              const blue = data[index + 2];
              const maxChannel = Math.max(red, green, blue);
              const minChannel = Math.min(red, green, blue);
              if (maxChannel - minChannel > varianceLimit) continue;

              if (minChannel <= Math.max(0, threshold - feather)) continue;
              if (minChannel >= threshold) {{
                data[index + 3] = 0;
                continue;
              }}

              const progress = (minChannel - (threshold - feather)) / feather;
              const keepFactor = Math.max(0, Math.min(1, 1 - progress));
              data[index + 3] = Math.round(alpha * keepFactor);
            }}

            context.putImageData(imageData, 0, 0);
            const processed = canvas.toDataURL("image/png");
            TRANSPARENT_BG_CACHE.set(cacheKey, processed);
            resolve(processed);
          }} catch (error) {{
            TRANSPARENT_BG_CACHE.set(cacheKey, false);
            resolve(null);
          }}
        }};
        image.onerror = () => {{
          TRANSPARENT_BG_CACHE.set(cacheKey, false);
          resolve(null);
        }};
        try {{
          image.src = source;
        }} catch (error) {{
          TRANSPARENT_BG_CACHE.set(cacheKey, false);
          resolve(null);
        }}
      }});

      const wrapped = task.finally(() => {{
        TRANSPARENT_BG_PENDING.delete(cacheKey);
      }});
      TRANSPARENT_BG_PENDING.set(cacheKey, wrapped);
      return wrapped;
    }}

    function syncTransparentBackground(node, element) {{
      if (!node || node.tagName !== "IMG") return;

      const override = getElementOverride(element.id);
      if (!override || !override.removeBackground) {{
        restoreOriginalImage(node);
        return;
      }}

      const originalSrc = node.dataset.studioOriginalSrc || node.getAttribute("src") || "";
      if (!originalSrc) return;
      if (!node.dataset.studioOriginalSrc) {{
        node.dataset.studioOriginalSrc = originalSrc;
      }}

      const threshold = clampNumber(override.bgThreshold, 0, 255, 244);
      const softness = clampNumber(override.bgSoftness, 0, 64, 18);
      const cacheKey = transparentBgCacheKey(originalSrc, threshold, softness);
      if (TRANSPARENT_BG_CACHE.has(cacheKey)) {{
        const cached = TRANSPARENT_BG_CACHE.get(cacheKey);
        if (typeof cached === "string") {{
          node.dataset.studioProcessedKey = cacheKey;
          if (node.getAttribute("src") !== cached) {{
            node.setAttribute("src", cached);
          }}
        }} else {{
          restoreOriginalImage(node);
        }}
        return;
      }}

      if (node.dataset.studioProcessedKey !== cacheKey && node.getAttribute("src") !== originalSrc) {{
        node.setAttribute("src", originalSrc);
        delete node.dataset.studioProcessedKey;
      }}
      if (node.dataset.studioProcessingKey === cacheKey) return;
      node.dataset.studioProcessingKey = cacheKey;

      createTransparentImageSource(originalSrc, threshold, softness).then((processedSrc) => {{
        const latestOverride = getElementOverride(element.id);
        delete node.dataset.studioProcessingKey;

        if (!latestOverride || !latestOverride.removeBackground) return;
        if ((node.dataset.studioOriginalSrc || "") !== originalSrc) return;
        if (
          transparentBgCacheKey(
            originalSrc,
            clampNumber(latestOverride.bgThreshold, 0, 255, 244),
            clampNumber(latestOverride.bgSoftness, 0, 64, 18),
          ) !== cacheKey
        ) return;
        if (!processedSrc) {{
          restoreOriginalImage(node);
          return;
        }}

        node.dataset.studioProcessedKey = cacheKey;
        node.setAttribute("src", processedSrc);
      }});
    }}

    function applyElementOverride(node, element) {{
      const override = getElementOverride(element.id);
      if (!override) {{
        node.style.removeProperty("translate");
        node.style.removeProperty("scale");
        if (!isUserElement(element)) {{
          node.style.removeProperty("font-size");
          node.style.removeProperty("color");
          node.style.removeProperty("text-align");
        }}
        if (node.tagName === "IMG") {{
          node.style.removeProperty("object-fit");
          restoreOriginalImage(node);
        }}
        return;
      }}

      node.style.transformOrigin = "center center";
      node.style.translate = `${{Number(override.offsetX || 0)}}px ${{Number(override.offsetY || 0)}}px`;
      node.style.scale = `${{Number(override.scale || 1)}}`;

      if (isTextElement(element)) {{
        if (override.fontSize) {{
          node.style.fontSize = `${{Number(override.fontSize)}}px`;
        }} else if (!isUserElement(element)) {{
          node.style.removeProperty("font-size");
        }}
        if (override.color) {{
          node.style.color = override.color;
        }} else if (!isUserElement(element)) {{
          node.style.removeProperty("color");
        }}
        if (override.textAlign) {{
          node.style.textAlign = override.textAlign;
        }} else if (!isUserElement(element)) {{
          node.style.removeProperty("text-align");
        }}
      }}

      if (isImageElement(element) && node.tagName === "IMG") {{
        if (override.objectFit) {{
          node.style.objectFit = override.objectFit;
        }} else {{
          node.style.removeProperty("object-fit");
        }}
        syncTransparentBackground(node, element);
      }}
    }}

    function refreshPreviewFromState() {{
      if (usesLiveDomPreview()) {{
        applyPreviewState();
        renderPropertyPanel(selectedElement());
        return;
      }}
      rerenderPreview();
    }}

    function mountPreview() {{
      const wrapper = APP.querySelector("#preview-wrapper");
      const frame = APP.querySelector("#preview-frame");
      previewReady = false;

      const sizePreviewFrame = () => {{
        const scale = Math.min(wrapper.clientWidth / STATE.template.templateWidth, 1);
        const height = Math.round(STATE.template.templateHeight * scale);
        wrapper.style.height = `${{height}}px`;
        frame.style.width = `${{STATE.template.templateWidth}}px`;
        frame.style.height = `${{STATE.template.templateHeight}}px`;
        frame.style.transform = `translateX(-50%) scale(${{scale}})`;
        renderAddMenu();
      }};

      if (previewResizeHandler) {{
        window.removeEventListener("resize", previewResizeHandler);
      }}
      previewResizeHandler = sizePreviewFrame;
      window.addEventListener("resize", previewResizeHandler);

      if (!frame.dataset.bound) {{
        frame.addEventListener("load", () => {{
          const doc = frame.contentDocument;
          previewReady = true;
          injectPreviewHelpers(doc);
          applyPreviewState();
          sizePreviewFrame();
          renderPropertyPanel(selectedElement());
        }});
        frame.dataset.bound = "1";
      }}

      sizePreviewFrame();
      rerenderPreview();
    }}

    function rerenderPreview() {{
      const frame = APP.querySelector("#preview-frame");
      if (!frame) return;
      previewReady = false;
      STATE.renderedHtml = renderTemplateHtml();
      frame.srcdoc = STATE.renderedHtml;
    }}

    function injectPreviewHelpers(doc) {{
      const style = doc.createElement("style");
      style.textContent = `
        [data-studio-node] {{
          cursor: grab;
          transition: box-shadow 120ms ease, outline-color 120ms ease;
          user-select: none;
        }}
        [data-studio-node].studio-selected {{
          outline: 3px solid rgba(255, 90, 54, 0.88);
          outline-offset: 4px;
          box-shadow: 0 0 0 8px rgba(255, 90, 54, 0.12);
        }}
        [data-studio-node].studio-hover {{
          outline: 2px solid rgba(255, 90, 54, 0.42);
          outline-offset: 3px;
        }}
        [data-studio-user="1"] {{
          position: absolute;
          box-sizing: border-box;
        }}
      `;
      doc.head.appendChild(style);

      doc.addEventListener("mousedown", (event) => {{
        const target = event.target.closest("[data-studio-node]");
        if (!target || event.button !== 0) return;
        const nodeName = target.getAttribute("data-studio-node");
        const match = allElements().find((item) => selectorNodeName(item.selector) === nodeName);
        if (!match) return;
        STATE.selectedElementId = match.id;
        hideAddMenu();
        const override = ensureElementOverride(match.id);
        dragState = {{
          elementId: match.id,
          startX: event.clientX,
          startY: event.clientY,
          initialX: Number(override.offsetX || 0),
          initialY: Number(override.offsetY || 0),
          moved: false,
        }};
        applyPreviewState();
        renderPropertyPanel(match);
        event.preventDefault();
      }});

      doc.addEventListener("mousemove", (event) => {{
        if (!dragState) return;
        const override = ensureElementOverride(dragState.elementId);
        override.offsetX = Math.round(dragState.initialX + event.clientX - dragState.startX);
        override.offsetY = Math.round(dragState.initialY + event.clientY - dragState.startY);
        dragState.moved = true;
        applyPreviewState();
      }});

      doc.addEventListener("mouseup", () => {{
        if (!dragState) return;
        const activeElementId = dragState.elementId;
        const moved = dragState.moved;
        dragState = null;
        if (moved) {{
          renderPropertyPanel(elementById(activeElementId) || selectedElement());
        }}
      }});

      doc.addEventListener("click", (event) => {{
        const target = event.target.closest("[data-studio-node]");
        if (!target) {{
          if (canEditCurrentTemplate() && usesLiveDomPreview()) {{
            showAddMenu(
              clampNumber(event.clientX, 0, STATE.template.templateWidth, 0),
              clampNumber(event.clientY, 0, STATE.template.templateHeight, 0),
            );
          }}
          return;
        }}
        const nodeName = target.getAttribute("data-studio-node");
        const match = allElements().find((item) => selectorNodeName(item.selector) === nodeName);
        if (!match) {{
          if (canEditCurrentTemplate() && usesLiveDomPreview()) {{
            showAddMenu(
              clampNumber(event.clientX, 0, STATE.template.templateWidth, 0),
              clampNumber(event.clientY, 0, STATE.template.templateHeight, 0),
            );
          }}
          return;
        }}
        event.preventDefault();
        event.stopPropagation();
        STATE.selectedElementId = match.id;
        hideAddMenu();
        syncSelectionUI();
      }});

      doc.addEventListener("mouseover", (event) => {{
        const target = event.target.closest("[data-studio-node]");
        doc.querySelectorAll(".studio-hover").forEach((node) => node.classList.remove("studio-hover"));
        if (target) target.classList.add("studio-hover");
      }});
      doc.addEventListener("mouseout", () => {{
        doc.querySelectorAll(".studio-hover").forEach((node) => node.classList.remove("studio-hover"));
      }});
    }}

    function applyPreviewState() {{
      const frame = APP.querySelector("#preview-frame");
      const doc = previewReady && frame ? frame.contentDocument : null;
      if (!doc) return;

      if (!usesLiveDomPreview()) {{
        allElements().forEach((element) => {{
          const node = doc.querySelector(element.selector);
          if (node) applyElementOverride(node, element);
        }});
        doc.querySelectorAll(".studio-selected").forEach((node) => node.classList.remove("studio-selected"));
        const selected = selectedElement();
        if (!selected) return;
        const selectedNode = doc.querySelector(selected.selector);
        if (selectedNode) selectedNode.classList.add("studio-selected");
        elementMetrics(selected);
        return;
      }}

      syncUserElements(doc);

      Object.entries(STATE.customParams).forEach(([paramName, config]) => {{
        const value = STATE.params[paramName];
        doc.documentElement.style.setProperty(paramToCssVar(paramName), cssValue(paramName, config, value));
      }});

      allElements().forEach((element) => {{
        const node = doc.querySelector(element.selector);
        if (!node) return;

        if (element.fieldName === "title") {{
          setNodeTextValue(node, STATE.preview.title);
        }} else if (element.fieldName === "text") {{
          setNodeTextValue(node, STATE.preview.text);
        }} else if (element.fieldName === "image") {{
          const imageSource = liveImageSource(STATE.preview.image);
          const imageOverride = getElementOverride(element.id);
          if (element.bindingAttribute === "background-image") {{
            setOriginalBackgroundImageSource(node, imageSource);
          }} else if (node.tagName === "IMG") {{
            if (!imageOverride || !imageOverride.removeBackground || node.dataset.studioOriginalSrc !== imageSource) {{
              setOriginalImageSource(node, imageSource);
            }} else if (!node.dataset.studioOriginalSrc) {{
              node.dataset.studioOriginalSrc = imageSource;
            }}
            node.setAttribute("alt", STATE.preview.title);
          }} else {{
            setBoundImageSource(node, imageSource, element.bindingAttribute);
          }}
          syncBlurCardBackgroundImage(doc, imageSource);
        }} else if (element.bindingSource === "param") {{
          const paramName = (element.paramNames && element.paramNames[0]) || element.bindingName;
          if (paramName && Object.prototype.hasOwnProperty.call(STATE.params, paramName)) {{
            const rawValue = STATE.params[paramName];
            const value = rawValue === undefined || rawValue === null ? "" : String(rawValue);
            if (
              element.bindingAttribute === "background-image"
              || element.bindingAttribute === "src"
              || node.tagName === "IMG"
            ) {{
              setBoundImageSource(node, value ? liveImageSource(value) : "", element.bindingAttribute);
            }} else {{
              setNodeTextValue(node, value);
            }}
          }}
        }}

        applyElementOverride(node, element);
      }});

      doc.querySelectorAll(".studio-selected").forEach((node) => node.classList.remove("studio-selected"));
      const selected = selectedElement();
      if (!selected) return;
      const selectedNode = doc.querySelector(selected.selector);
      if (selectedNode) selectedNode.classList.add("studio-selected");
      elementMetrics(selected);
    }}

    renderShell();
  </script>
</body>
</html>
"""


def _draft_dir() -> Path:
    draft_dir = Path("preview_outputs") / "template_studio"
    draft_dir.mkdir(parents=True, exist_ok=True)
    return draft_dir


def _list_saved_drafts() -> list[str]:
    return [str(path) for path in sorted(_draft_dir().glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)]


def _save_current_draft(template_path: str) -> Path:
    raw_name = st.session_state.get("studio_draft_name", "sketch_card")
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw_name).strip("._") or "sketch_card"
    draft_path = _draft_dir() / f"{safe_name}.json"
    payload = {
        "template_path": template_path,
        "selected_element_id": st.session_state.get("studio_selected_element_id", DEFAULT_SELECTED_ELEMENT_ID),
        "preview_dataset": st.session_state.get("studio_preview_dataset", "medium"),
        "preview": {
            "title": st.session_state.get("studio_preview_title", ""),
            "text": st.session_state.get("studio_preview_text", ""),
            "image": st.session_state.get("studio_preview_image", ""),
        },
        "params": _get_current_param_values(),
    }
    draft_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return draft_path


def _load_draft(draft_path: Path, custom_params: dict[str, dict[str, Any]]) -> None:
    payload = json.loads(draft_path.read_text(encoding="utf-8"))
    preview = payload.get("preview", {})
    st.session_state["studio_preview_title"] = preview.get("title", PREVIEW_DATASETS["medium"]["title"])
    st.session_state["studio_preview_text"] = preview.get("text", PREVIEW_DATASETS["medium"]["text"])
    st.session_state["studio_preview_image"] = preview.get("image", PREVIEW_DATASETS["medium"]["image"])
    st.session_state["studio_preview_dataset"] = payload.get("preview_dataset", "medium")
    st.session_state["studio_preview_dataset_applied"] = payload.get("preview_dataset", "medium")
    st.session_state["studio_selected_element_id"] = payload.get("selected_element_id", DEFAULT_SELECTED_ELEMENT_ID)
    st.query_params["studio_selected"] = st.session_state["studio_selected_element_id"]
    for param_name, config in custom_params.items():
        st.session_state[_param_key(param_name)] = payload.get("params", {}).get(param_name, config.get("default"))
    st.session_state["studio_preview_path"] = ""
    st.session_state["studio_preview_error"] = ""
