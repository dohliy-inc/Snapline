from pathlib import Path
from tkinter import filedialog

from PIL import Image, ImageGrab

import compose
import config
from theme import CROPS, HANDLES, VOID, WHITE, px
from widgets import FramePick, Pill


class ImagesTool:
    def mark_overlay(self, geo):
        if self.tool != "images" or not geo or self.active_ov >= len(geo["overlays"]):
            return
        box = geo["overlays"][self.active_ov]
        if not box:
            return
        l, t, r, b = box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]
        self.c.create_rectangle(l, t, r - 1, b - 1, outline=WHITE, width=1, dash=(4, 3), tags=("shot",))
        locked = compose.lock_ratio(self.target["edit"]["overlays"][self.active_ov].get("cut", "free")) is not None
        spots = {"l": (l, (t + b) / 2), "r": (r, (t + b) / 2), "t": ((l + r) / 2, t), "b": ((l + r) / 2, b),
                 "lt": (l, t), "rt": (r, t), "lb": (l, b), "rb": (r, b)}
        k = px(5)
        for name in HANDLES:
            if locked and len(name) == 1:
                continue
            x, y = spots[name]
            tag = f"handle-{name}"
            self.c.create_rectangle(x - k, y - k, x + k, y + k, fill=WHITE, outline=VOID, tags=("shot", tag))
            cursor = {"l": "sb_h_double_arrow", "r": "sb_h_double_arrow", "t": "sb_v_double_arrow",
                      "b": "sb_v_double_arrow"}.get(name, "sizing")
            self.c.tag_bind(tag, "<Enter>", lambda _, c=cursor: self.c.config(cursor=c))
            self.c.tag_bind(tag, "<Leave>", lambda _: self.c.config(cursor=""))

    def sheet_images(self, body):
        overlays = self.target["edit"].setdefault("overlays", [])
        self.label(body, "Второй ракурс, коллаж или стикер поверх СС. С мягкими краями фото растворяется в ней.")
        self.buttons(body, (("Из файла", self.add_file), ("Из буфера", self.add_clipboard)))
        self.buttons(body, (("Из другой СС", lambda: self.toggle_tool("photopick")),), 6)
        if overlays:
            self.active_ov = min(self.active_ov, len(overlays) - 1)
            ov = overlays[self.active_ov]
            pct = lambda v: f"{v:.0f}%"
            if len(overlays) > 1:
                self.field(body, "Картинка")
                self.choice(body, {str(i): str(i + 1) for i in range(len(overlays))}, str(self.active_ov),
                            lambda v: self.select_ov(int(v)))
            self.field(body, "Размер по ширине кадра")
            size = self.slider(body, 5, 200, round(ov["w"] * 100), lambda v: self.change_ov(w=round(v / 100, 4)),
                               fmt=pct)
            self.sliders["ov"] = (size, lambda: round(self.target["edit"]["overlays"][self.active_ov]["w"] * 100))
            self.field(body, "Мягкие края")
            self.slider(body, 0, 100, round(ov.get("soft", 0.0) * 100), lambda v: self.change_ov(soft=v / 100),
                        fmt=pct)
            self.field(body, "Прозрачность")
            self.slider(body, 0, 90, round((1 - ov.get("alpha", 1.0)) * 100),
                        lambda v: self.change_ov(alpha=round(1 - v / 100, 2)), fmt=pct)
            self.field(body, "Обрезка")
            FramePick(body, ov.get("cut", "free"), self.crop_ov, self.crop_size, self.sheet_w, CROPS,
                      (16, 20000)).pack(anchor="w")
            self.buttons(body, (("Сбросить обрезку", lambda: self.crop_ov("reset")), ("Убрать", self.remove_ov)), 8)

    def sheet_photopick(self, body):
        self.label(body, "Нажми на СС справа — её фон ляжет поверх этой с мягкими краями.")
        Pill(body, "Назад", lambda: self.toggle_tool("images"), kind="ghost").pack(anchor="w", pady=(px(8), 0))

    def pick_file(self, title):
        path = filedialog.askopenfilename(title=title, filetypes=[
            ("Картинки", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("Все файлы", "*.*")])
        if not path:
            return None
        try:
            with Image.open(path) as im:
                return im.copy()
        except OSError as e:
            self.note = f"картинка не открылась: {e}"
            self.update_meta()
            return None

    def clipboard_image(self):
        try:
            data = ImageGrab.grabclipboard()
            if isinstance(data, list):
                with Image.open(next(p for p in data if Path(p).is_file())) as im:
                    data = im.copy()
        except (OSError, StopIteration):
            data = None
        if not isinstance(data, Image.Image):
            self.note = "в буфере обмена нет картинки"
            self.update_meta()
            return None
        return data

    def add_file(self):
        image = self.pick_file("Картинка поверх СС")
        if image is not None:
            self.add_image(image)

    def add_clipboard(self):
        image = self.clipboard_image()
        if image is not None:
            self.add_image(image)

    def add_image(self, image):
        overlays = self.target["edit"].setdefault("overlays", [])
        if len(overlays) >= compose.MAX_OVERLAYS:
            self.note = f"больше {compose.MAX_OVERLAYS} картинок не поместится"
            self.update_meta()
            return
        try:
            ov = compose.add_overlay(self.target["out"], self.target["name"], image)
        except OSError as e:
            self.note = f"картинка не сохранилась: {e}"
            self.update_meta()
            return
        p = compose.plan(self.target["bg"], self.look(self.target)[0])
        if p["ext_box"] and ov["soft"]:
            compose.fit_field(ov, p, image.size)
        overlays.append(ov)
        self.active_ov = len(overlays) - 1
        self.redraw()
        self.schedule_save()

    def select_ov(self, k):
        self.active_ov = k
        self.redraw()

    def source_size(self, ov):
        try:
            return compose.overlay_image(self.target["out"] / "src" / ov["file"]).size
        except OSError:
            return None

    def crop_size(self):
        ov = self.target["edit"]["overlays"][self.active_ov]
        W, H = self.source_size(ov) or (1, 1)
        l, t, r, b = ov["crop"]
        return round((r - l) * W), round((b - t) * H)

    def crop_ov(self, value):
        ov = self.target["edit"]["overlays"][self.active_ov]
        size = self.source_size(ov)
        if size is None:
            return
        out_w = compose.plan(self.target["bg"], self.look(self.target)[0])["size"][0]
        before = ov["w"] * out_w / max(1e-6, ov["crop"][2] - ov["crop"][0])
        exact = config.exact_of(value)
        if value == "reset":
            ov["crop"], value = [0.0, 0.0, 1.0, 1.0], "free"
        elif exact:
            ov["crop"] = compose.crop_exact(size, exact[0], exact[1], ov["crop"])
        elif value != "free":
            ov["crop"] = compose.crop_for(size, compose.lock_ratio(value), ov["crop"])
        ov["w"] = round(before * (ov["crop"][2] - ov["crop"][0]) / out_w, 4)
        changed, ov["cut"] = ov.get("cut") != value, value
        if changed:
            self.redraw()
        else:
            self.media_redraw()
        self.schedule_save()

    def change_ov(self, **values):
        self.target["edit"]["overlays"][self.active_ov].update(values)
        self.media_redraw()
        self.schedule_save()

    def remove_ov(self):
        overlays = self.target["edit"]["overlays"]
        overlays.pop(self.active_ov)
        self.active_ov = max(0, self.active_ov - 1)
        self.redraw()
        self.schedule_save()

    def snap_ov(self, ov, box, geo):
        if not box:
            return
        (W, H), d = geo["out"], geo["d"]
        near = 0.015 * min(W, H)
        for key, size, half in (("x", W, box["w"] / d / 2), ("y", H, box["h"] / d / 2)):
            c = ov[key] * size
            if abs(c - half) < near:
                ov[key] = round(half / size, 4)
            elif abs(c + half - size) < near:
                ov[key] = round((size - half) / size, 4)

    def drag_crop(self, e, geo):
        drag = self.drag
        ov = self.target["edit"]["overlays"][drag["part"]]
        (out_w, out_h), d = geo["out"], geo["d"]
        box, (SW, SH), (l, t, r, b) = drag["box"], drag["size"], drag["crop"]
        X, Y = (box["x"] - geo["img"][0]) / d, (box["y"] - geo["img"][1]) / d
        Wd, Hd = box["w"] / d, box["h"] / d
        k = Wd / max(1e-6, (r - l) * SW)
        L, T, R, B = X, Y, X + Wd, Y + Hd
        bounds = (X - l * SW * k, Y - t * SH * k, R + (1 - r) * SW * k, B + (1 - b) * SH * k)
        dx, dy, h = (e.x - drag["x"]) / d, (e.y - drag["y"]) / d, drag["handle"]
        least = 12 / d
        if "l" in h:
            L = min(max(L + dx, bounds[0]), R - least)
        if "r" in h:
            R = max(min(R + dx, bounds[2]), L + least)
        if "t" in h:
            T = min(max(T + dy, bounds[1]), B - least)
        if "b" in h:
            B = max(min(B + dy, bounds[3]), T + least)
        ratio = compose.lock_ratio(ov.get("cut", "free"))
        if ratio and len(h) == 2:
            w, hh = R - L, B - T
            if abs(dx) >= abs(dy) * ratio:
                hh = w / ratio
            else:
                w = hh * ratio
            room_w = (R - bounds[0]) if "l" in h else (bounds[2] - L)
            room_h = (B - bounds[1]) if "t" in h else (bounds[3] - T)
            scale = min(1.0, room_w / w, room_h / hh)
            w, hh = w * scale, hh * scale
            L, R = (R - w, R) if "l" in h else (L, L + w)
            T, B = (B - hh, B) if "t" in h else (T, T + hh)
        span_x, span_y = SW * k, SH * k
        ov["crop"] = [round(min(max(l + (L - X) / span_x, 0.0), 1.0), 5), round(min(max(t + (T - Y) / span_y, 0.0), 1.0), 5),
                      round(min(max(r + (R - X - Wd) / span_x, 0.0), 1.0), 5),
                      round(min(max(b + (B - Y - Hd) / span_y, 0.0), 1.0), 5)]
        ov["w"] = round((R - L) / out_w, 5)
        ov["x"], ov["y"] = round((L + R) / 2 / out_w, 5), round((T + B) / 2 / out_h, 5)
        if not self.pending_media:
            self.pending_media = True
            self.c.after(16, self.flush_media)
