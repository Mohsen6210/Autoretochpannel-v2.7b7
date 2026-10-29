import os
import sys
import threading
import traceback
import tempfile
import webbrowser
import colorsys
import tkinter as tk
from tkinter import filedialog, messagebox

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import cv2
import numpy as np
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk, ImageOps

import engine as E

Image.MAX_IMAGE_PIXELS = None
LOG_PATH = os.path.join(tempfile.gettempdir(), "AutoRetouch_error.log")
PREVIEW_MAX = 2000
ANALYSIS_MAX = 2400
DB_RANGE = 14.0          # L units reached at full dodge / burn strength
ACTIVE = "#1f6aa5"
IDLE = "#3a3a3a"
CONTACT_NAME = "[ MohsenPourjam / 09132067843 ]"
CONTACT_MAIL = "pouryaphotography@gmail.com"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def log_error(text):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


def load_image(path):
    pil = Image.open(path)
    icc = pil.info.get("icc_profile")
    pil = ImageOps.exif_transpose(pil)  # applies the camera rotation
    exif = None
    try:
        ex = pil.getexif()
        if ex:
            ex[0x0112] = 1
            exif = ex.tobytes()
    except Exception:
        exif = None
    pil = pil.convert("RGB")
    bgr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return bgr, icc, exif


def make_icon(kind, size=22):
    """Small Photoshop-style tool icons drawn with PIL (no external files)."""
    S = 88
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = (236, 236, 236, 255)
    if kind == "move":
        cx = cy = S // 2
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            d.line([cx, cy, cx + dx * 32, cy + dy * 32], fill=c, width=7)
            tip = (cx + dx * 42, cy + dy * 42)
            pts = [tip, (cx + dx * 28, cy - 12), (cx + dx * 28, cy + 12)] if dx else \
                  [tip, (cx - 12, cy + dy * 28), (cx + 12, cy + dy * 28)]
            d.polygon(pts, fill=c)
    elif kind == "brush":
        d.line([(70, 12), (36, 46)], fill=c, width=13)
        d.polygon([(34, 44), (46, 56), (30, 74), (14, 74), (12, 62)], fill=c)
    elif kind == "quick":
        for a in range(0, 360, 50):
            d.arc([8, 24, 58, 74], a, a + 28, fill=c, width=6)
        d.line([(46, 48), (76, 10)], fill=c, width=8)
        d.ellipse([66, 4, 82, 20], fill=c)
    elif kind == "lasso":
        d.arc([8, 12, 74, 56], 20, 330, fill=c, width=7)
        d.line([(24, 52), (18, 72), (34, 80)], fill=c, width=6)
    elif kind == "eraser":
        d.polygon([(10, 56), (44, 14), (78, 36), (44, 78)], outline=c, width=6)
        d.polygon([(10, 56), (30, 34), (62, 56), (44, 78)], fill=c)
    elif kind == "history":
        d.arc([10, 14, 70, 74], 40, 330, fill=c, width=8)
        d.polygon([(66, 6), (84, 30), (56, 34)], fill=c)
        d.line([(40, 30), (40, 46), (54, 54)], fill=c, width=7)
    elif kind == "dodge":
        d.ellipse([12, 10, 58, 56], fill=c)
        d.line([(50, 50), (76, 78)], fill=c, width=12)
    elif kind == "burn":
        d.rounded_rectangle([22, 40, 66, 78], radius=10, fill=c)
        for i, x in enumerate((24, 36, 48, 60)):
            d.rounded_rectangle([x, 8 + (i in (0, 3)) * 8, x + 9, 46], radius=4, fill=c)
        d.polygon([(22, 56), (6, 40), (14, 34), (26, 46)], fill=c)
    im = im.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=im, dark_image=im, size=(size, size))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Auto Retouch - Smart Dodge & Burn")
        self.geometry("1460x880")
        self.minsize(1000, 640)
        self._reset_state()

        self._results = []
        self._rc_running = False
        self._rc_pending = False
        self._rc_after = None
        self._comp_after = None
        self._hair_after = None
        self._busy = False
        self.mode = "auto"
        self.view = "preview"
        self.tool = "move"
        self.space = False
        self._photo = None

        self._build_ui()
        self._bind_keys()
        self.after(80, self._poll)

    def _reset_state(self):
        self.path = self.full = self.icc = self.exif = None
        self.A = self.an = self.P = self.P_rgb = self.lab_P = self.lab8s = None
        self.fp_P = 100.0
        self.mask = self.mask_eff = self.maps = self.spots = self.forbid = None
        self.bbox = self.spot_bbox = None
        self.result_rgb = self.disp = None
        self.undo = []
        self.D = self.R = None
        self.db_bbox = self.rs_bbox = None
        self.zoom, self.tx, self.ty = 1.0, 0.0, 0.0
        self.auto_fit = True
        self._pan_last = self._last_pt = self._qlast = None
        self._painting = False
        self._lasso = []

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(6, 3))
        ctk.CTkButton(top, text="Open", width=70, command=self.open_dialog).pack(side="left", padx=(6, 10), pady=6)
        self.btn_view = {}
        for key, text in (("original", "Original"), ("preview", "Preview"), ("mask", "Mask")):
            b = ctk.CTkButton(top, text=text, width=80, fg_color=IDLE, command=lambda k=key: self.set_view(k))
            b.pack(side="left", padx=2)
            self.btn_view[key] = b
        ctk.CTkButton(top, text="Reset (R)", width=80, fg_color=IDLE, command=self.reset_sliders).pack(side="left", padx=(16, 2))
        ctk.CTkButton(top, text="Close image", width=90, fg_color="#7a2f2f", hover_color="#964040",
                      command=self.close_image).pack(side="left", padx=2)

        sf = ctk.CTkFrame(self)
        sf.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=3)
        self.sl = {}
        for key, text, lo, hi, init in (("warmth", "Warmth", -50, 50, 0), ("blend", "Blend", 0, 100, 100),
                                        ("strength", "Strength", 0, 200, 100), ("texture", "Texture", 0, 200, 100),
                                        ("spots", "Spots", 0, 100, 0)):
            f = ctk.CTkFrame(sf, fg_color="transparent")
            f.pack(side="left", padx=(4, 0), pady=4)
            lab = ctk.CTkLabel(f, text=f"{text}: {init}", width=92, anchor="w", font=ctk.CTkFont(size=12))
            lab.pack(side="left")
            s = ctk.CTkSlider(f, from_=lo, to=hi, number_of_steps=hi - lo, width=100,
                              command=lambda v, k=key: self._on_slider(k))
            s.set(init)
            s.pack(side="left")
            self.sl[key] = (s, lab, text)

        # ---- left panel: tools ----
        left = ctk.CTkScrollableFrame(self, width=150)
        left.grid(row=2, column=0, sticky="ns", padx=(6, 3), pady=3)
        self.btn_tool = {}

        def tool_btn(key, text, icon):
            b = ctk.CTkButton(left, text=text, image=make_icon(icon), compound="left", anchor="w", width=136,
                              height=30, fg_color=IDLE, command=lambda k=key: self.set_tool(k))
            b.pack(padx=2, pady=2)
            self.btn_tool[key] = b

        tool_btn("move", "Move  (V)", "move")
        ctk.CTkLabel(left, text="Mask tools", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#6fb1e6").pack(anchor="w", padx=4, pady=(8, 0))
        tool_btn("brush", "Brush Tool  (B)", "brush")
        tool_btn("quick", "Quick Select  (W)", "quick")
        tool_btn("lasso", "Lasso Tool  (L)", "lasso")
        tool_btn("eraser", "Eraser Tool  (E)", "eraser")
        tool_btn("history", "History Brush  (Y)", "history")
        ctk.CTkLabel(left, text="Light tools", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#6fb1e6").pack(anchor="w", padx=4, pady=(8, 0))
        tool_btn("dodge", "Dodge Tool  (1)", "dodge")
        tool_btn("burn", "Burn Tool  (2)", "burn")
        self.sel = ctk.CTkSegmentedButton(left, values=["Add", "Subtract"], width=136)
        self.sel.set("Add")
        self.sel.pack(padx=2, pady=(8, 2))
        ctk.CTkLabel(left, text="Add / Subtract: Quick Selection, Lasso", font=ctk.CTkFont(size=10),
                     text_color="#8a8a8a", wraplength=130, justify="left").pack(padx=4)
        for text, cmd in (("Invert mask (I)", self.invert_mask), ("Undo (Ctrl+Z)", self.undo_mask),
                          ("Re-detect", lambda: self.set_mode(self.mode)), ("Clear D&B", self.clear_db),
                          ("Clear history brush", self.clear_rest)):
            ctk.CTkButton(left, text=text, width=136, height=26, fg_color=IDLE, command=cmd).pack(padx=2, pady=(2, 0))

        def side_slider(text, lo, hi, init, cb=None):
            lab = ctk.CTkLabel(left, text=f"{text}: {init}", font=ctk.CTkFont(size=12))
            lab.pack(pady=(8, 0))
            sl = ctk.CTkSlider(left, from_=lo, to=hi, number_of_steps=hi - lo, width=120,
                               command=lambda v: (lab.configure(text=f"{text}: {int(v)}"), cb() if cb else None))
            sl.set(init)
            sl.pack(padx=2, pady=2)
            return sl

        self.brush = side_slider("Brush size (px)", 5, 1000, 150)
        self.hard = side_slider("Hardness", 0, 100, 40)
        self.opac = side_slider("Brush opacity", 5, 100, 100)
        self.dodge_exp = side_slider("Dodge exposure", 1, 100, 40)
        self.burn_exp = side_slider("Burn exposure", 1, 100, 40)
        self.dbamt = side_slider("D&B layer %", 0, 200, 100, cb=self._db_changed)
        self.fth = side_slider("Mask feather (px)", 0, 80, 20, cb=self._feather_changed)
        self.mlight = side_slider("Mask light", -100, 100, 0, cb=self._db_changed)
        self.hair = side_slider("Hair / beard protect", 0, 100, 60, cb=self._hair_changed)
        self.tol = side_slider("Select tolerance", 2, 40, 14)
        self.db_limit = ctk.CTkCheckBox(left, text="D&B on skin mask only", command=self._db_changed,
                                        font=ctk.CTkFont(size=11))
        self.db_limit.pack(padx=4, pady=(10, 2), anchor="w")
        ctk.CTkButton(left, text="Shortcuts", width=136, height=26, fg_color=IDLE,
                      command=self.show_shortcuts).pack(padx=2, pady=(6, 4))

        # ---- right panel: whole-image adjustments ----
        right = ctk.CTkScrollableFrame(self, width=250, label_text="Adjust (whole image)")
        right.grid(row=2, column=2, sticky="ns", padx=(3, 6), pady=3)
        self.adj_limit = ctk.CTkCheckBox(right, text="Only on skin mask", command=self._composite, font=ctk.CTkFont(size=11))
        self.adj_limit.pack(anchor="w", padx=4, pady=(2, 2))
        ctk.CTkButton(right, text="Reset adjustments", fg_color=IDLE, command=self.reset_adjust).pack(padx=4, pady=(2, 4))
        self.adj, self.adj_var, self.adj_sec, self.sec_on = {}, {}, {}, {}
        blue_yellow = [(45, 60, 200), (120, 120, 120), (232, 220, 40)]
        green_magenta = [(40, 170, 60), (120, 120, 120), (190, 40, 170)]
        rainbow = [tuple(int(255 * c) for c in colorsys.hsv_to_rgb(h / 6.0, 0.8, 0.95)) for h in range(7)]
        sections = (
            ("Light", (("brightness", "Exposure", None), ("contrast", "Contrast", None),
                       ("highlights", "Highlights", None), ("shadows", "Shadows", None),
                       ("whites", "Whites", None), ("blacks", "Blacks", None))),
            ("Color", (("temp", "Temperature", blue_yellow), ("tint", "Tint", green_magenta),
                       ("hue", "Hue", rainbow), ("vib", "Vibrance", None), ("sat", "Saturation", None),
                       ("red", "Red", None), ("green", "Green", None), ("blue", "Blue", None))),
            ("Detail", (("sharpen", "Sharpen", None), ("blur", "Blur", None))),
        )
        for title, items in sections:
            body = self._make_section(right, title)
            for key, text, grad in items:
                self._make_adj_row(body, key, text, 0 if key == "blur" else -100, 100, grad, title)

        self.canvas = tk.Canvas(self, bg="#1c1c1c", highlightthickness=0, cursor="fleur")
        self.canvas.grid(row=2, column=1, sticky="nsew", pady=3)

        bottom = ctk.CTkFrame(self)
        bottom.grid(row=3, column=0, columnspan=3, sticky="ew", padx=6, pady=3)
        self.btn_mode = {}
        for key, text in (("auto", "Auto"), ("face", "Face"), ("half", "Half-body"), ("full", "Full-body")):
            b = ctk.CTkButton(bottom, text=text, width=84, fg_color=IDLE, command=lambda k=key: self.set_mode(k))
            b.pack(side="left", padx=2, pady=6)
            self.btn_mode[key] = b
        zf = ctk.CTkFrame(bottom, fg_color="transparent")
        zf.pack(side="left", expand=True)
        ctk.CTkButton(zf, text="-", width=36, command=lambda: self.zoom_by(1 / 1.25)).pack(side="left", padx=2)
        self.zoom_lab = ctk.CTkLabel(zf, text="100%", width=60)
        self.zoom_lab.pack(side="left")
        ctk.CTkButton(zf, text="+", width=36, command=lambda: self.zoom_by(1.25)).pack(side="left", padx=2)
        ctk.CTkButton(zf, text="Fit", width=46, fg_color=IDLE, command=self.fit).pack(side="left", padx=(10, 2))
        ctk.CTkButton(zf, text="100%", width=50, fg_color=IDLE, command=self.zoom_actual).pack(side="left", padx=2)
        ctk.CTkButton(bottom, text="Exit", width=70, fg_color=IDLE, command=self.destroy).pack(side="right", padx=(2, 6))
        ctk.CTkButton(bottom, text="Save As", width=80, command=lambda: self.save(True)).pack(side="right", padx=2)
        self.btn_save = ctk.CTkButton(bottom, text="Save", width=80, command=lambda: self.save(False))
        self.btn_save.pack(side="right", padx=2)

        self.status = ctk.CTkLabel(self, text="Open a portrait to start.", anchor="w")
        self.status.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 5))
        cf = ctk.CTkFrame(self, fg_color="transparent")
        cf.grid(row=4, column=2, sticky="e", padx=(0, 10), pady=(0, 4))
        ctk.CTkLabel(cf, text=CONTACT_NAME, font=ctk.CTkFont(size=11), text_color="#9fb7d1").pack(anchor="e")
        em = ctk.CTkLabel(cf, text="contact : " + CONTACT_MAIL, font=ctk.CTkFont(size=11, underline=True),
                          text_color="#6fb1e6")
        em.pack(anchor="e")
        try:
            em.configure(cursor="hand2")
        except Exception:
            pass
        em.bind("<Button-1>", lambda e: webbrowser.open("mailto:" + CONTACT_MAIL))

        c = self.canvas
        c.bind("<Configure>", self._on_resize)
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        for b in ("2", "3"):
            c.bind(f"<ButtonPress-{b}>", self._pan_start)
            c.bind(f"<B{b}-Motion>", self._pan_move)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Button-4>", lambda e: self._wheel_zoom(e, 1.15))
        c.bind("<Button-5>", lambda e: self._wheel_zoom(e, 1 / 1.15))
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", lambda e: c.delete("cur"))
        self._refresh_buttons()

    # ---- adjust-panel widgets ----
    def _make_section(self, parent, title):
        hdr = ctk.CTkFrame(parent, fg_color="#3a3a3a", corner_radius=4)
        hdr.pack(fill="x", pady=(8, 0))
        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.pack(fill="x")
        self.sec_on[title] = True
        state = {"open": True}

        def toggle_open():
            state["open"] = not state["open"]
            chev.configure(text=("v  " if state["open"] else ">  ") + title)
            if state["open"]:
                body.pack(fill="x", after=hdr)
            else:
                body.pack_forget()

        def toggle_eye():
            self.sec_on[title] = not self.sec_on[title]
            eye.configure(text="(o)" if self.sec_on[title] else "( )")
            self._composite()

        chev = ctk.CTkButton(hdr, text="v  " + title, anchor="w", width=170, height=26, fg_color="transparent",
                             hover_color="#4a4a4a", font=ctk.CTkFont(size=13, weight="bold"), command=toggle_open)
        chev.pack(side="left")
        eye = ctk.CTkButton(hdr, text="(o)", width=40, height=26, fg_color="transparent", hover_color="#4a4a4a",
                            command=toggle_eye)
        eye.pack(side="right")
        return body

    def _make_adj_row(self, parent, key, text, lo, hi, grad, section):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=(5, 0))
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        lab = ctk.CTkLabel(top, text=text, anchor="w", font=ctk.CTkFont(size=12))
        lab.pack(side="left")
        var = tk.StringVar(value="0")
        ent = ctk.CTkEntry(top, width=54, height=24, textvariable=var, justify="center", font=ctk.CTkFont(size=12))
        ent.pack(side="right")
        inner = ent._entry  # typing must not trigger the app shortcuts
        inner.bindtags((str(inner), "Entry"))
        if grad:
            strip = tk.Canvas(row, height=5, width=200, highlightthickness=0, bg="#2b2b2b")
            strip.pack(fill="x", pady=(3, 0))

            def draw(e=None, strip=strip, grad=grad):
                w = max(40, strip.winfo_width())
                strip.delete("all")
                n = 60
                for i in range(n):
                    t = i / (n - 1) * (len(grad) - 1)
                    a, b = int(t), min(int(t) + 1, len(grad) - 1)
                    f = t - a
                    c = tuple(int(grad[a][k] + (grad[b][k] - grad[a][k]) * f) for k in range(3))
                    strip.create_rectangle(i * w / n, 0, (i + 1) * w / n + 1, 6, fill="#%02x%02x%02x" % c, outline="")

            strip.bind("<Configure>", draw)
        sl = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=hi - lo, width=200,
                           command=lambda v, k=key: self._adj_changed(k))
        sl.set(0)
        sl.pack(fill="x", pady=(1, 2))
        ent.bind("<Return>", lambda e, k=key: self._adj_entry(k))
        ent.bind("<FocusOut>", lambda e, k=key: self._adj_entry(k))
        lab.bind("<Double-Button-1>", lambda e, k=key: self._adj_set(k, 0))
        self.adj[key], self.adj_var[key], self.adj_sec[key] = (sl, lab, text), var, section

    def _adj_set(self, key, v):
        sl = self.adj[key][0]
        v = int(max(sl.cget("from_"), min(sl.cget("to"), v)))
        sl.set(v)
        self.adj_var[key].set(str(v))
        self._adj_changed(key)

    def _adj_entry(self, key):
        try:
            v = int(round(float(self.adj_var[key].get().replace(",", "."))))
        except ValueError:
            v = int(self.adj[key][0].get())
        self._adj_set(key, v)
        self.canvas.focus_set()

    def _adj_changed(self, key):
        sl, lab, text = self.adj[key]
        self.adj_var[key].set(str(int(sl.get())))
        self._schedule_composite(50)

    def reset_adjust(self):
        for k, (sl, lab, text) in self.adj.items():
            sl.set(0)
            self.adj_var[k].set("0")
        self._composite()

    # ------------------------------------------------------------ keys etc.
    def _bind_keys(self):
        self.bind("<Control-z>", lambda e: self.undo_mask())
        self.bind_all("<KeyPress-space>", self._space_down)
        self.bind_all("<KeyRelease-space>", self._space_up)
        self.bind("<KeyPress-r>", lambda e: self.reset_sliders())
        self.bind("<Control-Key-1>", lambda e: self.zoom_actual())
        self.bind("<KeyPress-bracketleft>", lambda e: self._size_step(0.85))
        self.bind("<KeyPress-bracketright>", lambda e: self._size_step(1.18))
        for k, f in (("v", lambda: self.set_tool("move")), ("b", lambda: self.set_tool("brush")),
                     ("w", lambda: self.set_tool("quick")), ("l", lambda: self.set_tool("lasso")),
                     ("e", lambda: self.set_tool("eraser")), ("y", lambda: self.set_tool("history")),
                     ("1", lambda: self.set_tool("dodge")), ("2", lambda: self.set_tool("burn")),
                     ("i", self.invert_mask), ("0", self.fit),
                     ("plus", lambda: self.zoom_by(1.25)), ("equal", lambda: self.zoom_by(1.25)),
                     ("minus", lambda: self.zoom_by(1 / 1.25))):
            self.bind(f"<KeyPress-{k}>", lambda e, f=f: f())

    def show_shortcuts(self):
        messagebox.showinfo("Shortcuts", "V Move   B Brush   W Quick Selection   L Lasso   E Eraser\n"
                            "Y History Brush   1 Dodge   2 Burn   I Invert mask\n"
                            "[ ] brush size   R reset sliders   0 Fit   Ctrl+1 actual pixels\n"
                            "Space + drag: pan   Wheel: zoom   Right-drag: pan\n"
                            "Ctrl+Z undo   Ctrl+click Brush/Eraser: fill / clear mask\n"
                            "Double-click a slider name in Adjust: reset it")

    def _space_down(self, e):
        self.space = True
        self.canvas.configure(cursor="fleur")
        return "break"

    def _space_up(self, e):
        self.space = False
        self._refresh_buttons()
        return "break"

    def _size_step(self, f):
        self.brush.set(float(np.clip(self.brush.get() * f, 5, 1000)))

    def report_callback_exception(self, exc, val, tb):
        err = "".join(traceback.format_exception(exc, val, tb))
        log_error(err)
        messagebox.showerror("Unexpected error", err[-900:])

    def _refresh_buttons(self):
        for k, b in self.btn_view.items():
            b.configure(fg_color=ACTIVE if k == self.view else IDLE)
        for k, b in self.btn_tool.items():
            b.configure(fg_color=ACTIVE if k == self.tool else IDLE)
        for k, b in self.btn_mode.items():
            b.configure(fg_color=ACTIVE if k == self.mode else IDLE)
        self.canvas.configure(cursor="fleur" if self.tool == "move" else "crosshair")

    def set_status(self, t):
        self.status.configure(text=t)

    def reset_sliders(self):
        for k, v in (("warmth", 0), ("blend", 100), ("strength", 100), ("texture", 100), ("spots", 0)):
            self.sl[k][0].set(v)
            self.sl[k][1].configure(text=f"{self.sl[k][2]}: {v}")
        self._composite()

    # ------------------------------------------------------------ open/close
    def open_dialog(self):
        if self._busy:
            return
        p = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp")])
        if p:
            self.open_path(p)

    def close_image(self):
        """Close the current photo but keep the program open."""
        if self._busy:
            return
        self._reset_state()
        self.canvas.delete("all")
        self.zoom_lab.configure(text="100%")
        self.set_status("Image closed. Open a portrait to start.")

    def open_path(self, p):
        try:
            self.set_status("Loading image...")
            self.update_idletasks()
            full, icc, exif = load_image(p)
        except Exception:
            err = traceback.format_exc()
            log_error(err)
            messagebox.showerror("Cannot open image", err[-700:])
            return
        self._reset_state()
        self.path, self.full, self.icc, self.exif = p, full, icc, exif
        self.P = E.resize_max(full, PREVIEW_MAX)
        self.P_rgb = cv2.cvtColor(self.P, cv2.COLOR_BGR2RGB)
        self.lab_P = cv2.cvtColor(self.P.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
        self.lab8s = np.ascontiguousarray(cv2.GaussianBlur(cv2.cvtColor(self.P, cv2.COLOR_BGR2LAB), (0, 0),
                                                           max(1.5, max(self.P.shape[:2]) / 900.0)))
        self.A = E.resize_max(full, ANALYSIS_MAX)
        ph, pw = self.P.shape[:2]
        self.mask = np.zeros((ph, pw), np.float32)
        self.mask_eff = self.mask.copy()
        self.D = np.zeros((ph, pw), np.float32)
        self.R = np.zeros((ph, pw), np.float32)
        self.view = "original"
        self._refresh_buttons()
        self._update_disp()
        self.fit()
        self.set_status("Detecting faces... (first run takes a few seconds)")
        A, mode, hair = self.A, self.mode, self.hair.get() / 100.0

        def work():
            try:
                an = E.analyze(A)
                m, info = E.build_mask(an, mode, hair)
                self._results.append(("analysis", an, m, info, A.shape))
            except Exception:
                self._results.append(("error", traceback.format_exc()))

        threading.Thread(target=work, daemon=True).start()

    def set_mode(self, mode):
        self.mode = mode
        self._refresh_buttons()
        if self.an is None or self._busy:
            return
        self.set_status("Rebuilding mask...")
        an, hair = self.an, self.hair.get() / 100.0

        def work():
            try:
                m, info = E.build_mask(an, mode, hair)
                self._results.append(("mode", m, info, an.shape))
            except Exception:
                self._results.append(("error", traceback.format_exc()))

        threading.Thread(target=work, daemon=True).start()

    def _hair_changed(self):
        if self._hair_after:
            self.after_cancel(self._hair_after)
        self._hair_after = self.after(600, lambda: self.set_mode(self.mode))

    # --------------------------------------------------------- bg results
    def _poll(self):
        while self._results:
            r = self._results.pop(0)
            try:
                self._handle(r)
            except Exception:
                err = traceback.format_exc()
                log_error(err)
                messagebox.showerror("Error", err[-800:])
        self.after(80, self._poll)

    def _handle(self, r):
        kind = r[0]
        if kind in ("analysis", "mode", "maps") and self.P is None:
            self._rc_running = False
            return
        if kind == "analysis":
            if r[4] != self.A.shape:
                return
            self.an = r[1]
            self.forbid = E.forbid_mask(self.an, self.P.shape[:2]) if self.an.faces else None
            self._apply_mask_result(r[2], r[3], first=True)
        elif kind == "mode":
            if r[3] != self.an.shape:
                return
            self._apply_mask_result(r[1], r[2], first=False)
        elif kind == "maps":
            self._rc_running = False
            if r[1].shape[:2] != self.P.shape[:2]:
                return
            self.maps, self.spots = r[1], r[2]
            ys, xs = np.where(self.maps[..., 0] > 0.002)
            self.bbox = (ys.min(), ys.max() + 1, xs.min(), xs.max() + 1) if len(ys) else None
            sy, sx = np.where(np.abs(self.spots).sum(axis=2) > 1e-3)
            self.spot_bbox = (sy.min(), sy.max() + 1, sx.min(), sx.max() + 1) if len(sy) else None
            self._composite()
            if self._rc_pending:
                self._rc_pending = False
                self._start_recompute()
        elif kind == "progress":
            self.set_status(f"Saving... {int(r[1] * 100)}%")
        elif kind == "saved":
            self._busy = False
            self.btn_save.configure(state="normal")
            self.set_status(f"Saved: {r[1]}")
            messagebox.showinfo("Saved", f"Saved to:\n{r[1]}")
        elif kind == "error":
            self._busy = False
            self._rc_running = False
            self.btn_save.configure(state="normal")
            log_error(r[1])
            self.set_status("An error occurred")
            messagebox.showerror("Error", r[1][-900:])

    def _apply_mask_result(self, mask_A, info, first):
        Ph, Pw = self.P.shape[:2]
        self.mask = cv2.resize(mask_A, (Pw, Ph), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        if self.an is not None and self.an.faces:
            self.fp_P = self.an.med_face_px * Ph / self.A.shape[0]
        else:
            self.fp_P = 0.25 * Ph
        self.undo = []
        names = {"face": "close-up", "half": "half-body", "full": "full-body"}
        if info["faces"] == 0:
            self.set_status("No face found. Paint skin with the Brush / Quick Selection, or press Invert to select everything.")
        else:
            warn = "" if info["mesh"] == info["faces"] else f" ({info['faces'] - info['mesh']} approximate)"
            self.set_status(f"{info['faces']} face(s){warn} - mode: {names.get(info['mode'], info['mode'])}. "
                            f"Check the Mask view; fix it with Brush / Eraser / Lasso / Quick Selection.")
        if first:
            self.view = "preview"
            self._refresh_buttons()
        self._mask_changed()

    # ------------------------------------------------------ mask editing
    def _mask_changed(self):
        self.mask_eff = E.feather(self.mask, self.fth.get(), max(self.mask.shape))
        self._schedule_recompute()
        self._update_disp()
        self._render()

    def _feather_changed(self):
        if self.mask is not None:
            self._mask_changed()

    def _schedule_recompute(self, delay=150):
        if self._rc_after:
            self.after_cancel(self._rc_after)
        self._rc_after = self.after(delay, self._start_recompute)

    def _start_recompute(self):
        self._rc_after = None
        if self.P is None:
            return
        if self._rc_running:
            self._rc_pending = True
            return
        self._rc_running = True
        me, lab, fp, Pbgr, forbid = self.mask_eff.copy(), self.lab_P, self.fp_P, self.P, self.forbid

        def work():
            try:
                dL, da, db = E.compute_delta(lab, me, fp)
                spots = E.compute_spots(Pbgr, lab, me, fp, forbid)
                self._results.append(("maps", np.dstack([me, dL, da, db]).astype(np.float32), spots))
            except Exception:
                self._results.append(("error", traceback.format_exc()))

        threading.Thread(target=work, daemon=True).start()

    def push_undo(self, kind="mask"):
        if self.P is None:
            return
        if kind == "db":
            snap = np.round(np.clip(self.D, -1, 1) * 127).astype(np.int8)
        elif kind == "rs":
            snap = (np.clip(self.R, 0, 1) * 255).astype(np.uint8)
        else:
            snap = (np.clip(self.mask, 0, 1) * 255).astype(np.uint8)
        self.undo.append((kind, snap))
        if len(self.undo) > 15:
            self.undo.pop(0)

    def undo_mask(self):
        if not self.undo or self.P is None:
            return
        kind, arr = self.undo.pop()
        full = (0, arr.shape[0], 0, arr.shape[1])
        if kind == "db":
            self.D = arr.astype(np.float32) / 127.0
            self.db_bbox = full if np.any(arr) else None
            self._db_changed()
        elif kind == "rs":
            self.R = arr.astype(np.float32) / 255.0
            self.rs_bbox = full if np.any(arr) else None
            self._db_changed()
        else:
            self.mask = arr.astype(np.float32) / 255.0
            self._mask_changed()

    def invert_mask(self):
        if self.mask is None:
            return
        self.push_undo()
        self.mask = 1.0 - self.mask
        self._mask_changed()

    def clear_db(self):
        if self.D is None or self.db_bbox is None:
            return
        self.push_undo("db")
        self.D[:] = 0
        self.db_bbox = None
        self._db_changed()

    def clear_rest(self):
        if self.R is None or self.rs_bbox is None:
            return
        self.push_undo("rs")
        self.R[:] = 0
        self.rs_bbox = None
        self._db_changed()

    def _db_changed(self):
        self._schedule_composite(40)

    def _schedule_composite(self, delay=50):
        if self._comp_after:
            self.after_cancel(self._comp_after)
        self._comp_after = self.after(delay, self._composite)

    # ------------------------------------------------------ view / render
    def set_view(self, v):
        self.view = v
        self._refresh_buttons()
        self._update_disp()
        self._render()

    def set_tool(self, t):
        self.tool = t
        if t != "move" and self.view == "original":
            self.view = "preview"
        if t in ("quick", "lasso") and self.view == "preview" and self.P is not None:
            self.view = "mask"  # you need to see the selection
        self._refresh_buttons()
        self._update_disp()
        self._render()

    def _on_slider(self, key):
        s, lab, text = self.sl[key]
        lab.configure(text=f"{text}: {int(s.get())}")
        self._schedule_composite(50)

    def _params(self):
        v = {k: self.sl[k][0].get() for k in self.sl}
        p = dict(blend=v["blend"] / 100.0, strength=v["strength"] / 100.0, warm=v["warmth"],
                 texture=v["texture"] / 100.0, spot=v["spots"] / 100.0, mask_light=self.mlight.get() / 100.0,
                 dbamt=self.dbamt.get() / 100.0, db_limit=bool(self.db_limit.get()),
                 adj_limit=bool(self.adj_limit.get()))
        for k, (sl, _l, _t) in self.adj.items():
            p[k] = sl.get() / 100.0 if self.sec_on.get(self.adj_sec[k], True) else 0.0
        return p

    def _scales(self, p):
        long_p = float(max(self.P.shape[:2]))
        return (max(0.8, self.fp_P / 260.0), max(0.6, long_p / 1800.0), p["blur"] * long_p / 80.0)

    def _region(self, p):
        Ph, Pw = self.P.shape[:2]
        if E.adj_active(p) and not p["adj_limit"]:
            return (0, Ph, 0, Pw)
        regs = []
        if self.maps is not None and self.bbox is not None:
            y0, y1, x0, x1 = self.bbox
            regs.append((max(0, y0 - 12), min(Ph, y1 + 12), max(0, x0 - 12), min(Pw, x1 + 12)))
        if self.spot_bbox is not None and p["spot"] > 0:
            regs.append(self.spot_bbox)
        if self.db_bbox is not None and p["dbamt"] > 0:
            regs.append(self.db_bbox)
        if self.rs_bbox is not None:
            regs.append(self.rs_bbox)
        if not regs:
            return None
        return (min(r[0] for r in regs), max(r[1] for r in regs), min(r[2] for r in regs), max(r[3] for r in regs))

    def _composite(self):
        self._comp_after = None
        if self.P is None:
            return
        out = self.P
        p = self._params()
        reg = self._region(p)
        if reg is not None:
            y0, y1, x0, x1 = reg
            sub = (slice(y0, y1), slice(x0, x1))
            maps = self.maps[sub] if self.maps is not None else np.zeros((y1 - y0, x1 - x0, 4), np.float32)
            db = self.D[sub] * (DB_RANGE * p["dbamt"]) if self.db_bbox is not None else None
            sp = self.spots[sub] if (self.spots is not None and p["spot"] > 0) else None
            rs = self.R[sub] if self.rs_bbox is not None else None
            out = self.P.copy()
            out[sub] = E.apply_maps(self.P[sub], maps, p, db=db, s=self._scales(p), spots=sp, rest=rs)
        self.result_rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        self._update_disp()
        self._render()

    def _update_disp(self):
        if self.P_rgb is None:
            self.disp = None
        elif self.view == "original":
            self.disp = self.P_rgb
        elif self.view == "mask":
            m = np.clip(self.mask_eff, 0, 1)[..., None] * 0.55   # what is really applied (feathered)
            red = np.array([255, 40, 40], np.float32)
            self.disp = (self.P_rgb * (1 - m) + red * m).astype(np.uint8)
        else:
            self.disp = self.result_rgb if self.result_rgb is not None else self.P_rgb

    def _render(self):
        c = self.canvas
        c.delete("img")
        if self.disp is None:
            return
        cw, ch = c.winfo_width(), c.winfo_height()
        H, W = self.disp.shape[:2]
        z = self.zoom
        x0 = max(0, int(np.floor(-self.tx / z)))
        y0 = max(0, int(np.floor(-self.ty / z)))
        x1 = min(W, int(np.ceil((cw - self.tx) / z)))
        y1 = min(H, int(np.ceil((ch - self.ty) / z)))
        if x1 <= x0 or y1 <= y0:
            return
        crop = self.disp[y0:y1, x0:x1]
        dw, dh = max(1, int(round((x1 - x0) * z))), max(1, int(round((y1 - y0) * z)))
        interp = cv2.INTER_AREA if z < 1 else (cv2.INTER_NEAREST if z >= 4 else cv2.INTER_LINEAR)
        pic = cv2.resize(crop, (dw, dh), interpolation=interp)
        self._photo = ImageTk.PhotoImage(Image.fromarray(pic))
        c.create_image(self.tx + x0 * z, self.ty + y0 * z, anchor="nw", image=self._photo, tags="img")
        c.tag_lower("img")
        self.zoom_lab.configure(text=f"{int(round(self._zoom_pct()))}%")

    def _zoom_pct(self):
        """Zoom relative to the FULL resolution photo (100% = one photo pixel per screen pixel)."""
        if self.full is None:
            return self.zoom * 100.0
        return self.zoom * self.P.shape[1] / self.full.shape[1] * 100.0

    def fit(self):
        if self.P is None:
            return
        cw, ch = max(50, self.canvas.winfo_width()), max(50, self.canvas.winfo_height())
        H, W = self.P.shape[:2]
        self.zoom = min(cw / W, ch / H) * 0.98
        self.tx = (cw - W * self.zoom) / 2
        self.ty = (ch - H * self.zoom) / 2
        self.auto_fit = True
        self._render()

    def zoom_actual(self):
        if self.P is not None:
            self.set_zoom(self.full.shape[1] / self.P.shape[1])

    def set_zoom(self, z, cx=None, cy=None):
        if self.P is None:
            return
        z = float(np.clip(z, 0.05, 16))
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        cx = cw / 2 if cx is None else cx
        cy = ch / 2 if cy is None else cy
        ix, iy = (cx - self.tx) / self.zoom, (cy - self.ty) / self.zoom
        self.zoom = z
        self.tx, self.ty = cx - ix * z, cy - iy * z
        self.auto_fit = False
        self._render()

    def zoom_by(self, f):
        self.set_zoom(self.zoom * f)

    def _on_wheel(self, e):
        self._wheel_zoom(e, 1.15 ** (e.delta / 120.0))

    def _wheel_zoom(self, e, f):
        self.set_zoom(self.zoom * f, e.x, e.y)

    def _on_resize(self, e):
        if self.auto_fit and self.P is not None:
            self.fit()
        else:
            self._render()

    # -------------------------------------------------------- mouse tools
    def _to_img(self, x, y):
        return (x - self.tx) / self.zoom, (y - self.ty) / self.zoom

    def _brush_r(self):
        """Brush radius in preview pixels. The slider is the brush DIAMETER in photo pixels."""
        return max(0.6, self.brush.get() / 2.0 * self.P.shape[1] / self.full.shape[1])

    def _pan_start(self, e):
        self._pan_last = (e.x, e.y)

    def _pan_move(self, e):
        if self._pan_last:
            self.tx += e.x - self._pan_last[0]
            self.ty += e.y - self._pan_last[1]
            self._pan_last = (e.x, e.y)
            self.auto_fit = False
            self._render()

    def _on_motion(self, e):
        self.canvas.delete("cur")
        if self.P is None:
            return
        if self.tool in ("brush", "eraser", "history", "dodge", "burn"):
            r = self._brush_r() * self.zoom
            col = "#ffb347" if self.tool == "burn" else "#ffffff"
            self.canvas.create_oval(e.x - r, e.y - r, e.x + r, e.y + r, outline=col, tags="cur")

    def _on_press(self, e):
        self.canvas.focus_set()
        if self.P is None:
            return
        if self.tool == "move" or self.space:
            self._pan_start(e)
            return
        x, y = self._to_img(e.x, e.y)
        t = self.tool
        ctrl = bool(e.state & 0x4)
        if t in ("dodge", "burn"):
            self.push_undo("db")
            self._painting, self._last_pt = True, (x, y)
            self._paint_db(x, y, x, y)
        elif t == "history":
            self.push_undo("rs")
            if ctrl:
                self.R[:] = 1.0
                self.rs_bbox = (0, self.R.shape[0], 0, self.R.shape[1])
                self._db_changed()
                return
            self._painting, self._last_pt = True, (x, y)
            self._paint_rest(x, y, x, y)
        elif t == "quick":
            self.push_undo()
            self._painting, self._qlast = True, (e.x, e.y)
            self._quick(x, y)
        elif t == "lasso":
            self.push_undo()
            self._painting, self._lasso = True, [(x, y)]
        elif t in ("brush", "eraser"):
            self.push_undo()
            val = 1.0 if t == "brush" else 0.0
            if ctrl:
                self.mask[:] = val
                self._mask_changed()
                return
            self._painting, self._last_pt = True, (x, y)
            self._paint_mask(x, y, x, y)

    def _on_drag(self, e):
        if self.P is None:
            return
        if self.tool == "move" or self.space:
            self._pan_move(e)
            return
        self._on_motion(e)
        if not self._painting:
            return
        x, y = self._to_img(e.x, e.y)
        t = self.tool
        if t in ("dodge", "burn"):
            self._paint_db(self._last_pt[0], self._last_pt[1], x, y)
            self._last_pt = (x, y)
        elif t == "history":
            self._paint_rest(self._last_pt[0], self._last_pt[1], x, y)
            self._last_pt = (x, y)
        elif t in ("brush", "eraser"):
            self._paint_mask(self._last_pt[0], self._last_pt[1], x, y)
            self._last_pt = (x, y)
        elif t == "quick":
            if np.hypot(e.x - self._qlast[0], e.y - self._qlast[1]) > 8:
                self._qlast = (e.x, e.y)
                self._quick(x, y)
        elif t == "lasso":
            self._lasso.append((x, y))
            pts = []
            for px, py in self._lasso:
                pts += [px * self.zoom + self.tx, py * self.zoom + self.ty]
            self.canvas.delete("lasso")
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill="#00e5ff", dash=(5, 3), width=1, tags="lasso")

    def _on_release(self, e):
        self._pan_last = None
        if self.tool == "lasso" and self._painting and len(self._lasso) >= 3 and self.P is not None:
            pts = np.array(self._lasso, np.float32).round().astype(np.int32).reshape(-1, 1, 2)
            val = 0.0 if self.sel.get() == "Subtract" else 1.0
            cv2.fillPoly(self.mask, [pts], float(val))
            self._mask_changed()
        self.canvas.delete("lasso")
        self._lasso = []
        self._painting = False

    def _stroke(self, arr, x0, y0, x1, y1, op, amt):
        """Soft round stamps along the line. Returns the touched bounding box (y0, y1, x0, x1)."""
        H, W = arr.shape
        r = self._brush_r()
        hard = self.hard.get() / 100.0
        n = max(1, int(float(np.hypot(x1 - x0, y1 - y0)) / max(1.0, r * 0.25)))
        bb = None
        for i in range(n + 1):
            t = i / n
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            xa, xb = int(max(0, x - r - 1)), int(min(W, x + r + 2))
            ya, yb = int(max(0, y - r - 1)), int(min(H, y + r + 2))
            if xb <= xa or yb <= ya:
                continue
            yy, xx = np.ogrid[ya:yb, xa:xb]
            a = np.clip((r - np.sqrt((xx - x) ** 2 + (yy - y) ** 2)) / max(r * (1.0 - hard), 1e-3), 0, 1)
            a = (a * amt).astype(np.float32)
            roi = arr[ya:yb, xa:xb]
            if op == "max":
                np.maximum(roi, a, out=roi)
            elif op == "mul":
                roi *= (1.0 - a)
            else:  # signed accumulate
                roi += a
                np.clip(roi, -1.0, 1.0, out=roi)
            bb = (ya, yb, xa, xb) if bb is None else (min(bb[0], ya), max(bb[1], yb), min(bb[2], xa), max(bb[3], xb))
        return bb

    def _paint_mask(self, x0, y0, x1, y1):
        op = "max" if self.tool == "brush" else "mul"
        self._stroke(self.mask, x0, y0, x1, y1, op, self.opac.get() / 100.0)
        self._mask_changed()

    def _paint_rest(self, x0, y0, x1, y1):
        bb = self._stroke(self.R, x0, y0, x1, y1, "max", self.opac.get() / 100.0)
        self.rs_bbox = self._union(self.rs_bbox, bb)
        self._db_changed()

    def _paint_db(self, x0, y0, x1, y1):
        if self.tool == "dodge":
            amt = self.dodge_exp.get() / 100.0 * 0.07
        else:
            amt = -self.burn_exp.get() / 100.0 * 0.07
        bb = self._stroke(self.D, x0, y0, x1, y1, "acc", amt)
        self.db_bbox = self._union(self.db_bbox, bb)
        self._db_changed()

    @staticmethod
    def _union(a, b):
        if b is None:
            return a
        if a is None:
            return b
        return (min(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), max(a[3], b[3]))

    def _quick(self, x, y):
        """Quick Selection: grow a region of similar colour from the clicked pixel."""
        h, w = self.P.shape[:2]
        xi, yi = int(x), int(y)
        if not (0 <= xi < w and 0 <= yi < h):
            return
        t = int(self.tol.get())
        m = np.zeros((h + 2, w + 2), np.uint8)
        flags = 4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
        cv2.floodFill(self.lab8s, m, (xi, yi), 0, (t, t, t), (t, t, t), flags)
        self.mask[m[1:-1, 1:-1] > 0] = 0.0 if self.sel.get() == "Subtract" else 1.0
        self._mask_changed()

    # ------------------------------------------------------------- saving
    def save(self, ask):
        if self.full is None or self.P is None:
            messagebox.showinfo("Save", "Open an image first.")
            return
        if self._busy:
            return
        base, ext = os.path.splitext(self.path)
        if ask:
            p = filedialog.asksaveasfilename(
                defaultextension=".jpg", initialfile=os.path.basename(base) + "_retouched",
                filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("TIFF", "*.tif")])
            if not p:
                return
        else:
            e = ext.lower() if ext.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff") else ".png"
            p = base + "_retouched" + e
            n = 2
            while os.path.exists(p):
                p = f"{base}_retouched_{n}{e}"
                n += 1
        self._busy = True
        self.btn_save.configure(state="disabled")
        self.set_status("Saving... 0%")
        prm = self._params()
        db_p = (self.D * (DB_RANGE * prm["dbamt"])).astype(np.float32) if self.db_bbox is not None else None
        rest_p = self.R.copy() if self.rs_bbox is not None else None
        s_p = self._scales(prm)
        me, lab, fp, full, Pbgr, forbid = self.mask_eff.copy(), self.lab_P, self.fp_P, self.full, self.P, self.forbid
        icc, exif = self.icc, self.exif

        def work():
            try:
                dL, da, db = E.compute_delta(lab, me, fp)
                maps = np.dstack([me, dL, da, db]).astype(np.float32)
                sp = E.compute_spots(Pbgr, lab, me, fp, forbid) if prm["spot"] > 0 else None
                out = E.render_full(full, maps, prm, db_p, s_p, progress=lambda f: self._results.append(("progress", f)),
                                    spots_p=sp, rest_p=rest_p)
                im = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
                ext2 = os.path.splitext(p)[1].lower()
                kw = {}
                if icc:
                    kw["icc_profile"] = icc
                if exif:
                    kw["exif"] = exif
                if ext2 in (".jpg", ".jpeg"):
                    kw.update(quality=95, subsampling=0)
                elif ext2 in (".tif", ".tiff"):
                    kw.update(compression="tiff_lzw")
                    kw.pop("exif", None)
                try:
                    im.save(p, **kw)
                except Exception:
                    kw.pop("exif", None)
                    im.save(p, **kw)
                self._results.append(("saved", p))
            except Exception:
                self._results.append(("error", traceback.format_exc()))

        threading.Thread(target=work, daemon=True).start()


def selftest():
    """Used by the build pipeline: checks that the face / segmentation models load inside the exe."""
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    out = os.path.join(base, "selftest.txt")
    try:
        import mediapipe as mp
        img = np.full((600, 800, 3), 170, np.uint8)
        an = E.analyze(img)
        E.build_mask(an, "auto")
        with mp.solutions.face_mesh.FaceMesh(static_image_mode=True, refine_landmarks=True) as fm:
            fm.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        with open(out, "w") as f:
            f.write("OK")
    except Exception:
        with open(out, "w") as f:
            f.write(traceback.format_exc())


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    App().mainloop()
