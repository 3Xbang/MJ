import torch

class AFE_TransitionEffect:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images_a": ("IMAGE",),
                "images_b": ("IMAGE",),
                "transition_type": (["cut", "fade", "dissolve", "fade_to_black", "fade_from_black"],),
                "transition_frames": ("INT", {"default": 12, "min": 1, "max": 48}),
            },
            "optional": {
                "easing": (["linear", "ease_in", "ease_out", "ease_in_out"],),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("transition_frames",)
    FUNCTION = "create_transition"
    CATEGORY = "AI Film Editor/Production"

    def _get_alpha(self, t, easing):
        if easing == "ease_in":
            return t * t
        elif easing == "ease_out":
            return 1.0 - (1.0 - t) ** 2
        elif easing == "ease_in_out":
            return 3 * t * t - 2 * t * t * t
        return t  # linear

    def create_transition(self, images_a, images_b, transition_type, transition_frames, easing="linear"):
        n = transition_frames

        if transition_type == "cut":
            return (images_b[0:1],)

        elif transition_type == "fade_to_black":
            last = images_a[-1:]
            if n == 1:
                return (torch.zeros_like(last),)
            frames = [last * (1.0 - self._get_alpha(i / (n - 1), easing)) for i in range(n)]
            return (torch.cat(frames, dim=0),)

        elif transition_type == "fade_from_black":
            first = images_b[0:1]
            if n == 1:
                return (first,)
            frames = [first * self._get_alpha(i / (n - 1), easing) for i in range(n)]
            return (torch.cat(frames, dim=0),)

        elif transition_type == "dissolve":
            na = images_a.shape[0]
            nb = images_b.shape[0]
            if na >= n:
                a_slice = images_a[-n:]
            else:
                pad = images_a[0:1].expand(n - na, -1, -1, -1)
                a_slice = torch.cat([pad, images_a], dim=0)
            if nb >= n:
                b_slice = images_b[:n]
            else:
                pad = images_b[-1:].expand(n - nb, -1, -1, -1)
                b_slice = torch.cat([images_b, pad], dim=0)
            frames = []
            for i in range(n):
                t = i / (n - 1) if n > 1 else 1.0
                alpha = self._get_alpha(t, easing)
                frames.append(a_slice[i:i+1] * (1.0 - alpha) + b_slice[i:i+1] * alpha)
            return (torch.cat(frames, dim=0),)

        elif transition_type == "fade":
            to_black, = self.create_transition(images_a, images_b, "fade_to_black", n, easing)
            from_black, = self.create_transition(images_a, images_b, "fade_from_black", n, easing)
            return (torch.cat([to_black, from_black], dim=0),)

        return (images_b[0:1],)
