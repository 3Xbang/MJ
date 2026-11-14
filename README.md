# AI Film Editor Nodes for ComfyUI

A ComfyUI custom node package for AI-assisted film production. Provides digital asset management (DAM), shot director controls, and video model adaptation — all as composable ComfyUI nodes.

## Installation

1. Clone into your ComfyUI custom_nodes directory:
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/YOUR_USERNAME/ai_film_editor_nodes
   ```

2. Install Python dependencies:
   ```bash
   cd ai_film_editor_nodes
   python install.py
   ```
   Or manually: `pip install -r requirements.txt`

3. Restart ComfyUI. The nodes appear under the **AI Film Editor** category.

## Nodes

### Assets (AI Film Editor/Assets)
| Node | Function |
|------|----------|
| **AFE_CharacterAsset** | Create or load a character with positive/negative prompts, model config, and SQLite persistence |
| **AFE_OutfitAsset** | Create or load an outfit linked to a character |
| **AFE_SceneAsset** | Create or load a scene/background asset |

### Director (AI Film Editor/Director)
| Node | Function |
|------|----------|
| **AFE_ShotDuration** | Calculate total_frames and duration_seconds for a video shot |
| **AFE_ScriptParser** | Parse a film script into a structured shot sequence using an LLM API |
| **AFE_TailFrameExtractor** | Extract the first or last frame from a video IMAGE batch (tail-frame relay) |
| **AFE_ToneCompensation** | Match colour tone between consecutive video segments using numpy |

### Adapters (AI Film Editor/Adapters)
| Node | Function |
|------|----------|
| **AFE_VideoModelAdapter** | Merge character/scene/outfit assets into model-optimised prompts for Wan, Kling, or generic models |

## Custom Data Types
Nodes pass structured data between themselves using these custom ComfyUI types:
- `CHARACTER_ASSET` — character asset dict
- `OUTFIT_ASSET` — outfit asset dict
- `SCENE_ASSET` — scene asset dict
- `SHOT_SEQUENCE` — list of parsed shot dicts

## Database
Assets are stored in `ai_film_editor_nodes/assets.db` (SQLite, local). Set `AFE_DB_PATH` environment variable to override.

## Workflow Templates
See `workflow_templates/`:
- `01_character_generation.json` — Generate a character image
- `02_outfit_generation.json` — Generate outfit variations
- `03_first_pass_video.json` — First-pass video generation with tail-frame relay

Load these in ComfyUI via **Load** → select the JSON file.

## Required Third-Party Nodes
See [REQUIRED_NODES.md](REQUIRED_NODES.md).

## Minimum Requirements
- Python 3.10+
- ComfyUI latest stable
- 16 GB RAM (32 GB for 14B video models)
- GPU 8 GB+ VRAM

## Verification
```python
import sys
sys.path.insert(0, "/path/to/ComfyUI/custom_nodes")
from ai_film_editor_nodes import NODE_CLASS_MAPPINGS
print(list(NODE_CLASS_MAPPINGS.keys()))
# ['AFE_CharacterAsset', 'AFE_OutfitAsset', 'AFE_SceneAsset', 'AFE_ScriptParser',
#  'AFE_ShotDuration', 'AFE_TailFrameExtractor', 'AFE_ToneCompensation', 'AFE_VideoModelAdapter']
```
