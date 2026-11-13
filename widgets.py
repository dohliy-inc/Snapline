import json
import os
import re
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

import chat
import core
import styles
from theme import (
    CHROME, CHROME_TEXT, DIM, ERR, FONT, FORMATS, LINE, MIST, ROW, SIZES, SLATE, SUB, VOID, WHITE, animations_on, px,
    rgb, rounded, same, shade
)


class Wordmark(tk.Label):
    SILVER = rgb("#9ea5b1")
    PEAK = rgb("#ffffff")
    SWEEP_S = 1.3
    PAUSE_MS = 6000

    def __init__(self, parent, text, size=15):
        super().__init__(parent, bg=VOID, bd=0)
        px = round(size * parent.winfo_fpixels("1i") / 72)
        try:
            font = ImageFont.truetype(str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeuib.ttf"), px)
        except OSError:
            self.config(text=text, fg=WHITE, font=(FONT["display"], size))
            return
        left, top, right, bottom = font.getbbox(text)
        w, h = right - left + 4, bottom - top + 4
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).text((2 - left, 2 - top), text, font=font, fill=255)
        self.mask = np.asarray(mask, np.float32)[..., None] / 255
        ys, xs = np.mgrid[0:h, 0:w]
        self.coord = (xs + ys * 0.45).astype(np.float32)
        self.span = float(w)
        self.ground = rgb(VOID)
        self.photo = ImageTk.PhotoImage(self.frame(None))
        self.config(image=self.photo)
        if animations_on():
            self.after(1200, self.start)

    def frame(self, center):
        if center is None:
            color = self.PEAK
        else:
            u = (self.coord - center) / (self.span * 0.22)
            lum = 1 - 0.42 * np.exp(-u ** 2) + 0.42 * np.exp(-(u / 0.32) ** 2)
            t = np.clip((lum - 0.58) / 0.42, 0, 1)[..., None]
            color = self.SILVER + (self.PEAK - self.SILVER) * t
        out = self.ground * (1 - self.mask) + color * self.mask
        return Image.fromarray(out.round().astype(np.uint8))

    def start(self):
        self.t0 = time.monotonic()
        self.tick()

    def tick(self):
        p = (time.monotonic() - self.t0) / self.SWEEP_S
        if p >= 1:
            self.photo.paste(self.frame(None))
            self.after(self.PAUSE_MS, self.start)
            return
        eased = 1 - (1 - p) ** 3
        self.photo.paste(self.frame(-0.4 * self.span + eased * 1.9 * self.span))
        self.after(33, self.tick)


class CaptionButton(tk.Canvas):
    def __init__(self, parent, glyph, command, danger=False):
        self.w, self.h = px(44), px(32)
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0)
        self.glyph, self.command, self.danger, self.hover = glyph, command, danger, False
        self.bind("<Enter>", lambda _: self.set_hover(True))
        self.bind("<Leave>", lambda _: self.set_hover(False))
        self.bind("<ButtonRelease-1>", self.release)
        self.draw()

    def set_glyph(self, glyph):
        if glyph != self.glyph:
            self.glyph = glyph
            self.draw()

    def set_hover(self, hover):
        self.hover = hover
        self.draw()

    def release(self, e):
        if 0 <= e.x < self.w and 0 <= e.y < self.h:
            self.command()

    def draw(self):
        self.delete("all")
        if self.hover:
            self.photo = ImageTk.PhotoImage(rounded(self.w, self.h, px(8), "#c42b1c" if self.danger else MIST))
            self.create_image(0, 0, anchor="nw", image=self.photo)
        icon = FONT["icon"]
        self.create_text(self.w / 2, self.h / 2, text=(CHROME if icon else CHROME_TEXT)[self.glyph],
                         font=(icon, 9) if icon else (FONT["ui"], 11), fill=WHITE if self.hover else "#c9ccd2")


class Pill(tk.Canvas):
    def __init__(self, parent, text, command, kind="chip", size=10, height=32, padx=13):
        height, padx = px(height), px(padx)
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2",
                         takefocus=1)
        self.text, self.command, self.kind, self.size, self.h, self.padx = text, command, kind, size, height, padx
        self.hover = self.focused = False
        self.bind("<Button-1>", lambda _: self.command())
        self.bind("<Key-Return>", lambda _: self.command())
        self.bind("<Key-space>", lambda _: self.command())
        self.bind("<Enter>", lambda _: self.state_to(hover=True))
        self.bind("<Leave>", lambda _: self.state_to(hover=False))
        self.bind("<FocusIn>", lambda _: self.state_to(focused=True))
        self.bind("<FocusOut>", lambda _: self.state_to(focused=False))
        self.set_text(text)

    def set_text(self, text):
        self.text = text
        font = FONT["semi"] if self.kind in ("on", "primary") else FONT["ui"]
        self.font = (font, self.size)
        self.w = tkfont.Font(family=font, size=self.size).measure(text) + 2 * self.padx
        self.config(width=self.w)
        self.draw()

    def set_kind(self, kind):
        self.kind = kind
        self.set_text(self.text)

    def state_to(self, hover=None, focused=None):
        self.hover = self.hover if hover is None else hover
        self.focused = self.focused if focused is None else focused
        self.draw()

    def draw(self):
        fill, line, fg = {
            "chip": (MIST if self.hover else SLATE, None, WHITE if self.hover else "#d7d9de"),
            "on": (WHITE, None, VOID),
            "primary": ("#ffffff" if self.hover else WHITE, None, VOID),
            "ghost": (SLATE if self.hover else None, WHITE if self.hover else LINE, WHITE),
        }[self.kind]
        if self.focused:
            line = WHITE
        self.photo = ImageTk.PhotoImage(rounded(self.w, self.h, self.h // 2, fill, line, 1.2))
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self.photo)
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=fg, font=self.font)


class Choice(tk.Frame):
    def __init__(self, parent, options, value, on_pick, cols=None, wrap=None):
        super().__init__(parent, bg=parent["bg"])
        self.pills = {}
        self.on_pick = on_pick
        measure = tkfont.Font(family=FONT["semi"], size=10).measure
        line, used = None, 0
        for i, (v, label) in enumerate(options.items()):
            if cols:
                pill = Pill(self, label, lambda v=v: self.pick(v))
                pill.grid(row=i // cols, column=i % cols, padx=(0, px(6)), pady=(0, px(6)), sticky="w")
            else:
                w = measure(label) + px(13) * 2 + px(6)
                if line is None or (wrap and used and used + w > wrap):
                    line = tk.Frame(self, bg=self["bg"])
                    line.pack(anchor="w", pady=(0, px(6) if wrap else 0))
                    used = 0
                pill = Pill(line, label, lambda v=v: self.pick(v))
                pill.pack(side="left", padx=(0, px(6)))
                used += w
            self.pills[v] = pill
        self.set(value)

    def set(self, value):
        for v, pill in self.pills.items():
            pill.set_kind("on" if same(v, value) else "chip")

    def pick(self, value):
        self.set(value)
        self.on_pick(value)


class Corners(tk.Canvas):
    def __init__(self, parent, value, on_pick):
        self.w, self.h, self.value = px(48), px(32), value
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0,
                         cursor="hand2")
        self.frame = ImageTk.PhotoImage(rounded(self.w, self.h, px(6), None, LINE, 1.2))
        self.create_image(0, 0, anchor="nw", image=self.frame)
        r, inset, self.dots = px(4), px(9), {}
        for corner in core.CHAT_POSITIONS:
            v, side = corner.split("-")
            x, y = inset if side == "left" else self.w - inset, inset if v == "top" else self.h - inset
            on = corner == value
            self.dots[corner] = self.create_oval(x - r, y - r, x + r, y + r, fill=WHITE if on else "",
                                                 outline=WHITE if on else DIM)
        self.bind("<Button-1>", lambda e: on_pick(self.spot(e)))
        self.bind("<Motion>", lambda e: self.lit(self.spot(e)))
        self.bind("<Leave>", lambda _: self.lit(None))

    def spot(self, e):
        return ("top" if e.y < self.h / 2 else "bottom") + "-" + ("left" if e.x < self.w / 2 else "right")

    def lit(self, near):
        for corner, dot in self.dots.items():
            if corner != self.value:
                self.itemconfig(dot, outline=WHITE if corner == near else DIM)


class FramePick(tk.Frame):
    def __init__(self, parent, value, on_pick, current, wrap, options=FORMATS, limits=core.FRAME_RANGE):
        super().__init__(parent, bg=parent["bg"])
        self.on_pick, self.current, self.job, self.limits = on_pick, current, None, limits
        custom = core.exact_of(value)
        self.choice = Choice(self, {**options, "custom": "Свой"}, "custom" if custom else value, self.pick, wrap=wrap)
        self.choice.pack(anchor="w")
        self.line = tk.Frame(self, bg=self["bg"])
        self.w = self.entry()
        tk.Label(self.line, text="×", bg=self["bg"], fg=SUB, font=(FONT["ui"], 10)).pack(side="left", padx=px(6))
        self.h = self.entry()
        tk.Label(self.line, text="px", bg=self["bg"], fg=SUB, font=(FONT["ui"], 10)).pack(side="left", padx=px(6))
        if custom:
            self.fill(custom)
            self.line.pack(anchor="w", pady=(px(2), 0))
        self.bind("<Destroy>", lambda e: e.widget is self and self.job and self.after_cancel(self.job))

    def entry(self):
        e = tk.Entry(self.line, width=6, bg=ROW, fg=WHITE, insertbackground=WHITE, relief="flat", justify="center",
                     font=(FONT["ui"], 10), highlightthickness=1, highlightbackground=LINE, highlightcolor=WHITE)
        e.pack(side="left", ipady=px(4))
        e.bind("<KeyRelease>", lambda _: self.typed())
        return e

    def fill(self, size):
        for e, v in zip((self.w, self.h), size):
            e.delete(0, "end")
            e.insert(0, str(v))

    def pick(self, value):
        if value == "custom":
            self.fill(self.current())
            self.line.pack(anchor="w", pady=(px(2), 0))
            self.apply()
        else:
            self.line.pack_forget()
            self.on_pick(value)

    def typed(self):
        if self.job:
            self.after_cancel(self.job)
        self.job = self.after(250, self.apply)

    def apply(self):
        self.job = None
        for e in (self.w, self.h):
            pasted = re.split(r"\s*[x×х*]\s*|\s+", e.get().strip().lower())
            if len(pasted) == 2 and all(pasted):
                self.fill(pasted)
                break
        lo, hi = self.limits
        values = [e.get().strip() for e in (self.w, self.h)]
        ok = [v.isdigit() and lo <= int(v) <= hi for v in values]
        for e, good in zip((self.w, self.h), ok):
            e.config(fg=WHITE if good else ERR, highlightbackground=LINE if good else ERR)
        if all(ok):
            self.on_pick(f"{int(values[0])}x{int(values[1])}")


class SizePick(tk.Frame):
    def __init__(self, parent, value, on_pick, wrap):
        super().__init__(parent, bg=parent["bg"])
        options = SIZES if value in SIZES else {**SIZES, value: value}
        self.choice = Choice(self, options, value, on_pick, wrap=wrap)
        self.note = tk.Label(self, text="Задан шириной и высотой кадра", bg=self["bg"], fg=SUB,
                             font=(FONT["ui"], 10), anchor="w")

    def show(self, fmt):
        self.choice.pack_forget()
        self.note.pack_forget()
        (self.note if core.exact_of(fmt) else self.choice).pack(anchor="w")


class Slider(tk.Canvas):
    def __init__(self, parent, lo, hi, value, on_move, on_done=None, width=None, step=1, fmt=None):
        self.w, self.h = width or px(260), px(30)
        super().__init__(parent, width=self.w, height=self.h, bg=parent["bg"], highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1)
        self.lo, self.hi, self.step = lo, hi, step
        self.fmt = fmt or (lambda v: f"{v:g}")
        self.on_move, self.on_done = on_move, on_done or on_move
        self.value = self.snap(value)
        self.focused = False
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<B1-Motion>", self.press)
        self.bind("<ButtonRelease-1>", lambda _: self.on_done(self.value))
        self.bind("<MouseWheel>", lambda e: self.nudge(1 if e.delta > 0 else -1))
        self.bind("<Key-Left>", lambda _: self.nudge(-1))
        self.bind("<Key-Right>", lambda _: self.nudge(1))
        self.bind("<FocusIn>", lambda _: self.focus_to(True))
        self.bind("<FocusOut>", lambda _: self.focus_to(False))
        self.draw()

    def snap(self, v):
        v = round(round((v - self.lo) / self.step) * self.step + self.lo, 4)
        return min(max(v, self.lo), self.hi)

    def track(self):
        return px(9), self.w - px(64)

    def press(self, e):
        self.focus_set()
        a, b = self.track()
        self.move_to(self.lo + (e.x - a) / (b - a) * (self.hi - self.lo), self.on_move)

    def nudge(self, k):
        self.move_to(self.value + k * self.step, self.on_done)

    def move_to(self, v, notify):
        v = self.snap(v)
        if v != self.value:
            self.value = v
            self.draw()
            notify(v)

    def set(self, v):
        v = self.snap(v)
        if v != self.value:
            self.value = v
            self.draw()

    def focus_to(self, on):
        self.focused = on
        self.draw()

    def draw(self):
        a, b = self.track()
        y, r = self.h // 2, px(8)
        x = a + (self.value - self.lo) / (self.hi - self.lo) * (b - a)
        self.delete("all")
        self.create_line(a, y, b, y, fill=MIST, width=px(4), capstyle="round")
        self.create_line(a, y, x, y, fill=WHITE, width=px(4), capstyle="round")
        self.knob = ImageTk.PhotoImage(rounded(2 * r, 2 * r, r, WHITE, SUB if self.focused else VOID, 2.0))
        self.create_image(x, y, image=self.knob)
        self.create_text(self.w, y, anchor="e", text=self.fmt(self.value), fill=WHITE, font=(FONT["semi"], 10))


class Loupe:
    def __init__(self, canvas):
        self.c = canvas
        self.photo = None

    def show(self, x, y, rect, arr):
        ix, iy, dw, dh = rect
        H, W = arr.shape[:2]
        side = px(240)
        cx, cy = (x - ix) * W / dw, (y - iy) * H / dh
        x0 = int(min(max(cx - side / 2, 0), max(W - side, 0)))
        y0 = int(min(max(cy - side / 2, 0), max(H - side, 0)))
        crop = arr[y0:y0 + side, x0:x0 + side]
        h, w = crop.shape[:2]
        self.photo = ImageTk.PhotoImage(Image.fromarray(crop))
        gap = px(28)
        lx = x + gap if x + gap + w < self.c.winfo_width() else x - gap - w
        ly = min(max(y - h / 2, px(4)), self.c.winfo_height() - h - px(4))
        self.c.delete("loupe")
        self.c.create_rectangle(lx - 2, ly - 2, lx + w + 1, ly + h + 1, outline=WHITE, fill=VOID, tags=("loupe",))
        self.c.create_image(lx, ly, anchor="nw", image=self.photo, tags=("loupe",))
        self.c.create_rectangle(lx, ly, lx + px(34), ly + px(20), outline="", fill=VOID, tags=("loupe",))
        self.c.create_text(lx + px(17), ly + px(10), text="1:1", fill=WHITE, font=(FONT["semi"], 9), tags=("loupe",))

    def hide(self):
        self.c.delete("loupe")
        self.photo = None


class Painter:
    def __init__(self, canvas):
        self.c = canvas
        self.join_key = None
        self.join_img = None
        self.key = None
        self.layer = None
        self.photos = []
        self.geo = None
        self.scaled = None
        self.small = {}
        self.layers = []
        self.pieces = {}
        self.soft = {}

    def frame(self, bg, rect, size):
        x0, y0, x1, y1 = rect
        d = size[0] / (x1 - x0)
        if d >= 1:
            return Image.fromarray(bg[y0:y1, x0:x1]).resize(size, Image.BILINEAR)
        if self.scaled is None or self.scaled[0] is not bg or self.scaled[1] != d:
            H, W = bg.shape[:2]
            whole = Image.fromarray(bg).resize((max(1, round(W * d)), max(1, round(H * d))), Image.BILINEAR,
                                               reducing_gap=2.0)
            self.scaled = (bg, d, whole)
        part = self.scaled[2].crop((round(x0 * d), round(y0 * d), round(x1 * d), round(y1 * d)))
        return part if part.size == size else part.resize(size, Image.BILINEAR)

    def draw(self, shot, area, tag="shot", edit=None, laps=(0, 0)):
        bg, rows, edit = shot["bg"], shot["rows"], edit or shot["edit"]
        p = core.plan(bg, edit)
        out_w, out_h = p["size"]
        ax, ay, aw, ah = area
        d = min(aw / out_w, ah / out_h)
        dw, dh = max(1, round(out_w * d)), max(1, round(out_h * d))
        ix, iy = ax + (aw - dw) // 2, ay + (ah - dh) // 2
        if p["size"] == p["base"]:
            frame = self.frame(bg, p["rect"], (dw, dh))
        else:
            frame = self.joined(shot, p, d, (dw, dh))
        frame = styles.obscure(frame, edit.get("blurs"))
        if any(laps):
            frame = shade(frame, [lap * d for lap in laps])
        it, ib = laps[0] // 2, laps[1] // 2
        inner = out_h - it - ib
        groups = core.parts(rows, edit)
        key = (id(shot), shot.get("name"), id(rows), len(rows), tuple(r["keep"] for r in rows),
               tuple((tuple(map(tuple, r.get("hide", []))), tuple(map(tuple, r.get("drop", [])))) for r in rows),
               tuple(core.cuts(rows, edit)), p["outline"], round(p["scale"], 4), inner, p["margin"])
        if key != self.key:
            self.layers = [chat.chat_layer(part, p["outline"], p["scale"], inner - 2 * p["margin"])
                           for part, _ in groups]
            self.key = key
            self.small = {}
        self.c.delete(tag)
        self.photos = [ImageTk.PhotoImage(frame)]
        self.c.create_image(ix, iy, anchor="nw", image=self.photos[0], tags=(tag,))
        pad = p["outline"] + 2
        geo = {"img": (ix, iy, dw, dh), "d": d, "out": (out_w, out_h), "plan": p, "pad": pad, "chats": [],
               "painted": sum(n for _, n, _ in self.layers), "overlays": [], "join": None, "inset": (it, ib)}
        if p["ext_box"]:
            l, t, r, b = p["ext_box"]
            geo["join"] = (ix + l * d, iy + t * d, ix + r * d, iy + b * d)
        self.draw_overlays(shot, geo, tag)
        spots = core.chat_spots((out_w, inner), [layer for layer, _, _ in self.layers], [pos for _, pos in groups],
                                pad, p["margin"])
        for k, ((layer, _, _), spot) in enumerate(zip(self.layers, spots)):
            if layer is None:
                geo["chats"].append(None)
                continue
            lh, lw = layer.shape[:2]
            left, top = spot[0], spot[1] + it
            size = (max(1, round(lw * d)), max(1, round(lh * d)))
            if k not in self.small or self.small[k][0] != size:
                small = Image.fromarray(layer, "RGBA").resize(size, Image.LANCZOS)
                self.small[k] = (size, ImageTk.PhotoImage(small))
            self.photos.append(self.small[k][1])
            cx, cy = ix + round(left * d), iy + round(top * d)
            self.c.create_image(cx, cy, anchor="nw", image=self.small[k][1], tags=(tag, tag + "-chat", f"{tag}-chat{k}"))
            geo["chats"].append({"x": cx, "y": cy, "w": size[0], "h": size[1], "lw": lw, "lh": lh})
        self.geo = geo
        return geo

    def joined(self, shot, p, d, size):
        join = shot["edit"]["join"]
        key = (id(shot["bg"]), p["rect"], size, json.dumps(join, sort_keys=True))
        if key != self.join_key:
            bw, bh = p["base"]
            base = self.frame(shot["bg"], p["rect"], (max(1, round(bw * d)), max(1, round(bh * d))))
            img = core.join_canvas(base, join)
            self.join_key, self.join_img = key, img if img.size == size else img.resize(size, Image.BILINEAR)
        return self.join_img

    def draw_overlays(self, shot, geo, tag):
        out, overlays = shot.get("out"), shot["edit"].get("overlays", [])
        ix, iy, dw, dh = geo["img"]
        d, (out_w, out_h) = geo["d"], geo["out"]
        if len(self.pieces) > 12:
            self.pieces.clear()
        for k, ov in enumerate(overlays if out else []):
            try:
                source = core.overlay_image(out / "src" / ov["file"])
            except OSError:
                geo["overlays"].append(None)
                continue
            x, y, w, h = core.overlay_box(ov, (out_w, out_h), source.size)
            dx, dy = round(ix + x * d), round(iy + y * d)
            size = (max(1, round(w * d)), max(1, round(h * d)))
            edges = core.soft_edges((x, y, w, h), (out_w, out_h))
            base = (ov["file"], tuple(ov["crop"]), size)
            key = base + (ov.get("soft", 0.0), ov.get("alpha", 1.0), edges)
            if base not in self.pieces:
                self.pieces[base] = core.overlay_piece(source, ov, size)
            if key not in self.soft:
                if len(self.soft) > 24:
                    self.soft.clear()
                self.soft[key] = core.soften(self.pieces[base], ov, edges)
            l, t = max(ix, dx), max(iy, dy)
            r, b = min(ix + dw, dx + size[0]), min(iy + dh, dy + size[1])
            if r <= l or b <= t:
                geo["overlays"].append(None)
                continue
            photo = ImageTk.PhotoImage(self.soft[key].crop((l - dx, t - dy, r - dx, b - dy)))
            self.photos.append(photo)
            self.c.create_image(l, t, anchor="nw", image=photo, tags=(tag, tag + "-ov", f"{tag}-ov{k}"))
            geo["overlays"].append({"x": dx, "y": dy, "w": size[0], "h": size[1], "box": (l, t, r, b)})
