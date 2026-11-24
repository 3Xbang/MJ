# AFE 部署与更新

## 一键（推荐）

在 RunPod 终端粘贴这一行。新 Pod 和已有 Pod 都能用，可以重复运行，已有模型自动跳过：

```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes && { [ -d ai_film_editor_nodes/.git ] && git -C ai_film_editor_nodes pull origin main || git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes; } && bash ai_film_editor_nodes/deploy_pod.sh
```

脚本内容在仓库根目录 `deploy_pod.sh`。下面是它的分步版本，仅供参考。

---

# AFE 新 Pod 完整部署命令（分步版）

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

## Workflow loading

Customers use `/afe/` only. Do not edit JSON or connect ComfyUI nodes by hand.
`workflow_templates/afe_script_pipeline.json` is the safe single-batch parser graph. `workflow_templates/afe_full_pipeline.json` retains the original material, first-frame, Wan, movie, props, and `show_text_party` nodes, but all downstream analysis inputs come from `AFE_AnalysisLoader`, never from the partial parser node. The loader accepts only a complete, session-signed `analysis.json`, so the full artifact cannot start generation from an unfinished batch. Do not queue legacy `D:\download\now-02.json` or `D:\download\now-03.json`, because those graphs lack the persisted batch-session gate. The web UI creates stages 2-5 only after all batches validate and publishes `analysis.json`.

The web UI keeps the five-step order: 1 script, 2 assets, 3 keyframes, 4 video, 5 movie.

每个分镜现在会保存场景 ID、场景出现次序、角色表情/微表情、视线、business 微动作、道具互动、动作起始/过程/结束和运镜计划。首帧和 Wan 使用同一份事实；静止机位只有剧本明确要求锁定/静止时才会出现。第二步生成的道具图会按道具 ID 自动进入第三步首帧，上传的同名道具图优先。没有上传参考图时继续使用文字生成。

若场景或道具生成失败，网页会显示资产 ID、失败节点和重试建议，不会用白图或其他场景顶替。更换角色、场景视角或道具只会让使用该素材的镜头失效；已完成的其他镜头、选择、过期提示和断点状态会保留。客户不需要编辑 JSON 或手工连线。

每次更新后可在 RunPod 执行 CPU 图和批次校验：
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes/ai_film_editor_nodes && python3 -m compileall -q nodes webui tests && python3 tests/test_analysis_session.py && python3 tests/test_scene_map.py && python3 tests/test_parser_merge.py && python3 tests/test_prompt_fidelity.py && python3 tests/test_reference_dependencies.py && python3 tests/test_shot_contract.py && python3 tests/test_webui_validation.py && python3 tests/test_workflow_graph.py && python3 tests/check_graphs.py && python3 tests/ui_e2e.py
```

这些 CPU 检查不能证明真实模型的视觉效果。部署后必须确认 ComfyUI 日志没有 `IMPORT FAILED`，在 `/afe/` 先用试跑模式生成两个镜头，再检查实际首帧和 Wan 片段是否保留表情、微表情、动作三阶段、场景切换和非静止运镜。确认无误后再关闭试跑模式生成完整影片。取消、重启后重新排队和素材重做也应检查已完成文件被复用、失败镜头被明确阻止，而不是生成白图或拼接缺片。

注意：这个页面没有密码，知道网址的人都能使用。不要把网址公开发布。

下面的「逐步确认与挑选」是给高级用户在 ComfyUI 画布里用的。

## 分批解析与 RunPod 验收

客户只使用 `/afe/`，不要编辑 JSON 或手工连线。第 ① 步默认每批 4 个镜头，36 镜头会依次执行 9 批。页面显示当前批次、已完成镜头、失败原因，并提供继续、只重试失败批次和取消。每批结果保存在项目的 `analysis_session/`，重启后继续；未完成全部批次前不会发布 `analysis.json`，也不会进入 Krea、Qwen Image、Wan 或成片阶段。参考图可上传也可不上传，空角色/空道具会走空数组路径。

部署后验收：打开 `/afe/`，粘贴 180 秒/36 镜头剧本，先完成第 1 批，刷新页面确认进度，再取消并继续；让一批失败，确认只重试该批且已完成批次不重复；重启 ComfyUI 后确认 running 批次变为可重试状态。全部批次完成后确认第 ② 至第 ⑤ 步按素材、首帧、Wan、成片顺序执行，并检查有/无参考图和试跑模式。查看 `/tmp/comfyui.log`，确认没有 `IMPORT FAILED`。CPU/mock 测试不能替代 GPU、真实 ComfyUI 或视觉质量验收。

本地 CPU 检查：

```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes/ai_film_editor_nodes
python3 -m compileall -q nodes webui tests
python3 tests/test_analysis_session.py && python3 tests/test_scene_map.py && python3 tests/test_parser_merge.py && python3 tests/test_prompt_fidelity.py && python3 tests/test_reference_dependencies.py && python3 tests/test_shot_contract.py && python3 tests/test_webui_validation.py && python3 tests/test_workflow_graph.py && python3 tests/check_graphs.py && python3 tests/ui_e2e.py
```

成片输出位置：`ComfyUI/output/afe_projects/<project_name>/`
（`keyframes/` 首帧，`clips/` 每个分镜的视频，`final_movie.mp4` 成片）
