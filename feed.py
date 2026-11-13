import json
import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageEnhance, ImageFilter, ImageTk

import chat
import compose
import config
import store
import theme
import winui
from theme import (
    DONORS, EDITS, ERR, FONT, FRAMED, ICONS, LINE, MIST, PREVIEWS, RAIL_HINTS, SUB, TOOLS, UNDO_MAX, UNDO_MERGE_S,
    VOID, WHITE, megabytes, px, rounded, when
)
from widgets import Choice, Loupe, Painter, Pill, Slider
from tools.blur import BlurTool
from tools.crop import CropTool
from tools.file import FileTool
from tools.images import ImagesTool
from tools.lines import LinesTool
from tools.logpick import LogTool
from tools.scene import SceneTool
from tools.style import StyleTool
from tools.text import TextTool
from tour import Tour


class Feed(LinesTool, LogTool, CropTool, TextTool, ImagesTool, SceneTool, FileTool, StyleTool, BlurTool):
    def __init__(self, app, parent):
        self.app = app
        self.c = tk.Canvas(parent, bg=VOID, highlightthickness=0, bd=0)
        self.painter = Painter(self.c)
        self.names = []
        self.index = 0
        self.shot = None
        self.cache = {}
        self.tool = None
        self.drag = None
        self.busy = False
        self.message = None
        self.note = ""
        self.save_job = None
        self.saves = {}
        self.history, self.future, self.known, self.last_push, self.replaying = [], [], {}, None, False
        self.whole = False
        self.save_queue = queue.Queue()
        threading.Thread(target=self.save_loop, daemon=True).start()
        self.part = None
        self.items = []
        self.added = set()
        self.popup = None
        self.hint_text = None
        self.hint_photo = None
        self.active_ov = 0
        self.active_blur = 0
        self.tour = None
        self.loading = set()
        self.offset = 0
        self.last_wheel = 0.0
        self.sheet = None
        self.media = None
        self.photos = []
        self.pending_media = False
        self.media_src = None
        self.resize_job = None
        self.thumbs = {}
        self.sliders = {}
        self.sheet_tool = None
        self.sheet_offset = 0
        self.preview = None
        self.preview_info = None
        self.preview_rev = 0
        self.preview_job = None
        self.style_job = None
        self.preview_photo = None
        self.preview_rect = None
        self.preview_view = None
        self.preview_img = None
        self.view_box = None
        self.view = {"zoom": 1.0, "cx": 0.5, "cy": 0.5}
        self.seam = "all"
        self.layout = None
        self.logview = None
        self.log_font = None
        self.loupe = Loupe(self.c)
        self.c.bind("<Leave>", lambda _: (self.loupe.hide(), self.hint(None)))
        self.c.bind("<Configure>", lambda _: self.settle())
        self.c.bind("<ButtonPress-1>", self.press)
        self.c.bind("<B1-Motion>", self.motion)
        self.c.bind("<ButtonRelease-1>", self.release)
        self.c.bind("<MouseWheel>", self.wheel)
        self.c.bind("<Motion>", self.hover)
        self.refresh_names()

    def refresh_names(self):
        self.names = store.list_shots(self.app.cfg["out"])
        self.media = None

    @property
    def name(self):
        return self.names[self.index - 1] if 0 < self.index <= len(self.names) else None

    def area(self):
        W, H = self.c.winfo_width(), self.c.winfo_height()
        return theme.SIDE_W, px(12), W - theme.SIDE_W - theme.RAIL_W, H - px(24)

    def go(self, index):
        index = max(0, min(index, len(self.names)))
        if index == self.index and (index == 0 or self.shot is not None):
            return
        self.index, self.tool, self.offset, self.note = index, None, 0, ""
        self.open_current()

    def open_current(self):
        self.flush_save()
        name = self.name
        self.shot = None
        self.preview = self.preview_info = self.layout = self.part = None
        self.view, self.seam = {"zoom": 1.0, "cx": 0.5, "cy": 0.5}, "all"
        self.loupe.hide()
        if name is None:
            self.redraw()
            return
        if name in self.cache:
            self.shot = self.cache[name] or None
            self.redraw()
            self.fetch_next()
            return
        self.redraw()
        self.fetch(name)

    def fetch(self, name):
        if name in self.cache or name in self.loading:
            return
        self.loading.add(name)
        cfg = self.app.cfg

        def work():
            try:
                shot = store.load_shot(cfg["out"], name, cfg)
            except Exception:
                shot = None
            self.app.inbox.put(("loaded", name, shot))

        threading.Thread(target=work, daemon=True).start()

    def fetch_next(self):
        if 0 < self.index < len(self.names):
            self.fetch(self.names[self.index])

    def loaded(self, name, shot):
        self.loading.discard(name)
        if self.cache.get(name):
            return
        self.cache[name] = shot or False
        self.remember(shot)
        keep = set(self.scene_names()) | {self.name}
        while len(self.cache) > 6 + len(keep):
            old = next((n for n in self.cache if n not in keep), None)
            if old is None:
                break
            self.cache.pop(old)
        if name == self.name:
            self.shot = shot
            if shot and self.tour is None and self.app.cfg["tour"]:
                self.tour = Tour(self, lambda: self.app.set("tour", "no"))
            self.redraw()
            self.fetch_next()
        elif self.shot is not None and self.drag is None and name in self.scene_names() and self.tool in EDITS:
            if self.tool == "lines" or name == self.part:
                self.redraw()

    def new_shot(self, name):
        if self.saves.pop(name, None) and not self.saves and self.save_job:
            self.c.after_cancel(self.save_job)
            self.save_job = None
        self.cache.pop(name, None)
        self.forget(name)
        self.refresh_names()
        if self.drag is None:
            self.index, self.tool, self.offset = 1, None, 0
            self.note = "только что"
            self.open_current()

    def settle(self):
        if self.resize_job:
            self.c.after_cancel(self.resize_job)
        self.resize_job = self.c.after(110, self.settled)

    def settled(self):
        self.resize_job = None
        self.redraw()

    def redraw(self):
        W, H = self.c.winfo_width(), self.c.winfo_height()
        if W < 100 or H < 100:
            return
        self.c.delete("all")
        self.photos = []
        self.preview_rect = self.view_box = self.popup = self.hint_text = None
        if self.sheet:
            self.sheet.destroy()
            self.sheet = None
        if self.index == 0:
            self.draw_ready(W, H)
        else:
            self.draw_item(W, H)
        if self.tour:
            self.tour.draw()

    def start_tour(self):
        if not self.names:
            self.note = "Сначала сними СС: обучение проходит по редактору"
            return
        self.tour = Tour(self, lambda: self.app.set("tour", "no"))
        if self.index == 0:
            self.go(1)
        else:
            self.redraw()

    def text(self, x, y, s, font, fill=WHITE, width=None, tags=("cap",)):
        item = self.c.create_text(x, y, text=s, font=font, fill=fill, anchor="nw", width=width, tags=tags)
        return self.c.bbox(item)[3]

    def lift_block(self, tag, bottom):
        box = self.c.bbox(tag)
        if box:
            self.c.move(tag, 0, bottom - box[3])

    def ready_media(self, W, H):
        if self.media and self.media[0] == (W, H):
            return self.media[1]
        photo = None
        if self.names:
            path = store.shot_image(self.app.cfg["out"], self.names[0])
            try:
                key = (path, path.stat().st_mtime)
                if self.media_src is None or self.media_src[0] != key:
                    with Image.open(path) as im:
                        im = im.convert("RGB")
                        im.thumbnail((360, 360), Image.BILINEAR)
                    self.media_src = (key, ImageEnhance.Brightness(im).enhance(0.3))
                small = self.media_src[1]
                k = max(W / small.width, H / small.height)
                sw, sh = max(1, round(W / k)), max(1, round(H / k))
                left, top = (small.width - sw) // 2, (small.height - sh) // 2
                im = small.crop((left, top, left + sw, top + sh)).filter(ImageFilter.GaussianBlur(22 / k))
                im = im.resize((W, H), Image.BICUBIC)
                scrim = Image.linear_gradient("L").resize((W, H)).point(lambda v: int(v * 0.85))
                photo = ImageTk.PhotoImage(Image.composite(Image.new("RGB", (W, H), VOID), im, scrim))
            except OSError:
                photo = None
        self.media = ((W, H), photo)
        return photo

    def draw_ready(self, W, H):
        cfg = self.app.cfg
        media = self.ready_media(W, H)
        if media:
            self.c.create_image(0, 0, anchor="nw", image=media)
        key, hud, dark = cfg["key"], cfg["hud_key"], cfg["dark_key"]
        x, width = theme.PAD + px(12), theme.SIDE_W + px(120)
        cap_h = px(54)
        cap = rounded(tkfont.Font(family=FONT["display"], size=20).measure(key) + px(44), cap_h, px(14), None, WHITE,
                      1.4 * theme.K)
        self.photos.append(ImageTk.PhotoImage(cap))
        self.c.create_image(x, 0, anchor="nw", image=self.photos[-1], tags=("cap",))
        self.c.create_text(x + cap.width / 2, cap_h / 2, text=key, fill=WHITE, font=(FONT["display"], 20), tags=("cap",))
        y = cap_h + px(26)
        title, body, level = "Готово к съёмке", None, "info"
        if self.busy:
            title = "Снимаю…"
        elif self.message:
            level, body = self.message
            title = {"fail": "Не вышло", "step": "Половина есть"}.get(level, title)
        log = cfg["source"] == "log"
        if body is None:
            if log:
                first = (f"Нажми {key} в игре и программа сама спрячет интерфейс" if cfg["auto"]
                         else f"В игре нажми {hud}, затем {key}")
                body = (f"{first}: снимется только сцена, без затемнения. Строки потом отметишь в «Строках» "
                        f"из чатлога. Готовая СС появится здесь или в папке скриншотов.")
            elif cfg["auto"]:
                body = (f"Нажми {key} в игре и программа сама спрячет интерфейс и затемнит экран, "
                        f"а готовая СС появится здесь или в папке скриншотов.")
            else:
                body = (f"В игре нажми {hud}, затем {key} — это фон. Потом {dark}, затем {key} — это чат. "
                        f"Готовая СС появится здесь или в папке скриншотов.")
        if level == "fail":
            dot = ImageTk.PhotoImage(rounded(px(10), px(10), px(5), ERR))
            self.photos.append(dot)
            self.c.create_image(x, y + px(16), anchor="nw", image=dot, tags=("cap",))
            y = self.text(x + px(22), y, title, (FONT["display"], 30)) + px(12)
        else:
            y = self.text(x, y, title, (FONT["display"], 30)) + px(12)
        y = self.text(x, y, body, (FONT["ui"], 13), SUB if level != "fail" else WHITE, width) + px(14)
        tip = ("Памятка: в чатлоге видны строки за час до и после СС, так что отыграть сцену можно и после "
               "снимка." if log else
               f"Памятка: если диалог длинный, то нажми {dark} и вновь {key}. "
               f"Тогда в одной СС будет несколько чатбоксов.")
        y = self.text(x, y, tip, (FONT["ui"], 10), SUB, width)
        if self.app.update:
            version, url = self.app.update
            self.c.create_text(x, y + px(10), text=f"Вышла Snapline {version} — скачать", fill=WHITE, anchor="nw",
                               font=(FONT["semi"], 10), tags=("cap", "update", "link"))
            self.c.tag_bind("update", "<Button-1>", lambda _: os.startfile(url))
            self.c.tag_bind("update", "<Enter>", lambda _: self.c.config(cursor="hand2"))
            self.c.tag_bind("update", "<Leave>", lambda _: self.c.config(cursor=""))
        self.lift_block("cap", H - theme.PAD - px(12))
        if self.names:
            cx = (x + width + W - theme.RAIL_W) / 2
            label = f"Прошлые СС · {len(self.names)}"
            self.c.create_text(cx, H - theme.PAD - px(4), text=label, fill=SUB, font=(FONT["ui"], 10), anchor="s",
                               tags=("older", "link"))
            if FONT["icon"]:
                self.c.create_text(cx, H - theme.PAD - px(26), text=ICONS["down"], fill=SUB, font=(FONT["icon"], 14),
                                   anchor="s", tags=("older", "link"))
            self.c.tag_bind("older", "<Button-1>", lambda _: self.go(1))
            self.hover_link("older")
        self.rail(W, H, [("folder", "Папка", self.open_folder, False)])

    def hover_link(self, tag):
        self.c.tag_bind(tag, "<Enter>", lambda _: (self.c.itemconfig(tag, fill=WHITE), self.c.config(cursor="hand2")))
        self.c.tag_bind(tag, "<Leave>", lambda _: (self.c.itemconfig(tag, fill=SUB), self.c.config(cursor="")))

    def draw_item(self, W, H):
        area = self.area()
        name = self.name
        view_only = self.cache.get(name) is False
        geo = None
        if self.shot is None:
            self.draw_saved(area, name)
        else:
            self.draw_media(area)
        if self.tool:
            self.build_sheet(H)
        else:
            self.caption(H, name, view_only)
        tools = [] if self.shot is None else [
            ("lines", "Строки", lambda: self.toggle_tool("lines"), self.tool in ("lines", "carry", "logpick")),
            ("crop", "Кадр", lambda: self.toggle_tool("crop"), self.tool == "crop"),
            ("text", "Текст", lambda: self.toggle_tool("text"), self.tool == "text"),
            ("images", "Картинки", lambda: self.toggle_tool("images"), self.tool in ("images", "photopick")),
            ("scene", "Сцена", lambda: self.toggle_tool("scene"), self.tool in ("scene", "scenepick")),
            ("file", "Файл", lambda: self.toggle_tool("file"), self.tool == "file"),
            ("style", "Стиль", lambda: self.toggle_tool("style"), self.tool == "style"),
            ("blur", "Размытие", lambda: self.toggle_tool("blur"), self.tool == "blur"),
        ]
        tools.append(None)
        if self.shot is not None or view_only:
            tools.append(("copy", "Копировать", self.copy, False))
        tools.append(("folder", "В папке", self.open_folder, False))
        self.rail(W, H, tools)

    def draw_media(self, area):
        self.preview_rect = self.view_box = None
        if self.tool == "lines":
            self.draw_lines(area)
        elif self.tool == "logpick":
            self.draw_log(area)
        elif self.tool in DONORS:
            self.draw_donors(area)
        elif (self.tool is None or self.previewing()) and self.scene_names():
            self.draw_scene(area)
        elif self.target is None:
            ax, ay, aw, ah = area
            self.painter.geo = None
            text = "Исходники этой СС не найдены" if self.cache.get(self.part) is False else "Загружаю СС…"
            self.c.create_text(ax + aw // 2, ay + ah // 2, text=text, fill=SUB, font=(FONT["ui"], 12), tags=("shot",))
        else:
            edit, laps = self.look(self.target)
            self.decorate(self.painter.draw(self.target, area, edit=edit, laps=laps))

    def scene_names(self):
        scene = self.shot["edit"].get("scene") if self.shot else None
        return list(scene["shots"]) if scene and self.shot["name"] in scene["shots"] else []

    @property
    def target(self):
        if self.shot is None or self.tool not in EDITS or self.part in (None, self.name):
            return self.shot
        if self.part not in self.scene_names():
            return self.shot
        return self.cache.get(self.part) or None

    def members(self):
        return [(n, self.shot if n == self.name else self.cache.get(n) or None) for n in self.scene_names()]

    def previewing(self):
        return self.tool in PREVIEWS or self.tool == "text" and self.whole and bool(self.scene_names())

    def member(self, name):
        if name == self.name:
            return self.shot
        shot = self.cache.get(name)
        if not shot:
            try:
                shot = store.load_shot(self.shot["out"], name, self.app.cfg)
            except (OSError, ValueError):
                shot = None
            if shot:
                self.cache[name] = shot
                self.remember(shot)
        return shot or None

    def fetch_scene(self):
        for name in self.scene_names():
            self.fetch(name)

    def look(self, shot):
        names = self.scene_names()
        if not names or shot.get("name") not in names:
            return shot["edit"], (0, 0)
        edit = compose.framed(shot["edit"], self.shot["edit"])
        width, _, laps = self.scene_plan()
        k = names.index(shot["name"])
        f = compose.plan(shot["bg"], edit)["size"][0] / width
        return edit, (round(laps[k - 1] * f) if k else 0, round(laps[k] * f) if k < len(laps) else 0)

    def current(self):
        names = self.scene_names()
        return self.part if self.part in names else self.name

    def pick_part(self, name):
        self.part = None if name == self.name else name
        self.fetch(name)
        self.active_ov = 0
        self.redraw()

    def frame_strip(self, body):
        names, current = self.scene_names(), self.current()
        self.field(body, "СС в сцене", 0)
        box = tk.Frame(body, bg=VOID)
        box.pack(anchor="w", pady=(0, px(10)))
        per = max(1, self.sheet_w // (px(54) + px(12)))
        for k, name in enumerate(names):
            on = name == current
            cell = tk.Frame(box, bg=VOID, cursor="hand2")
            cell.grid(row=k // per, column=k % per, padx=(0, px(8)), pady=(0, px(6)), sticky="nw")
            photo = self.frame_thumb(name)
            pic = tk.Label(cell, image=photo, bg=VOID, bd=0, highlightthickness=px(2),
                           highlightbackground=WHITE if on else VOID) if photo else None
            if pic:
                pic.pack(anchor="w")
            text = f"{k + 1}" + (" · эта" if name == self.name else "")
            tag = tk.Label(cell, text=text, bg=VOID, fg=WHITE if on else SUB, font=(FONT["ui"], 9), anchor="w")
            tag.pack(anchor="w")
            for w in (cell, pic, tag):
                if w:
                    w.bind("<Button-1>", lambda _, n=name: self.pick_part(n))

    def zoom_view(self, zoom, at=None):
        if self.preview is None or not self.view_box:
            return
        ax, ay, aw, ah = self.area()
        x0, y0, d = self.view_box
        H, W = self.preview.shape[:2]
        fit = min(aw / W, ah / H)
        zoom = min(max(zoom, 1.0), max(1.0, 4 / fit))
        if at is not None:
            rx, ry = self.preview_rect[:2]
            sx, sy = x0 + (at[0] - rx) / d, y0 + (at[1] - ry) / d
            nd = fit * zoom
            self.view["cx"] = (sx - (at[0] - ax - aw / 2) / nd) / W
            self.view["cy"] = (sy - (at[1] - ay - ah / 2) / nd) / H
        self.view["zoom"] = zoom
        self.media_redraw()

    def view_fit(self, kind):
        if self.preview is None:
            return
        ax, ay, aw, ah = self.area()
        H, W = self.preview.shape[:2]
        fit = min(aw / W, ah / H)
        self.zoom_view({"all": 1.0, "width": aw / W / fit, "real": 1 / fit}[kind])

    def focus_frame(self, k):
        if self.preview is None or not self.layout or k >= len(self.layout["tops"]):
            return
        ax, ay, aw, ah = self.area()
        H, W = self.preview.shape[:2]
        top, h = self.layout["tops"][k], self.layout["heights"][k]
        self.view.update(cx=0.5, cy=(top + h / 2) / H)
        self.zoom_view(min(aw / W, ah / h) / min(aw / W, ah / H))

    def decorate(self, geo):
        ix, iy, dw, dh = geo["img"]
        if self.tool == "crop":
            self.c.create_rectangle(ix - 1, iy - 1, ix + dw, iy + dh, outline=WHITE, width=1, tags=("shot",))
            if geo["join"]:
                l, t, r, b = geo["join"]
                self.c.create_rectangle(l, t, r - 1, b - 1, outline=WHITE, width=1, dash=(4, 3), tags=("shot",))
        elif self.tool in ("file", "style"):
            self.draw_preview(geo["img"])
        elif self.tool == "blur":
            self.draw_blurs(geo)
        self.mark_overlay(geo)

    def draw_saved(self, area, name):
        ax, ay, aw, ah = area
        try:
            with Image.open(store.shot_image(self.app.cfg["out"], name)) as im:
                im = im.convert("RGB")
                im.thumbnail((aw, ah), Image.BILINEAR)
                self.photos.append(ImageTk.PhotoImage(im))
                self.c.create_image(ax + aw // 2, ay + ah // 2, image=self.photos[-1], tags=("shot",))
        except OSError:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="Файл СС не найден", fill=SUB, font=(FONT["ui"], 12))

    def meta(self):
        if self.shot is None:
            return "загружаю…" if self.cache.get(self.name) is None else "только просмотр"
        shot, scene = self.target, self.scene_names()
        if not scene:
            w, h = compose.plan(self.shot["bg"], self.shot["edit"])["size"]
            parts = [f"{w} × {h}"]
        elif self.tool in FRAMED and shot is not None and not self.previewing():
            w, h = compose.plan(shot["bg"], self.look(shot)[0])["size"]
            parts = [f"СС {scene.index(shot['name']) + 1} из {len(scene)}", f"кадр {w} × {h}",
                     "сцена {} × {}".format(*self.scene_size())]
        else:
            parts = [f"сцена из {len(scene)} СС"]
            if self.preview is not None and self.previewing():
                parts.append(f"{self.preview.shape[1]} × {self.preview.shape[0]}")
            if self.view_box:
                parts.append(f"масштаб {round(self.view_box[2] * 100)}%")
        geo = self.painter.geo
        kept = sum(r["keep"] for r in shot["rows"]) if shot else 0
        drawn = self.tool in FRAMED or not scene and self.tool in (None, "file", "style")
        if geo and shot and drawn and geo["painted"] < kept:
            parts.append(f"влезло {geo['painted']} из {kept} строк")
        if self.note:
            parts.append(self.note)
        elif self.shot.get("legacy"):
            parts.append("старая СС, файл обновится после правки")
        return " · ".join(parts)

    def caption(self, H, name, view_only):
        x, width = theme.PAD + px(12), theme.SIDE_W - theme.PAD - px(24)
        y = self.text(x, 0, when(name), (FONT["display"], 24)) + px(6)
        y = self.text(x, y, self.meta(), (FONT["ui"], 11), SUB, width, tags=("cap", "meta")) + px(18)
        if view_only:
            hint = "Исходные кадры этой СС не найдены, её можно только посмотреть и скопировать."
        elif self.empty_log():
            hint = "Чат пока пустой: открой «Строки» клавишей 1 и отметь нужные строки чатлога."
        elif self.scene_names():
            hint = "Это сцена из нескольких СС. Инструменты — справа или клавишами 1–8, колесо листает СС."
        else:
            hint = "Инструменты — справа или клавишами 1–8. Колесо листает СС."
        self.text(x, y, hint, (FONT["ui"], 10), SUB, width)
        self.lift_block("cap", H - theme.PAD - px(12))

    def rail(self, W, H, items):
        cx = W - theme.RAIL_W / 2
        top, bottom = theme.PAD, H - theme.PAD - (px(86) if self.names else 0)
        slots = sum(0.5 if item is None else 1 for item in items)
        step = min(px(76), (bottom - top) / max(1, slots))
        ring, drop = min(px(46), round(step * 0.6)), min(px(34), round(step * 0.5))
        y = (top + bottom) / 2 - step * (slots - 1) / 2 - px(9)
        for item in items:
            if item is None:
                line = y - step + (drop + px(6) + step * 1.5 - ring / 2) / 2
                self.c.create_line(cx - px(16), line, cx + px(16), line, fill=LINE, tags=("rail",))
                y += step * 0.5
                continue
            key, label, command, active = item
            tag, idle = f"rail-{key}", WHITE if key == "copy" else SUB
            if active or key == "copy":
                image = rounded(ring, ring, ring / 2, WHITE) if active else rounded(ring, ring, ring / 2, None, WHITE,
                                                                                    1.4 * theme.K)
                self.photos.append(ImageTk.PhotoImage(image))
                self.c.create_image(cx, y, image=self.photos[-1], tags=(tag, "rail"))
            if FONT["icon"]:
                self.c.create_text(cx, y, text=ICONS[key], font=(FONT["icon"], 18), fill=VOID if active else WHITE,
                                   tags=(tag, "rail", tag + "-ink" if not active else tag + "-on"))
            self.c.create_text(cx, y + drop, text=label, font=(FONT["ui"], 9), fill=WHITE if active else idle,
                               tags=(tag, "rail", tag + "-label"))
            self.c.create_rectangle(cx - px(46), y - step * 0.4, cx + px(46), y + step * 0.6, outline="", fill="",
                                    tags=(tag, "rail"))
            self.c.tag_bind(tag, "<Button-1>", lambda _, f=command: f())
            if not active:
                self.c.tag_bind(tag, "<Enter>", lambda _, t=tag: (self.c.itemconfig(t + "-label", fill=WHITE),
                                                                  self.c.config(cursor="hand2")))
                self.c.tag_bind(tag, "<Leave>", lambda _, t=tag, c=idle: (self.c.itemconfig(t + "-label", fill=c),
                                                                          self.c.config(cursor="")))
            y += step
        if self.names:
            total = len(self.names) + 1
            ny = H - theme.PAD - px(40)
            pos = "съёмка" if self.index == 0 else f"{self.index} из {len(self.names)}"
            self.c.create_text(cx, ny, text=pos, font=(FONT["ui"], 9), fill=SUB, tags=("rail",))
            if FONT["icon"]:
                for key, dy, delta, enabled in (("up", -px(26), -1, self.index > 0),
                                                ("down", px(24), 1, self.index < total - 1)):
                    tag = f"nav-{key}"
                    self.c.create_text(cx, ny + dy, text=ICONS[key], font=(FONT["icon"], 13),
                                       fill=SUB if enabled else MIST, tags=(tag, "rail"))
                    if enabled:
                        self.c.tag_bind(tag, "<Button-1>", lambda _, d=delta: self.go(self.index + d))
                        self.hover_link(tag)

    def toggle_tool(self, tool):
        if tool == "scene" and self.tool != "scene" and self.shot is not None and not self.scene_names():
            tool = "scenepick"
        if tool == "lines" and self.tool not in ("lines", "logpick") and self.empty_log():
            tool = "logpick"
        was = self.previewing()
        old, self.tool = self.tool, None if self.tool == tool else tool
        self.offset = 0
        self.loupe.hide()
        if old == "scenepick" and self.added and self.scene_names():
            self.drop_repeats()
        self.added = set()
        if self.tool in EDITS:
            self.fetch_scene()
        if self.previewing():
            if not was:
                self.preview = self.preview_info = None
            self.want_preview()
        if self.tool == "logpick":
            self.open_log()
        self.redraw()

    def build_sheet(self, H):
        sheet = tk.Frame(self.c, bg=VOID)
        self.sheet_w = theme.SIDE_W - 2 * theme.PAD - px(12)
        sheet.place(x=theme.PAD + px(12), y=theme.PAD, width=self.sheet_w + px(12), height=H - 2 * theme.PAD)
        self.sheet = sheet
        head = tk.Frame(sheet, bg=VOID)
        head.pack(fill="x", padx=(0, px(12)))
        title = {"lines": "Строки чата", "crop": "Кадр", "text": "Текст", "images": "Картинки", "file": "Файл", "style": "Стиль", "blur": "Размытие",
                 "carry": "Чат из другой СС", "logpick": "Чатлог", "photopick": "Фото из другой СС", "scene": "Сцена",
                 "scenepick": "СС для сцены"}[self.tool]
        tk.Label(head, text=title, bg=VOID, fg=WHITE, font=(FONT["display"], 20)).pack(side="left")
        close = tk.Label(head, text=ICONS["close"] if FONT["icon"] else "Закрыть", bg=VOID, fg=SUB, cursor="hand2",
                         font=(FONT["icon"], 12) if FONT["icon"] else (FONT["ui"], 10))
        close.pack(side="right", pady=(px(6), 0))
        close.bind("<Button-1>", lambda _: self.toggle_tool(self.tool))
        close.bind("<Enter>", lambda _: close.config(fg=WHITE))
        close.bind("<Leave>", lambda _: close.config(fg=SUB))
        scope = self.scope()
        if scope:
            tk.Label(sheet, text=scope, bg=VOID, fg=SUB, font=(FONT["ui"], 10), anchor="w").pack(fill="x")
        holder = tk.Frame(sheet, bg=VOID)
        holder.pack(fill="both", expand=True, pady=(px(14) if scope else px(18), px(8)))
        body = tk.Frame(holder, bg=VOID)
        body.place(x=0, y=0, width=self.sheet_w)
        self.sheet_holder, self.sheet_body = holder, body
        self.sheet_thumb = tk.Frame(holder, bg=LINE)
        if self.tool != self.sheet_tool:
            self.sheet_tool, self.sheet_offset = self.tool, 0
        self.sliders = {}
        if self.tool in FRAMED and self.scene_names():
            self.frame_strip(body)
        if self.target is None:
            self.label(body, "Загружаю эту СС…" if self.cache.get(self.part) is None else
                       "Исходники этой СС не найдены, её не поправить.")
        else:
            getattr(self, "sheet_" + self.tool)(body)
        self.sheet_meta = tk.Label(sheet, text=self.meta(), bg=VOID, fg=SUB, font=(FONT["ui"], 10), anchor="w",
                                   justify="left", wraplength=self.sheet_w)
        self.sheet_meta.pack(fill="x", padx=(0, px(12)))
        self.bind_sheet_wheel(holder)
        holder.bind("<Configure>", lambda _: self.scroll_sheet(0))
        body.bind("<Configure>", lambda _: self.scroll_sheet(0))

    def scope(self):
        names = self.scene_names()
        if self.tool == "scenepick" or not names and self.tool in ("scene", "carry", "logpick", "photopick"):
            return None
        if not names:
            return "только эта СС"
        if self.previewing():
            return "вся сцена"
        if self.tool == "lines":
            return "все СС сцены"
        return f"СС {names.index(self.current()) + 1} из {len(names)} сцены"

    def hint(self, text):
        if text == self.hint_text:
            return
        self.hint_text = text
        self.c.delete("hint")
        if not text or self.index == 0:
            return
        ax, ay, aw, ah = self.area()
        w = min(aw - px(20), tkfont.Font(family=FONT["ui"], size=10).measure(text) + px(32))
        h = px(32)
        x, y = ax + (aw - w) // 2, ay + ah - h - px(12)
        self.hint_photo = ImageTk.PhotoImage(rounded(w, h, h // 2, (10, 10, 10, 228), (69, 75, 87, 255)))
        self.c.create_image(x, y, anchor="nw", image=self.hint_photo, state="disabled", tags=("hint",))
        self.c.create_text(x + w / 2, y + h / 2, text=text, fill=WHITE, font=(FONT["ui"], 10), state="disabled",
                           tags=("hint",))

    def bind_sheet_wheel(self, widget):
        if not isinstance(widget, Slider):
            widget.bind("<MouseWheel>", lambda e: self.scroll_sheet(-px(60) if e.delta > 0 else px(60)), add="+")
        for child in widget.winfo_children():
            self.bind_sheet_wheel(child)

    def scroll_sheet(self, delta):
        holder, body = self.sheet_holder, self.sheet_body
        if not holder.winfo_exists():
            return
        seen, full = holder.winfo_height(), body.winfo_reqheight()
        self.sheet_offset = max(0, min(self.sheet_offset + delta, full - seen))
        body.place_configure(y=-self.sheet_offset)
        if full > seen > 1:
            h = max(px(24), seen * seen / full)
            self.sheet_thumb.place(x=self.sheet_w + px(6), y=(seen - h) * self.sheet_offset / (full - seen),
                                   width=px(3), height=h)
        else:
            self.sheet_thumb.place_forget()

    def label(self, parent, text, top=0):
        tk.Label(parent, text=text, bg=VOID, fg=SUB, font=(FONT["ui"], 10), anchor="w", justify="left",
                 wraplength=self.sheet_w).pack(fill="x", pady=(px(top), px(8)))

    def field(self, parent, text, top=14):
        tk.Label(parent, text=text, bg=VOID, fg=WHITE, font=(FONT["semi"], 10), anchor="w").pack(
            fill="x", pady=(px(top), px(6)))

    def choice(self, body, options, value, on_pick, **kw):
        Choice(body, options, value, on_pick, wrap=self.sheet_w, **kw).pack(anchor="w")

    def slider(self, body, lo, hi, value, on_change, **kw):
        bar = Slider(body, lo, hi, value, on_change, width=self.sheet_w, **kw)
        bar.pack(anchor="w")
        return bar

    def buttons(self, body, items, top=0):
        line = tk.Frame(body, bg=VOID)
        line.pack(anchor="w", pady=(px(top), 0))
        for text, command in items:
            Pill(line, text, command, kind="ghost").pack(side="left", padx=(0, px(6)))

    def change(self, **values):
        shot = self.target
        if shot is None:
            return
        shot["edit"].update(values)
        self.media_redraw()
        if self.previewing():
            self.want_preview()
        self.schedule_save(shot)

    def media_redraw(self):
        if self.shot is None or self.index == 0:
            return
        if self.tool not in DONORS:
            self.c.delete("shot")
            self.draw_media(self.area())
            self.c.tag_lower("shot")
        for bar, value in self.sliders.values():
            if bar.winfo_exists():
                bar.set(value())
        self.update_meta()
        if self.tour:
            self.tour.draw()

    def want_preview(self):
        self.preview_rev += 1
        if self.preview_job:
            self.c.after_cancel(self.preview_job)
        self.preview_job = self.c.after(150, self.encode_preview)

    def encode_preview(self):
        self.preview_job = None
        if self.shot is None or not self.previewing():
            return
        snap, key = self.snapshot(), (self.name, self.preview_rev)

        def work():
            try:
                layout = {}
                img, _, data = store.encoded(snap, layout)
                arr = store.decoded(data) if snap["edit"]["file"] == "jpg" else img
                self.app.inbox.put(("previewed", key, (arr, len(data), layout or None)))
            except Exception as e:
                self.app.inbox.put(("previewed", key, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def previewed(self, key, value):
        if key != (self.name, self.preview_rev) or not self.previewing():
            return
        if isinstance(value, str):
            self.preview_info = f"размер не посчитался: {value}"
        else:
            self.preview, size, self.layout = value
            self.preview_info = f"≈ {megabytes(size)} · {self.preview.shape[1]} × {self.preview.shape[0]}"
            self.media_redraw()
        info = getattr(self, "file_info", None)
        if self.sheet is not None and info is not None and info.winfo_exists():
            info.config(text=self.preview_info)

    def draw_preview(self, rect):
        if self.preview is None:
            return
        self.preview_rect, self.preview_view = rect, self.preview
        ix, iy, dw, dh = rect
        key = (id(self.preview), dw, dh)
        if self.preview_photo is None or self.preview_photo[0] != key:
            img = Image.fromarray(self.preview).resize((dw, dh), Image.BILINEAR, reducing_gap=2.0)
            self.preview_photo = (key, ImageTk.PhotoImage(img))
        self.c.create_image(ix, iy, anchor="nw", image=self.preview_photo[1], tags=("shot",))

    def update_meta(self):
        if self.sheet is not None:
            self.sheet_meta.config(text=self.meta())
        else:
            self.c.itemconfig("meta", text=self.meta())

    def tags_here(self):
        return self.c.gettags("current")

    def press(self, e):
        tags = self.tags_here()
        if any(t.startswith(("rail", "nav", "older", "tour")) for t in tags) or self.shot is None or self.index == 0:
            return
        row = next((t for t in tags if re.fullmatch(r"row\d+", t)), None)
        cut = next((t for t in tags if re.fullmatch(r"cut\d+", t)), None)
        head = next((t for t in tags if re.fullmatch(r"head\d+", t)), None)
        if self.tool == "logpick":
            row = next((int(t[4:]) for t in tags if re.fullmatch(r"lrow\d+", t)), None)
            head = next((int(t[5:]) for t in tags if re.fullmatch(r"lhead\d+", t)), None)
            if head is not None:
                self.toggle_chunk(head)
            elif row is not None:
                on = self.logview["items"][row][1] not in self.logview["on"]
                self.drag = {"kind": "log", "on": on, "first": row, "last": row}
                self.mark_log(row, row, on)
            return
        if self.tool == "lines":
            pick = next((t[4:] for t in tags if t.startswith("pop-") and not t.endswith("-bg")), None)
            if pick or self.popup:
                self.popup_pick(pick) if pick else self.close_popup()
                return
            home = next((int(t[4:]) for t in tags if re.fullmatch(r"home\d+", t)), None)
            if home is not None:
                self.next_home(home)
                return
            if not (head or cut or row):
                return
            j = int(head[4:] if head else (cut or row)[3:])
            name = self.items[j][3]
            self.part = None if name == self.name else name
            self.hint(None)
            if head:
                self.draw_lines(self.area())
            elif cut:
                self.toggle_cut(j)
            else:
                shot, i = self.items[j][:2]
                self.drag = {"kind": "rows", "keep": not shot["rows"][i]["keep"], "first": j, "last": j,
                             "shots": {}, "moved": False}
            return
        if self.tool == "blur":
            self.blur_press(e)
            return
        hit = self.scene_chat_at(e) if self.previewing() else None
        if hit:
            self.drag = {"kind": "scenechat", "x": e.x, "y": e.y, "hit": hit}
            self.c.config(cursor="fleur")
            return
        if self.view_box and self.inside(e, {"img": self.preview_rect}):
            self.drag = {"kind": "view", "x": e.x, "y": e.y, "at": (self.view["cx"], self.view["cy"]), "moved": False}
            self.loupe.hide()
            return
        shot = self.target
        if self.tool in DONORS + PREVIEWS or shot is None or self.previewing():
            return
        over = self.tool == "images"
        handle = next((t[7:] for t in tags if t.startswith("handle-")), None)
        if over and handle and self.painter.geo:
            item = shot["edit"]["overlays"][self.active_ov]
            box = self.painter.geo["overlays"][self.active_ov]
            size = self.source_size(item)
            if box and size:
                self.drag = {"kind": "crop", "handle": handle, "part": self.active_ov, "x": e.x, "y": e.y,
                             "crop": list(item["crop"]), "box": dict(box), "size": size}
            return
        ov = next((int(t[7:]) for t in tags if re.fullmatch(r"shot-ov\d+", t)), None)
        if over and ov is not None:
            self.active_ov = ov
            item = shot["edit"]["overlays"][ov]
            kind = "ovpan" if e.state & 0x1 else "ov"
            self.drag = {"kind": kind, "part": ov, "x": e.x, "y": e.y, "at": (item["x"], item["y"]),
                         "crop": list(item["crop"])}
            self.c.config(cursor="fleur")
            return
        geo = self.painter.geo
        part = next((int(t[9:]) for t in tags if re.fullmatch(r"shot-chat\d+", t)), None)
        if geo and part is not None and part < len(geo["chats"]) and geo["chats"][part]:
            self.drag = {"kind": "chat", "part": part, "x": e.x, "y": e.y, "at": self.c.coords(f"shot-chat{part}")}
        elif geo and self.tool == "crop" and self.inside(e, geo):
            self.drag = {"kind": "pan", "x": e.x, "y": e.y, "center": list(shot["edit"]["center"])}
            self.c.config(cursor="fleur")

    def inside(self, e, geo):
        ix, iy, dw, dh = geo["img"]
        return ix <= e.x <= ix + dw and iy <= e.y <= iy + dh

    def motion(self, e):
        if not self.drag:
            return
        geo = self.painter.geo
        if self.drag["kind"] == "log":
            j = self.log_item_at(e.y)
            if j != self.drag["last"]:
                self.drag["last"] = j
                self.mark_log(self.drag["first"], j, self.drag["on"])
        elif self.drag["kind"] == "rows":
            i = self.row_at(e.y)
            if i != self.drag["last"]:
                self.drag["moved"], self.drag["last"] = True, i
                self.mark_rows(self.drag["first"], i, self.drag)
        elif self.drag["kind"] == "chat":
            at = (self.drag["at"][0] + e.x - self.drag["x"], self.drag["at"][1] + e.y - self.drag["y"])
            self.c.coords(f"shot-chat{self.drag['part']}", *self.chat_spot(self.drag["part"], *at)[1:])
        elif self.drag["kind"] == "crop":
            self.drag_crop(e, geo)
        elif self.drag["kind"] == "scenechat":
            x0, y0, d = self.view_box
            rx, ry = self.preview_rect[:2]
            _, _, left, top, w, h = self.drag["hit"]
            x = rx + (left - x0) * d + e.x - self.drag["x"]
            y = ry + (top - y0) * d + e.y - self.drag["y"]
            self.c.delete("ghost")
            self.c.create_rectangle(x, y, x + w * d, y + h * d, outline=VOID, width=3, tags=("ghost",))
            self.c.create_rectangle(x, y, x + w * d, y + h * d, outline=WHITE, width=1, dash=(5, 3), tags=("ghost",))
        elif self.drag["kind"] == "view":
            dx, dy = e.x - self.drag["x"], e.y - self.drag["y"]
            if not self.drag["moved"] and max(abs(dx), abs(dy)) < px(4):
                return
            self.drag["moved"] = True
            self.c.config(cursor="fleur")
            H, W = self.preview.shape[:2]
            d = self.view_box[2]
            self.view["cx"] = self.drag["at"][0] - dx / d / W
            self.view["cy"] = self.drag["at"][1] - dy / d / H
            if not self.pending_media:
                self.pending_media = True
                self.c.after(16, self.flush_media)

        elif self.drag["kind"] in ("bnew", "bmove", "bsize"):
            self.blur_motion(e)
        elif self.drag["kind"] in ("ov", "ovpan"):
            ov = self.target["edit"]["overlays"][self.drag["part"]]
            (out_w, out_h), d = geo["out"], geo["d"]
            if self.drag["kind"] == "ov":
                ov["x"] = round(min(max(self.drag["at"][0] + (e.x - self.drag["x"]) / d / out_w, 0.0), 1.0), 4)
                ov["y"] = round(min(max(self.drag["at"][1] + (e.y - self.drag["y"]) / d / out_h, 0.0), 1.0), 4)
                self.snap_ov(ov, geo["overlays"][self.drag["part"]], geo)
            elif geo["overlays"][self.drag["part"]]:
                box = geo["overlays"][self.drag["part"]]
                l, t, r, b = self.drag["crop"]
                sx = min(max(-(e.x - self.drag["x"]) * (r - l) / box["w"], -l), 1 - r)
                sy = min(max(-(e.y - self.drag["y"]) * (b - t) / box["h"], -t), 1 - b)
                ov["crop"] = [round(l + sx, 4), round(t + sy, 4), round(r + sx, 4), round(b + sy, 4)]
                ov["cut"] = ov.get("cut", "free")
            if not self.pending_media:
                self.pending_media = True
                self.c.after(16, self.flush_media)
        else:
            shot = self.target
            H, W = shot["bg"].shape[:2]
            x0, y0, x1, y1 = geo["plan"]["rect"]
            k = (x1 - x0) / (geo["plan"]["base"][0] * geo["d"])
            cx = self.drag["center"][0] - (e.x - self.drag["x"]) * k / W
            cy = self.drag["center"][1] - (e.y - self.drag["y"]) * k / H
            shot["edit"]["center"] = [cx, cy]
            if not self.pending_media:
                self.pending_media = True
                self.c.after(16, self.flush_media)

    def loaded_members(self):
        return [(n, shot) for n, shot in self.members() if shot]

    def flush_media(self):
        self.pending_media = False
        self.media_redraw()

    def release(self, e):
        drag, self.drag = self.drag, None
        self.c.config(cursor="")
        if not drag or self.shot is None or drag["kind"] == "log":
            return
        if drag["kind"] == "scenechat":
            self.c.delete("ghost")
            self.drop_scene_chat(drag, e)
            return
        if drag["kind"] == "view":
            k = None if drag["moved"] or self.tool != "scene" else self.seam_at(e.y)
            if k is not None:
                self.seam = "all" if self.seam == str(k) else str(k)
                self.redraw()
            return
        if drag["kind"] == "rows":
            if not drag["moved"]:
                j = drag["first"]
                shot, i = self.items[j][:2]
                r, x = shot["rows"][i], (e.x - self.lines_x0) / self.lines_s
                word = next(((a, b) for a, b in chat.words(r) if a - 3 <= x <= b + 3), None)
                if r["keep"] and word and e.x >= self.lines_x0 - px(4):
                    self.open_popup(j, word)
                    return
                self.mark_rows(j, j, drag)
            for shot in drag["shots"].values():
                self.schedule_save(shot)
            return
        shot = self.target
        if shot is None:
            return
        if drag["kind"] in ("bnew", "bmove", "bsize"):
            self.blur_release(drag)
            return
        if drag["kind"] == "chat":
            at = (drag["at"][0] + e.x - drag["x"], drag["at"][1] + e.y - drag["y"])
            self.set_place(drag["part"], self.chat_spot(drag["part"], *at)[0])
        elif drag["kind"] in ("ov", "ovpan", "crop"):
            self.redraw()
            self.schedule_save()
            return
        else:
            look = self.look(shot)[0]
            H, W = shot["bg"].shape[:2]
            x0, y0, x1, y1 = chat.frame_rect(W, H, config.ratio_of(look["format"]), look["zoom"], look["center"])
            shot["edit"]["center"] = [round((x0 + x1) / 2 / W, 4), round((y0 + y1) / 2 / H, 4)]
        self.media_redraw()
        if self.tool == "text":
            self.redraw()
        self.schedule_save()

    def hover(self, e):
        if self.drag or self.index == 0 or self.shot is None:
            return
        tags = self.tags_here()
        rail = next((t[5:] for t in tags if t.startswith("rail-")), None)
        if any(t.startswith("tour") for t in tags):
            return
        if rail or any(t.startswith(("rail", "nav", "older")) for t in tags):
            self.loupe.hide()
            self.hint(RAIL_HINTS.get(rail))
            return
        if self.tool == "lines":
            self.hint(self.lines_hint(tags, e))
            return
        if self.tool == "logpick":
            head = any(re.fullmatch(r"lhead\d+", t) for t in tags)
            row = any(re.fullmatch(r"lrow\d+", t) for t in tags)
            self.hint("Клик — отметить весь кусок или снять с него отметки" if head else
                      "Клик — отметить строку · веди мышью, чтобы отметить несколько" if row else None)
            return
        if self.tool in DONORS:
            donor = any(re.fullmatch(r"donor\d+", t) for t in tags)
            self.hint({"carry": "Клик — добавить строки этой СС", "photopick": "Клик — положить фон этой СС поверх",
                       "scenepick": "Клик — добавить в сцену или убрать"}[self.tool] if donor else None)
            return
        if self.previewing():
            rect = self.preview_rect
            inside = self.preview is not None and rect and self.inside(e, {"img": rect})
            grab = inside and self.view_box and self.scene_chat_at(e) is not None
            seam = inside and self.view_box and self.tool == "scene" and self.seam_at(e.y) is not None
            self.c.config(cursor=("hand2" if seam else "fleur") if inside and self.view_box else "")
            if inside and not grab and (not self.view_box or self.view_box[2] < 1):
                self.loupe.show(e.x, e.y, rect, self.preview_view)
            else:
                self.loupe.hide()
            self.hint(None if not inside else
                      "Тяни чат — на переход, на другую СС или в её угол" if grab else
                      "Клик — настроить только этот переход" if seam else
                      "Тяни — двигать · колесо — прокрутка · Ctrl + колесо — масштаб" if self.view_box else
                      "Точно как в файле · лупа показывает пиксели 1:1")
            return
        if self.tool == "blur":
            self.blur_hover(e)
            return
        over = self.tool == "images"
        if "shot-chat" in tags:
            self.c.config(cursor="fleur")
            self.hint("Тяни чат мышью — у края он сам встанет на отступ")
        elif over and any(t.startswith("handle-") for t in tags):
            self.hint("Тяни — обрезать картинку")
        elif over and "shot-ov" in tags:
            self.c.config(cursor="fleur")
            self.hint("Тяни — двигать · колесо — размер · Shift + тяни — сдвинуть обрезку")
        elif self.tool == "crop" and self.painter.geo and self.inside(e, self.painter.geo):
            self.c.config(cursor="fleur")
            self.hint("Тяни — выбрать, что в кадре · колесо — приближение")
        else:
            self.c.config(cursor="")
            self.hint(None)

    def wheel(self, e):
        step = -1 if e.delta > 0 else 1
        if self.popup:
            self.close_popup()
        if self.tool == "logpick" and self.logview and self.logview["offset"] is not None:
            self.logview["offset"] += step * px(72)
            self.draw_log(self.area())
            return
        if self.view_box:
            if e.state & 0x4:
                self.zoom_view(self.view["zoom"] * (1.25 if step < 0 else 0.8), (e.x, e.y))
            else:
                x0, y0, d = self.view_box
                self.view["cy"] += step * 0.25 * self.preview_rect[3] / d / self.preview.shape[0]
                self.media_redraw()
            self.loupe.hide()
            return
        if self.tool == "lines" and self.shot is not None:
            self.offset += step * px(72)
            self.draw_lines(self.area())
            return
        shot = self.target
        ov = next((int(t[7:]) for t in self.tags_here() if re.fullmatch(r"shot-ov\d+", t)), None)
        if self.tool == "images" and shot is not None and ov is not None:
            item = shot["edit"]["overlays"][ov]
            item["w"] = round(min(max(item["w"] * (1.08 if step < 0 else 1 / 1.08), 0.05), 2.0), 4)
            self.active_ov = ov
            self.media_redraw()
            self.schedule_save()
            return
        if self.tool == "crop" and shot is not None:
            zoom = min(3.0, max(1.0, round(shot["edit"]["zoom"] - step * 0.1, 2)))
            self.change(zoom=zoom)
            return
        now = time.monotonic()
        if self.tool is None and now - self.last_wheel > 0.25:
            self.last_wheel = now
            self.go(self.index + step)

    def schedule_save(self, shot=None):
        shot = shot or self.target
        if shot is None:
            return
        self.record(shot)
        self.note = "сохраняю…"
        self.update_meta()
        if self.save_job:
            self.c.after_cancel(self.save_job)
        self.saves[shot["name"]] = shot
        self.save_job = self.c.after(450, self.save_now)

    @staticmethod
    def state_of(shot):
        edit = json.loads(json.dumps(shot["edit"]))
        marks = json.loads(json.dumps([[r["keep"], r.get("hide") or [], r.get("drop") or []] for r in shot["rows"]]))
        return {"edit": edit, "marks": marks, "key": json.dumps([edit, marks], sort_keys=True)}

    def remember(self, shot):
        if shot and shot["name"] not in self.known:
            self.known[shot["name"]] = self.state_of(shot)

    def forget(self, name):
        self.known.pop(name, None)
        self.history = [h for h in self.history if h[0] != name]
        self.future = [h for h in self.future if h[0] != name]

    def record(self, shot):
        name, new = shot["name"], self.state_of(shot)
        old = self.known.get(name)
        self.known[name] = new
        if self.replaying or old is None or old["key"] == new["key"]:
            return
        if len(old["marks"]) != len(new["marks"]):
            self.forget(name)
            self.known[name] = new
            return
        keys = {k for k in old["edit"].keys() | new["edit"].keys() if old["edit"].get(k) != new["edit"].get(k)}
        keys |= {"marks"} if old["marks"] != new["marks"] else set()
        now = time.monotonic()
        last = self.last_push
        if not (last and last[0] == name and last[1] == keys and now - last[2] < UNDO_MERGE_S):
            self.history.append((name, old))
            del self.history[:-UNDO_MAX]
        self.last_push = (name, keys, now)
        self.future.clear()

    def undo(self, back=True):
        src, dst = (self.history, self.future) if back else (self.future, self.history)
        scope = {self.name, *self.scene_names()}
        k = next((k for k in range(len(src) - 1, -1, -1) if src[k][0] in scope), None)
        shot = None if k is None else self.member(src[k][0])
        if shot is None:
            self.note = "нечего отменять" if back else "нечего вернуть"
            self.update_meta()
            return
        name, state = src.pop(k)
        dst.append((name, self.known.get(name) or self.state_of(shot)))
        shot["edit"].clear()
        shot["edit"].update(json.loads(json.dumps(state["edit"])))
        for r, (keep, hide, drop) in zip(shot["rows"], state["marks"]):
            r["keep"], r["hide"], r["drop"] = keep, [tuple(w) for w in hide], [tuple(w) for w in drop]
        self.last_push, self.replaying = None, True
        try:
            self.schedule_save(shot)
        finally:
            self.replaying = False
        self.note = "отменено" if back else "возвращено"
        self.close_popup()
        self.redraw()
        if self.previewing():
            self.want_preview()

    def flush_save(self):
        if self.save_job:
            self.c.after_cancel(self.save_job)
            self.save_now()

    def save_sync(self):
        if self.save_job:
            self.c.after_cancel(self.save_job)
            self.save_job = None
            snaps, self.saves = [self.snapshot(s) for s in self.saves.values()], {}
            self.store(snaps, lambda *_: None)

    def snapshot(self, shot=None, deep=True):
        shot = shot or self.shot
        snap = {**shot, "rows": [dict(r) for r in shot["rows"]], "edit": json.loads(json.dumps(shot["edit"]))}
        scene = shot["edit"].get("scene") if deep else None
        if scene:
            snap["members"] = {n: self.snapshot(m, False) for n in scene["shots"]
                               if n != shot["name"] and (m := self.cache.get(n))}
        return snap

    def save_now(self):
        self.save_job = None
        snaps, self.saves = [self.snapshot(s) for s in self.saves.values()], {}
        if snaps:
            self.save_queue.put(snaps)

    def save_loop(self):
        while True:
            self.store(self.save_queue.get(), lambda *a: self.app.inbox.put(("saved",) + a))

    @staticmethod
    def store(snaps, report):
        snaps.sort(key=lambda snap: bool(snap["edit"].get("scene")))
        for snap in snaps:
            try:
                store.save_shot(snap, heads=False)
                report(snap["name"], None)
            except Exception as e:
                report(snap["name"], str(e))
        if snaps:
            names = [snap["name"] for snap in snaps]
            for head in store.refresh_heads(snaps[0]["out"], names, snaps[0].get("cfg"), names):
                report(head, None)

    def saved(self, name, error):
        self.media = None
        if name in (self.name, self.part):
            self.note = f"не сохранилось: {error}" if error else "сохранено"
            self.update_meta()
        if self.shot is not None and name in self.scene_names() and self.drag is None:
            if self.previewing() and name != self.name:
                self.want_preview()
            elif self.tool is None:
                self.redraw()

    def copy(self):
        name = self.name
        snap = self.snapshot() if self.shot is not None else None
        path = store.shot_image(self.app.cfg["out"], name)
        self.note = "копирую…"
        self.update_meta()

        def work():
            try:
                img = store.render_shot(snap)[0] if snap else store.read_image(path)
                winui.copy_image(img)
                self.app.inbox.put(("copied", name, None))
            except Exception as e:
                self.app.inbox.put(("copied", name, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def copied(self, name, error):
        if name == self.name:
            self.note = f"не скопировалось: {error}" if error else "скопировано, вставляй через Ctrl+V"
            self.update_meta()

    def open_folder(self):
        out = self.app.cfg["out"]
        out.mkdir(parents=True, exist_ok=True)
        path = store.shot_image(out, self.name) if self.name else None
        if path and path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(out)

    def key(self, e):
        if e.keysym in ("Up", "Prior"):
            self.go(self.index - 1)
        elif e.keysym in ("Down", "Next"):
            self.go(self.index + 1)
        elif e.keysym == "Escape" and self.tour:
            self.tour.finish()
        elif e.keysym == "Escape" and self.popup:
            self.close_popup()
        elif e.keysym == "Escape" and self.tool:
            self.toggle_tool(self.tool)
        elif e.keysym == "Delete" and self.tool == "blur" and self.drag is None:
            self.remove_blur()
        elif e.keycode == 67 and e.state & 0x4 and self.index > 0:
            self.copy()
        elif e.keycode in (89, 90) and e.state & 0x4 and self.shot is not None and self.drag is None:
            self.undo(back=e.keycode == 90 and not e.state & 0x1)
        elif 49 <= e.keycode < 49 + len(TOOLS) and self.shot is not None and self.index > 0:
            self.toggle_tool(TOOLS[e.keycode - 49])
