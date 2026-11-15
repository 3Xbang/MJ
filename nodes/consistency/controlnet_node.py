import torch
import numpy as np
from ai_film_editor_nodes.lib.utils.model_checker import get_model_list

class AFE_ControlNetPose:
    DESCRIPTION = "需要安装 comfyui_controlnet_aux + ComfyUI-Advanced-ControlNet。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pose_image": ("IMAGE",),
                "controlnet_model": (get_model_list("controlnet", "(未安装，ComfyUI Manager 搜索 controlnet openpose)"),),
                "control_strength": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0}),
                "start_percent": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0}),
                "end_percent": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0}),
            },
            "optional": {
                "pose_preset": (["standing", "walking", "sitting", "running", "talking", "custom"],),
                "flip_pose": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("AFE_POSE_CONFIG",)
    RETURN_NAMES = ("pose_config",)
    FUNCTION = "build_pose_config"
    CATEGORY = "AI Film Editor/Consistency"

    # 18 keypoints (x,y) normalized 0-1 for each preset
    PRESETS = {
        "standing": [
            (0.50,0.08),(0.50,0.20),(0.40,0.25),(0.35,0.40),(0.30,0.55),
            (0.60,0.25),(0.65,0.40),(0.70,0.55),(0.42,0.55),(0.40,0.72),
            (0.40,0.90),(0.58,0.55),(0.60,0.72),(0.60,0.90),(0.47,0.07),
            (0.53,0.07),(0.44,0.10),(0.56,0.10),
        ],
        "walking": [
            (0.50,0.08),(0.50,0.20),(0.40,0.25),(0.33,0.38),(0.28,0.52),
            (0.60,0.25),(0.67,0.38),(0.72,0.52),(0.44,0.55),(0.38,0.70),
            (0.33,0.88),(0.56,0.55),(0.64,0.70),(0.68,0.88),(0.47,0.07),
            (0.53,0.07),(0.44,0.10),(0.56,0.10),
        ],
        "sitting": [
            (0.50,0.08),(0.50,0.20),(0.40,0.25),(0.35,0.40),(0.30,0.55),
            (0.60,0.25),(0.65,0.40),(0.70,0.55),(0.42,0.55),(0.35,0.65),
            (0.30,0.60),(0.58,0.55),(0.65,0.65),(0.70,0.60),(0.47,0.07),
            (0.53,0.07),(0.44,0.10),(0.56,0.10),
        ],
        "running": [
            (0.52,0.08),(0.50,0.20),(0.38,0.24),(0.28,0.35),(0.22,0.48),
            (0.62,0.24),(0.72,0.33),(0.78,0.46),(0.44,0.52),(0.36,0.68),
            (0.30,0.86),(0.56,0.52),(0.68,0.66),(0.74,0.84),(0.49,0.07),
            (0.55,0.07),(0.46,0.10),(0.58,0.10),
        ],
        "talking": [
            (0.50,0.08),(0.50,0.20),(0.40,0.25),(0.30,0.38),(0.25,0.30),
            (0.60,0.25),(0.70,0.36),(0.76,0.28),(0.42,0.55),(0.40,0.72),
            (0.40,0.90),(0.58,0.55),(0.60,0.72),(0.60,0.90),(0.47,0.07),
            (0.53,0.07),(0.44,0.10),(0.56,0.10),
        ],
    }

    # Skeleton connections (index pairs)
    SKELETON = [
        (0,1),(1,2),(2,3),(3,4),(1,5),(5,6),(6,7),
        (1,8),(8,9),(9,10),(1,11),(11,12),(12,13),
        (0,14),(0,15),(14,16),(15,17),
    ]

    def _make_skeleton_image(self, preset_name):
        kps = self.PRESETS[preset_name]
        size = 512
        img = np.zeros((size, size, 3), dtype=np.uint8)
        pts = [(int(x*size), int(y*size)) for x,y in kps]
        colors_line = (100,100,255)
        colors_joint = (255,255,0)
        for a, b in self.SKELETON:
            if a < len(pts) and b < len(pts):
                x1,y1 = pts[a]; x2,y2 = pts[b]
                # draw line using numpy
                steps = max(abs(x2-x1), abs(y2-y1), 1)
                for s in range(steps+1):
                    xi = int(x1 + (x2-x1)*s/steps)
                    yi = int(y1 + (y2-y1)*s/steps)
                    if 0<=xi<size and 0<=yi<size:
                        img[max(0,yi-1):min(size,yi+2), max(0,xi-1):min(size,xi+2)] = colors_line
        for px,py in pts:
            if 0<=px<size and 0<=py<size:
                img[max(0,py-3):min(size,py+4), max(0,px-3):min(size,px+4)] = colors_joint
        return torch.from_numpy(img.astype(np.float32)/255.0).unsqueeze(0)  # [1,H,W,3]

    def build_pose_config(self, pose_image, controlnet_model, control_strength, start_percent, end_percent, pose_preset="custom", flip_pose=False):
        if pose_preset != "custom":
            tensor = self._make_skeleton_image(pose_preset)
        else:
            tensor = pose_image
        if flip_pose:
            tensor = torch.flip(tensor, dims=[2])  # flip width dim
        config = {
            "pose_image_tensor": tensor,
            "control_strength": control_strength,
            "start_percent": start_percent,
            "end_percent": end_percent,
            "controlnet_model": controlnet_model,
        }
        return (config,)
