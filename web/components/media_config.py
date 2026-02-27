# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Media generation mode UI components (API / ComfyUI).

Extracted from style_config.py to keep file sizes manageable.
"""

import streamlit as st
from loguru import logger

from web.i18n import tr
from web.utils.async_helpers import run_async
from web.utils.streamlit_helpers import check_and_warn_selfhost_workflow
from pixelle_video.config import config_manager


def render_api_media_section(template_media_type: str) -> tuple:
    """Render media section for API mode.

    Returns:
        (prompt_prefix, workflow_key, media_width, media_height)
    """
    with st.container(border=True):
        section_title = tr('section.video') if template_media_type == "video" else tr('section.image')
        st.markdown(f"**{section_title}**")
        st.info(tr("style.api_mode_info"))

        api_cfg = config_manager.config.media.api
        image_model = api_cfg.image_model or "\u2014"
        video_model = api_cfg.video_model or "\u2014"
        video_provider = api_cfg.video_provider or "\u2014"
        st.caption(tr("style.api_mode_model_info",
                      image_model=image_model,
                      video_model=video_model,
                      video_provider=video_provider))

        media_width = st.session_state.get('template_media_width')
        media_height = st.session_state.get('template_media_height')
        if media_width and media_height:
            if template_media_type == "video":
                st.caption(tr("style.video_size_info", width=media_width, height=media_height))
            else:
                st.caption(tr("style.image_size_info", width=media_width, height=media_height))

        comfyui_config = config_manager.get_comfyui_config()
        media_config_key = "video" if template_media_type == "video" else "image"
        default_prefix = comfyui_config.get(media_config_key, {}).get("prompt_prefix", "")

        with st.expander(tr("help.feature_description"), expanded=False):
            st.markdown(f"**{tr('help.what')}**")
            st.markdown(tr("style.prompt_prefix_what"))

        prompt_prefix = st.text_area(
            tr("style.prompt_prefix"),
            value=default_prefix,
            placeholder=tr("style.prompt_prefix_placeholder"),
            help=tr("style.prompt_prefix_help"),
            height=80,
            key="api_prompt_prefix"
        )

        return prompt_prefix, None, media_width, media_height


def render_comfyui_media_section(pixelle_video, template_media_type: str) -> tuple:
    """Render media section for ComfyUI mode.

    Returns:
        (prompt_prefix, workflow_key, media_width, media_height)
    """
    with st.container(border=True):
        section_title = tr('section.video') if template_media_type == "video" else tr('section.image')
        st.markdown(f"**{section_title}**")

        with st.expander(tr("help.feature_description"), expanded=False):
            st.markdown(f"**{tr('help.what')}**")
            if template_media_type == "video":
                st.markdown(tr('style.video_workflow_what'))
            else:
                st.markdown(tr("style.workflow_what"))
            st.markdown(f"**{tr('help.how')}**")
            if template_media_type == "video":
                st.markdown(tr('style.video_workflow_how'))
            else:
                st.markdown(tr("style.workflow_how"))

        all_workflows = pixelle_video.media.list_workflows()

        if template_media_type == "video":
            workflows = [wf for wf in all_workflows if "video_" in wf["key"].lower()]
        else:
            workflows = [wf for wf in all_workflows if "video_" not in wf["key"].lower()]

        workflow_options = [wf["display_name"] for wf in workflows]
        workflow_keys = [wf["key"] for wf in workflows]

        default_workflow_index = 0

        comfyui_config = config_manager.get_comfyui_config()
        media_config_key = "video" if template_media_type == "video" else "image"
        saved_workflow = comfyui_config.get(media_config_key, {}).get("default_workflow", "")
        if saved_workflow and saved_workflow in workflow_keys:
            default_workflow_index = workflow_keys.index(saved_workflow)

        workflow_display = st.selectbox(
            "Workflow",
            workflow_options if workflow_options else ["No workflows found"],
            index=default_workflow_index,
            label_visibility="collapsed",
            key="media_workflow_select"
        )

        if workflow_options:
            workflow_selected_index = workflow_options.index(workflow_display)
            workflow_key = workflow_keys[workflow_selected_index]
        else:
            workflow_key = "runninghub/image_flux.json"

        check_and_warn_selfhost_workflow(workflow_key)

        media_width = st.session_state.get('template_media_width')
        media_height = st.session_state.get('template_media_height')

        if template_media_type == "video":
            size_info_text = tr('style.video_size_info', width=media_width, height=media_height)
        else:
            size_info_text = tr('style.image_size_info', width=media_width, height=media_height)
        st.info(f"\U0001f4d0 {size_info_text}")

        current_prefix = comfyui_config.get(media_config_key, {}).get("prompt_prefix", "")

        prompt_prefix = st.text_area(
            tr('style.prompt_prefix'),
            value=current_prefix,
            placeholder=tr("style.prompt_prefix_placeholder"),
            height=80,
            label_visibility="visible",
            help=tr("style.prompt_prefix_help")
        )

        _render_media_preview(
            pixelle_video, template_media_type,
            workflow_key, prompt_prefix, media_width, media_height
        )

    return prompt_prefix, workflow_key, media_width, media_height


def _render_media_preview(pixelle_video, template_media_type, workflow_key, prompt_prefix, media_width, media_height):
    """Render the media preview expander (used in ComfyUI mode)."""
    preview_title = tr("style.video_preview_title") if template_media_type == "video" else tr("style.preview_title")
    with st.expander(preview_title, expanded=False):
        if template_media_type == "video":
            test_prompt_label = tr("style.test_video_prompt")
            test_prompt_value = "a dog running in the park"
        else:
            test_prompt_label = tr("style.test_prompt")
            test_prompt_value = "a dog"

        test_prompt = st.text_input(
            test_prompt_label,
            value=test_prompt_value,
            help=tr("style.test_prompt_help"),
            key="style_test_prompt"
        )

        preview_button_label = tr("style.video_preview") if template_media_type == "video" else tr("style.preview")
        if st.button(preview_button_label, key="preview_style", use_container_width=True):
            previewing_text = tr("style.video_previewing") if template_media_type == "video" else tr("style.previewing")
            with st.spinner(previewing_text):
                try:
                    from pixelle_video.utils.prompt_helper import build_image_prompt

                    final_prompt = build_image_prompt(test_prompt, prompt_prefix)

                    media_result = run_async(pixelle_video.media(
                        prompt=final_prompt,
                        workflow=workflow_key,
                        media_type=template_media_type,
                        width=int(media_width),
                        height=int(media_height)
                    ))
                    preview_media_path = media_result.url

                    if preview_media_path:
                        success_text = tr("style.video_preview_success") if template_media_type == "video" else tr("style.preview_success")
                        st.success(success_text)

                        if template_media_type == "video":
                            st.video(preview_media_path)
                        else:
                            st.image(preview_media_path, caption="Style Preview")

                        st.info(f"**{tr('style.final_prompt_label')}**\n{final_prompt}")
                        st.caption(f"\U0001f4c1 {preview_media_path}")
                    else:
                        st.error(tr("style.preview_failed_general"))
                except Exception as e:
                    st.error(tr("style.preview_failed", error=str(e)))
                    logger.exception(e)
