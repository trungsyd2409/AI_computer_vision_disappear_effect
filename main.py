"""Disappear effect - pinch your right thumb and index finger to vanish.

Keys (click the video window first):
    B      capture background (countdown, step out of the frame)
    X      open / close the settings window
    Q/Esc  quit (settings are saved to settings.json)
"""
import time
import tkinter as tk

import cv2
import numpy as np

import config as C
import overlay as O
from camera import Camera
from effect import BackgroundCapture, Fader, MaskRefiner, PinchState, composite, pinch_ratio
from settings_ui import SettingsWindow
from vision import HandTracker, PersonSegmenter, to_mp_image

WIN = "Disappear Effect  |  B: capture background   X: settings   Q: quit"


def main():
    cfg = C.load()

    print("Loading models (first run downloads them, ~10 MB)...")
    hands = HandTracker(cfg["effect"]["min_hand_conf"])
    seg = PersonSegmenter(cfg["effect"]["seg_model"])
    hand_conf_used = cfg["effect"]["min_hand_conf"]

    cam = Camera(cfg)
    cam.start()

    # Tk root stays hidden; the settings window is a Toplevel. We pump Tk
    # events ourselves (root.update) so OpenCV and Tk share the main thread.
    root = tk.Tk()
    root.withdraw()
    state = {"pinch_ratio": None, "touching": False}
    settings = SettingsWindow(root, cfg, cam, state)

    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)

    pinch, fader, refiner, bgcap = PinchState(), Fader(), MaskRefiner(), BackgroundCapture()
    mirror_used = cfg["display"]["mirror"]
    frame_id = 0
    fps = 0.0
    t_prev = time.perf_counter()
    last_display = None

    try:
        while True:
            # ---------- keep Tk alive ----------
            try:
                root.update()
            except tk.TclError:
                pass
            settings.tick()

            eff, disp = cfg["effect"], cfg["display"]

            # ---------- rebuild models if their settings changed ----------
            if eff["seg_model"] != seg.model_name:
                try:
                    new = PersonSegmenter(eff["seg_model"])
                    seg.close()
                    seg = new
                    refiner.reset()
                except Exception as e:  # noqa: BLE001
                    print("[seg]", e)
                    eff["seg_model"] = seg.model_name
            if eff["min_hand_conf"] != hand_conf_used:
                hands.close()
                hands = HandTracker(eff["min_hand_conf"])
                hand_conf_used = eff["min_hand_conf"]
            if disp["mirror"] != mirror_used:
                bgcap.flip()          # keep the saved background lined up
                refiner.reset()
                mirror_used = disp["mirror"]

            # ---------- get newest camera frame ----------
            raw, new_id = cam.wait_frame(frame_id)
            if raw is None:
                if last_display is None:
                    blank = np.zeros((450, 800, 3), np.uint8)
                    O.draw_warning(blank, cam.error or "Waiting for camera...")
                    cv2.imshow(WIN, blank)
                if not handle_keys(cv2.waitKey(1), bgcap, settings, eff):
                    break
                if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                    break
                continue
            frame_id = new_id

            now = time.perf_counter()
            dt = now - t_prev
            t_prev = now
            if dt > 0:
                fps = 1.0 / dt if fps == 0 else fps * 0.9 + (1.0 / dt) * 0.1

            # ---------- resize to display size (keeps aspect), mirror ----------
            h0, w0 = raw.shape[:2]
            dw, dh = O.fit_size(w0, h0, disp["max_width"], disp["max_height"])
            frame = cv2.resize(raw, (dw, dh), interpolation=cv2.INTER_AREA)
            if disp["mirror"]:
                frame = cv2.flip(frame, 1)

            # ---------- background capture (uses the clean frame) ----------
            bgcap.feed(frame)
            bg_ok = bgcap.valid_for(frame)

            # ---------- hand + pinch ----------
            mp_img = to_mp_image(frame)
            lm, _label = hands.detect(mp_img, dw, dh, eff["hand"], disp["mirror"])
            ratio = pinch_ratio(lm) if lm is not None else None
            touching = pinch.update(ratio, eff, time.monotonic())
            state["pinch_ratio"], state["touching"] = ratio, touching

            # only hide when a background exists
            opacity = fader.update(touching and bg_ok, eff["fade_time"], dt)

            # ---------- person mask + composite ----------
            out = frame
            # skip segmentation while fully visible (saves CPU)
            if bg_ok and (opacity < 1.0 or touching):
                conf = seg.person_confidence(mp_img)
                mask = refiner.refine(conf, eff, frame.shape)
                out = composite(frame, bgcap.plate, mask, opacity)
            else:
                refiner.reset()

            # ---------- overlay ----------
            view = out.copy()
            if bgcap.state != BackgroundCapture.IDLE:
                O.draw_countdown(view, bgcap.seconds_left(),
                                 bgcap.state == BackgroundCapture.CAPTURING)
            else:
                if lm is not None:
                    O.draw_hand(view, lm, touching, opacity, eff["show_skeleton"])
                if not bg_ok:
                    msg = ("Background size changed - press B again" if bgcap.plate is not None
                           else "No background! Press B to capture")
                    O.draw_warning(view, msg)
                if cam.error:
                    O.draw_warning(view, cam.error)
                O.draw_opacity(view, opacity)
            O.draw_fps(view, fps, cam.cam_fps)

            cv2.imshow(WIN, view)
            last_display = view

            if not handle_keys(cv2.waitKey(1), bgcap, settings, eff):
                break
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cam.stop()
        C.save(cfg)
        hands.close()
        seg.close()
        cv2.destroyAllWindows()
        try:
            root.destroy()
        except tk.TclError:
            pass


def handle_keys(key, bgcap, settings, eff):
    """Return False to quit."""
    if key == -1:
        return True
    key &= 0xFF
    if key in (ord("q"), ord("Q"), 27):
        return False
    if key in (ord("x"), ord("X")):
        settings.toggle()
    elif key in (ord("b"), ord("B")):
        bgcap.start(eff["bg_countdown"], eff["bg_frames"])
    return True


if __name__ == "__main__":
    main()
