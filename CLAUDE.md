# CLAUDE.md — Pixelle-Video（SayDoneAI Fork）

> 本项目是 [AIDC-AI/Pixelle-Video](https://github.com/AIDC-AI/Pixelle-Video) 的 Fork，在上游基础上新增 API 直连模式（无需 GPU / ComfyUI）。

## 分支策略

| 分支 | 用途 |
|------|------|
| `main` | 与上游 AIDC-AI/Pixelle-Video 保持同步，不做自定义改动 |
| `dev` | 所有自定义功能（F001-F007），日常开发分支 |

日常开发在 `dev` 分支进行；PR 目标分支为 `main`（如需合回上游）或 `dev`（Fork 内部）。

## 项目结构

```
Pixelle-Video/
├── pixelle_video/                # 核心 Python 包
│   ├── config/
│   │   └── schema.py            # Pydantic 配置模型（PixelleVideoConfig 为根）
│   ├── models/
│   │   ├── media.py             # MediaResult 数据模型
│   │   ├── progress.py          # 进度回调模型
│   │   └── storyboard.py        # 分镜脚本模型
│   ├── pipelines/
│   │   ├── base.py              # BasePipeline 抽象基类
│   │   ├── standard.py          # 标准流水线（文案→生图→TTS→合成）
│   │   ├── linear.py            # 线性流水线
│   │   ├── asset_based.py       # 自定义素材流水线
│   │   └── custom.py            # 自定义脚本流水线
│   ├── services/
│   │   ├── api_media.py         # [Fork] ApiMediaService — API 模式入口
│   │   ├── media.py             # ComfyUI MediaService
│   │   ├── frame_processor.py   # 帧合成（下载媒体 + 渲染模板 + 截图）
│   │   ├── tts_service.py       # TTS 语音合成
│   │   ├── video.py             # ffmpeg 视频拼接
│   │   └── providers/           # [Fork] 媒体生成 Provider
│   │       ├── base.py          #   MediaProvider 抽象基类
│   │       ├── openai.py        #   OpenAI Provider（图片）
│   │       ├── kling.py         #   Kling Provider（异步视频）
│   │       ├── sucloud_video.py #   Sucloud Provider（统一视频协议）
│   │       └── errors.py        #   共享错误类型 + 重试常量
│   ├── prompts/                 # LLM Prompt 模板
│   │   ├── image_generation.py  # 生图 prompt（含角色注入逻辑）
│   │   └── ...
│   ├── utils/                   # 工具函数
│   │   ├── content_generators.py
│   │   ├── llm_util.py
│   │   └── ...
│   ├── service.py               # ServiceManager — 根据 config 初始化各 Service
│   ├── llm_presets.py           # LLM 预设配置
│   └── tts_voices.py            # TTS 音色列表
├── web/                         # Streamlit Web UI
│   ├── app.py                   # 入口
│   └── components/
│       ├── media_config.py      # [Fork] API/ComfyUI 模式切换 + 视频开关
│       ├── model_presets.py     # [Fork] 模型预设（含 sucloud 定价）
│       ├── style_config.py      # 视觉风格配置
│       ├── content_input.py     # 内容输入
│       ├── settings.py          # 系统设置
│       └── output_preview.py    # 输出预览
├── templates/                   # HTML 视频帧模板
├── workflows/                   # ComfyUI 工作流 JSON
├── tests/                       # 测试
│   ├── test_api_media.py        # ApiMediaService 单元/集成测试
│   ├── test_config_schema.py    # 配置 schema 测试
│   ├── test_f007_character.py   # 角色配置化测试
│   ├── test_model_presets.py    # 模型预设测试
│   └── test_template_image_style.py
├── config.yaml                  # 运行时配置（.gitignore，不提交）
├── config.example.yaml          # 配置模板（提交到 Git）
└── pyproject.toml               # 项目依赖
```

## Fork 新增功能（F001-F007）

| 编号 | 功能 | 核心文件 |
|------|------|----------|
| F001 | API 直连生图 | `services/api_media.py`, `providers/openai.py` |
| F002 | API 异步生视频 | `services/api_media.py`, `providers/kling.py` |
| F003 | Web UI 模式切换 | `web/components/media_config.py` |
| F004 | Sucloud 视频 Provider | `providers/sucloud_video.py` |
| F005 | Web UI 模型下拉 | `web/components/model_presets.py` |
| F006 | 视频生成开关 | `config/schema.py` → `video_enabled`, `web/components/media_config.py` |
| F007 | 角色配置化 | `config/schema.py` → `CharacterConfig`, `prompts/image_generation.py` |

## 核心链路

### 标准视频生成流水线
```
用户输入主题 → LLM 生成分镜脚本 → 逐帧生成媒体（图片/视频）
→ TTS 语音合成 → FrameProcessor 帧合成 → ffmpeg 视频拼接 + BGM
```

### API 模式链路（Fork 新增）
```
config.yaml media.mode=api
→ ServiceManager 初始化 ApiMediaService（而非 ComfyUI MediaService）
→ ApiMediaService 根据 media_type 路由到 Provider：
    - image → OpenAIProvider → /v1/images/generations
    - video → SucloudVideoProvider → /v1/video/create + /v1/video/query（轮询）
→ 返回 URL 格式 MediaResult → FrameProcessor._download_media 下载到本地
```

## 配置

配置单一来源：`config/schema.py`（Pydantic 模型）。

运行时配置文件：`config.yaml`（从 `config.example.yaml` 复制）。

关键配置路径：
- `llm.*` — LLM 配置
- `comfyui.*` — ComfyUI 模式配置
- `media.mode` — `"comfyui"` 或 `"api"`
- `media.api.base_url / api_key / image_model` — 图片 API
- `media.api.video_provider / video_model` — 视频 API
- `media.api.video_enabled` — 视频生成开关
- `media.api.character.*` — 角色一致性配置
- `template.default_template` — 默认帧模板

## 开发工作流

### 运行项目
```bash
uv run streamlit run web/app.py
```

### 运行测试
```bash
uv run pytest tests/ -v
```

### 代码风格
- Python 3.10+，使用 type hints
- Pydantic BaseModel 做配置校验
- 异步 Provider 使用 httpx.AsyncClient
- Provider 模式：`MediaProvider` 抽象基类 → 具体 Provider 实现
- 不可变模式：配置对象创建后不修改

### 提交规范
```
<type>: <description>
```
类型：`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`

### 注意事项
- `config.yaml` 包含 API Key，已在 `.gitignore` 中，**绝对不要提交**
- `config.example.yaml` 是配置模板，新增配置项时必须同步更新
- 上游同步：`main` 分支定期 `git pull upstream main`，然后 `dev` 分支 rebase
