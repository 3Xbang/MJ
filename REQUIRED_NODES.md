# Required & Recommended Nodes

## Built-in ComfyUI Nodes (No Installation)
These come with every ComfyUI installation:
- `KSampler` / `KSamplerAdvanced`
- `CLIPTextEncode`
- `VAEDecode` / `VAEEncode`
- `CheckpointLoaderSimple`
- `LoadImage`
- `SaveImage`
- `EmptyLatentImage`
- `LoraLoader`
- `VAELoader`
- `CLIPLoader`
- `ImageScale` / `ImageUpscaleWithModel`

## Recommended Third-Party Nodes

### ComfyUI-VideoHelperSuite (required for video workflows)
- **Repo**: https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite
- **Nodes used**: `VHS_VideoCombine`, `VHS_LoadVideo`, `VHS_LoadImages`
- **Install via ComfyUI Manager** or:
  ```bash
  cd ComfyUI/custom_nodes
  git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite
  ```

## Video Model Nodes (Install one based on your model)

### Wan 2.1
Wan video nodes are included in recent ComfyUI versions (search for `WanImageToVideo` or `WanTextToVideo` in your node list). If not present, search **ComfyUI Manager** for "Wan" to install a community pack.
- Wan 2.1 I2V 14B 480p model: https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P
- Wan 2.1 T2V 1.3B model (lighter): https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B

### Kling
Search ComfyUI Manager for "Kling" or use Kling's official API with a generic HTTP node.

## Model Files (Download Required)
Place model files in the ComfyUI `models/` subdirectory as directed by each loader node.

| Model | Type | Link | Destination |
|-------|------|------|-------------|
| SD 1.5 | Checkpoint | https://huggingface.co/runwayml/stable-diffusion-v1-5 | `models/checkpoints/` |
| SDXL 1.0 | Checkpoint | https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0 | `models/checkpoints/` |
| Wan 2.1 I2V 14B 480p | Video | https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P | `models/wan/` |
| Wan 2.1 T2V 1.3B | Video | https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B | `models/wan/` |

## Minimum System Requirements
- Python 3.10+
- ComfyUI latest stable (https://github.com/comfyanonymous/ComfyUI)
- 16 GB RAM (32 GB recommended for 14B video models)
- NVIDIA GPU 8 GB VRAM+ (24 GB+ for 14B video models)
- CUDA 11.8+ or 12.x
