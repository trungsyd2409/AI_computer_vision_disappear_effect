"""Settings: default values + load/save to settings.json.

Everything the settings window (key X) can change lives in one nested dict,
so it is easy to save as JSON and reload next time.
"""
import copy
import json
import os

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")
BACKGROUND_PATH = os.path.join(HERE, "background.png")
MODELS_DIR = os.path.join(HERE, "models")

# --- Camera properties shown as sliders in the "Camera" tab -----------------
# key: (label, cv2 property id, slider min, slider max, resolution)
# Ranges differ between webcams. If a slider range does not fit your camera,
# edit "prop_ranges" in settings.json.
CAMERA_PROPS = {
    "brightness":     ("Brightness",     cv2.CAP_PROP_BRIGHTNESS,     -64, 255, 1),
    "contrast":       ("Contrast",       cv2.CAP_PROP_CONTRAST,         0, 255, 1),
    "saturation":     ("Saturation",     cv2.CAP_PROP_SATURATION,       0, 255, 1),
    "hue":            ("Hue",            cv2.CAP_PROP_HUE,           -180, 180, 1),
    "gain":           ("Gain",           cv2.CAP_PROP_GAIN,             0, 255, 1),
    "sharpness":      ("Sharpness",      cv2.CAP_PROP_SHARPNESS,        0, 255, 1),
    "gamma":          ("Gamma",          cv2.CAP_PROP_GAMMA,            0, 500, 1),
    "backlight":      ("Backlight comp", cv2.CAP_PROP_BACKLIGHT,        0,  10, 1),
    "exposure":       ("Exposure",       cv2.CAP_PROP_EXPOSURE,       -13,   0, 1),
    "wb_temperature": ("White balance",  cv2.CAP_PROP_WB_TEMPERATURE, 2000, 10000, 50),
    "focus":          ("Focus",          cv2.CAP_PROP_FOCUS,            0, 255, 1),
}

# --- Auto modes shown as checkboxes ------------------------------------------
# key: (label, cv2 property id)
CAMERA_AUTO = {
    "auto_exposure": ("Auto exposure", cv2.CAP_PROP_AUTO_EXPOSURE),
    "auto_wb":       ("Auto white balance", cv2.CAP_PROP_AUTO_WB),
    "autofocus":     ("Autofocus", cv2.CAP_PROP_AUTOFOCUS),
}

BACKENDS = {
    "DSHOW": cv2.CAP_DSHOW,   # best on Windows: MJPG + 30/60 fps + driver dialog
    "MSMF": cv2.CAP_MSMF,
    "ANY": cv2.CAP_ANY,
}

SEG_MODELS = {
    # name shown in UI: (file name, download url)
    "selfie_landscape (fast)": (
        "selfie_segmenter_landscape.tflite",
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
        "selfie_segmenter_landscape/float16/latest/selfie_segmenter_landscape.tflite",
    ),
    "selfie_square (fast)": (
        "selfie_segmenter.tflite",
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
        "selfie_segmenter/float16/latest/selfie_segmenter.tflite",
    ),
    "multiclass (best edges, slower)": (
        "selfie_multiclass_256x256.tflite",
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
        "selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
    ),
}

HAND_MODEL = (
    "hand_landmarker.task",
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task",
)

DEFAULTS = {
    "camera": {
        "index": 0,
        "backend": "DSHOW",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "fourcc": "MJPG",          # MJPG is what lets most USB webcams reach 30 fps at 720p
        # every slider: apply=False means "do not touch, keep camera default"
        "props": {k: {"apply": False, "value": 0} for k in CAMERA_PROPS},
        "auto": {k: {"apply": False, "value": True} for k in CAMERA_AUTO},
        # raw values sent for auto on/off. DSHOW usually 1/0, MSMF/V4L2 0.75/0.25.
        "auto_exposure_on_value": 1,
        "auto_exposure_off_value": 0,
        "prop_ranges": {},          # e.g. {"brightness": [0, 100]} to override slider range
    },
    "display": {
        "max_width": 800,
        "max_height": 600,
        "mirror": True,
    },
    "effect": {
        # Right hand -> opacity, left hand -> glitch.
        # value = (ratio - ratio_closed) / (ratio_open - ratio_closed), clipped to 0..1
        # ratio = thumb-index distance / hand size
        "ratio_closed": 0.2,       # fingers touching -> 0%
        "ratio_open": 1.0,         # fingers fully open -> 100%
        "value_smooth": 0.5,       # 0 = raw (jittery) .. 0.95 = very smooth / slow
        "hand_lost": "Show person",  # "Show person" (100% opacity, 0% glitch) or "Keep state"
        "hand_lost_grace": 0.3,    # seconds before "Show person" kicks in
        "glitch_strength": 1.0,    # glitch at 100% left hand: 0 = none .. 2 = crazy
        "glitch_shift": 60,        # max px a slice is torn sideways
        "glitch_rgb": 14,          # max px the red / blue channels split
        "seg_model": "selfie_landscape (fast)",
        "mask_low": 0.3,           # confidence below -> background
        "mask_high": 0.7,          # confidence above -> fully person
        "mask_dilate": 8,          # px, grow mask to hide the halo around the body
        "mask_feather": 9,         # px, soft edge
        "mask_smooth": 0.5,        # temporal smoothing 0 (none) .. 0.95 (very smooth)
        "invert_mask": False,
        "min_hand_conf": 0.5,
        "bg_countdown": 3,
        "bg_frames": 15,
        "show_skeleton": True,
    },
}


def _deep_merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                cfg = _deep_merge(DEFAULTS, json.load(f))
            # drop options from older versions that no longer exist
            for sec in ("effect", "display"):
                for k in list(cfg[sec]):
                    if k not in DEFAULTS[sec]:
                        del cfg[sec][k]
            return cfg
        except (OSError, ValueError) as e:
            print(f"[config] cannot read settings.json ({e}), using defaults")
    return copy.deepcopy(DEFAULTS)


def save(cfg):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"[config] saved -> {SETTINGS_PATH}")


def defaults():
    return copy.deepcopy(DEFAULTS)


def prop_range(cfg, key):
    _, _, lo, hi, res = CAMERA_PROPS[key]
    custom = cfg["camera"].get("prop_ranges", {}).get(key)
    if custom and len(custom) == 2:
        lo, hi = custom
    return lo, hi, res
