"""Model availability utilities for AFE nodes."""
from __future__ import annotations

try:
    import folder_paths as _fp
except ImportError:
    _fp = None

from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("model_checker")

MODEL_REQUIREMENTS: dict[str, dict] = {
    "wan_i2v_model": {
        "folder": "diffusion_models",
        "patterns": ["Wan2.1-I2V", "wan2.1-i2v", "wan_i2v"],
        "manager_search": "Wan2.1 I2V",
        "description": "Wan 2.1 图生视频主模型",
        "required_by": ["AFE_VideoModelAdapter (wan_i2v 模式)"],
    },
    "wan_t5_encoder": {
        "folder": "text_encoders",
        "patterns": ["umt5-xxl", "umt5_xxl"],
        "manager_search": "umt5-xxl",
        "description": "Wan T5 文本编码器",
        "required_by": ["WanTextEncode 节点"],
    },
    "wan_vae": {
        "folder": "vae",
        "patterns": ["wan_2.1_vae", "wan2.1_vae"],
        "manager_search": "wan vae",
        "description": "Wan 2.1 VAE",
        "required_by": ["WanImageToVideoLatent 节点"],
    },
    "wan_clip_vision": {
        "folder": "clip_vision",
        "patterns": ["clip_vision_h"],
        "manager_search": "clip vision h",
        "description": "CLIP Vision（Wan I2V 图像编码）",
        "required_by": ["WanImageToVideoLatent 节点"],
    },
    "flux_checkpoint": {
        "folder": "checkpoints",
        "patterns": ["flux1-dev", "flux1_dev", "flux-dev"],
        "manager_search": "flux1-dev fp8",
        "description": "Flux.1-dev 图片生成模型",
        "required_by": ["AFE_CharacterAsset 图片生成"],
    },
    "flux_t5": {
        "folder": "clip",
        "patterns": ["t5xxl", "t5-xxl"],
        "manager_search": "t5xxl_fp8_e4m3fn",
        "description": "T5-XXL 文本编码器（Flux 用）",
        "required_by": ["DualCLIPLoader 节点"],
    },
    "codeformer": {
        "folder": "facerestore_models",
        "patterns": ["codeformer"],
        "manager_search": "codeformer",
        "description": "CodeFormer 人脸修复模型",
        "required_by": ["AFE_FaceEnhancer"],
    },
    "ipadapter_plus": {
        "folder": "ipadapter",
        "patterns": ["ip-adapter-plus", "ip_adapter_plus"],
        "manager_search": "ip-adapter-plus",
        "description": "IP-Adapter Plus 角色一致性模型",
        "required_by": ["AFE_IPAdapterConfig"],
    },
    "controlnet_openpose": {
        "folder": "controlnet",
        "patterns": ["openpose", "control_v11p_sd15_openpose"],
        "manager_search": "controlnet openpose",
        "description": "ControlNet OpenPose 姿态控制模型",
        "required_by": ["AFE_ControlNetPose"],
    },
}


def find_model(folder: str, patterns: list[str]) -> str | None:
    """Return the first filename in *folder* where any pattern is a case-insensitive substring."""
    if _fp is None:
        return None
    try:
        files = _fp.get_filename_list(folder)
    except Exception:
        return None
    for filename in files:
        name_lower = filename.lower()
        for pattern in patterns:
            if pattern.lower() in name_lower:
                return filename
    return None


def get_model_list(folder: str, empty_msg: str | None = None) -> list[str]:
    """Return sorted filenames from *folder*, or a single-item placeholder list."""
    if _fp is None:
        return [empty_msg or "(未找到模型，请用 ComfyUI Manager 安装)"]
    try:
        files = sorted(_fp.get_filename_list(folder))
    except Exception:
        files = []
    if not files:
        return [empty_msg or "(未找到模型，请用 ComfyUI Manager 安装)"]
    return files


def check_requirement(key: str) -> tuple[bool, str]:
    """Return (True, filename) if the model is installed, else (False, install tip)."""
    if key not in MODEL_REQUIREMENTS:
        return (False, f"未知的模型需求键: {key}")
    req = MODEL_REQUIREMENTS[key]
    filename = find_model(req["folder"], req["patterns"])
    if filename:
        return (True, filename)
    tip = (
        f"❌ {req['description']} 未安装。"
        f"请在 ComfyUI Manager 中搜索 \"{req['manager_search']}\" 下载。"
        f"（需要此模型的节点: {', '.join(req['required_by'])}）"
    )
    return (False, tip)


def require_model(key: str) -> str:
    """Return the filename if installed, otherwise raise ValueError with an install tip."""
    installed, msg = check_requirement(key)
    if not installed:
        raise ValueError(msg)
    return msg


def check_all_requirements() -> dict[str, tuple[bool, str]]:
    """Check all model requirements and return a mapping of key → (installed, message)."""
    return {key: check_requirement(key) for key in MODEL_REQUIREMENTS}
