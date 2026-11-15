# Review — AI Film Editor: Complete ComfyUI Workflow Implementation

## Evidence Summary

### 1. `nodes/director/tone_comp_node.py`
- `reference_frame` is in the `optional` INPUT_TYPES section. ✅
- `enable` is also in `optional`. ✅
- Signature: `apply_tone_compensation(self, current_image, strength, enable=True, reference_frame=None)` ✅
- Early return `(current_image,)` when `reference_frame is None or not enable`. ✅
- Mean-shift compensation via numpy applied otherwise; result clamped to [0,1] and cast back to original dtype. ✅

### 2. `nodes/adapters/video_adapter_node.py`
- `seed` is in `required`. ✅
- `scene` is in `optional`. ✅
- `target_model` list is exactly `["wan_i2v", "wan_t2v", "generic"]`. ✅
- `adapt_for_model` signature: `scene=None` default, `scene.get(...) if scene else ""` guard handles None correctly. ✅

### 3. `nodes/utils/prompt_preview_node.py`
- File exists. ✅
- `OUTPUT_NODE = True`. ✅
- `RETURN_TYPES = ("STRING", "STRING", "INT", "INT", "INT")`. ✅
- `RETURN_NAMES = ("positive", "negative", "seed", "width", "height")`. ✅
- `preview_and_passthrough` returns `{"ui": ..., "result": ...}`. ✅

### 4. `__init__.py`
- Imports `AFE_PromptPreview` from `ai_film_editor_nodes.nodes.utils.prompt_preview_node`. ✅
- `NODE_CLASS_MAPPINGS` has exactly 9 entries: AFE_CharacterAsset, AFE_OutfitAsset, AFE_SceneAsset, AFE_ScriptParser, AFE_ShotDuration, AFE_TailFrameExtractor, AFE_ToneCompensation, AFE_VideoModelAdapter, AFE_PromptPreview. ✅

### 5. `workflow_templates/01_asset_character_generation.json`
- File exists and is valid JSON. ✅
- Nodes "1"–"10" present with correct class_type values. ✅
- Node "3" is `AFE_PromptPreview`; inputs linked from node "2": `["2",0]`..`["2",4]`. ✅
- Node "8" is `KSampler` with `"seed": ["3", 2]`. ✅

### 6. `workflow_templates/02_first_pass_i2v_wan.json`
- File exists and is valid JSON. ✅
- Nodes "1"–"18" present. ✅
- Node "14" is `KSamplerAdvanced` with `noise_seed=["6",2]`, `add_noise="enable"`, `return_with_leftover_noise="disable"`. ✅
- Node "13" is `WanImageToVideoLatent` with `length=["4",0]`; node "4" is `AFE_ShotDuration` whose index-0 output is `total_frames` (confirmed from shot_duration_node.py RETURN_NAMES). ✅
- Node "8" is `AFE_ToneCompensation` with key `reference_frame` (not `reference_image`). ✅

### 7. `workflow_templates/03_script_to_shots.json`
- File exists, valid JSON, node "1" is `AFE_ScriptParser`. ✅

### 8. `REQUIRED_NODES.md`
- Section 1: built-in ComfyUI nodes list. ✅
- Section 2: VideoHelperSuite + WanVideoWrapper with Manager install instructions. ✅
- Section 3: model download paths table (3 model files, target directories, download URL). ✅

### 9. Commit verification evidence
- Commit message records: "NODE_CLASS_MAPPINGS -> 9 nodes incl. AFE_PromptPreview [PASS]". ✅
- Commit message records: "json.load 02_first_pass_i2v_wan.json -> JSON OK [PASS]" and "json.load 01_asset_character_generation.json -> JSON OK [PASS]". ✅

## Blockers

None.
