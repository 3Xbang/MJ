# AFE 新 Pod 完整部署命令

复制粘贴到 RunPod 终端，一次性完成所有安装和下载。
总下载量约 60GB（Qwen 7B 15GB + Qwen Image 2.1 31GB + Krea 2 约 15GB），预计 25-30 分钟。

```bash
COMFY=/workspace/runpod-slim/ComfyUI
CN=$COMFY/custom_nodes

# ── Step 0: 升级 ComfyUI 本体（Krea 2 需要较新版本，CLIPLoader 才有 krea2 类型）──
cd $COMFY && git pull && pip install -r requirements.txt -q

# ── Step 1: 安装自定义节点 ──────────────────────────────────────────────────
cd $CN
[ -d ai_film_editor_nodes ] || git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes
pip install loguru json_repair imageio-ffmpeg -q

# ── Step 2: 安装 LLM Party（文字显示节点 show_text_party）和 KJNodes（Krea2PromptWeight）──
[ -d comfyui_LLM_party ] || git clone https://github.com/heshengtao/comfyui_LLM_party.git
cd comfyui_LLM_party && pip install -r requirements.txt -q && cd ..
[ -d ComfyUI-KJNodes ] || git clone https://github.com/kijai/ComfyUI-KJNodes.git
cd ComfyUI-KJNodes && pip install -r requirements.txt -q && cd ..

# ── Step 3: 下载 Qwen 2.5-7B LLM 模型（15GB，剧本解析用）─────────────────────
mkdir -p $COMFY/models/LLM
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='Qwen/Qwen2.5-7B-Instruct',
    local_dir='$COMFY/models/LLM/Qwen2.5-7B-Instruct',
    ignore_patterns=['*.bin']
)
print('✅ Qwen 2.5-7B 完成')
"

# ── Step 4: 下载 Krea 2 Turbo（场景图、道具图用，官方 Comfy-Org/Krea-2，无需登录）──
python3 << 'EOF'
from huggingface_hub import hf_hub_download
import os, shutil
C   = '/workspace/runpod-slim/ComfyUI/models'
TMP = '/tmp/krea2_dl'
files = [
    ('diffusion_models/krea2_turbo_fp8_scaled.safetensors', f'{C}/diffusion_models'),
    ('text_encoders/qwen3vl_4b_fp8_scaled.safetensors',     f'{C}/text_encoders'),
    ('vae/qwen_image_vae.safetensors',                       f'{C}/vae'),
]
for rel, dst in files:
    os.makedirs(dst, exist_ok=True)
    hf_hub_download('Comfy-Org/Krea-2', rel, local_dir=TMP)
    shutil.move(f'{TMP}/{rel}', f'{dst}/{os.path.basename(rel)}')
    print('✅', rel)
print('🎉 Krea 2 完成')
EOF

# ── Step 5: 下载 Qwen Image 2.1 模型（九视图角色卡用，约31GB）─────────────────
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

# ── Step 5b: 下载 Wan 2.2 图生视频模型（分镜视频渲染用，约 40GB，Apache 2.0）─────
python3 << 'EOF'
from huggingface_hub import hf_hub_download
import os, shutil
C   = '/workspace/runpod-slim/ComfyUI/models'
TMP = '/tmp/wan22_dl'
R   = 'Comfy-Org/Wan_2.2_ComfyUI_Repackaged'
files = [
    ('split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors', 'diffusion_models'),
    ('split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors',  'diffusion_models'),
    ('split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors',   'loras'),
    ('split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors',    'loras'),
    ('split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors',              'text_encoders'),
    ('split_files/vae/wan_2.1_vae.safetensors',                                       'vae'),
]
for rel, sub in files:
    dst = f'{C}/{sub}'; os.makedirs(dst, exist_ok=True)
    target = f'{dst}/{os.path.basename(rel)}'
    if os.path.exists(target):
        print('✅ 已存在', os.path.basename(rel)); continue
    hf_hub_download(R, rel, local_dir=TMP)
    shutil.move(f'{TMP}/{rel}', target); print('✅', os.path.basename(rel))
print('🎉 Wan 2.2 完成')
EOF

# ── Step 6: 复制姿势参考图 ────────────────────────────────────────────────────
mkdir -p $COMFY/input/poses
cp $CN/ai_film_editor_nodes/assets/poses/*.png $COMFY/input/
cp $CN/ai_film_editor_nodes/assets/poses/*.png $COMFY/input/poses/

# ── Step 7: 启动 ComfyUI ──────────────────────────────────────────────────────
pkill -f "python main.py" || true
sleep 3
cd $COMFY
nohup python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header "*" > /tmp/comfyui.log 2>&1 &
echo "✅ 部署完成！等30秒后访问 ComfyUI"
```

## 加载 Workflow

重启后在 ComfyUI 里加载（本地文件）：
- 角色卡：`D:\下载\character_card_9views.json`
- 完整流程（含视频生产）：`D:\下载\now-03.json`（仓库里的副本：`workflow_templates/afe_full_pipeline.json`）
- 仅剧本分析：`D:\下载\afe_script_pipeline.json`

成片输出位置：`ComfyUI/output/afe_projects/<project_name>/`
（`keyframes/` 首帧，`clips/` 每个分镜的视频，`final_movie.mp4` 成片）
