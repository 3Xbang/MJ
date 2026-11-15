#!/bin/bash
# AI Film Editor - 一键安装脚本
# 在 RunPod ComfyUI Pod 的 JupyterLab Terminal 里运行
# 用法: bash install.sh

set -e

COMFYUI_DIR="/workspace/runpod-slim/ComfyUI"
CUSTOM_NODES_DIR="$COMFYUI_DIR/custom_nodes"
REPO_URL="https://github.com/3Xbang/MJ.git"
NODE_DIR="$CUSTOM_NODES_DIR/ai_film_editor_nodes"

echo "====================================="
echo " AI Film Editor 安装脚本"
echo "====================================="

# 1. 克隆/更新我们的节点包
echo ""
echo "[1/5] 安装 AI Film Editor 节点..."
if [ -d "$NODE_DIR" ]; then
    echo "  已存在，更新中..."
    cd "$NODE_DIR" && git pull
else
    echo "  克隆仓库..."
    git clone "$REPO_URL" "$NODE_DIR"
fi

# 2. 安装 Python 依赖
echo ""
echo "[2/5] 安装 Python 依赖..."
pip install -r "$NODE_DIR/requirements.txt" -q

# 3. 安装 LLM Party（本地 Qwen）
echo ""
echo "[3/5] 安装 ComfyUI-LLM-Party..."
LLM_PARTY_DIR="$CUSTOM_NODES_DIR/comfyui_llm_party"
if [ -d "$LLM_PARTY_DIR" ]; then
    echo "  已存在，跳过"
else
    git clone https://github.com/heshengtao/comfyui_LLM_party.git "$LLM_PARTY_DIR"
    pip install -r "$LLM_PARTY_DIR/requirements.txt" -q
fi

# 4. 安装 VideoHelperSuite（视频处理）
echo ""
echo "[4/5] 安装 ComfyUI-VideoHelperSuite..."
VHS_DIR="$CUSTOM_NODES_DIR/ComfyUI-VideoHelperSuite"
if [ -d "$VHS_DIR" ]; then
    echo "  已存在，跳过"
else
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git "$VHS_DIR"
    pip install -r "$VHS_DIR/requirements.txt" -q 2>/dev/null || true
fi

# 5. 验证安装
echo ""
echo "[5/5] 验证安装..."
python -c "
import sys
sys.path.insert(0, '$CUSTOM_NODES_DIR')
from ai_film_editor_nodes import NODE_CLASS_MAPPINGS
print(f'  ✅ AI Film Editor: {len(NODE_CLASS_MAPPINGS)} 个节点')
"

echo ""
echo "====================================="
echo " 安装完成！"
echo "====================================="
echo ""
echo "启动 ComfyUI："
echo "  cd $COMFYUI_DIR"
echo "  nohup python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header \"*\" > /tmp/comfyui.log 2>&1 &"
echo ""
echo "然后从 RunPod 面板 → Connect → ComfyUI 进入"
echo ""
echo "工作流模板位置："
echo "  $NODE_DIR/workflow_templates/"
echo ""
echo "⚠️  还需要手动在 ComfyUI Manager 安装："
echo "  - ComfyUI-WanVideoWrapper (Wan 2.1 视频生成)"
echo "  - ComfyUI-Custom-Scripts  (ShowText 节点)"
