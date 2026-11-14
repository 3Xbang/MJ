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
