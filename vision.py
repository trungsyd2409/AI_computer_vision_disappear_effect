"""MediaPipe wrappers: hand landmarks + person segmentation (Tasks API).

Newer MediaPipe versions (0.10.30+) removed the old `mp.solutions` API, so this
project uses `mediapipe.tasks`. Model files are downloaded into ./models on
first run.
"""
import os
import time
import urllib.request

import cv2
import mediapipe as mp
import numpy as np

import config as C

vision = mp.tasks.vision

# 21 landmarks: 0 wrist, 4 thumb tip, 8 index tip, 9 middle-finger base
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),            # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),            # index
    (5, 9), (9, 10), (10, 11), (11, 12),       # middle
    (9, 13), (13, 14), (14, 15), (15, 16),     # ring
    (13, 17), (17, 18), (18, 19), (19, 20),    # pinky
    (0, 17),                                   # palm
]


def ensure_model(filename, url):
    os.makedirs(C.MODELS_DIR, exist_ok=True)
    path = os.path.join(C.MODELS_DIR, filename)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    print(f"[models] downloading {filename} ...")
    tmp = path + ".part"
    try:
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(
            f"Could not download {filename}: {e}\n"
            f"Download it manually from:\n  {url}\nand put it in: {C.MODELS_DIR}"
        ) from e
    print(f"[models] saved {path}")
    return path


class _Clock:
    """VIDEO mode needs strictly increasing timestamps (ms)."""

    def __init__(self):
        self.last = -1

    def next(self):
        t = int(time.monotonic() * 1000)
        if t <= self.last:
            t = self.last + 1
        self.last = t
        return t


def to_mp_image(bgr):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))


class HandTracker:
    def __init__(self, min_conf=0.5):
        path = ensure_model(*C.HAND_MODEL)
        opts = vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=path),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,  # detect both so the left hand is never mistaken for the right
            min_hand_detection_confidence=min_conf,
            min_hand_presence_confidence=min_conf,
            min_tracking_confidence=min_conf,
        )
        self.lm = vision.HandLandmarker.create_from_options(opts)
        self.clock = _Clock()

    def detect(self, mp_image, w, h, want="Right", mirrored=True):
        """Return (Nx2 pixel landmarks, label) of the wanted hand, or (None, None).

        MediaPipe labels handedness assuming a mirrored (selfie) image. We
        flip the frame when mirror is on, so labels are correct; when mirror
        is off we swap them.
        """
        res = self.lm.detect_for_video(mp_image, self.clock.next())
        best, best_score, best_label = None, -1.0, None
        for lms, hd in zip(res.hand_landmarks, res.handedness):
            label = hd[0].category_name
            if not mirrored:
                label = "Left" if label == "Right" else "Right"
            if want != "Any" and label != want:
                continue
            if hd[0].score > best_score:
                best_score = hd[0].score
                best_label = label
                best = np.array([[p.x * w, p.y * h] for p in lms], dtype=np.float32)
        return best, best_label

    def close(self):
        self.lm.close()


class PersonSegmenter:
    def __init__(self, model_name):
        filename, url = C.SEG_MODELS[model_name]
        path = ensure_model(filename, url)
        opts = vision.ImageSegmenterOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=path),
            running_mode=vision.RunningMode.VIDEO,
            output_confidence_masks=True,
            output_category_mask=False,
        )
        self.seg = vision.ImageSegmenter.create_from_options(opts)
        self.clock = _Clock()
        self.model_name = model_name

    def person_confidence(self, mp_image):
        """HxW float32 in [0,1]: how likely each pixel is part of a person."""
        res = self.seg.segment_for_video(mp_image, self.clock.next())
        masks = res.confidence_masks
        m0 = np.squeeze(masks[0].numpy_view()).astype(np.float32)
        if len(masks) == 1:
            # binary selfie model: one channel = person
            return m0.copy()
        # multi-class models: channel 0 = background, everything else = person
        return 1.0 - m0

    def close(self):
        self.seg.close()
