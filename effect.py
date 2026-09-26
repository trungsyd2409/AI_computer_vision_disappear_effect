"""The effect: hand opening -> value, mask cleanup, glitch compositing,
and background-plate capture. Pure numpy/OpenCV, no MediaPipe, so it is easy
to test."""
import time

import cv2
import numpy as np

THUMB_TIP, INDEX_TIP, WRIST, MIDDLE_MCP = 4, 8, 0, 9


def pinch_ratio(lm):
    """Thumb-index tip distance divided by hand size (wrist -> middle finger base).

    Dividing by hand size makes the value the same whether the hand is near
    or far from the camera. ~0.1-0.2 when touching, ~1.0 when wide open.
    """
    size = np.linalg.norm(lm[MIDDLE_MCP] - lm[WRIST])
    if size < 1e-3:
        return None
    return float(np.linalg.norm(lm[THUMB_TIP] - lm[INDEX_TIP]) / size)


def ratio_to_value(ratio, eff):
    """Pinch ratio -> 0..1. Fingers touching (<= ratio_closed) = 0,
    fully open (>= ratio_open) = 1, linear in between."""
    lo, hi = float(eff["ratio_closed"]), float(eff["ratio_open"])
    if hi <= lo + 1e-3:
        hi = lo + 1e-3
    return float(np.clip((ratio - lo) / (hi - lo), 0.0, 1.0))


class HandValue:
    """One hand -> one smoothed value in 0..1.

    hand visible  -> value follows how wide the thumb-index are open
    hand lost     -> "Keep state": keep last value
                     "Show person": go back to `rest` after a short delay
    """

    def __init__(self, rest):
        self.rest = rest            # value when the hand is not there
        self.value = rest
        self.ratio = None
        self.last_seen = -1e9

    def update(self, lm, eff, now):
        target = None
        self.ratio = pinch_ratio(lm) if lm is not None else None
        if self.ratio is not None:
            self.last_seen = now
            target = ratio_to_value(self.ratio, eff)
        elif eff["hand_lost"] == "Show person" and now - self.last_seen > eff["hand_lost_grace"]:
            target = self.rest
        if target is not None:
            a = float(eff["value_smooth"])   # smoothing against hand jitter
            self.value = self.value * a + target * (1.0 - a)
            if abs(self.value - target) < 0.005:
                self.value = target
        return self.value


class MaskRefiner:
    """Raw model confidence -> clean, soft, stable person mask."""

    def __init__(self):
        self.prev = None

    def reset(self):
        self.prev = None

    def refine(self, conf, eff, shape):
        """Work at ~400 px wide (fast), then upscale to the frame size."""
        h, w = shape[:2]
        s = min(1.0, 400.0 / w)
        ww, wh = max(1, int(w * s)), max(1, int(h * s))
        conf = cv2.resize(conf, (ww, wh), interpolation=cv2.INTER_LINEAR)
        if eff.get("invert_mask"):
            conf = 1.0 - conf
        lo, hi = float(eff["mask_low"]), float(eff["mask_high"])
        m = np.clip((conf - lo) / max(hi - lo, 1e-3), 0.0, 1.0).astype(np.float32)

        # temporal smoothing: less flicker on the edges
        a = float(eff["mask_smooth"])
        if self.prev is not None and self.prev.shape == m.shape and a > 0:
            m = self.prev * a + m * (1.0 - a)
        self.prev = m

        d = int(round(float(eff["mask_dilate"]) * s))
        if d > 0:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * d + 1, 2 * d + 1))
            m = cv2.dilate(m, k)
        f = int(round(float(eff["mask_feather"]) * s))
        if f > 0:
            m = cv2.GaussianBlur(m, (2 * f + 1, 2 * f + 1), 0)
        return cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)


def composite(live, bg, mask, opacity):
    """Replace the person area with the background plate.

    alpha = mask * (1 - opacity): 0 -> live pixel, 1 -> background pixel.
    """
    hide = 1.0 - opacity
    if hide <= 0.0 or bg is None or mask is None:
        return live
    alpha = (mask * hide).astype(np.float32)
    # out = bg * alpha + live * (1 - alpha), done in C++ (much faster than numpy)
    return cv2.blendLinear(bg, live, alpha, 1.0 - alpha)


def glitch_composite(live, bg, mask, opacity, glitch, eff, rng):
    """Person-only effect.

    opacity (right hand): 1 = person fully visible, 0 = gone (background plate).
    glitch  (left hand):  0 = clean, 1 = maximum glitch (x "Max strength").
    """
    g = float(np.clip(glitch, 0.0, 1.0)) * float(eff["glitch_strength"])
    if mask is None or bg is None:
        return live
    if g <= 0.01:
        return composite(live, bg, mask, opacity)
    if opacity <= 0.0:
        return composite(live, bg, mask, 0.0)

    # work only inside the person's bounding box (+ margin for the tearing)
    x, y, bw, bh = cv2.boundingRect((mask > 0.02).astype(np.uint8))
    if bw == 0 or bh == 0:
        return live
    pad = int(float(eff["glitch_shift"]) * g + float(eff["glitch_rgb"]) * g) + 10
    H, W = mask.shape[:2]
    x0, y0 = max(0, x - pad), max(0, y - 10)
    x1, y1 = min(W, x + bw + pad), min(H, y + bh + 10)
    out = live.copy()
    out[y0:y1, x0:x1] = _glitch_roi(live[y0:y1, x0:x1], bg[y0:y1, x0:x1],
                                    mask[y0:y1, x0:x1], opacity, g, eff, rng)
    return out


def _glitch_roi(live, bg, mask, opacity, g, eff, rng):
    h, w = mask.shape[:2]
    person = live.astype(np.float32)
    alpha = mask.astype(np.float32) * float(opacity)   # right hand: see-through

    # 1) horizontal slices: random shift + random flicker dropout (-> background)
    max_shift = int(float(eff["glitch_shift"]) * g)
    y = 0
    while y < h:
        y2 = min(h, y + int(rng.integers(3, 30)))
        if max_shift > 0 and rng.random() < 0.15 + 0.5 * g:
            dx = int(rng.integers(-max_shift, max_shift + 1))
            person[y:y2] = np.roll(person[y:y2], dx, axis=1)
            alpha[y:y2] = np.roll(alpha[y:y2], dx, axis=1)
        if rng.random() < 0.3 * min(g, 1.0):    # stronger glitch -> more flicker
            alpha[y:y2] = 0.0
        y = y2

    # 2) blocks copied from a nearby spot and tinted cyan / magenta
    ys, xs = np.nonzero(mask > 0.5)
    if len(ys):
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        for _ in range(int(8 * g)):
            bw, bh = int(rng.integers(20, 120)), int(rng.integers(6, 40))
            by = int(rng.integers(y0, max(y0 + 1, y1 - bh)))
            bx = int(rng.integers(x0, max(x0 + 1, x1 - bw)))
            sy = int(np.clip(by + rng.integers(-40, 41), 0, h - bh))
            sx = int(np.clip(bx + rng.integers(-80, 81), 0, w - bw))
            if by + bh > h or bx + bw > w:
                continue
            block = person[sy:sy + bh, sx:sx + bw].copy()
            tint = (255.0, 255.0, 0.0) if rng.random() < 0.5 else (255.0, 0.0, 255.0)
            person[by:by + bh, bx:bx + bw] = block * 0.5 + np.array(tint, np.float32) * 0.5

    # 3) scanlines + blocky noise
    person[::3] *= 1.0 - 0.4 * min(g, 1.0)
    if g > 0.05:
        noise = rng.normal(0.0, 40.0 * g, (max(1, h // 4), max(1, w // 4))).astype(np.float32)
        noise = cv2.resize(noise, (w, h), interpolation=cv2.INTER_NEAREST)
        person += noise[..., None]

    # 4) RGB split: blue goes left, red goes right (with their own alpha)
    d = int(float(eff["glitch_rgb"]) * g)
    bgf = bg.astype(np.float32)
    out = np.empty_like(person)
    for c, dx in ((0, -d), (1, 0), (2, d)):
        pc = np.roll(person[..., c], dx, axis=1) if dx else person[..., c]
        ac = np.roll(alpha, dx, axis=1) if dx else alpha
        out[..., c] = bgf[..., c] + (pc - bgf[..., c]) * ac
    return np.clip(out, 0, 255).astype(np.uint8)


class BackgroundCapture:
    """Press G -> countdown -> average N frames -> background plate.

    The plate is saved to background.png and loaded again on the next start,
    so you only need to capture once. It is stored un-mirrored on disk.
    """

    IDLE, COUNTDOWN, CAPTURING = 0, 1, 2

    def __init__(self, path=None, mirrored=False):
        self.path = path
        self.mirrored = mirrored
        self.plate = None
        self.state = self.IDLE
        self.t_start = 0.0
        self._acc = None
        self._n = 0
        self.countdown = 3
        self.frames = 15
        self.load()

    # ---------------------------------------------------------- disk
    def load(self):
        if not self.path:
            return
        try:
            data = np.fromfile(self.path, dtype=np.uint8)   # works with any path on Windows
            img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
        except OSError:
            img = None
        if img is None:
            return
        if self.mirrored:
            img = cv2.flip(img, 1)
        self.plate = img
        print(f"[bg] loaded {self.path} {img.shape[1]}x{img.shape[0]}")

    def _save(self):
        if not self.path or self.plate is None:
            return
        img = cv2.flip(self.plate, 1) if self.mirrored else self.plate
        ok, buf = cv2.imencode(".png", img)
        if ok:
            buf.tofile(self.path)
            print(f"[bg] saved {self.path}")

    # ---------------------------------------------------------- capture
    def start(self, countdown, frames):
        self.state = self.COUNTDOWN
        self.t_start = time.monotonic()
        self.countdown = float(countdown)
        self.frames = max(1, int(frames))
        self._acc, self._n = None, 0

    def seconds_left(self):
        if self.state != self.COUNTDOWN:
            return 0.0
        return max(0.0, self.countdown - (time.monotonic() - self.t_start))

    def feed(self, frame):
        """Call every frame with the clean (no overlay) image."""
        if self.state == self.COUNTDOWN and self.seconds_left() <= 0:
            self.state = self.CAPTURING
        if self.state == self.CAPTURING:
            f = frame.astype(np.float32)
            if self._acc is None or self._acc.shape != f.shape:
                self._acc, self._n = np.zeros_like(f), 0
            self._acc += f
            self._n += 1
            if self._n >= self.frames:
                self.plate = (self._acc / self._n).round().astype(np.uint8)
                self.state = self.IDLE
                self._acc = None
                print("[bg] background captured", self.plate.shape)
                self._save()

    def valid_for(self, frame):
        """True if the plate fits this frame. Same aspect ratio but another
        size (e.g. window size changed) -> resize the plate."""
        if self.plate is None:
            return False
        if self.plate.shape == frame.shape:
            return True
        ph, pw = self.plate.shape[:2]
        fh, fw = frame.shape[:2]
        if abs(pw / ph - fw / fh) < 0.01:
            self.plate = cv2.resize(self.plate, (fw, fh), interpolation=cv2.INTER_AREA)
            return True
        return False

    def flip(self, mirrored):
        self.mirrored = mirrored
        if self.plate is not None:
            self.plate = np.ascontiguousarray(self.plate[:, ::-1])
