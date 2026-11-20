# Required Nodes for AI Film Editor Workflows

---

## Section 1 — 内置节点（ComfyUI 自带，无需安装）

KSampler, KSamplerAdvanced, CLIPTextEncode, VAEDecode, VAELoader, CLIPLoader, CheckpointLoaderSimple, LoadImage, SaveImage, EmptyLatentImage, ImageScale

---

## Section 2 — 通过 ComfyUI Manager 安装

- **ComfyUI-VideoHelperSuite**（作者：Kosinkadink）
  - 安装方式：ComfyUI Manager → Search "VideoHelperSuite"
  - 提供节点：VHS_VideoCombine

- **ComfyUI-WanVideoWrapper**（作者：kijai）
  - 安装方式：ComfyUI Manager → Search "WanVideoWrapper"
  - 提供节点：WanVideoModelLoader, WanTextEncode, WanImageToVideoLatent, WanVideoVAEDecode

---

## Section 3 — 模型文件下载（放到 ComfyUI 对应 models 子目录）

| 文件名 | 目标目录 |
|--------|----------|
| Wan2.1-I2V-14B-480P_fp8_e4m3fn.safetensors | models/diffusion_models/ |
| umt5-xxl-enc-bf16.safetensors | models/text_encoders/ |
| wan_2.1_vae.safetensors | models/vae/ |

下载地址：https://huggingface.co/Kijai/WanVideo_comfy

---

## Section 4 — 自定义节点类型（本项目输出类型）

以下是 AI Film Editor 节点之间传递的自定义数据类型：

| 类型名称 | 描述 |
|----------|------|
| CHARACTER_ASSET | 角色资产，包含角色提示词、LoRA 配置、视图等 |
| OUTFIT_ASSET | 服装资产，关联到角色 |
| SCENE_ASSET | 场景/背景资产，包含环境信息 |
| PROPS_ASSET | 道具资产，包含道具类型、提示词、关联角色与场景 |

## Part 2 — 二采精修 (Second Pass Refinement)

### Required Downloads
- **ComfyUI_CodeFormer** — AI face restoration and enhancement
  - Install from ComfyUI Manager
  - Used by: `AFE_FaceEnhancer` node (graceful fallback passthrough if not installed)
- **ComfyUI-BSRGAN** or **ComfyUI-Real-ESRGAN** — AI video/image super-resolution
  - Install from ComfyUI Manager
  - Chain after `AFE_VideoUpscaler` for AI-quality super-resolution

## Part 3 — 音频唇形同步 (Audio & Lip Sync)

### Required Downloads (choose one)
- **ComfyUI-LatentSync** — Latent-space lip sync (recommended)
  - Install from ComfyUI Manager
- **ComfyUI-Wav2Lip** — Wav2Lip-based lip sync
  - Install from ComfyUI Manager
- **ComfyUI-SadTalker** — SadTalker-based talking head
  - Install from ComfyUI Manager

### Notes
- `AFE_LipSyncConfig` outputs `images` + `audio_path` → connect to your chosen lip sync node
- `AFE_AudioVideoSync` outputs `images` + `frame_rate` + `audio_path` → connect directly to `VHS_VideoCombine`

## Part 4 — 剪辑发布 (Edit & Export)

### No additional downloads required
- Part 4 uses VideoHelperSuite (`VHS_VideoCombine`) already listed in Part 1
- `AFE_ShotSequenceBuilder`, `AFE_ProjectExport`, and `AFE_Watermark` are self-contained

---

## Section 5 — 剧本解析流水线 (Script Analysis Pipeline)

### Required: comfyui_LLM_party

The `afe_script_pipeline.json` workflow template uses nodes from
[comfyui_LLM_party](https://github.com/heshengtao/comfyui_LLM_party):

| Node used in template | Purpose |
|-----------------------|---------|
| `LLM_local_loader` | Load a local LLM model (e.g. Qwen2.5-7B-Instruct) |
| `LLM_local` | Run inference with the loaded model |
| `show_text_party` | Display text output in the ComfyUI canvas (×5 display nodes) |

**Install steps (RunPod / Linux):**
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/heshengtao/comfyui_LLM_party
pip install -r comfyui_LLM_party/requirements.txt
```

**Install steps (ComfyUI Manager):**
ComfyUI Manager → Search "LLM Party" → Install

> ⚠️ **Without comfyui_LLM_party installed, the `afe_script_pipeline.json`
> template will fail to open.** The AFE analysis nodes (AFE_ScriptParser,
> AFE_SceneAnalyzer, AFE_PropsAnalyzer, AFE_CharacterTracker,
> AFE_ShotPromptBuilder, AFE_ShotList) work independently and do not require
> LLM Party.

### Required: Local LLM model

Place your model under `models/LLM/`, e.g.:

```
models/LLM/Qwen2.5-7B-Instruct/
```

The workflow template is pre-configured for `models/LLM/Qwen2.5-7B-Instruct/`.
Any model compatible with `LLM_local_loader` can be substituted by editing
Node 1's widget value.

See **MIGRATION.md** for slot-change notes if you are updating existing workflows.
