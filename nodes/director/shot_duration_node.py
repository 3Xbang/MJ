class AFE_ShotDuration:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_frames": ("INT", {"default": 124, "min": 24, "step": 24}),
                "fps": ("INT", {"default": 24, "min": 8, "max": 60}),
                "add_seconds": ("FLOAT", {"default": 0.0, "min": -10.0, "max": 30.0, "step": 0.5}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "FLOAT")
    RETURN_NAMES = ("total_frames", "fps", "duration_seconds")
    FUNCTION = "calculate_duration"
    CATEGORY = "AI Film Editor/Director"

    def calculate_duration(self, base_frames, fps, add_seconds):
        total_frames = max(fps, base_frames + round(add_seconds * fps))
        duration_seconds = total_frames / fps
        return (total_frames, fps, float(duration_seconds))
