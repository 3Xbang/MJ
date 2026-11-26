# AFE 部署与更新（RunPod）

## 每次开机必跑（唯一推荐命令）

租用 Pod **每次启动**后，在终端粘贴这一行：

```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes && { [ -d ai_film_editor_nodes/.git ] && git -C ai_film_editor_nodes pull --ff-only origin main || git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes; } && bash ai_film_editor_nodes/deploy_pod.sh
```

| 情况 | 大约耗时 |
|------|----------|
| 新 Pod / `/workspace` 被清空 | 30–60 分钟（下模型） |
| 模型还在 `/workspace` | 几分钟（跳过已有文件） |

**成功标志（必须看到）：**

```text
✅ 部署完成，/afe/ 可访问。
```

然后浏览器打开 `/afe/`，继续出片。  
没有这句 = 部署未完成，不要开始分析剧本。

可选：端口不是默认时先导出再跑：

```bash
export COMFY_PORT=8188
```

---

## 这一条命令会做什么

1. 更新 ComfyUI 本体（`fetch` + `reset --hard`，避免分支分叉卡死）
2. 拉取 / 克隆 AFE，安装依赖（含 **`accelerate`**，剧本解析必需）
3. 跑 CPU / 工作流回归；浏览器 E2E 尽力跑，**失败不阻断部署**
4. 安装 `comfyui_LLM_party`、`ComfyUI-KJNodes`
5. 下载出片主路径模型（已有则跳过）
6. 重启 ComfyUI，检查 `/afe/` 可访问

### 会安装的依赖（摘要）

- AFE：`requirements.txt` + `accelerate` / `json_repair` / `imageio-ffmpeg` / `loguru`
- 节点：`comfyui_LLM_party`、`ComfyUI-KJNodes`

### 会下载的模型（出片主路径）

| 步骤 | 模型 |
|------|------|
| ① 剧本解析 | Qwen2.5-7B-Instruct |
| ② 素材 | Krea 2 Turbo |
| ③ 首帧 | Qwen Image 2.1 |
| ④ 视频 | Wan 2.2 I2V 14B + 4 步 LoRA + umT5 + VAE |

**不在默认部署内（后期再加）：** 口型、超分、人脸修复、配音专用模型。

---

## 开机后出片检查清单

1. 看到 `✅ 部署完成，/afe/ 可访问。`
2. 打开 `/afe/`，强制刷新
3. 若只要完整成片：关闭顶部「试跑模式」
4. ① 分析剧本 → 全部批次完成 → ②③④⑤
5. 当前先无声成片即可；配音后期再加

若第 ① 批报 `requires 'accelerate'`：说明旧环境未装上，重新跑上面一键命令（脚本会装），再点「重试此批」。

---

## 常见中断与续跑

### 1）ComfyUI `divergent branches` / `Need to specify how to reconcile`

旧脚本用 `git pull` 会中断。当前 `deploy_pod.sh` 已改为 `fetch` + `reset --hard`。  
若仍停在旧脚本，先执行：

```bash
cd /workspace/runpod-slim/ComfyUI
BR="$(git rev-parse --abbrev-ref HEAD)"; [ "$BR" = "HEAD" ] && BR=master
git fetch origin "$BR" && git reset --hard "origin/$BR"
```

再重新跑「每次开机必跑」那一行。

### 2）`No module named 'playwright'` / ui_e2e 失败

**不会再阻断部署**（新脚本会跳过或警告后继续）。若你还在跑旧脚本被打断，直接再跑一键命令即可。

### 3）只想装依赖、确认 accelerate（应急）

```bash
pip install accelerate -q && python -c "import accelerate; print('accelerate OK')"
```

然后回 `/afe/` 点「重试此批」。完整环境仍建议跑完整一键部署。

---

## 仅更新 AFE 代码并重启（模型已在、ComfyUI 正运行）

```bash
COMFY=/workspace/runpod-slim/ComfyUI
CN="$COMFY/custom_nodes"
PID="$(pgrep -f '[p]ython.*main.py' | head -n1)"
[ -n "$PID" ] || { echo "找不到正在运行的 ComfyUI"; exit 1; }
mapfile -d '' ARGV < "/proc/$PID/cmdline"
PYTHON_BIN="${ARGV[0]}"
ARGS=("${ARGV[@]:1}")
for ((i=0; i<${#ARGS[@]}; i++)); do
  if [ "${ARGS[$i]}" = "--port" ] && [ $((i + 1)) -lt ${#ARGS[@]} ]; then PORT="${ARGS[$((i + 1))]}"; fi
done
[ -n "${PORT:-}" ] || { echo "当前 ComfyUI 参数没有 --port"; exit 1; }
git -C "$CN/ai_film_editor_nodes" pull --ff-only origin main
pip install -r "$CN/ai_film_editor_nodes/requirements.txt" -q
kill "$PID"
for _ in {1..30}; do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
cd "$COMFY"
nohup "$PYTHON_BIN" "${ARGS[@]}" > /tmp/comfyui.log 2>&1 &
sleep 5
curl -fsS "http://127.0.0.1:${PORT}/afe/" >/dev/null && echo "AFE /afe/ 已更新并可访问"
```

---

## 建议：持久盘

租用 Pod 尽量挂 **Network Volume**，把 `/workspace` 留下。  
这样每次停机再开，一键部署会跳过模型下载，几分钟就能用。

---

## 工作流说明

客户只用 `/afe/`，不要编辑 JSON 或手工连节点。  
五步顺序：① 剧本 → ② 素材 → ③ 首帧 → ④ Wan → ⑤ 成片。  
第 ① 步默认每批 4 镜；180 秒 / 5 秒镜 = 36 镜 = 9 批。全部批次校验通过后才发布 `analysis.json`。

成片目录：`ComfyUI/output/afe_projects/<project_name>/`

本地 / Pod 上可单独跑 CPU 检查（不能替代 GPU 真片验收）：

```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes/ai_film_editor_nodes
python3 -m compileall -q nodes webui tests
python3 tests/test_analysis_session.py
python3 tests/test_scene_map.py
python3 tests/test_parser_merge.py
python3 tests/test_prompt_fidelity.py
python3 tests/test_reference_dependencies.py
python3 tests/test_shot_contract.py
python3 tests/test_webui_validation.py
python3 tests/test_workflow_graph.py
python3 tests/check_graphs.py
```

注意：`/afe/` 无密码，不要公开分享地址。
