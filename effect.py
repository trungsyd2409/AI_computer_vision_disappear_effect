"""The disappear effect: pinch detection, fade, mask cleanup, compositing,
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


class PinchState:
    """Touch / release with hysteresis so the state does not flicker at the edge."""

    def __init__(self):
        self.touching = False
        self.last_seen = 0.0

    def update(self, ratio, eff, now):
        if ratio is not None:
            self.last_seen = now
            off = max(eff["pinch_off"], eff["pinch_on"] + 0.02)
            if self.touching and ratio > off:
                self.touching = False
            elif not self.touching and ratio < eff["pinch_on"]:
                self.touching = True
        elif eff["hand_lost"] == "Show person" and now - self.last_seen > eff["hand_lost_grace"]:
            self.touching = False
        return self.touching


class Fader:
    """opacity 1.0 = person fully visible, 0.0 = fully gone."""

    def __init__(self):
        self.opacity = 1.0

    def update(self, hide, fade_time, dt):
        target = 0.0 if hide else 1.0
        if fade_time <= 1e-3:
            self.opacity = target
        else:
            step = dt / fade_time
            if self.opacity < target:
                self.opacity = min(target, self.opacity + step)
            else:
                self.opacity = max(target, self.opacity - step)
        return self.opacity


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


class BackgroundCapture:
    """Press B -> countdown -> average N frames -> background plate."""

    IDLE, COUNTDOWN, CAPTURING = 0, 1, 2

    def __init__(self):
        self.plate = None
        self.state = self.IDLE
        self.t_start = 0.0
        self._acc = None
        self._n = 0
        self.countdown = 3
        self.frames = 15

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

    def valid_for(self, frame):
        return self.plate is not None and self.plate.shape == frame.shape

    def flip(self):
        if self.plate is not None:
            self.plate = np.ascontiguousarray(self.plate[:, ::-1])
