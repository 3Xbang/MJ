# AFE 新 Pod 完整部署命令

复制粘贴到 RunPod 终端，一次性完成所有安装和下载。

```bash
# ── Step 1: 安装自定义节点 ──────────────────────────────────────────────────
cd /workspace/runpod-slim/ComfyUI/custom_nodes
git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes
pip install loguru json_repair -q

# ── Step 2: 安装 LLM Party ──────────────────────────────────────────────────
git clone https://github.com/heshengtao/comfyui_LLM_party.git
cd comfyui_LLM_party && pip install -r requirements.txt -q && cd ..

# ── Step 3: 下载 Qwen 2.5-7B LLM 模型（15GB，约5分钟）────────────────────
mkdir -p /workspace/runpod-slim/ComfyUI/models/LLM
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='Qwen/Qwen2.5-7B-Instruct',
    local_dir='/workspace/runpod-slim/ComfyUI/models/LLM/Qwen2.5-7B-Instruct',
    ignore_patterns=['*.bin']
)
print('✅ Qwen 2.5-7B 完成')
"

# ── Step 4: 下载 Qwen Image 2.1 模型（约31GB，约15分钟）─────────────────────
python3 << 'EOF'
from huggingface_hub import hf_hub_download
import os, shutil

TMP   = '/tmp/qwen_img_dl'
UNET  = '/workspace/runpod-slim/ComfyUI/models/unet'
VAE   = '/workspace/runpod-slim/ComfyUI/models/vae'
TE    = '/workspace/runpod-slim/ComfyUI/models/text_encoders'

os.makedirs(UNET, exist_ok=True); os.makedirs(VAE, exist_ok=True); os.makedirs(TE, exist_ok=True)

# UNET
hf_hub_download('toxicdog/Qwen-Image-2.1-INT4ConvRot-ComfyUI',
    'diffusion_models/qwen_image_2.1_int8_convrot.safetensors', local_dir=TMP)
shutil.move(f'{TMP}/diffusion_models/qwen_image_2.1_int8_convrot.safetensors',
            f'{UNET}/qwen_image_2.1_turbo_int8_convrot.safetensors')
print('✅ UNET')

# VAE
hf_hub_download('toxicdog/Qwen-Image-2.1-INT4ConvRot-ComfyUI',
    'vae/qwen_image_2.1_vae_bf16.safetensors', local_dir=TMP)
shutil.move(f'{TMP}/vae/qwen_image_2.1_vae_bf16.safetensors',
            f'{VAE}/qwen_image_2.1_vae_bf16.safetensors')
print('✅ VAE')

# Text Encoder VL
hf_hub_download('toxicdog/Qwen-Image-2.1-INT4ConvRot-ComfyUI',
    'text_encoders/qwen3vl_8b_int8_convrot.safetensors', local_dir=TMP)
shutil.move(f'{TMP}/text_encoders/qwen3vl_8b_int8_convrot.safetensors',
            f'{TE}/qwen3vl_8b_int8_convrot.safetensors')
print('✅ Text Encoder VL')

# PE model
hf_hub_download('HarleyWang/Qwen-Image-2.1-PE-ComfyUI',
    'qwen_image_2.1_pe_i2i_int8_convrot.safetensors', local_dir=TMP)
shutil.move(f'{TMP}/qwen_image_2.1_pe_i2i_int8_convrot.safetensors',
            f'{TE}/qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors')
print('✅ PE model')
print('🎉 Qwen Image 2.1 全部完成')
EOF

# ── Step 5: 复制姿势参考图 ────────────────────────────────────────────────────
mkdir -p /workspace/runpod-slim/ComfyUI/input/poses
cp ai_film_editor_nodes/assets/poses/*.png /workspace/runpod-slim/ComfyUI/input/
cp ai_film_editor_nodes/assets/poses/*.png /workspace/runpod-slim/ComfyUI/input/poses/

# ── Step 6: 启动 ComfyUI ──────────────────────────────────────────────────────
cd /workspace/runpod-slim/ComfyUI
nohup python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header "*" > /tmp/comfyui.log 2>&1 &
echo "✅ 部署完成！等30秒后访问 ComfyUI"
```

## 加载 Workflow

重启后在 ComfyUI 里加载（本地文件）：
- 角色卡：`D:\下载\character_card_9views.json`
- 完整流程：`D:\下载\afe_script_pipeline.json`
