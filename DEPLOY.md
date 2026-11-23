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

## 加载 Workflow

重启后在 ComfyUI 里加载（本地文件）：
- 角色卡：`D:\下载\character_card_9views.json`
- 完整流程（含视频生产）：`D:\下载\now-03.json`（仓库里的副本：`workflow_templates/afe_full_pipeline.json`）
- 仅剧本分析：`D:\下载\afe_script_pipeline.json`

## 网页界面（给你和客户用，不需要碰节点连线）

部署完成后，在 ComfyUI 网址后面加 `/afe/` 即可打开，例如
`https://<你的Pod编号>-8188.proxy.runpod.net/afe/`（建议加入浏览器书签）。

按页面上的五步依次点按钮：① 分析剧本 → ② 生成素材（挑场景图和角色形象）→ ③ 生成首帧 → ④ 渲染视频 → ⑤ 合成成片。
页面顶部的「试跑模式」默认开启，只处理前 2 个分镜，先看效果；满意后关闭它再生成完整影片。
每一步的结果、挑选和重做都在页面里点选，不用写任何代码。项目会自动保存，刷新页面或重启后可以继续。

每个分镜现在会保存场景 ID、场景出现次序、角色表情/微表情、视线、business 微动作、道具互动、动作起始/过程/结束和运镜计划。首帧和 Wan 使用同一份事实；静止机位只有剧本明确要求锁定/静止时才会出现。第二步生成的道具图会按道具 ID 自动进入第三步首帧，上传的同名道具图优先。没有上传参考图时继续使用文字生成。

若场景或道具生成失败，网页会显示资产 ID、失败节点和重试建议，不会用白图或其他场景顶替。更换角色、场景视角或道具只会让使用该素材的镜头失效；已完成的其他镜头、选择、过期提示和断点状态会保留。客户不需要编辑 JSON 或手工连线。

每次更新后可在 RunPod 执行 CPU 图校验：
```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes/ai_film_editor_nodes && python3 tests/test_workflow_graph.py
```

注意：这个页面没有密码，知道网址的人都能使用。不要把网址公开发布。

下面的「逐步确认与挑选」是给高级用户在 ComfyUI 画布里用的。

## 逐步确认与挑选（ComfyUI 画布版）

工作流里有一个总开关节点「🚦 全自动模式」。
- **关（默认）**：每个耗时步骤都停在「⏸ 等待确认」，你看完上一步的结果，把该节点的开关切到「▶ 已确认」，再点 Queue。已完成且输入没变的步骤会直接用缓存，不会重做。
- **开**：一路跑到底，不停顿。

确认顺序：场景图 → 道具图 → 角色参考图 → 分镜首帧 → 分镜视频 → 成片合成。

挑选与重做（都在对应节点里填，改完再点 Queue，只会重做受影响的部分）：

| 节点 | 设置 | 写法示例 | 作用 |
|---|---|---|---|
| 角色参考图 | `candidates_per_character` | `3` | 每个角色画 3 个版本 |
| | `picks` | `1:2, Ann:3` | 角色 1 用 2 号版本，Ann 用 3 号 |
| | `redo_characters` | `2` 或 `Bo:2` | 重画某角色（再重画就把数字加 1） |
| 分镜首帧 | `variants_per_shot` | `2` | 每个分镜画 2 个版本 |
| | `picks` | `shot_005:2, 7:1` | 指定使用的版本 |
| | `redo_shots` | `shot_007, 12:2` | 重画某些分镜 |
| | `scene_view_picks` | `1:2, 2:3` | 场景 1 用中景图、场景 2 用氛围图作地点参考 |
| 分镜视频 | `redo_shots` | `shot_005` | 重新渲染某个分镜 |
| | `long_take_overrides` | `shot_005:15` | 把某个分镜做成 15 秒长镜头 |
| 成片合成 | `skip_shots` | `shot_007, 12` | 成片里不要这些分镜 |

候选图在「角色候选」「首帧候选」两个预览框里，每张图左上角有编号（如 `C1 v2`、`shot_005 v1`），选用的带 `*`。
换了角色版本或场景视角，用到它的分镜首帧会自动重画，对应的视频也会自动重新渲染。

成片输出位置：`ComfyUI/output/afe_projects/<project_name>/`
（`keyframes/` 首帧，`clips/` 每个分镜的视频，`final_movie.mp4` 成片）
