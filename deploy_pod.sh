#!/usr/bin/env bash
# AFE 一键部署 / 更新（RunPod ComfyUI Pod）
# 每次开机都可重复执行；已有模型自动跳过。
#
# 每次开机在 RunPod 终端粘贴：
#   cd /workspace/runpod-slim/ComfyUI/custom_nodes && { [ -d ai_film_editor_nodes/.git ] && git -C ai_film_editor_nodes pull --ff-only origin main || git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes; } && bash ai_film_editor_nodes/deploy_pod.sh
#
# 可选环境变量：
#   COMFY_PORT=8188     未检测到运行中的 ComfyUI 时使用
#   AFE_RUN_E2E=1       强制跑浏览器 E2E（默认能装就跑，失败不阻断部署）

set -euo pipefail

COMFY=/workspace/runpod-slim/ComfyUI
CN=$COMFY/custom_nodes
# RunPod 模板把对外 8188 留给 comfy-auth-proxy，真正的 ComfyUI 在 COMFYUI_UPSTREAM（常见 18188）。
# 直接占用 8188 会报 “Port 8188 is already in use”，页面也进不去。
if [ -z "${COMFY_PORT:-}" ] && [ -n "${COMFYUI_UPSTREAM:-}" ]; then
  COMFY_PORT="${COMFYUI_UPSTREAM##*:}"
fi
DEFAULT_PORT="${COMFY_PORT:-18188}"

echo "=============================================="
echo " AFE 部署开始"
echo " 新 Pod / 空磁盘：约 30-60 分钟（主要下模型）"
echo " 模型已在 /workspace：约几分钟（跳过下载）"
echo "=============================================="
df -h /workspace | tail -1 | awk '{print "磁盘：已用 "$3" / 总共 "$2"，剩余 "$4" （全部模型约需 100-150GB）"}'

echo ""
echo "== 1/6 更新 ComfyUI 本体（Krea 2 / Wan 2.2 需要较新版本）"
# 不用 git pull：Pod 上 ComfyUI 常与远程分叉，会触发
# "Need to specify how to reconcile divergent branches" 并中断部署。
# 这里只要求核心跟上远程，本地改动直接丢弃。
cd "$COMFY"
COMFY_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$COMFY_BRANCH" = "HEAD" ]; then
  COMFY_BRANCH=master
  echo "当前处于 detached HEAD，改用 origin/master"
fi
git fetch origin "$COMFY_BRANCH"
git reset --hard "origin/$COMFY_BRANCH"
pip install -r requirements.txt -q

echo ""
echo "== 2/6 安装或更新 AFE 节点和依赖"
cd "$CN"
if [ -d ai_film_editor_nodes/.git ]; then
  # AFE 用 --ff-only：不改 git config，分叉时明确失败而不是交互合并。
  (cd ai_film_editor_nodes && git pull --ff-only origin main)
else
  git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes
fi

# 剧本解析 Qwen 需要 accelerate；TTS/成片等见 requirements.txt
pip install -r ai_film_editor_nodes/requirements.txt -q
pip install loguru json_repair imageio-ffmpeg accelerate -q

cd "$CN/ai_film_editor_nodes"
python3 -m compileall -q nodes webui tests

if ! command -v node >/dev/null 2>&1; then
  echo "⚠️  未检测到 Node.js，尝试 apt 安装以便检查 app.js..."
  apt-get update -y >/dev/null 2>&1 || true
  apt-get install -y nodejs >/dev/null 2>&1 || true
fi
if command -v node >/dev/null 2>&1; then
  node --check webui/static/app.js
else
  echo "⚠️  Node.js 不可用，已跳过 app.js 语法检查。"
fi

# 必过的 CPU / 图检查：失败则停止部署
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

# 浏览器 E2E：尽力跑，失败不阻断部署（租用 Pod 常无 Chromium）
run_e2e=0
if python3 -c "from playwright.sync_api import sync_playwright" >/dev/null 2>&1; then
  run_e2e=1
else
  echo "⚠️  未检测到 playwright，尝试安装..."
  pip install playwright -q >/dev/null 2>&1 || true
  python3 -m playwright install --with-deps chromium >/dev/null 2>&1 || true
  if python3 -c "from playwright.sync_api import sync_playwright" >/dev/null 2>&1; then
    run_e2e=1
  fi
fi
if [ "$run_e2e" = "1" ] || [ "${AFE_RUN_E2E:-0}" = "1" ]; then
  if ! python3 tests/ui_e2e.py; then
    echo "⚠️  ui_e2e 未通过，继续部署（不影响 /afe/ 出片主路径）。"
  fi
else
  echo "⚠️  playwright 不可用，已跳过 ui_e2e。"
fi

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

# ① 剧本解析
llm = f'{M}/LLM/Qwen2.5-7B-Instruct'
if os.path.exists(f'{llm}/model.safetensors.index.json'):
    print('  已有   Qwen2.5-7B-Instruct', flush=True)
else:
    print('  下载中 Qwen2.5-7B-Instruct（约 15GB）', flush=True)
    os.makedirs(llm, exist_ok=True)
    snapshot_download('Qwen/Qwen2.5-7B-Instruct', local_dir=llm, ignore_patterns=['*.bin'])
    print('  完成   Qwen2.5-7B-Instruct', flush=True)

# ② 场景 / 道具 / 角色参考：Krea 2
K = 'Comfy-Org/Krea-2'
get(K, 'diffusion_models/krea2_turbo_fp8_scaled.safetensors', 'diffusion_models')
get(K, 'text_encoders/qwen3vl_4b_fp8_scaled.safetensors', 'text_encoders')
get(K, 'vae/qwen_image_vae.safetensors', 'vae')

# ③ 首帧 / 九视图：Qwen Image 2.1
Q = 'toxicdog/Qwen-Image-2.1-INT4ConvRot-ComfyUI'
get(Q, 'diffusion_models/qwen_image_2.1_int8_convrot.safetensors', 'unet',
    'qwen_image_2.1_turbo_int8_convrot.safetensors')
get(Q, 'vae/qwen_image_2.1_vae_bf16.safetensors', 'vae')
get(Q, 'text_encoders/qwen3vl_8b_int8_convrot.safetensors', 'text_encoders')
get('HarleyWang/Qwen-Image-2.1-PE-ComfyUI', 'qwen_image_2.1_pe_i2i_int8_convrot.safetensors',
    'text_encoders', 'qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors')

# ④ 分镜视频：Wan 2.2
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
cp "$CN"/ai_film_editor_nodes/assets/poses/*.png "$COMFY/input/" 2>/dev/null || true
cp "$CN"/ai_film_editor_nodes/assets/poses/*.png "$COMFY/input/poses/" 2>/dev/null || true

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
COMFY_PORT="${COMFY_PORT:-$DEFAULT_PORT}"
echo "使用 ComfyUI 端口：$COMFY_PORT"
pkill -f "python.*main.py" 2>/dev/null || true
sleep 3
# 必须用绝对路径启动：部署脚本末尾 cwd 常在 custom_nodes，相对 main.py 会点到不存在的
# /workspace/.../custom_nodes/main.py，导致进程秒退、/afe/ 永远起不来。
cd "$COMFY"
# 只监听本机：对外入口是 8188 上的 auth proxy，它再转到这个端口。
nohup python "$COMFY/main.py" --listen 127.0.0.1 --port "$COMFY_PORT" --enable-cors-header "*" > /tmp/comfyui.log 2>&1 &
echo "ComfyUI 已在后台启动（127.0.0.1:$COMFY_PORT, pid=$!）"

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

echo ""
echo "✅ 部署完成，/afe/ 可访问。"
echo "   打开：http://<Pod公网或代理>:${COMFY_PORT}/afe/"
echo "   客户入口只用 /afe/；不要手工排队旧 JSON 工作流。"
echo "   出片前若曾开「试跑模式」，关了再跑 ③④⑤。"
