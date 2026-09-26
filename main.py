"""Disappear effect.

Right hand: thumb-index distance = your opacity (touching 0% .. wide open 100%).
Left hand:  thumb-index distance = glitch strength (touching 0% .. wide open 100%).

Keys (click the video window first):
    G      (re)capture background (countdown, step out of the frame).
           It is saved to background.png and loaded automatically next time.
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
from effect import BackgroundCapture, HandValue, MaskRefiner, glitch_composite
from settings_ui import SettingsWindow
from vision import HandTracker, PersonSegmenter, to_mp_image

WIN = "App"


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
    state = {}   # live values shown in the settings window
    settings = SettingsWindow(root, cfg, cam, state)

    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)

    refiner = MaskRefiner()
    right = HandValue(rest=1.0)   # right hand -> opacity (1 = fully visible)
    left = HandValue(rest=0.0)    # left hand  -> glitch  (0 = clean)
    bgcap = BackgroundCapture(C.BACKGROUND_PATH, cfg["display"]["mirror"])
    rng = np.random.default_rng()
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
                bgcap.flip(disp["mirror"])   # keep the saved background lined up
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

            # ---------- hands: right = opacity, left = glitch ----------
            mp_img = to_mp_image(frame)
            found = hands.detect(mp_img, dw, dh, disp["mirror"])
            now_m = time.monotonic()
            opacity = right.update(found.get("Right"), eff, now_m)
            glitch = left.update(found.get("Left"), eff, now_m)
            if not bg_ok:
                opacity = 1.0   # cannot hide without a background plate
            state.update(right_ratio=right.ratio, left_ratio=left.ratio,
                         opacity=opacity, glitch=glitch)

            # ---------- person mask + effect ----------
            out = frame
            active = opacity < 0.999 or glitch * eff["glitch_strength"] > 0.01
            if active:   # skip segmentation when nothing to do (saves CPU)
                conf = seg.person_confidence(mp_img)
                mask = refiner.refine(conf, eff, frame.shape)
                # without a saved background, glitch is drawn over the live frame
                plate = bgcap.plate if bg_ok else frame
                out = glitch_composite(frame, plate, mask, opacity, glitch, eff, rng)
            else:
                refiner.reset()

            # ---------- overlay ----------
            view = out.copy()
            if bgcap.state != BackgroundCapture.IDLE:
                O.draw_countdown(view, bgcap.seconds_left(),
                                 bgcap.state == BackgroundCapture.CAPTURING)
            else:
                if "Right" in found:
                    O.draw_hand(view, found["Right"], O.GREEN, f"{opacity * 100:.0f}%",
                                eff["show_skeleton"])
                if "Left" in found:
                    O.draw_hand(view, found["Left"], O.MAGENTA, f"{glitch * 100:.0f}%",
                                eff["show_skeleton"])
                if not bg_ok:
                    msg = ("Background does not fit this resolution - press G" if bgcap.plate is not None
                           else "No background! Press G to capture")
                    O.draw_warning(view, msg)
                if cam.error:
                    O.draw_warning(view, cam.error)
                O.draw_values(view, opacity, glitch)
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
    elif key in (ord("g"), ord("G")):
        bgcap.start(eff["bg_countdown"], eff["bg_frames"])
    return True


if __name__ == "__main__":
    main()
