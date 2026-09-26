"""Everything drawn on top of the image (never baked into the background)."""
import cv2
import numpy as np

from vision import HAND_CONNECTIONS
from effect import THUMB_TIP, INDEX_TIP

FONT = cv2.FONT_HERSHEY_SIMPLEX
WHITE, BLACK = (255, 255, 255), (0, 0, 0)
GREEN, RED, CYAN, YELLOW = (80, 220, 80), (60, 60, 255), (255, 220, 0), (0, 220, 255)
MAGENTA = (255, 80, 255)


def fit_size(w, h, max_w, max_h):
    """Largest size inside max_w x max_h that keeps the camera aspect ratio."""
    s = min(max_w / w, max_h / h)
    return max(1, int(round(w * s))), max(1, int(round(h * s)))


def text(img, s, org, scale=0.6, color=WHITE, thick=1, anchor="tl"):
    """Text with a dark outline so it is readable on any background.
    anchor: tl (top-left), tr (top-right), bl (bottom-left), c (center)."""
    (tw, th), base = cv2.getTextSize(s, FONT, scale, thick)
    x, y = org
    if anchor == "tr":
        x -= tw
        y += th
    elif anchor == "tl":
        y += th
    elif anchor == "c":
        x -= tw // 2
        y += th // 2
    # "bl": org is already the baseline
    x, y = int(x), int(y)
    outline = thick + (2 if scale >= 0.6 else 1)
    cv2.putText(img, s, (x, y), FONT, scale, BLACK, outline, cv2.LINE_AA)
    cv2.putText(img, s, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def draw_fps(img, fps, cam_fps):
    w = img.shape[1]
    text(img, f"FPS {fps:5.1f}", (w - 10, 8), 0.7, YELLOW, 2, "tr")
    text(img, f"cam {cam_fps:4.1f}", (w - 10, 38), 0.5, WHITE, 1, "tr")


def draw_hand(img, lm, color, label, show_skeleton=True):
    """Skeleton + thumb-index line in `color`, with `label` (e.g. "Opacity 64%")
    written next to the fingers."""
    p = lm.astype(np.int32)
    if show_skeleton:
        for a, b in HAND_CONNECTIONS:
            cv2.line(img, tuple(p[a]), tuple(p[b]), CYAN, 2, cv2.LINE_AA)
        for i, pt in enumerate(p):
            r = 5 if i in (THUMB_TIP, INDEX_TIP) else 3
            cv2.circle(img, tuple(pt), r, WHITE, -1, cv2.LINE_AA)
            cv2.circle(img, tuple(pt), r, BLACK, 1, cv2.LINE_AA)
    t, i = tuple(p[THUMB_TIP]), tuple(p[INDEX_TIP])
    cv2.line(img, t, i, color, 3, cv2.LINE_AA)
    cv2.circle(img, t, 7, color, -1, cv2.LINE_AA)
    cv2.circle(img, i, 7, color, -1, cv2.LINE_AA)
    mid = ((t[0] + i[0]) // 2 + 14, (t[1] + i[1]) // 2)
    text(img, label, mid, 0.6, color, 2, "tl")


def draw_values(img, opacity, glitch):
    h = img.shape[0]
    text(img, f"Glitch:  {glitch * 100:.0f}%", (10, h - 42), 0.7, MAGENTA, 2, "bl")
    text(img, f"Opacity: {opacity * 100:.0f}%", (10, h - 12), 0.7, GREEN, 2, "bl")


def draw_warning(img, msg):
    text(img, msg, (10, 10), 0.6, RED, 2, "tl")


def draw_countdown(img, seconds_left, capturing):
    h, w = img.shape[:2]
    dim = img.copy()
    cv2.rectangle(dim, (0, 0), (w, h), BLACK, -1)
    cv2.addWeighted(dim, 0.25, img, 0.75, 0, img)
    if capturing:
        text(img, "Capturing background...", (w // 2, h // 2), 1.0, YELLOW, 2, "c")
    else:
        text(img, str(int(np.ceil(seconds_left))), (w // 2, h // 2 - 20), 3.0, YELLOW, 6, "c")
        text(img, "Step out of the frame!", (w // 2, h // 2 + 50), 0.9, WHITE, 2, "c")
