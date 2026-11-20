#!/usr/bin/env python3
"""
Generate 8 pose reference images for Qwen Image 2.1 character card workflow.
These plug into image_2~9 slots to guide multi-angle character generation.

Output: E:/MJ/assets/poses/pose_01_front_full.png  ... pose_08_sit_cross.png
Then copy these to RunPod: /workspace/runpod-slim/ComfyUI/input/poses/
"""

from PIL import Image, ImageDraw
import os, math

W, H = 1024, 1024

# Color palette
WHITE    = (255, 255, 255)
BG       = (248, 248, 248)
SKIN     = (200, 185, 170)
BODY     = (160, 160, 165)
BODY_DK  = ( 90,  90,  95)
SHADOW   = (220, 215, 210)
LABEL_BG = ( 30,  30,  30)
LABEL_FG = (255, 255, 255)
EYE      = ( 50,  50,  50)
SMILE    = ( 70,  50,  50)
FROWN    = ( 50,  50,  70)
CHAIR    = (140, 110,  80)
CHAIR_DK = ( 90,  65,  40)

OUT = 5  # outline width

# ─────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────

def new_canvas(label_text, border_color=(40, 100, 180)):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    # subtle gradient-like bg
    for y in range(H):
        t = y / H
        c = int(248 - t * 8)
        draw.line([(0, y), (W, y)], fill=(c, c, c))
    # border strip
    draw.rectangle([0, 0, W-1, H-1], outline=border_color, width=12)
    # label badge
    draw.rectangle([0, H-90, W, H], fill=LABEL_BG)
    draw.rectangle([0, H-90, W, H-88], fill=border_color)
    # text using default font – large
    try:
        from PIL import ImageFont
        fnt = ImageFont.truetype("arial.ttf", 52)
    except Exception:
        fnt = None
    draw.text((W//2, H-44), label_text, fill=LABEL_FG, anchor="mm", font=fnt)
    return img, draw

def rr(draw, x0, y0, x1, y1, r=18, fill=BODY, outline=BODY_DK, width=OUT):
    """Rounded rect helper."""
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)

def ell(draw, cx, cy, rx, ry, fill=BODY, outline=BODY_DK, width=OUT):
    draw.ellipse([cx-rx, cy-ry, cx+rx, cy+ry], fill=fill, outline=outline, width=width)

def ground_shadow(draw, cx, bot, w=180):
    """Elliptical shadow on the ground."""
    draw.ellipse([cx-w//2, bot-20, cx+w//2, bot+20], fill=SHADOW)

# ─────────────────────────────────────────────
# figure drawing functions
# ─────────────────────────────────────────────

def draw_full_front(draw, cx, cy):
    """Full body front view – symmetrical, face visible."""
    ground_shadow(draw, cx, cy + 320)
    # legs
    rr(draw, cx-72, cy+50, cx-14, cy+320, r=18, fill=BODY)
    rr(draw, cx+14, cy+50, cx+72, cy+320, r=18, fill=BODY)
    # feet
    ell(draw, cx-44, cy+328, 36, 16, fill=BODY_DK, outline=BODY_DK)
    ell(draw, cx+44, cy+328, 36, 16, fill=BODY_DK, outline=BODY_DK)
    # torso
    rr(draw, cx-85, cy-150, cx+85, cy+60, r=28, fill=BODY)
    # arms
    rr(draw, cx-135, cy-140, cx-83, cy+40, r=20, fill=BODY)
    rr(draw, cx+83, cy-140, cx+135, cy+40, r=20, fill=BODY)
    # neck
    rr(draw, cx-22, cy-168, cx+22, cy-148, r=8, fill=SKIN, outline=SKIN, width=1)
    # head
    ell(draw, cx, cy-240, 70, 90, fill=SKIN)
    # eyes
    ell(draw, cx-22, cy-262, 10, 9, fill=EYE, outline=EYE, width=1)
    ell(draw, cx+22, cy-262, 10, 9, fill=EYE, outline=EYE, width=1)
    # neutral mouth
    draw.arc([cx-18, cy-230, cx+18, cy-215], 15, 165, fill=SMILE, width=4)

def draw_full_back(draw, cx, cy):
    """Full body back view – symmetrical, no face."""
    ground_shadow(draw, cx, cy + 320)
    # legs
    rr(draw, cx-72, cy+50, cx-14, cy+320, r=18, fill=BODY)
    rr(draw, cx+14, cy+50, cx+72, cy+320, r=18, fill=BODY)
    # feet (reversed shoes)
    ell(draw, cx-44, cy+328, 36, 16, fill=BODY_DK, outline=BODY_DK)
    ell(draw, cx+44, cy+328, 36, 16, fill=BODY_DK, outline=BODY_DK)
    # torso (back – slightly darker shade)
    rr(draw, cx-85, cy-150, cx+85, cy+60, r=28, fill=(145,145,150))
    # arms
    rr(draw, cx-135, cy-140, cx-83, cy+40, r=20, fill=BODY)
    rr(draw, cx+83, cy-140, cx+135, cy+40, r=20, fill=BODY)
    # neck
    rr(draw, cx-22, cy-168, cx+22, cy-148, r=8, fill=SKIN, outline=SKIN, width=1)
    # head (back – hair-colored, no face features)
    ell(draw, cx, cy-240, 70, 90, fill=(110, 95, 80))
    # "back of head" mark
    draw.arc([cx-30, cy-280, cx+30, cy-180], 200, 340, fill=(80,70,60), width=5)

def draw_full_side(draw, cx, cy):
    """Full body side view – facing right, narrow profile."""
    ground_shadow(draw, cx, cy + 320, w=100)
    # torso (side = narrow depth)
    rr(draw, cx-28, cy-150, cx+28, cy+60, r=14, fill=BODY)
    # one leg front
    rr(draw, cx-20, cy+50, cx+15, cy+320, r=14, fill=BODY)
    # one leg back (slightly behind / lighter)
    rr(draw, cx-10, cy+55, cx+5, cy+310, r=10, fill=(175,175,180))
    # foot front
    rr(draw, cx-5, cy+312, cx+50, cy+338, r=10, fill=BODY_DK, outline=BODY_DK)
    # one arm (front side, slightly bent forward)
    rr(draw, cx-50, cy-130, cx-24, cy+40, r=14, fill=BODY)
    # one arm behind torso edge
    rr(draw, cx+22, cy-120, cx+40, cy+30, r=10, fill=(155,155,160))
    # neck
    rr(draw, cx-12, cy-168, cx+12, cy-148, r=6, fill=SKIN, outline=SKIN, width=1)
    # head (profile)
    ell(draw, cx-5, cy-240, 55, 88, fill=SKIN)
    # nose bump
    draw.arc([cx+40, cy-258, cx+78, cy-220], 300, 60, fill=SKIN, width=18)
    # eye
    ell(draw, cx+15, cy-262, 9, 8, fill=EYE, outline=EYE, width=1)
    # ear
    ell(draw, cx-50, cy-242, 10, 14, fill=(185,165,145), outline=BODY_DK, width=2)
    # Arrow showing camera is on the LEFT
    ax, ay = cx - 180, cy - 240
    draw.polygon([(ax, ay), (ax-50, ay-20), (ax-50, ay+20)],
                 fill=(220, 60, 60), outline=(160, 30, 30))
    draw.rectangle([ax-130, ay-10, ax-50, ay+10], fill=(220, 60, 60))

def draw_face_neutral(draw, cx, cy):
    """Large head portrait – neutral expression."""
    # Neck & shoulders (barely visible)
    rr(draw, cx-200, cy+120, cx+200, cy+280, r=40, fill=BODY)
    rr(draw, cx-50, cy+70, cx+50, cy+140, r=14, fill=SKIN, outline=SKIN, width=1)
    # Big head – fills frame
    ell(draw, cx, cy-20, 220, 280, fill=SKIN)
    # ears
    ell(draw, cx-215, cy-20, 24, 32, fill=(185,165,145), outline=BODY_DK, width=3)
    ell(draw, cx+215, cy-20, 24, 32, fill=(185,165,145), outline=BODY_DK, width=3)
    # eyes
    ell(draw, cx-65, cy-80, 28, 22, fill=WHITE, outline=BODY_DK, width=3)
    ell(draw, cx+65, cy-80, 28, 22, fill=WHITE, outline=BODY_DK, width=3)
    ell(draw, cx-65, cy-80, 14, 14, fill=EYE, outline=EYE, width=1)
    ell(draw, cx+65, cy-80, 14, 14, fill=EYE, outline=EYE, width=1)
    # eyebrows – flat / neutral
    draw.arc([cx-90, cy-128, cx-38, cy-100], 200, 340, fill=BODY_DK, width=5)
    draw.arc([cx+38, cy-128, cx+90, cy-100], 200, 340, fill=BODY_DK, width=5)
    # nose
    draw.arc([cx-20, cy-20, cx+20, cy+20], 200, 340, fill=(160,120,100), width=5)
    # mouth – straight / neutral
    draw.line([cx-40, cy+60, cx+40, cy+60], fill=SMILE, width=5)

def draw_face_smile(draw, cx, cy):
    """Large head portrait – big warm smile."""
    # Neck & shoulders
    rr(draw, cx-200, cy+120, cx+200, cy+280, r=40, fill=BODY)
    rr(draw, cx-50, cy+70, cx+50, cy+140, r=14, fill=SKIN, outline=SKIN, width=1)
    # Head
    ell(draw, cx, cy-20, 220, 280, fill=SKIN)
    ell(draw, cx-215, cy-20, 24, 32, fill=(185,165,145), outline=BODY_DK, width=3)
    ell(draw, cx+215, cy-20, 24, 32, fill=(185,165,145), outline=BODY_DK, width=3)
    # Squinting happy eyes
    ell(draw, cx-65, cy-80, 30, 18, fill=WHITE, outline=BODY_DK, width=3)
    ell(draw, cx+65, cy-80, 30, 18, fill=WHITE, outline=BODY_DK, width=3)
    ell(draw, cx-65, cy-80, 14, 11, fill=EYE, outline=EYE, width=1)
    ell(draw, cx+65, cy-80, 14, 11, fill=EYE, outline=EYE, width=1)
    # Crow's feet / squint lines
    draw.line([cx-96, cy-90, cx-110, cy-100], fill=BODY_DK, width=3)
    draw.line([cx+96, cy-90, cx+110, cy-100], fill=BODY_DK, width=3)
    # Raised cheeks (smile circles)
    ell(draw, cx-85, cy+10, 30, 22, fill=(220,170,140), outline=None, width=0)
    ell(draw, cx+85, cy+10, 30, 22, fill=(220,170,140), outline=None, width=0)
    # Eyebrows – raised happy
    draw.arc([cx-95, cy-145, cx-30, cy-105], 215, 325, fill=BODY_DK, width=5)
    draw.arc([cx+30, cy-145, cx+95, cy-105], 215, 325, fill=BODY_DK, width=5)
    # Nose
    draw.arc([cx-20, cy-20, cx+20, cy+20], 200, 340, fill=(160,120,100), width=5)
    # Big open smile
    draw.arc([cx-60, cy+30, cx+60, cy+90], 10, 170, fill=SMILE, width=6)
    # Teeth hint
    draw.arc([cx-55, cy+32, cx+55, cy+85], 10, 170, fill=WHITE, width=14)

def draw_face_serious(draw, cx, cy):
    """Large head portrait – stern authoritative look."""
    # Neck & shoulders
    rr(draw, cx-200, cy+120, cx+200, cy+280, r=40, fill=BODY)
    rr(draw, cx-50, cy+70, cx+50, cy+140, r=14, fill=SKIN, outline=SKIN, width=1)
    # Head
    ell(draw, cx, cy-20, 220, 280, fill=SKIN)
    ell(draw, cx-215, cy-20, 24, 32, fill=(185,165,145), outline=BODY_DK, width=3)
    ell(draw, cx+215, cy-20, 24, 32, fill=(185,165,145), outline=BODY_DK, width=3)
    # Sharp eyes – wide open
    ell(draw, cx-65, cy-80, 30, 24, fill=WHITE, outline=BODY_DK, width=4)
    ell(draw, cx+65, cy-80, 30, 24, fill=WHITE, outline=BODY_DK, width=4)
    ell(draw, cx-65, cy-80, 15, 15, fill=EYE, outline=EYE, width=1)
    ell(draw, cx+65, cy-80, 15, 15, fill=EYE, outline=EYE, width=1)
    # Furrowed eyebrows – angled inward
    draw.line([cx-95, cy-120, cx-35, cy-108], fill=BODY_DK, width=8)
    draw.line([cx+35, cy-108, cx+95, cy-120], fill=BODY_DK, width=8)
    # Inner brow crease
    draw.line([cx-38, cy-110, cx-10, cy-100], fill=BODY_DK, width=4)
    draw.line([cx+10, cy-100, cx+38, cy-110], fill=BODY_DK, width=4)
    # Nose
    draw.arc([cx-20, cy-20, cx+20, cy+20], 200, 340, fill=(160,120,100), width=5)
    # Tight straight mouth
    draw.line([cx-45, cy+60, cx+45, cy+60], fill=FROWN, width=7)
    # slight frown corners
    draw.line([cx-45, cy+60, cx-55, cy+70], fill=FROWN, width=5)
    draw.line([cx+45, cy+60, cx+55, cy+70], fill=FROWN, width=5)

def draw_chair(draw, cx, cy):
    """Draw a simple wooden chair."""
    # Legs
    rr(draw, cx-90, cy-20, cx-70, cy+120, r=4, fill=CHAIR, outline=CHAIR_DK, width=3)
    rr(draw, cx+70, cy-20, cx+90, cy+120, r=4, fill=CHAIR, outline=CHAIR_DK, width=3)
    rr(draw, cx-90, cy+40, cx-70, cy+140, r=4, fill=CHAIR, outline=CHAIR_DK, width=3)
    rr(draw, cx+70, cy+40, cx+90, cy+140, r=4, fill=CHAIR, outline=CHAIR_DK, width=3)
    # Seat
    rr(draw, cx-100, cy-30, cx+100, cy+10, r=10, fill=CHAIR, outline=CHAIR_DK, width=3)
    # Back rest
    rr(draw, cx-95, cy-200, cx-70, cy-20, r=8, fill=CHAIR, outline=CHAIR_DK, width=3)
    rr(draw, cx+70, cy-200, cx+95, cy-20, r=8, fill=CHAIR, outline=CHAIR_DK, width=3)
    rr(draw, cx-95, cy-210, cx+95, cy-180, r=10, fill=CHAIR, outline=CHAIR_DK, width=3)

def draw_sitting_tea(draw, cx, cy):
    """Medium shot – sitting, leaning forward, holding tea cup."""
    draw_chair(draw, cx, cy + 60)
    # Lower body / lap
    rr(draw, cx-90, cy+30, cx+90, cy+70, r=20, fill=BODY)
    # Torso – leaning forward
    rr(draw, cx-80, cy-180, cx+80, cy+40, r=25, fill=BODY)
    # Left arm – bent, holding cup
    rr(draw, cx-130, cy-160, cx-78, cy+30, r=18, fill=BODY)
    # Right arm – raised toward mouth
    # upper arm
    rr(draw, cx+78, cy-160, cx+120, cy-60, r=18, fill=BODY)
    # forearm bent at elbow
    rr(draw, cx+80, cy-80, cx+140, cy-20, r=14, fill=BODY)
    # cup
    rr(draw, cx+130, cy-55, cx+170, cy-15, r=8, fill=(200,210,230), outline=(100,120,160), width=3)
    rr(draw, cx+120, cy-70, cx+180, cy-55, r=4, fill=(200,210,230), outline=(100,120,160), width=2)
    # Steam wisps
    for i, ox in enumerate([-5, 0, 5]):
        y0 = cy - 80 - i * 8
        draw.arc([cx+140+ox, y0-20, cx+160+ox, y0], 0, 180, fill=(200,200,200), width=3)
    # Neck
    rr(draw, cx-22, cy-195, cx+22, cy-175, r=8, fill=SKIN, outline=SKIN, width=1)
    # Head – slightly forward tilt
    ell(draw, cx-10, cy-280, 68, 88, fill=SKIN)
    ell(draw, cx-65, cy-280, 10, 14, fill=(185,165,145), outline=BODY_DK, width=2)
    # Simple face – focused
    ell(draw, cx-25, cy-305, 11, 10, fill=EYE, outline=EYE, width=1)
    ell(draw, cx+15, cy-300, 11, 10, fill=EYE, outline=EYE, width=1)
    draw.arc([cx-18, cy-268, cx+18, cy-255], 15, 165, fill=SMILE, width=4)

def draw_sitting_cross(draw, cx, cy):
    """Medium shot – sitting, leaning back, arms crossed."""
    draw_chair(draw, cx, cy + 60)
    # Lower body / lap
    rr(draw, cx-90, cy+30, cx+90, cy+70, r=20, fill=BODY)
    # Torso – upright / slightly back
    rr(draw, cx-80, cy-180, cx+80, cy+40, r=25, fill=BODY)
    # Crossed arms – left arm over right
    # right forearm (under): goes from right side across body
    rr(draw, cx+78, cy-120, cx+135, cy-80, r=16, fill=BODY)
    rr(draw, cx-20, cy-120, cx+90, cy-78, r=16, fill=(148,148,153))
    # left forearm (over): goes from left side across body
    rr(draw, cx-135, cy-130, cx-78, cy-88, r=16, fill=BODY)
    rr(draw, cx-90, cy-130, cx+30, cy-88, r=16, fill=BODY)
    # small cross marker
    draw.line([cx-30, cy-110, cx+30, cy-110], fill=BODY_DK, width=5)
    # Neck
    rr(draw, cx-22, cy-195, cx+22, cy-175, r=8, fill=SKIN, outline=SKIN, width=1)
    # Head – slight tilt back / confident
    ell(draw, cx+5, cy-280, 68, 88, fill=SKIN)
    ell(draw, cx+70, cy-280, 10, 14, fill=(185,165,145), outline=BODY_DK, width=2)
    # Wise, confident face
    ell(draw, cx-25, cy-305, 11, 10, fill=EYE, outline=EYE, width=1)
    ell(draw, cx+15, cy-300, 11, 10, fill=EYE, outline=EYE, width=1)
    # Slight confident smile
    draw.arc([cx-20, cy-265, cx+28, cy-250], 10, 170, fill=SMILE, width=5)
    # Eyebrows – relaxed / confident
    draw.arc([cx-45, cy-328, cx-5, cy-308], 215, 325, fill=BODY_DK, width=4)
    draw.arc([cx+8, cy-328, cx+48, cy-308], 215, 325, fill=BODY_DK, width=4)

# ─────────────────────────────────────────────
# view annotation helpers
# ─────────────────────────────────────────────

def add_view_badge(draw, text, color=(40, 100, 180)):
    """Small badge at top-left showing view type."""
    bx, by = 20, 20
    bw = max(len(text) * 22 + 20, 180)
    draw.rounded_rectangle([bx, by, bx+bw, by+52], radius=12, fill=color, outline=WHITE, width=2)
    try:
        from PIL import ImageFont
        fnt = ImageFont.truetype("arial.ttf", 30)
    except Exception:
        fnt = None
    draw.text((bx + bw//2, by + 26), text, fill=WHITE, anchor="mm", font=fnt)

def add_camera_icon(draw, x, y):
    """Simple camera symbol to show viewpoint direction."""
    rr(draw, x-32, y-20, x+32, y+20, r=6, fill=(220,60,60), outline=(160,30,30), width=3)
    ell(draw, x, y, 10, 10, fill=WHITE, outline=(160,30,30), width=2)
    rr(draw, x-10, y-28, x+10, y-20, r=4, fill=(220,60,60), outline=(160,30,30), width=2)

# ─────────────────────────────────────────────
# build the 8 images
# ─────────────────────────────────────────────

POSES = [
    # (filename_suffix, label_text, draw_fn, border_color, badge_text, badge_color)
    ("01_front_full",   "FULL BODY — FRONT VIEW",        "front_full",  (40,100,180),  "FRONT",   (40,100,180)),
    ("02_back_full",    "FULL BODY — BACK VIEW",          "back_full",   (40,100,180),  "BACK",    (40,100,180)),
    ("03_side_full",    "FULL BODY — SIDE PROFILE (90°)", "side_full",   (40,140,100),  "SIDE 90°",(40,140,100)),
    ("04_face_neutral", "FACE CLOSE-UP — NEUTRAL",        "face_neutral",(80, 80,180),  "NEUTRAL", (80, 80,180)),
    ("05_face_smile",   "FACE CLOSE-UP — SMILING",        "face_smile",  (60,160, 80),  "SMILE",   (60,160, 80)),
    ("06_face_serious", "FACE CLOSE-UP — SERIOUS",        "face_serious",(160, 60, 60), "SERIOUS", (160,60, 60)),
    ("07_sit_forward",  "MEDIUM SHOT — SITTING + TEA",    "sit_tea",     (160,120, 40), "SITTING", (160,120, 40)),
    ("08_sit_cross",    "MEDIUM SHOT — ARMS CROSSED",     "sit_cross",   (120, 60,160), "CROSSED", (120,60,160)),
]

FN_MAP = {
    "front_full":   (draw_full_front,   512, 540),
    "back_full":    (draw_full_back,    512, 540),
    "side_full":    (draw_full_side,    512, 540),
    "face_neutral": (draw_face_neutral, 512, 440),
    "face_smile":   (draw_face_smile,   512, 440),
    "face_serious": (draw_face_serious, 512, 440),
    "sit_tea":      (draw_sitting_tea,  512, 460),
    "sit_cross":    (draw_sitting_cross,512, 460),
}

def build_all(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for suffix, label, fn_key, border, badge_text, badge_color in POSES:
        img, draw = new_canvas(label, border_color=border)
        fn, cx, cy = FN_MAP[fn_key]
        fn(draw, cx, cy)
        add_view_badge(draw, badge_text, color=badge_color)
        # camera icon in top-right for full-body shots
        if "full" in fn_key:
            add_camera_icon(draw, W - 60, 56)
        path = os.path.join(out_dir, f"pose_{suffix}.png")
        img.save(path, "PNG")
        print(f"  Saved: {path}")
        files.append((suffix, path))
    return files

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "assets", "poses")
    print(f"Generating 8 pose reference images → {out_dir}")
    files = build_all(out_dir)
    print(f"\nDone. {len(files)} images created.")
    print("\nNext steps:")
    print("  1. Review images in E:/MJ/assets/poses/")
    print("  2. Upload to RunPod:")
    print("     rsync -av E:/MJ/assets/poses/ runpod:/workspace/runpod-slim/ComfyUI/input/poses/")
    print("  3. Run: python fix_qwen_workflow.py")
    print("     → produces D:/下载/10张_v4.json with pose images wired to slots")
