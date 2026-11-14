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
