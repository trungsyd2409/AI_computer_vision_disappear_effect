"""Settings window (press X). Tkinter, driven from the main loop with root.update().

Tab "Camera": resolution / FPS / codec + every manual control (exposure, gain,
white balance, focus, ...). Tab "Effect": pinch thresholds, fade, mask quality.
Changes apply immediately. "Save" writes settings.json (it is also saved when
you quit the app).
"""
import tkinter as tk
from tkinter import ttk

import config as C

RESOLUTIONS = ["640x480", "800x600", "1280x720", "1920x1080"]
FPS_LIST = ["15", "24", "30", "60"]
FOURCCS = ["MJPG", "YUY2", "default"]
AUTO_CHOICES = ["(camera default)", "On", "Off"]


class SettingsWindow:
    def __init__(self, root, cfg, camera, state):
        self.root = root
        self.cfg = cfg
        self.cam = camera
        self.state = state          # live values from the main loop (pinch ratio...)
        self.win = None
        self._labels = {}
        self._tick_n = 0

    # ------------------------------------------------------------ open/close
    def toggle(self):
        if self.win is not None and self.win.winfo_exists():
            self.close()
        else:
            self.open()

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            return
        self.win = tk.Toplevel(self.root)
        self.win.title("Settings  (press X in the video window to close)")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.cam.request("read")
        # sliders that are not "Set" yet start at the camera's current value,
        # so ticking "Set" does not suddenly jump to 0
        self.win.after(400, self._sync_unset_sliders)
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.win.after(300, lambda: self.win.attributes("-topmost", False))

    def close(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = None

    def is_open(self):
        return self.win is not None and self.win.winfo_exists()

    # ------------------------------------------------------------ build
    def _build(self):
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        cam_tab = ttk.Frame(nb, padding=8)
        eff_tab = ttk.Frame(nb, padding=8)
        nb.add(cam_tab, text="Camera")
        nb.add(eff_tab, text="Effect")
        self._build_camera(cam_tab)
        self._build_effect(eff_tab)

        bar = ttk.Frame(self.win, padding=(8, 0, 8, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Save settings", command=lambda: C.save(self.cfg)).pack(side="left")
        ttk.Button(bar, text="Reset ALL to defaults", command=self._reset).pack(side="left", padx=6)
        ttk.Button(bar, text="Close", command=self.close).pack(side="right")

    def _build_camera(self, f):
        cam = self.cfg["camera"]
        # --- stream format (needs reopen) ---
        box = ttk.LabelFrame(f, text="Stream (press Apply to reopen camera)", padding=6)
        box.grid(row=0, column=0, columnspan=4, sticky="ew")
        self.v_index = tk.StringVar(value=str(cam["index"]))
        self.v_backend = tk.StringVar(value=cam["backend"])
        self.v_res = tk.StringVar(value=f"{cam['width']}x{cam['height']}")
        self.v_fps = tk.StringVar(value=str(cam["fps"]))
        self.v_fourcc = tk.StringVar(value=cam["fourcc"])
        items = [
            ("Index", ttk.Spinbox(box, from_=0, to=9, width=4, textvariable=self.v_index)),
            ("Backend", ttk.Combobox(box, values=list(C.BACKENDS), width=7,
                                     textvariable=self.v_backend, state="readonly")),
            ("Resolution", ttk.Combobox(box, values=RESOLUTIONS, width=10, textvariable=self.v_res)),
            ("FPS", ttk.Combobox(box, values=FPS_LIST, width=5, textvariable=self.v_fps)),
            ("Codec", ttk.Combobox(box, values=FOURCCS, width=8,
                                   textvariable=self.v_fourcc, state="readonly")),
        ]
        for i, (name, w) in enumerate(items):
            ttk.Label(box, text=name).grid(row=0, column=2 * i, padx=(6, 2))
            w.grid(row=0, column=2 * i + 1)
        ttk.Button(box, text="Apply", command=self._apply_stream).grid(row=0, column=10, padx=6)
        self._labels["info"] = ttk.Label(box, text="", foreground="#2266aa")
        self._labels["info"].grid(row=1, column=0, columnspan=11, sticky="w", pady=(4, 0))

        # --- auto modes ---
        auto = ttk.LabelFrame(f, text="Auto modes (turn Off to use the manual slider)", padding=6)
        auto.grid(row=1, column=0, columnspan=4, sticky="ew", pady=6)
        for i, (key, (label, _)) in enumerate(C.CAMERA_AUTO.items()):
            item = cam["auto"][key]
            cur = "(camera default)" if not item["apply"] else ("On" if item["value"] else "Off")
            var = tk.StringVar(value=cur)
            ttk.Label(auto, text=label).grid(row=0, column=2 * i, padx=(6, 2))
            cb = ttk.Combobox(auto, values=AUTO_CHOICES, width=15, textvariable=var, state="readonly")
            cb.grid(row=0, column=2 * i + 1)
            cb.bind("<<ComboboxSelected>>", lambda e, k=key, v=var: self._set_auto(k, v.get()))

        # --- manual sliders ---
        man = ttk.LabelFrame(f, text="Manual controls (tick 'Set' to control; unticked = camera decides)",
                             padding=6)
        man.grid(row=2, column=0, columnspan=4, sticky="ew")
        self.prop_vars = {}
        for r, (key, (label, _, _, _, _)) in enumerate(C.CAMERA_PROPS.items()):
            lo, hi, res = C.prop_range(self.cfg, key)
            item = cam["props"][key]
            v_apply = tk.BooleanVar(value=item["apply"])
            v_val = tk.DoubleVar(value=item["value"])
            self.prop_vars[key] = (v_apply, v_val)
            ttk.Checkbutton(man, text="Set", variable=v_apply,
                            command=lambda k=key: self._prop_changed(k)).grid(row=r, column=0)
            ttk.Label(man, text=label, width=15).grid(row=r, column=1, sticky="w")
            tk.Scale(man, from_=lo, to=hi, resolution=res, orient="horizontal", length=320,
                     variable=v_val, showvalue=True,
                     command=lambda _v, k=key: self._prop_changed(k)).grid(row=r, column=2)
            lab = ttk.Label(man, text="cam: ?", width=14, foreground="#777")
            lab.grid(row=r, column=3, sticky="w", padx=6)
            self._labels["prop_" + key] = lab

        btns = ttk.Frame(f)
        btns.grid(row=3, column=0, columnspan=4, sticky="w", pady=6)
        ttk.Button(btns, text="Read values from camera", command=self._read_from_camera).pack(side="left")
        ttk.Button(btns, text="Webcam driver dialog (DSHOW)",
                   command=lambda: self.cam.request("dialog")).pack(side="left", padx=6)
        ttk.Label(f, text="Tip: for a clean effect set Auto exposure + Auto white balance = Off, "
                          "then capture the background (B).", foreground="#777").grid(
            row=4, column=0, columnspan=4, sticky="w")

    def _build_effect(self, f):
        eff, disp = self.cfg["effect"], self.cfg["display"]
        row = 0

        def section(title):
            nonlocal row
            ttk.Label(f, text=title, font=("TkDefaultFont", 9, "bold")).grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(8, 2))
            row += 1

        def scale(label, d, key, lo, hi, res, on_release=False):
            nonlocal row
            var = tk.DoubleVar(value=d[key])
            ttk.Label(f, text=label, width=24).grid(row=row, column=0, sticky="w")
            cast = int if res >= 1 else float

            def setv(*_):
                d[key] = cast(var.get())
            s = tk.Scale(f, from_=lo, to=hi, resolution=res, orient="horizontal", length=300,
                         variable=var, command=None if on_release else setv)
            if on_release:  # heavy change (rebuilds a model): apply when mouse is released
                s.bind("<ButtonRelease-1>", setv)
            s.grid(row=row, column=1, sticky="w")
            row += 1

        def combo(label, d, key, values):
            nonlocal row
            var = tk.StringVar(value=d[key])
            ttk.Label(f, text=label, width=24).grid(row=row, column=0, sticky="w")
            cb = ttk.Combobox(f, values=values, textvariable=var, state="readonly", width=30)
            cb.bind("<<ComboboxSelected>>", lambda e: d.__setitem__(key, var.get()))
            cb.grid(row=row, column=1, sticky="w")
            row += 1

        def check(label, d, key):
            nonlocal row
            var = tk.BooleanVar(value=d[key])
            ttk.Checkbutton(f, text=label, variable=var,
                            command=lambda: d.__setitem__(key, bool(var.get()))).grid(
                row=row, column=0, columnspan=2, sticky="w")
            row += 1

        section("Hand / pinch")
        combo("Control hand", eff, "hand", ["Right", "Left", "Any"])
        scale("Touch when ratio <", eff, "pinch_on", 0.05, 1.0, 0.01)
        scale("Release when ratio >", eff, "pinch_off", 0.05, 1.5, 0.01)
        self._labels["pinch"] = ttk.Label(f, text="Current ratio: -", foreground="#2266aa")
        self._labels["pinch"].grid(row=row, column=1, sticky="w")
        row += 1
        combo("When hand is lost", eff, "hand_lost", ["Show person", "Keep state"])
        scale("Hand lost delay (s)", eff, "hand_lost_grace", 0.0, 2.0, 0.05)
        scale("Hand detection confidence", eff, "min_hand_conf", 0.1, 0.9, 0.05, on_release=True)

        section("Fade")
        scale("Fade time (s)", eff, "fade_time", 0.0, 2.0, 0.05)

        section("Person mask")
        combo("Segmentation model", eff, "seg_model", list(C.SEG_MODELS))
        scale("Mask low (bg below)", eff, "mask_low", 0.0, 1.0, 0.01)
        scale("Mask high (person above)", eff, "mask_high", 0.0, 1.0, 0.01)
        scale("Grow mask (px)", eff, "mask_dilate", 0, 40, 1)
        scale("Soft edge (px)", eff, "mask_feather", 0, 40, 1)
        scale("Temporal smoothing", eff, "mask_smooth", 0.0, 0.95, 0.05)
        check("Invert mask (only if the wrong area disappears)", eff, "invert_mask")

        section("Background capture (key B)")
        scale("Countdown (s)", eff, "bg_countdown", 0, 10, 1)
        scale("Frames to average", eff, "bg_frames", 1, 60, 1)

        section("Display")
        check("Mirror (selfie view)", disp, "mirror")
        check("Show hand skeleton", eff, "show_skeleton")

    # ------------------------------------------------------------ actions
    def _apply_stream(self):
        cam = self.cfg["camera"]
        try:
            w, h = (int(x) for x in self.v_res.get().lower().split("x"))
            cam["width"], cam["height"] = w, h
            cam["fps"] = int(float(self.v_fps.get()))
            cam["index"] = int(self.v_index.get())
        except ValueError:
            print("[settings] bad resolution / fps / index")
            return
        cam["backend"] = self.v_backend.get()
        cam["fourcc"] = self.v_fourcc.get()
        self.cam.request("reopen")

    def _set_auto(self, key, choice):
        item = self.cfg["camera"]["auto"][key]
        item["apply"] = choice != "(camera default)"
        item["value"] = choice == "On"
        self.cam.request("set_auto", key)

    def _prop_changed(self, key):
        v_apply, v_val = self.prop_vars[key]
        item = self.cfg["camera"]["props"][key]
        item["apply"] = bool(v_apply.get())
        item["value"] = float(v_val.get())
        if item["apply"]:
            self.cam.request("set_prop", key)

    def _sync_unset_sliders(self):
        if not self.is_open():
            return
        for key, (v_apply, v_val) in self.prop_vars.items():
            val = self.cam.actual.get(key)
            if not v_apply.get() and val is not None and val != -1:
                v_val.set(val)
                self.cfg["camera"]["props"][key]["value"] = float(val)

    def _read_from_camera(self):
        for key, (v_apply, v_val) in self.prop_vars.items():
            val = self.cam.actual.get(key)
            if val is not None and val != -1:
                v_val.set(val)
                self.cfg["camera"]["props"][key]["value"] = float(val)

    def _reset(self):
        fresh = C.defaults()
        self.cfg.clear()
        self.cfg.update(fresh)
        self.cam.request("reopen")
        self.close()
        self.open()

    # ------------------------------------------------------------ live update
    def tick(self):
        """Called every frame from the main loop; refresh live labels ~5x/second."""
        if not self.is_open():
            return
        self._tick_n += 1
        if self._tick_n % 6:
            return
        try:
            fps = self.cam.cam_fps
            self._labels["info"].config(text=f"{self.cam.info}   |   measured: {fps:.1f} fps")
            for key in C.CAMERA_PROPS:
                v = self.cam.actual.get(key)
                txt = "cam: n/a" if v is None or v == -1 else f"cam: {v:g}"
                self._labels["prop_" + key].config(text=txt)
            r = self.state.get("pinch_ratio")
            self._labels["pinch"].config(
                text="Current ratio: no hand" if r is None else f"Current ratio: {r:.2f}"
                + ("   (TOUCHING)" if self.state.get("touching") else ""))
        except tk.TclError:
            pass
