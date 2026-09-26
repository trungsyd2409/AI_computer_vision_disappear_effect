"""Threaded webcam reader.

All cv2.VideoCapture calls happen in ONE background thread (the camera
thread). Other threads send commands through a queue. This keeps cap.read()
from blocking the UI, so the display runs at the real camera FPS.
"""
import queue
import threading
import time

import cv2

import config as C


class Camera(threading.Thread):
    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg                  # shared dict (read only here)
        self.cmds = queue.Queue()
        self.cond = threading.Condition()
        self.frame = None
        self.frame_id = 0
        self.cam_fps = 0.0
        self.info = "opening..."        # text shown in settings window
        self.actual = {}                # prop key -> value read back from camera
        self.error = None
        self._cap = None
        self._running = True

    # ---------------------------------------------------------------- public
    def request(self, cmd, *args):
        """cmd: 'reopen' | 'set_prop' key | 'set_auto' key | 'apply_all' | 'read' | 'dialog'"""
        self.cmds.put((cmd, args))

    def wait_frame(self, last_id, timeout=0.05):
        """Return (frame, id) when a newer frame than last_id exists, else (None, last_id)."""
        with self.cond:
            if self.frame_id == last_id:
                self.cond.wait(timeout)
            if self.frame_id == last_id or self.frame is None:
                return None, last_id
            return self.frame, self.frame_id

    def stop(self):
        self._running = False

    # ---------------------------------------------------------------- thread
    def run(self):
        self._open()
        t_prev = time.perf_counter()
        while self._running:
            self._handle_cmds()
            if self._cap is None or not self._cap.isOpened():
                time.sleep(0.2)
                continue
            ok, frame = self._cap.read()
            if not ok or frame is None:
                self.error = "Camera read failed"
                time.sleep(0.05)
                continue
            self.error = None
            now = time.perf_counter()
            dt = now - t_prev
            t_prev = now
            if dt > 0:
                inst = 1.0 / dt
                self.cam_fps = inst if self.cam_fps == 0 else self.cam_fps * 0.9 + inst * 0.1
            with self.cond:
                self.frame = frame
                self.frame_id += 1
                self.cond.notify_all()
        if self._cap is not None:
            self._cap.release()

    def _handle_cmds(self):
        pending = []   # drop duplicates (dragging a slider sends many)
        while True:
            try:
                item = self.cmds.get_nowait()
            except queue.Empty:
                break
            if item not in pending:
                pending.append(item)
        for cmd, args in pending:
            try:
                if cmd == "reopen":
                    self._open()
                elif cmd == "set_prop":
                    self._set_prop(args[0])
                    self._read_back()
                elif cmd == "set_auto":
                    self._set_auto(args[0])
                    self._read_back()
                elif cmd == "apply_all":
                    self._apply_all()
                elif cmd == "read":
                    self._read_back()
                elif cmd == "dialog" and self._cap is not None:
                    # Opens the webcam driver's own settings dialog (DirectShow only)
                    self._cap.set(cv2.CAP_PROP_SETTINGS, 1)
            except cv2.error as e:
                print(f"[camera] {cmd} failed: {e}")

    # ---------------------------------------------------------------- helpers
    def _open(self):
        cam = self.cfg["camera"]
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        backend = C.BACKENDS.get(cam["backend"], cv2.CAP_ANY)
        self.info = f"opening camera {cam['index']} ({cam['backend']})..."
        cap = cv2.VideoCapture(int(cam["index"]), backend)
        if not cap.isOpened():
            self.info = f"Cannot open camera {cam['index']} with {cam['backend']}"
            self.error = self.info
            print("[camera]", self.info)
            return
        # Order matters on DirectShow: FOURCC -> size -> fps
        if cam.get("fourcc") and cam["fourcc"] != "default":
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cam["fourcc"]))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cam["width"]))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cam["height"]))
        cap.set(cv2.CAP_PROP_FPS, float(cam["fps"]))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # always get the newest frame
        self._cap = cap
        self._apply_all()
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        fcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        fcc_s = "".join(chr((fcc >> 8 * i) & 0xFF) for i in range(4)) if fcc > 0 else "?"
        self.info = f"Camera {cam['index']} {cam['backend']}: {w}x{h} @ {fps:.0f} fps, {fcc_s}"
        print("[camera]", self.info)
        self.cam_fps = 0.0

    def _apply_all(self):
        # auto modes first (turning auto off is what allows manual values)
        for key in C.CAMERA_AUTO:
            self._set_auto(key)
        for key in C.CAMERA_PROPS:
            self._set_prop(key)
        self._read_back()

    def _set_auto(self, key):
        item = self.cfg["camera"]["auto"][key]
        if self._cap is None or not item["apply"]:
            return
        prop = C.CAMERA_AUTO[key][1]
        on = bool(item["value"])
        if key == "auto_exposure":
            cam = self.cfg["camera"]
            val = cam["auto_exposure_on_value"] if on else cam["auto_exposure_off_value"]
        else:
            val = 1 if on else 0
        self._cap.set(prop, float(val))
        # after switching auto off, push the manual value again
        if not on:
            manual = {"auto_exposure": "exposure", "auto_wb": "wb_temperature",
                      "autofocus": "focus"}[key]
            self._set_prop(manual)

    def _set_prop(self, key):
        item = self.cfg["camera"]["props"][key]
        if self._cap is None or not item["apply"]:
            return
        self._cap.set(C.CAMERA_PROPS[key][1], float(item["value"]))

    def _read_back(self):
        if self._cap is None:
            return
        vals = {}
        for key, spec in C.CAMERA_PROPS.items():
            vals[key] = self._cap.get(spec[1])
        for key, spec in C.CAMERA_AUTO.items():
            vals[key] = self._cap.get(spec[1])
        self.actual = vals
