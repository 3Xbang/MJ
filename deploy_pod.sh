#!/usr/bin/env bash
# AFE 一键部署 / 更新脚本（RunPod ComfyUI Pod 用）
# 新 Pod 和已有 Pod 都能用；可以重复运行，已有的模型会自动跳过，不会重新下载。
#
# 用法（在 RunPod 终端粘贴这一行）：
#   cd /workspace/runpod-slim/ComfyUI/custom_nodes && { [ -d ai_film_editor_nodes/.git ] && git -C ai_film_editor_nodes pull origin main || git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes; } && bash ai_film_editor_nodes/deploy_pod.sh

set -euo pipefail

COMFY=/workspace/runpod-slim/ComfyUI
CN=$COMFY/custom_nodes

echo "=============================================="
echo " AFE 部署开始（新 Pod 约 30-60 分钟，主要是下载模型）"
echo "=============================================="
df -h /workspace | tail -1 | awk '{print "磁盘：已用 "$3" / 总共 "$2"，剩余 "$4" （新 Pod 全部模型约需 150GB）"}'

echo ""
echo "== 1/6 更新 ComfyUI 本体（Krea 2 / Wan 2.2 需要较新版本）"
# Pull by explicit remote/branch instead of a bare `git pull`: a Pod's ComfyUI
# checkout may have no upstream tracking configured, which makes a bare
# `git pull` fail with "There is no tracking information for the current
# branch". Each command below is its own statement (not chained with &&) so a
# real failure here is NOT swallowed by the `&&`-chain errexit quirk and
# aborts the deployment with a clear message instead of silently skipping the
# ComfyUI core pip install.
cd "$COMFY"
COMFY_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git pull origin "$COMFY_BRANCH"
pip install -r requirements.txt -q

echo ""
echo "== 2/6 安装或更新 AFE 节点和依赖"
cd "$CN"
if [ -d ai_film_editor_nodes/.git ]; then
  (cd ai_film_editor_nodes && git pull origin main)
else
  git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes
fi
pip install loguru json_repair imageio-ffmpeg accelerate -q
# CPU-only regression and graph check: run from the repository root so every
# command validates the code that was just pulled.  A failure stops deployment.
cd "$CN/ai_film_editor_nodes"
python3 -m compileall -q nodes webui tests
# Node.js is not part of the base ComfyUI Pod image, so don't hard-depend on
# it: try to install it via apt if missing, and if that isn't possible,
# degrade with a clearly visible warning instead of failing the whole
# deployment or silently skipping with no trace. Every other check below
# remains mandatory and still stops deployment on failure.
if ! command -v node >/dev/null 2>&1; then
  echo "⚠️  未检测到 Node.js，尝试通过 apt 自动安装以检查 webui/static/app.js..."
  apt-get update -y >/dev/null 2>&1 || true
  apt-get install -y nodejs >/dev/null 2>&1 || true
fi
if command -v node >/dev/null 2>&1; then
  node --check webui/static/app.js
else
  echo "⚠️  Node.js 不可用，已跳过 webui/static/app.js 语法检查（其余 CPU/图/UI 检查仍然执行，任一失败都会停止部署）。"
fi
python3 tests/test_webui_registration.py
python3 tests/test_analysis_session.py
python3 tests/test_scene_map.py
python3 tests/test_parser_merge.py
python3 tests/test_prompt_fidelity.py
python3 tests/test_reference_dependencies.py
python3 tests/test_shot_contract.py
python3 tests/test_webui_validation.py
python3 tests/test_workflow_graph.py
python3 tests/check_graphs.py
python3 tests/ui_e2e.py
cd "$CN"

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
echo "== 5/6 重启 ComfyUI =="
ACTIVE_PID="$(pgrep -f '[p]ython.*main.py' | head -n1 || true)"
if [ -z "${COMFY_PORT:-}" ] && [ -n "$ACTIVE_PID" ] && [ -r "/proc/$ACTIVE_PID/cmdline" ]; then
  mapfile -d '' ACTIVE_ARGS < "/proc/$ACTIVE_PID/cmdline"
  for ((i = 0; i < ${#ACTIVE_ARGS[@]}; i++)); do
    if [ "${ACTIVE_ARGS[$i]}" = "--port" ] && [ $((i + 1)) -lt ${#ACTIVE_ARGS[@]} ]; then
      COMFY_PORT="${ACTIVE_ARGS[$((i + 1))]}"
      break
    fi
  done
fi
if [ -z "${COMFY_PORT:-}" ]; then
  echo "❌ 未配置 ComfyUI 端口，且没有可读取 --port 的现有进程。请先设置 COMFY_PORT。"
  exit 1
fi
echo "使用 ComfyUI 端口：$COMFY_PORT"
pkill -f "python main.py" 2>/dev/null || true
sleep 3
cd "$COMFY"
nohup python main.py --listen 0.0.0.0 --port "$COMFY_PORT" --enable-cors-header "*" > /tmp/comfyui.log 2>&1 &

echo ""
echo "== 6/6 检查 AFE 注册（等待 50 秒）=="
sleep 50
if [ ! -f /tmp/comfyui.log ]; then
  echo "❌ 无法确认 AFE 注册：日志文件不存在。"
  exit 1
fi
if grep -Eq "IMPORT FAILED|web UI registration FAILED" /tmp/comfyui.log; then
  echo "❌ AFE 节点或 Web UI 注册失败："
  grep -n -i -B2 -A12 -E "ai_film_editor|web UI registration" /tmp/comfyui.log | tail -60
  exit 1
fi
if ! grep -q "\[AFE\] web UI registered at /afe/" /tmp/comfyui.log; then
  echo "❌ 未找到 AFE Web UI 注册成功日志："
  grep -n -i -B2 -A12 -E "ai_film_editor|web UI" /tmp/comfyui.log | tail -60
  exit 1
fi
if ! curl -fsS "http://127.0.0.1:${COMFY_PORT}/afe/" >/dev/null; then
  echo "❌ ComfyUI 已启动，但 /afe/ 没有返回页面。"
  tail -80 /tmp/comfyui.log
  exit 1
fi
echo "✅ 部署完成，/afe/ 可访问。"
echo "AFE customer entry: use /afe/ only; do not queue legacy now-02.json/now-03.json"
