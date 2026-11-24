#!/usr/bin/env bash
# AFE 一键部署 / 更新脚本（RunPod ComfyUI Pod 用）
# 新 Pod 和已有 Pod 都能用；可以重复运行，已有的模型会自动跳过，不会重新下载。
#
# 用法（在 RunPod 终端粘贴这一行）：
#   cd /workspace/runpod-slim/ComfyUI/custom_nodes && { [ -d ai_film_editor_nodes/.git ] && git -C ai_film_editor_nodes pull origin main || git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes; } && bash ai_film_editor_nodes/deploy_pod.sh

COMFY=/workspace/runpod-slim/ComfyUI
CN=$COMFY/custom_nodes

echo "=============================================="
echo " AFE 部署开始（新 Pod 约 30-60 分钟，主要是下载模型）"
echo "=============================================="
df -h /workspace | tail -1 | awk '{print "磁盘：已用 "$3" / 总共 "$2"，剩余 "$4" （新 Pod 全部模型约需 150GB）"}'

echo ""
echo "== 1/6 更新 ComfyUI 本体（Krea 2 / Wan 2.2 需要较新版本）"
cd "$COMFY" && git pull && pip install -r requirements.txt -q

echo ""
echo "== 2/6 安装或更新 AFE 节点和依赖"
cd "$CN"
if [ -d ai_film_editor_nodes/.git ]; then
  (cd ai_film_editor_nodes && git pull origin main)
else
  git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes
fi
pip install loguru json_repair imageio-ffmpeg -q
# CPU-only regression and graph check: confirms structured prompts and generated props are connected.
python3 -m compileall -q nodes webui tests
python3 tests/test_analysis_session.py
python3 tests/test_scene_map.py
python3 tests/test_prompt_fidelity.py
python3 tests/test_reference_dependencies.py
python3 tests/test_workflow_graph.py

[ -d comfyui_LLM_party ] || git clone https://github.com/heshengtao/comfyui_LLM_party.git
(cd comfyui_LLM_party && pip install -r requirements.txt -q)

[ -d ComfyUI-KJNodes ] || git clone https://github.com/kijai/ComfyUI-KJNodes.git
(cd ComfyUI-KJNodes && pip install -r requirements.txt -q)

echo ""
echo "== 3/6 下载模型（已有的自动跳过）"
python3 - << 'EOF'
import os, shutil
from huggingface_hub import hf_hub_download, snapshot_download

M = '/workspace/runpod-slim/ComfyUI/models'
TMP = '/tmp/afe_dl'

def get(repo, rel, sub, name=None):
    name = name or os.path.basename(rel)
    dst_dir = f'{M}/{sub}'
    os.makedirs(dst_dir, exist_ok=True)
    dst = f'{dst_dir}/{name}'
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        print('  已有  ', name, flush=True)
        return
    print('  下载中', name, flush=True)
    path = hf_hub_download(repo, rel, local_dir=TMP)
    shutil.move(path, dst)
    print('  完成  ', name, flush=True)

# 剧本解析用的语言模型
llm = f'{M}/LLM/Qwen2.5-7B-Instruct'
if os.path.exists(f'{llm}/model.safetensors.index.json'):
    print('  已有   Qwen2.5-7B-Instruct', flush=True)
else:
    print('  下载中 Qwen2.5-7B-Instruct（约 15GB）', flush=True)
    os.makedirs(llm, exist_ok=True)
    snapshot_download('Qwen/Qwen2.5-7B-Instruct', local_dir=llm, ignore_patterns=['*.bin'])
    print('  完成   Qwen2.5-7B-Instruct', flush=True)

# 场景图、道具图、角色参考图用：Krea 2 Turbo
K = 'Comfy-Org/Krea-2'
get(K, 'diffusion_models/krea2_turbo_fp8_scaled.safetensors', 'diffusion_models')
get(K, 'text_encoders/qwen3vl_4b_fp8_scaled.safetensors', 'text_encoders')
get(K, 'vae/qwen_image_vae.safetensors', 'vae')

# 分镜首帧、九视图角色卡用：Qwen Image 2.1
Q = 'toxicdog/Qwen-Image-2.1-INT4ConvRot-ComfyUI'
get(Q, 'diffusion_models/qwen_image_2.1_int8_convrot.safetensors', 'unet',
    'qwen_image_2.1_turbo_int8_convrot.safetensors')
get(Q, 'vae/qwen_image_2.1_vae_bf16.safetensors', 'vae')
get(Q, 'text_encoders/qwen3vl_8b_int8_convrot.safetensors', 'text_encoders')
get('HarleyWang/Qwen-Image-2.1-PE-ComfyUI', 'qwen_image_2.1_pe_i2i_int8_convrot.safetensors',
    'text_encoders', 'qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors')

# 分镜视频用：Wan 2.2 图生视频 + 4 步加速
W = 'Comfy-Org/Wan_2.2_ComfyUI_Repackaged'
get(W, 'split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors', 'diffusion_models')
get(W, 'split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors', 'diffusion_models')
get(W, 'split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors', 'loras')
get(W, 'split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors', 'loras')
get(W, 'split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'text_encoders')
get(W, 'split_files/vae/wan_2.1_vae.safetensors', 'vae')

print('模型全部就绪', flush=True)
EOF

echo ""
echo "== 4/6 复制姿势参考图"
mkdir -p "$COMFY/input/poses"
cp "$CN"/ai_film_editor_nodes/assets/poses/*.png "$COMFY/input/" 2>/dev/null
cp "$CN"/ai_film_editor_nodes/assets/poses/*.png "$COMFY/input/poses/" 2>/dev/null

echo ""
echo "== 5/6 重启 ComfyUI"
pkill -f "python main.py" 2>/dev/null
sleep 3
cd "$COMFY"
nohup python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header "*" > /tmp/comfyui.log 2>&1 &

echo ""
echo "== 6/6 检查 AFE 节点是否加载成功（等待 50 秒）"
sleep 50
grep -E "ai_film_editor_nodes" /tmp/comfyui.log | tail -3
if grep -E "ai_film_editor_nodes" /tmp/comfyui.log | grep -q "IMPORT FAILED"; then
  echo "❌ AFE 节点加载失败。请把下面这段发给我："
  grep -n -i -B2 -A12 "ai_film_editor" /tmp/comfyui.log | tail -40
else
  echo "✅ 部署完成。"
  echo "   给客户用的网页界面：在 ComfyUI 网址后面加 /afe/ （例如 https://xxxx-8188.proxy.runpod.net/afe/ ）"
  echo "   专业画布：在浏览器按 F5 刷新 ComfyUI，再加载工作流 now-03.json"
fi
