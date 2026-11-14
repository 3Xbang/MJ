import torch
import numpy as np

class AFE_QualityGate:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "check_blur": ("BOOLEAN", {"default": True}),
                "check_black_frames": ("BOOLEAN", {"default": True}),
                "check_artifacts": ("BOOLEAN", {"default": True}),
                "blur_threshold": ("FLOAT", {"default": 100.0}),
            },
            "optional": {
                "fail_on_error": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "INT")
    RETURN_NAMES = ("images", "quality_report", "failed_frame_count")
    FUNCTION = "check_quality"
    CATEGORY = "AI Film Editor/Production"
    OUTPUT_NODE = True

    def _laplacian_variance(self, gray):
        """Compute Laplacian variance using numpy convolution."""
        try:
            from scipy.ndimage import convolve
            kernel = np.array([[0,1,0],[1,-4,1],[0,1,0]], dtype=np.float32)
            lap = convolve(gray, kernel)
        except ImportError:
            # Manual Laplacian via np.roll
            lap = (
                np.roll(gray, -1, axis=0) + np.roll(gray, 1, axis=0)
                + np.roll(gray, -1, axis=1) + np.roll(gray, 1, axis=1)
                - 4 * gray
            )
        return float(np.var(lap))

    def check_quality(self, images, check_blur, check_black_frames, check_artifacts,
                      blur_threshold, fail_on_error=False):
        blur_count = black_count = artifact_count = 0

        for i in range(images.shape[0]):
            frame_f = images[i].numpy()          # [H,W,3] float32 0-1
            frame_u8 = (frame_f * 255).astype(np.uint8)
            gray = (0.299 * frame_f[...,0] + 0.587 * frame_f[...,1]
                    + 0.114 * frame_f[...,2]).astype(np.float32)  # [H,W]

            if check_blur:
                var = self._laplacian_variance(gray * 255.0)
                if var < blur_threshold:
                    blur_count += 1

            if check_black_frames:
                if np.mean(frame_u8) < 5.0:
                    black_count += 1

            if check_artifacts:
                if np.var(frame_f) > 0.4:
                    artifact_count += 1

        parts = []
        if blur_count > 0:     parts.append(f"发现{blur_count}帧模糊")
        if black_count > 0:    parts.append(f"发现{black_count}帧黑帧")
        if artifact_count > 0: parts.append(f"发现{artifact_count}帧伪影")

        quality_report = "✅ 无问题" if not parts else "⚠️ " + "，".join(parts)
        failed_frame_count = blur_count + black_count + artifact_count

        if fail_on_error and failed_frame_count > 0:
            raise ValueError(quality_report)

        return (images, quality_report, failed_frame_count)
