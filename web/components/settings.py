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
System settings component for web UI
"""

import streamlit as st

from web.i18n import tr, get_language
from web.utils.streamlit_helpers import safe_rerun
from pixelle_video.config import config_manager


def render_advanced_settings():
    """Render system configuration (required) with 2-column layout"""
    # Check if system is configured
    is_configured = config_manager.validate()
    
    # Expand if not configured, collapse if configured
    with st.expander(tr("settings.title"), expanded=not is_configured):
        # 2-column layout: LLM | ComfyUI
        llm_col, comfyui_col = st.columns(2)
        
        # ====================================================================
        # Column 1: LLM Settings
        # ====================================================================
        with llm_col:
            with st.container(border=True):
                st.markdown(f"**{tr('settings.llm.title')}**")
                
                # Quick preset selection
                from pixelle_video.llm_presets import get_preset_names, get_preset, find_preset_by_base_url_and_model
                
                # Custom at the end
                preset_names = get_preset_names() + ["Custom"]
                
                # Get current config
                current_llm = config_manager.get_llm_config()
                
                # Auto-detect which preset matches current config
                current_preset = find_preset_by_base_url_and_model(
                    current_llm["base_url"], 
                    current_llm["model"]
                )
                
                # Determine default index based on current config
                if current_preset:
                    # Current config matches a preset
                    default_index = preset_names.index(current_preset)
                else:
                    # Current config doesn't match any preset -> Custom
                    default_index = len(preset_names) - 1
                
                selected_preset = st.selectbox(
                    tr("settings.llm.quick_select"),
                    options=preset_names,
                    index=default_index,
                    help=tr("settings.llm.quick_select_help"),
                    key="llm_preset_select"
                )
                
                # Auto-fill based on selected preset
                if selected_preset != "Custom":
                    # Preset selected
                    preset_config = get_preset(selected_preset)
                    
                    # If user switched to a different preset (not current one), clear API key
                    # If it's the same as current config, keep API key
                    if selected_preset == current_preset:
                        # Same preset as saved config: keep API key
                        default_api_key = current_llm["api_key"]
                    else:
                        # Different preset: use default_api_key if provided (e.g., Ollama), otherwise clear
                        default_api_key = preset_config.get("default_api_key", "")
                    
                    default_base_url = preset_config.get("base_url", "")
                    default_model = preset_config.get("model", "")
                    
                    # Show API key URL if available
                    if preset_config.get("api_key_url"):
                        st.markdown(f"🔑 [{tr('settings.llm.get_api_key')}]({preset_config['api_key_url']})")
                else:
                    # Custom: show current saved config (if any)
                    default_api_key = current_llm["api_key"]
                    default_base_url = current_llm["base_url"]
                    default_model = current_llm["model"]
                
                st.markdown("---")
                
                # API Key (use unique key to force refresh when switching preset)
                llm_api_key = st.text_input(
                    f"{tr('settings.llm.api_key')} *",
                    value=default_api_key,
                    type="password",
                    help=tr("settings.llm.api_key_help"),
                    key=f"llm_api_key_input_{selected_preset}"
                )
                
                # Base URL (use unique key based on preset to force refresh)
                llm_base_url = st.text_input(
                    f"{tr('settings.llm.base_url')} *",
                    value=default_base_url,
                    help=tr("settings.llm.base_url_help"),
                    key=f"llm_base_url_input_{selected_preset}"
                )
                
                # Model selection with dropdown and load button
                # Initialize session state for loaded models
                if "llm_loaded_models" not in st.session_state:
                    st.session_state.llm_loaded_models = []
                
                # Build model options: Custom option + loaded models
                CUSTOM_MODEL_OPTION = f"✏️ {tr('settings.llm.custom_model')}"
                model_options = [CUSTOM_MODEL_OPTION] + st.session_state.llm_loaded_models
                
                # Determine default selection
                if default_model in st.session_state.llm_loaded_models:
                    default_model_index = model_options.index(default_model)
                else:
                    # Default model not in loaded list, use custom
                    default_model_index = 0
                
                # Model dropdown with load button on the right
                model_col, load_col, test_col = st.columns([3, 1, 1])
                
                with model_col:
                    selected_model_option = st.selectbox(
                        f"{tr('settings.llm.model')} *",
                        options=model_options,
                        index=default_model_index,
                        help=tr("settings.llm.model_help"),
                        key=f"llm_model_select_{selected_preset}"
                    )
                
                with load_col:
                    st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                    load_clicked = st.button(
                        f"🔄 {tr('settings.llm.load_models')}",
                        help=tr("settings.llm.load_models_help"),
                        key="load_models_btn",
                        use_container_width=True
                    )
                
                with test_col:
                    st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                    test_clicked = st.button(
                        f"🔌 {tr('settings.llm.test_connection')}",
                        help=tr("settings.llm.test_connection_help"),
                        key="test_llm_connection_btn",
                        use_container_width=True
                    )
                
                # Handle load models button click
                if load_clicked:
                    if llm_api_key and llm_base_url:
                        try:
                            from pixelle_video.utils.llm_util import fetch_available_models
                            with st.spinner(tr("settings.llm.loading_models")):
                                models = fetch_available_models(llm_api_key, llm_base_url)
                                st.session_state.llm_loaded_models = models
                                st.success(tr("settings.llm.models_loaded").replace("{count}", str(len(models))))
                                safe_rerun()
                        except Exception as e:
                            st.error(tr("settings.llm.models_load_failed").replace("{error}", str(e)))
                    else:
                        st.warning(tr("status.llm_config_incomplete"))
                
                # Handle test connection button click
                if test_clicked:
                    if llm_api_key and llm_base_url:
                        try:
                            from pixelle_video.utils.llm_util import test_llm_connection
                            with st.spinner(tr("settings.llm.loading_models")):
                                success, message, model_count = test_llm_connection(llm_api_key, llm_base_url)
                                if success:
                                    st.success(tr("settings.llm.connection_success").replace("{count}", str(model_count)))
                                else:
                                    st.error(tr("settings.llm.connection_failed").replace("{error}", message))
                        except Exception as e:
                            st.error(tr("settings.llm.connection_failed").replace("{error}", str(e)))
                    else:
                        st.warning(tr("status.llm_config_incomplete"))
                
                # If custom option selected, show text input for custom model name
                if selected_model_option == CUSTOM_MODEL_OPTION:
                    llm_model = st.text_input(
                        tr("settings.llm.custom_model_input"),
                        value=default_model,
                        help=tr("settings.llm.model_help"),
                        key=f"llm_custom_model_input_{selected_preset}"
                    )
                else:
                    llm_model = selected_model_option
        
        # ====================================================================
        # Column 2: Media Mode + ComfyUI / API Settings
        # ====================================================================
        with comfyui_col:
            # --- Media Mode Selector ---
            with st.container(border=True):
                st.markdown(f"**{tr('settings.media.title')}**")

                media_config = config_manager.get_media_config()
                current_mode = media_config.get("mode", "comfyui")

                media_mode = st.radio(
                    tr("settings.media.mode"),
                    ["comfyui", "api"],
                    horizontal=True,
                    format_func=lambda x: tr(f"settings.media.mode_{x}"),
                    index=0 if current_mode == "comfyui" else 1,
                    help=tr("settings.media.mode_help"),
                    key="media_mode_radio"
                )

                if media_mode == "api":
                    st.caption(tr("settings.media.api_hint"))
                else:
                    st.caption(tr("settings.media.comfyui_hint"))

            # Default values for branch-dependent variables to avoid NameError
            media_api_base_url = ""
            media_api_key = ""
            media_image_model = ""
            media_video_model = ""
            media_video_provider = ""
            media_video_base_url = ""
            media_video_api_key = ""
            comfyui_url = ""
            comfyui_api_key = ""
            runninghub_api_key = ""
            runninghub_concurrent_limit = 1
            runninghub_48g_enabled = False

            # --- API Mode Config ---
            if media_mode == "api":
                from web.components.model_presets import (
                    CUSTOM_OPTION,
                    IMAGE_MODEL_PRESETS,
                    DEFAULT_IMAGE_MODEL,
                    VIDEO_PROVIDER_PRESETS,
                    DEFAULT_VIDEO_PROVIDER,
                    VIDEO_MODEL_PRESETS,
                    get_video_models_for_provider,
                    get_default_video_model,
                    resolve_selection,
                    format_model_label,
                )

                with st.container(border=True):
                    api_cfg = media_config.get("api", {})

                    media_api_base_url = st.text_input(
                        tr("settings.media.api_base_url"),
                        value=api_cfg.get("base_url", ""),
                        help=tr("settings.media.api_base_url_help"),
                        key="media_api_base_url_input"
                    )
                    media_api_key = st.text_input(
                        tr("settings.media.api_key"),
                        value=api_cfg.get("api_key", ""),
                        type="password",
                        help=tr("settings.media.api_key_help"),
                        key="media_api_key_input"
                    )

                    # --- Image model dropdown ---
                    saved_image_model = api_cfg.get("image_model", DEFAULT_IMAGE_MODEL)
                    img_preset_ids = [m.id for m in IMAGE_MODEL_PRESETS]
                    img_options = img_preset_ids + [CUSTOM_OPTION]
                    img_labels = {m.id: format_model_label(m) for m in IMAGE_MODEL_PRESETS}
                    img_labels[CUSTOM_OPTION] = tr("settings.media.custom_model")

                    if saved_image_model in img_preset_ids:
                        img_default_idx = img_options.index(saved_image_model)
                    else:
                        img_default_idx = img_options.index(CUSTOM_OPTION)

                    img_selected = st.selectbox(
                        tr("settings.media.image_model"),
                        options=img_options,
                        index=img_default_idx,
                        format_func=lambda x: img_labels.get(x, x),
                        help=tr("settings.media.image_model_help"),
                        key="media_image_model_select"
                    )

                    if img_selected == CUSTOM_OPTION:
                        img_custom = st.text_input(
                            tr("settings.media.custom_model_input"),
                            value=saved_image_model if saved_image_model not in img_preset_ids else "",
                            help=tr("settings.media.image_model_help"),
                            key="media_image_model_custom"
                        )
                        media_image_model = resolve_selection(img_selected, img_custom)
                    else:
                        media_image_model = img_selected

                    # --- Video provider dropdown ---
                    saved_provider = api_cfg.get("video_provider", DEFAULT_VIDEO_PROVIDER)
                    prov_ids = [p.id for p in VIDEO_PROVIDER_PRESETS]
                    prov_labels = {p.id: f"{p.label}  ({p.hint})" if p.hint else p.label for p in VIDEO_PROVIDER_PRESETS}

                    prov_default_idx = prov_ids.index(saved_provider) if saved_provider in prov_ids else 0

                    provider_col, vid_col = st.columns(2)
                    with provider_col:
                        media_video_provider = st.selectbox(
                            tr("settings.media.video_provider"),
                            options=prov_ids,
                            index=prov_default_idx,
                            format_func=lambda x: prov_labels.get(x, x),
                            help=tr("settings.media.video_provider_help"),
                            key="media_video_provider_select"
                        )

                    # --- Video model dropdown (linked to provider) ---
                    vid_preset_ids = get_video_models_for_provider(media_video_provider)
                    vid_options = vid_preset_ids + [CUSTOM_OPTION]
                    vid_presets = VIDEO_MODEL_PRESETS.get(media_video_provider, ())
                    vid_labels = {m.id: format_model_label(m) for m in vid_presets}
                    vid_labels[CUSTOM_OPTION] = tr("settings.media.custom_model")

                    saved_video_model = api_cfg.get("video_model", "")
                    if saved_video_model in vid_preset_ids:
                        vid_default_idx = vid_options.index(saved_video_model)
                    elif saved_video_model and saved_video_model not in vid_preset_ids:
                        vid_default_idx = vid_options.index(CUSTOM_OPTION)
                    else:
                        default_vm = get_default_video_model(media_video_provider)
                        vid_default_idx = vid_options.index(default_vm) if default_vm in vid_options else 0

                    with vid_col:
                        vid_selected = st.selectbox(
                            tr("settings.media.video_model"),
                            options=vid_options,
                            index=vid_default_idx,
                            format_func=lambda x: vid_labels.get(x, x),
                            help=tr("settings.media.video_model_help"),
                            key="media_video_model_select"
                        )

                    if vid_selected == CUSTOM_OPTION:
                        vid_custom = st.text_input(
                            tr("settings.media.custom_model_input"),
                            value=saved_video_model if saved_video_model not in vid_preset_ids else "",
                            help=tr("settings.media.video_model_help"),
                            key="media_video_model_custom"
                        )
                        media_video_model = resolve_selection(vid_selected, vid_custom)
                    else:
                        media_video_model = vid_selected

                    with st.expander(tr("settings.media.video_base_url"), expanded=False):
                        media_video_base_url = st.text_input(
                            tr("settings.media.video_base_url"),
                            value=api_cfg.get("video_base_url", ""),
                            help=tr("settings.media.video_base_url_help"),
                            key="media_video_base_url_input",
                            label_visibility="collapsed"
                        )
                        media_video_api_key = st.text_input(
                            tr("settings.media.video_api_key"),
                            value=api_cfg.get("video_api_key", ""),
                            type="password",
                            help=tr("settings.media.video_api_key_help"),
                            key="media_video_api_key_input"
                        )

            # --- ComfyUI Mode Config ---
            else:
                with st.container(border=True):
                    st.markdown(f"**{tr('settings.comfyui.title')}**")

                    comfyui_config = config_manager.get_comfyui_config()

                    st.markdown(f"**{tr('settings.comfyui.local_title')}**")
                    url_col, key_col = st.columns(2)
                    with url_col:
                        comfyui_url = st.text_input(
                            tr("settings.comfyui.comfyui_url"),
                            value=comfyui_config.get("comfyui_url", "http://127.0.0.1:8188"),
                            help=tr("settings.comfyui.comfyui_url_help"),
                            key="comfyui_url_input"
                        )
                    with key_col:
                        comfyui_api_key = st.text_input(
                            tr("settings.comfyui.comfyui_api_key"),
                            value=comfyui_config.get("comfyui_api_key", ""),
                            type="password",
                            help=tr("settings.comfyui.comfyui_api_key_help"),
                            key="comfyui_api_key_input"
                        )

                    if st.button(tr("btn.test_connection"), key="test_comfyui", use_container_width=True):
                        try:
                            import requests
                            response = requests.get(f"{comfyui_url}/system_stats", timeout=5)
                            if response.status_code == 200:
                                st.success(tr("status.connection_success"))
                            else:
                                st.error(tr("status.connection_failed"))
                        except Exception as e:
                            st.error(f"{tr('status.connection_failed')}: {str(e)}")

                    st.markdown("---")

                    st.markdown(f"**{tr('settings.comfyui.cloud_title')}**")
                    runninghub_api_key = st.text_input(
                        tr("settings.comfyui.runninghub_api_key"),
                        value=comfyui_config.get("runninghub_api_key", ""),
                        type="password",
                        help=tr("settings.comfyui.runninghub_api_key_help"),
                        key="runninghub_api_key_input"
                    )
                    st.caption(
                        f"{tr('settings.comfyui.runninghub_hint')} "
                        f"[{tr('settings.comfyui.runninghub_get_api_key')}]"
                        f"(https://www.runninghub{'.cn' if get_language() == 'zh_CN' else '.ai'}/?inviteCode=bozpdlbj)"
                    )

                    limit_col, instance_col = st.columns(2)
                    with limit_col:
                        runninghub_concurrent_limit = st.number_input(
                            tr("settings.comfyui.runninghub_concurrent_limit"),
                            min_value=1,
                            max_value=10,
                            value=comfyui_config.get("runninghub_concurrent_limit", 1),
                            help=tr("settings.comfyui.runninghub_concurrent_limit_help"),
                            key="runninghub_concurrent_limit_input"
                        )
                    with instance_col:
                        current_instance_type = comfyui_config.get("runninghub_instance_type") or ""
                        is_plus_enabled = current_instance_type == "plus"
                        instance_options = [
                            tr("settings.comfyui.runninghub_instance_24g"),
                            tr("settings.comfyui.runninghub_instance_48g"),
                        ]
                        runninghub_instance_type_display = st.selectbox(
                            tr("settings.comfyui.runninghub_instance_type"),
                            options=instance_options,
                            index=1 if is_plus_enabled else 0,
                            help=tr("settings.comfyui.runninghub_instance_type_help"),
                            key="runninghub_instance_type_input"
                        )
                        runninghub_48g_enabled = runninghub_instance_type_display == tr("settings.comfyui.runninghub_instance_48g")

        # ====================================================================
        # Action Buttons (full width at bottom)
        # ====================================================================
        st.markdown("---")

        col1, col2 = st.columns(2)
        with col1:
            if st.button(tr("btn.save_config"), use_container_width=True, key="save_config_btn"):
                try:
                    if not (llm_api_key and llm_base_url and llm_model):
                        st.error(tr("status.llm_config_incomplete"))
                    else:
                        config_manager.set_llm_config(llm_api_key, llm_base_url, llm_model)

                    # Save media mode config
                    if media_mode == "api":
                        config_manager.set_media_config(
                            mode="api",
                            api_config={
                                "base_url": media_api_base_url,
                                "api_key": media_api_key,
                                "image_model": media_image_model,
                                "video_model": media_video_model,
                                "video_provider": media_video_provider,
                                "video_base_url": media_video_base_url,
                                "video_api_key": media_video_api_key,
                            }
                        )
                    else:
                        config_manager.set_media_config(mode="comfyui")
                        instance_type = "plus" if runninghub_48g_enabled else ""
                        config_manager.set_comfyui_config(
                            comfyui_url=comfyui_url if comfyui_url else None,
                            comfyui_api_key=comfyui_api_key if comfyui_api_key else None,
                            runninghub_api_key=runninghub_api_key if runninghub_api_key else None,
                            runninghub_concurrent_limit=int(runninghub_concurrent_limit),
                            runninghub_instance_type=instance_type
                        )

                    if llm_api_key and llm_base_url and llm_model:
                        config_manager.save()
                        st.success(tr("status.config_saved"))
                        safe_rerun()
                except Exception as e:
                    st.error(f"{tr('status.save_failed')}: {str(e)}")

        with col2:
            if st.button(tr("btn.reset_config"), use_container_width=True, key="reset_config_btn"):
                from pixelle_video.config.schema import PixelleVideoConfig
                config_manager.config = PixelleVideoConfig()
                config_manager.save()
                st.success(tr("status.config_reset"))
                safe_rerun()

