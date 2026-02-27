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

## 模型调研（2026-02-27）

### 图片生成模型

| 模型 | 平台 | 单价(1K) | 特点 | sucloud支持 |
|------|------|----------|------|-------------|
| gemini-3.1-flash-image-preview | Google | $0.067 | 4K输出、4-6秒、Flash速度+Pro级质量 | 已支持 |
| gemini-3-pro-image-preview | Google | $0.134 | 4K、94%文本渲染、角色一致性95%+ | 已支持 |
| gpt-image-1 | OpenAI | $0.04-0.17 | Prompt遵循度高 | 已支持 |
| DALL-E 3 | OpenAI | $0.016 | 性价比高但无4K | 已支持 |

### 视频生成模型（Seedance 2.0 竞品）

| 模型 | 开发商 | 分辨率 | 时长 | 唇同步 | 每10s约价 |
|------|--------|--------|------|--------|-----------|
| Runway Gen-4.5 | Runway | 1080p | 10s | 无 | ~$0.75 |
| Veo 3.1 | Google | 1080p/4K | 8s | 最佳原生 | ~$2.50 |
| Kling 3.0 | 快手 | 4K/60fps | 15s | 8+语言 | ~$0.50 |
| Seedance 2.0 | 字节跳动 | 2K | 15s | 8+语言 | ~$0.30-0.60 |
| Sora 2 | OpenAI | 1080p | 25s | 有限 | ~$1.00 |
| Wan 2.2 | 阿里巴巴 | 720p | 5s | 无 | ~$0.20(开源) |

### Talking Head（图片开口说话）

技术趋势：扩散模型取代GAN，从唇同步扩展到全身动画。

推荐方案（按优先级）：
1. **Seedance 2.0** — 全家桶，音频驱动+视频生成一体，API待正式开放（火山引擎）
2. **Veo 3.1** — 原生音频+唇同步最佳，价格较高
3. **Kling 3.0** — 性价比最高，已有Provider可复用
4. **OmniHuman 1.5**（字节）— 专用talking head，$0.04-0.16/s

开源SOTA（需GPU）：Hallo3（复旦）、LatentSync 1.6（字节）、MuseTalk 1.5（腾讯）

### API聚合平台

| 平台 | 支持模型 | 协议 | 特点 |
|------|---------|------|------|
| sucloud.vip | 图片+LLM（300+模型） | OpenAI兼容 | 项目已用，视频模型待确认 |
| Atlas Cloud | Seedance 2.0+Kling 3.0+Sora 2 | OpenAI兼容 | 视频模型推荐 |
| 硅基流动 SiliconFlow | Wan 2.2+HunyuanVideo | OpenAI兼容 | 开源视频极低价 |
| fal.ai | Veo 3.1+Kling+多种 | REST API | 海外开发者常用 |

### TTS 语音合成

当前方案：Edge TTS（免费，微软），默认晓晓 XiaoxiaoNeural。

| 方案 | 热门声音 | 成本 | 中文质量 | 接入状态 |
|------|---------|------|---------|---------|
| Edge TTS | 晓晓(女声天花板)、云希(男声第一) | 免费 | 极佳 | 已集成(默认) |
| 豆包TTS(火山引擎) | 解说小帅(现象级)、灿灿、擎苍 | ¥2/万字 | 顶级 | 待对接 |
| MiniMax speech-02-hd | 青涩青年、甜美女声、御姐 | ¥5.6/万字 | 优秀 | sucloud已支持 |
| Gemini 2.5 Flash TTS | 自然语言控制风格 | $10/M tokens | 好 | sucloud已支持 |

sucloud 音频模型：26个，含 MiniMax TTS、Gemini TTS、OpenAI TTS/Audio、Kling Audio、Vidu TTS。
