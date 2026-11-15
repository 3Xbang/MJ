# Review — AI Film Editor ComfyUI Node Package

## Evidence Checked

### 1. `__init__.py` — 8-node registration
All eight classes (`AFE_CharacterAsset`, `AFE_OutfitAsset`, `AFE_SceneAsset`, `AFE_ScriptParser`, `AFE_ShotDuration`, `AFE_TailFrameExtractor`, `AFE_ToneCompensation`, `AFE_VideoModelAdapter`) are present as keys in both `NODE_CLASS_MAPPINGS` and `NODE_DISPLAY_NAME_MAPPINGS`. ✓

### 2. Node files and ComfyUI attributes

| File | Class | INPUT_TYPES | RETURN_TYPES | RETURN_NAMES | FUNCTION | CATEGORY |
|------|-------|-------------|--------------|--------------|----------|----------|
| `nodes/dam/character_node.py` | `AFE_CharacterAsset` | ✓ | `("CHARACTER_ASSET","STRING")` | ✓ | `create_or_load_character` | `AI Film Editor/Assets` |
| `nodes/dam/outfit_node.py` | `AFE_OutfitAsset` | ✓ | `("OUTFIT_ASSET","STRING")` | ✓ | `create_or_load_outfit` | `AI Film Editor/Assets` |
| `nodes/dam/scene_node.py` | `AFE_SceneAsset` | ✓ | `("SCENE_ASSET","STRING")` | ✓ | `create_or_load_scene` | `AI Film Editor/Assets` |
| `nodes/director/shot_duration_node.py` | `AFE_ShotDuration` | ✓ | `("INT","INT","FLOAT")` | ✓ | `calculate_duration` | `AI Film Editor/Director` |
| `nodes/director/script_parser_node.py` | `AFE_ScriptParser` | ✓ | `("SHOT_SEQUENCE","INT","STRING")` | ✓ | `parse_script` | `AI Film Editor/Director` |
| `nodes/director/tail_frame_node.py` | `AFE_TailFrameExtractor` | ✓ | `("IMAGE",)` | ✓ | `extract_frame` | `AI Film Editor/Director` |
| `nodes/director/tone_comp_node.py` | `AFE_ToneCompensation` | ✓ | `("IMAGE",)` | ✓ | `apply_tone_compensation` | `AI Film Editor/Director` |
| `nodes/adapters/video_adapter_node.py` | `AFE_VideoModelAdapter` | ✓ | `("STRING","STRING","INT","INT","INT")` | ✓ | `adapt_for_model` | `AI Film Editor/Adapters` |

Custom type strings `CHARACTER_ASSET`, `OUTFIT_ASSET`, `SCENE_ASSET`, `SHOT_SEQUENCE` are used consistently between producer RETURN_TYPES and consumer INPUT_TYPES. ✓

### 3. `lib/persistence/database.py` — sync SQLAlchemy only
- `create_engine` used; `create_async_engine` absent ✓
- `Session` and `sessionmaker` used; `AsyncSession` absent ✓
- No `async def`, no `await`, no `aiosqlite` ✓
- `expire_on_commit=False` on session factory ensures ORM row attributes remain accessible after session close ✓
- `init_db()` and `get_session()` (context manager) both present ✓

### 4. `lib/models/` — common.py, assets.py, shot.py
All three files exist. Imports reference `ai_film_editor_nodes.lib.models.*`. No `comfy_contracts.py` found. ✓

### 5. Workflow templates
`01_character_generation.json`, `02_outfit_generation.json`, `03_first_pass_video.json` all exist and parse as valid JSON. ✓

### 6. Documentation
`README.md` contains installation steps (clone + pip / install.py + restart) and a full node table. `REQUIRED_NODES.md` lists built-in ComfyUI nodes, recommends ComfyUI-VideoHelperSuite with download link, and lists Wan 2.1 / Kling video model nodes with HuggingFace download links. ✓

### 7. Supporting files
`requirements.txt` and `install.py` present at package root. ✓

### 8. Verification commit evidence
Full commit body (`git log -1 --format="%B"`):
```
feat: initial ComfyUI node package
Verification outputs:
1. NODE_CLASS_MAPPINGS: ['AFE_CharacterAsset', 'AFE_OutfitAsset', 'AFE_SceneAsset',
   'AFE_ScriptParser', 'AFE_ShotDuration', 'AFE_TailFrameExtractor',
   'AFE_ToneCompensation', 'AFE_VideoModelAdapter']
2. Models OK
3. DB OK
```
All three verifications recorded. ✓

### Additional correctness checks
- All subdirectory `__init__.py` files present (lib, lib/models, lib/persistence, lib/utils, nodes, nodes/dam, nodes/director, nodes/adapters). ✓
- `torch` imported in `tail_frame_node.py` and `tone_comp_node.py`; correctly omitted from `requirements.txt` as a ComfyUI-provided dependency. ✓
- `AFE_ScriptParser.parse_script` calls `asyncio.run()` from a sync method. ComfyUI executes node functions on worker threads, not inside a running event loop, so this is safe in the standard ComfyUI execution model. ✓

## Verdict
No blockers found. All eight requirements satisfied.
