# 🎬 AI Film Editor Nodes — ComfyUI 影视工业化编辑器
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![ComfyUI](https://img.shields.io/badge/ComfyUI-custom%20nodes-orange)
![License MIT](https://img.shields.io/badge/License-MIT-green)
AI-powered film production pipeline for ComfyUI. 49 custom nodes covering 6 production stages — from raw script to final deliverable — following a shot-by-shot workflow modelled on professional film production.
---
## 功能概览
| 阶段 | 分组 | 节点数 | 核心节点 |
|------|------|--------|----------|
| 📝 Stage 1 | 剧本解析 | 5 | ScriptParser · ShotDirectorAI · ProductionBible |
| 🎭 Stage 2 | 角色资产 (DAM) | 12 | CastManager · CharacterAsset · AutoAssetPipeline · MultiCharacterBlend |
| 🎬 Stage 3 | 分镜生产 | 10 | ShotBatchController · ShotUnit · WanPromptOptimizer · ShotChain · ShotPreview |
| 🔊 Stage 4 | 音频层 | 5 | TTSGenerator · LipSyncConfig · AudioVideoSync · ShotVideoAudioMerge |
| 🎨 Stage 5 | 精修层 | 8 | RefinementConfig · SecondPassAdapter · FaceEnhancer · VideoUpscaler |
| 📤 Stage 6 | 导出层 | 9 | FinalAssembly · ColorGrade · SubtitleOverlay · Watermark · ProjectExport |
---
## 安装说明
**Step 1 — Clone 到 ComfyUI custom_nodes 目录**
```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/your-repo/ai_film_editor_nodes.git
```
**Step 2 — 安装依赖**
```bash
pip install -r ai_film_editor_nodes/requirements.txt
```
主要依赖：`Pillow`、`imageio[ffmpeg]`、`numpy`、`torch`
**Step 3 — 重启 ComfyUI**
重启 ComfyUI 或在 ComfyUI Manager 中点击 **Restart**，节点将自动注册。
---
## 快速开始
最小化路径：从剧本到成片
```
AFE_ScriptParser
    └─→ AFE_ShotDirectorAI       # AI 导演建议
    └─→ AFE_CastManager
            └─→ AFE_AutoAssetPipeline   # 自动生成角色资产
AFE_ShotBatchController
    └─→ AFE_ShotUnit
            └─→ AFE_ShotPromptComposer
                    └─→ AFE_WanPromptOptimizer
                            └─→ WanTextEncode → WanImageToVideoLatent → KSamplerAdvanced → WanVideoVAEDecode
                                        └─→ AFE_ShotChain    # 尾帧接力，保持镜间一致性
AFE_TTSGenerator
    └─→ AFE_ShotVideoAudioMerge  # 音视频合并（需要 FFmpeg）
AFE_FinalAssembly
    └─→ AFE_ColorGrade → AFE_SubtitleOverlay → AFE_Watermark
```
每个分镜（5-10 秒）单独生成，可以单独重新生成任意一条，然后合并。
---
## 工作流模板
| 文件 | 说明 |
|------|------|
| `complete_film_pipeline.json` | 完整 71 节点六阶段流水线（本 README 对应的全量模板） |
| `script_parser_workflow.json` | 仅剧本解析 + LLM 阶段 |
| `qwen_script_parser_workflow.json` | 使用 Qwen 本地模型的剧本解析工作流 |
**最简三步模板（手动连线示例）**
```
CheckpointLoaderSimple → KSampler → VAEDecode → SaveImage
         ↑                   ↑
   CLIPTextEncode(正)   CLIPTextEncode(负)
```
---
## 节点目录
### Director（导演/剧本）
| 节点 | 功能 |
|------|------|
| AFE_ScriptParser | 解析剧本，输出 SHOT_SEQUENCE |
| AFE_ShotDirectorAI | AI 导演，给出专业分镜建议 |
| AFE_ProductionBible | 生成制作手册 |
| AFE_ShotStatusBoard | 分镜状态看板 |
| AFE_ProjectManager | 项目管理，生成 project_id |
| AFE_ShotBatchController | 分镜批量控制器 |
| AFE_ShotUnit | 单分镜控制器 |
| AFE_ShotEditor | 分镜编辑器 |
| AFE_ShotChain | 尾帧接力（镜间一致性） |
| AFE_ShotPreview | 分镜预览（加载已生成视频帧） |
| AFE_ShotPromptComposer | 提示词合成器 |
| AFE_ShotDuration | 分镜时长控制 |
| AFE_TailFrameExtractor | 尾帧提取 |
| AFE_ToneCompensation | 色调补偿 |
### DAM（数字资产管理）
| 节点 | 功能 |
|------|------|
| AFE_CharacterAsset | 角色资产 |
| AFE_OutfitAsset | 服装资产 |
| AFE_PropsAsset | 道具资产 |
| AFE_SceneAsset | 场景资产 |
| AFE_CastManager | 演员表管理 |
| AFE_ExpressionSheet | 角色表情包 |
| AFE_CharacterViewPrompt | 角色视图提示词（三视图） |
| AFE_ReferenceImageManager | 参考图管理 |
| AFE_AutoAssetPipeline | 自动资产管线 |
### Consistency（角色一致性）
| 节点 | 功能 |
|------|------|
| AFE_CharacterConsistency | 角色一致性控制 |
| AFE_MultiCharacterBlend | 多角色 IP-Adapter 混合（最多3角色） |
| AFE_IPAdapterConfig | IP-Adapter 配置 |
| AFE_ControlNetPose | ControlNet 姿势控制 |
### Refinement（精修）
| 节点 | 功能 |
|------|------|
| AFE_RefinementConfig | 精修配置 |
| AFE_SecondPassAdapter | 二次过图适配器 |
| AFE_FaceEnhancer | 人脸增强 |
| AFE_VideoUpscaler | 视频超分 |
### Audio（音频）
| 节点 | 功能 |
|------|------|
| AFE_AudioAsset | 音频资产 |
| AFE_TTSGenerator | TTS 语音合成 |
| AFE_LipSyncConfig | 口型同步配置 |
| AFE_AudioVideoSync | 音视频同步 |
| AFE_ShotVideoAudioMerge | 分镜音视频合并（FFmpeg） |
### Export（导出）
| 节点 | 功能 |
|------|------|
| AFE_FinalAssembly | 最终合成 |
| AFE_ColorGrade | 调色 |
| AFE_SubtitleOverlay | 字幕叠加 |
| AFE_Watermark | 水印 |
| AFE_ShotSequenceBuilder | 分镜序列构建 |
| AFE_ProjectExport | 项目导出 |
### Production & Utils
| 节点 | 功能 |
|------|------|
| AFE_TransitionEffect | 转场效果 |
| AFE_QualityGate | 质量门控 |
| AFE_ShotReport | 分镜报告 |
| AFE_VideoModelAdapter | 视频模型适配器 |
| AFE_WanPromptOptimizer | Wan 提示词优化器 |
| AFE_PromptPreview | 提示词预览 |
| AFE_ModelChecker | 模型检查器 |
---
## 第三方节点依赖
| 节点包 | 用途 | 链接 |
|--------|------|------|
| ComfyUI-VideoHelperSuite (VHS) | VHS_VideoCombine 视频合并 | github.com/Kosinkadink/ComfyUI-VideoHelperSuite |
| ComfyUI-WanVideoWrapper 或 WanVideoNodes | Wan2.1 视频生成节点 | 见各自 GitHub |
---
## 模型下载
| 模型 | 用途 | 建议来源 |
|--------|------|----------|
| Wan2.1-I2V-14B（或更小版本） | 图生视频核心模型 | Hugging Face / 魔搭社区 |
| IP-Adapter weights | 角色一致性 | h94/IP-Adapter on HuggingFace |
| ControlNet pose | 姿势控制 | lllyasviel/ControlNet on HuggingFace |
| TTS 模型（如 edge-tts、CosyVoice） | 语音合成 | 见 AFE_TTSGenerator 说明 |
---
## License
MIT © AI Film Editor Contributors

## `/afe/` 分批剧本解析

客户只使用 ComfyUI 的 `/afe/` 网页，不需要编辑 JSON 或手工连接节点。第 ① 步按连续小批次调用 Qwen2.5-7B-Instruct，默认每批 4 个镜头；例如 180 秒、每镜 5 秒会形成 36 个镜头和 9 个批次。每批结束后会把结果写入项目的 `analysis_session/`，然后才允许继续下一批。

页面会显示“第 X 批/共 Y 批”和“已完成镜头/总镜头”，并提供继续、重试失败批次和取消。浏览器、ComfyUI 重启后可以继续，完成批次不会重复运行，失败批次会保留具体错误。只有所有批次通过 source fragment 覆盖、顺序、重复和镜头数量校验后，才发布 `analysis.json`，不完整结果不会进入素材、首帧、Wan 或成片阶段。参考图可以上传，也可以留空。无角色或无道具的剧本会保留空数组路径。

解析阶段只占用 Qwen。全部批次完成后，网页仍按素材、首帧、Wan、成片的五步顺序运行，并保留 `show_text_party` 和模型路径约定。

CPU 回归可在仓库根目录运行：

```bash
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
python3 tests/ui_e2e.py
```

这些检查使用 CPU/mock，不代表 GPU、真实 ComfyUI、Qwen/Krea/Qwen Image/Wan 的视觉效果已经验收。
