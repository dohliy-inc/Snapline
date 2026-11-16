import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageTk

import compose
from theme import FONT, ICONS, SUB, VOID, WHITE, px, when
from widgets import Pill


class SceneTool:
    def seams(self):
        given = self.shot["edit"]["scene"].get("seams") or []
        return [dict(compose.SEAM, **(given[k] if k < len(given) else {})) for k in range(len(self.scene_names()) - 1)]

    def scene_plan(self):
        head = self.shot["edit"]
        width = compose.plan(self.shot["bg"], compose.framed(head, head))["size"][0]
        hs = [compose.plan(s["bg"], compose.framed(s["edit"], head), width)["size"][1] if s else None
              for _, s in self.members()]
        mine = hs[self.scene_names().index(self.name)]
        hs = [h or mine for h in hs]
        return width, hs, compose.laps_of(hs, self.seams())

    def scene_size(self):
        width, hs, laps = self.scene_plan()
        return width, sum(hs) - sum(laps)

    def draw_scene(self, area):
        ax, ay, aw, ah = area
        if self.tool is None:
            self.draw_saved(area, self.name)
            return
        if self.preview is None:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="Собираю сцену…", fill=SUB, font=(FONT["ui"], 12),
                               tags=("shot",))
            return
        arr, view = self.preview, self.view
        H, W = arr.shape[:2]
        fit = min(aw / W, ah / H)
        view["zoom"] = min(max(view["zoom"], 1.0), max(1.0, 4 / fit))
        d = fit * view["zoom"]
        vw, vh = max(1, min(aw, round(W * d))), max(1, min(ah, round(H * d)))
        sw, sh = min(W, vw / d), min(H, vh / d)
        x0 = max(0.0, min(view["cx"] * W - sw / 2, W - sw))
        y0 = max(0.0, min(view["cy"] * H - sh / 2, H - sh))
        view["cx"], view["cy"] = (x0 + sw / 2) / W, (y0 + sh / 2) / H
        rect = (ax + (aw - vw) // 2, ay + (ah - vh) // 2, vw, vh)
        self.view_box, self.preview_rect = (x0, y0, d), rect
        self.preview_view = arr[int(y0):int(y0 + sh), int(x0):int(x0 + sw)]
        key = (id(arr), rect, round(x0, 2), round(y0, 2))
        if self.preview_photo is None or self.preview_photo[0] != key:
            if self.preview_img is None or self.preview_img[0] is not arr:
                self.preview_img = (arr, Image.fromarray(arr))
            img = self.preview_img[1].resize((vw, vh), Image.NEAREST if d >= 2 else Image.BILINEAR,
                                             box=(x0, y0, x0 + sw, y0 + sh), reducing_gap=None if d >= 1 else 2.0)
            self.preview_photo = (key, ImageTk.PhotoImage(img))
        self.c.create_image(rect[0], rect[1], anchor="nw", image=self.preview_photo[1], tags=("shot",))
        if self.seam == "all" or not self.layout or int(self.seam) >= len(self.layout["laps"]):
            return
        k = int(self.seam)
        top = self.layout["tops"][k + 1]
        edges = sorted({top, top + self.layout["laps"][k]})
        ix, iy = rect[:2]
        if iy + (edges[-1] - y0) * d < iy or iy + (edges[0] - y0) * d > iy + vh:
            return
        for y in edges:
            sy = iy + (y - y0) * d
            if iy <= sy <= iy + vh:
                self.c.create_line(ix, sy + 1, ix + vw, sy + 1, fill=VOID, width=2, tags=("shot",))
                self.c.create_line(ix, sy, ix + vw, sy, fill=WHITE, width=2, dash=(6, 4), tags=("shot",))
        label = f"переход {k + 1}–{k + 2}"
        ly = min(max(iy + (edges[0] - y0) * d - px(24), iy + px(4)), iy + vh - px(24))
        tw = tkfont.Font(family=FONT["semi"], size=9).measure(label) + px(16)
        self.c.create_rectangle(ix + px(6), ly, ix + px(6) + tw, ly + px(20), fill=VOID, outline="", tags=("shot",))
        self.c.create_text(ix + px(6) + tw / 2, ly + px(10), text=label, fill=WHITE, font=(FONT["semi"], 9),
                           tags=("shot",))

    def seam_at(self, y):
        if not self.view_box or not self.layout:
            return None
        x0, y0, d = self.view_box
        sy = y0 + (y - self.preview_rect[1]) / d
        near = px(8) / d
        for k, lap in enumerate(self.layout["laps"]):
            top = self.layout["tops"][k + 1]
            if top - near <= sy <= top + lap + near:
                return k
        return None

    def sheet_scene(self, body):
        scene, names = self.shot["edit"].get("scene"), self.scene_names()
        self.label(body, "Несколько СС одна под другой с плавными переходами — раскадровка для форума. Чат можно "
                         "тянуть мышью прямо здесь: на переход или на другую СС.")
        self.buttons(body, (("Выбрать СС", lambda: self.toggle_tool("scenepick")),) +
                     ((("Разобрать", self.drop_scene),) if names else ()))
        self.file_info = tk.Label(body, text=self.preview_info or "собираю…", bg=VOID, fg=WHITE,
                                  font=(FONT["semi"], 12), anchor="w")
        if not names:
            return
        self.field(body, "Порядок", 18)
        for k, name in enumerate(names):
            self.frame_row(body, k, name, len(names))
        seams = {"all": "Все"} | {str(k): f"{k + 1}–{k + 2}" for k in range(len(names) - 1)}
        self.seam = self.seam if self.seam in seams else "all"
        look = scene["seams"][0 if self.seam == "all" else int(self.seam)]
        pct = lambda v: f"{v:.0f}%"
        self.field(body, "Переход", 10)
        self.choice(body, seams, self.seam, self.pick_seam)
        self.field(body, "Плавность")
        self.slider(body, 0, 50, round(look["fade"] * 100), lambda v: self.change_seam(fade=v / 100), fmt=pct)
        self.field(body, "Размытие")
        self.slider(body, 0, 100, round(look["blur"] * 100), lambda v: self.change_seam(blur=v / 100), fmt=pct)
        self.field(body, "Затемнение")
        self.slider(body, 0, 100, round(look["dark"] * 100), lambda v: self.change_seam(dark=v / 100), fmt=pct)
        self.field(body, "Просмотр", 10)
        self.buttons(body, (("Целиком", lambda: self.view_fit("all")), ("По ширине", lambda: self.view_fit("width")),
                            ("1:1", lambda: self.view_fit("real"))))
        self.file_info.pack(fill="x", pady=(px(14), px(2)))

    def frame_row(self, body, k, name, count):
        mine = name == self.name
        row = tk.Frame(body, bg=VOID)
        row.pack(fill="x", pady=(0, px(4)))
        photo = self.frame_thumb(name)
        pick = []
        if photo:
            pick.append(tk.Label(row, image=photo, bg=VOID, cursor="hand2"))
            pick[-1].pack(side="left", padx=(0, px(8)))
        pick.append(tk.Label(row, text=f"{k + 1}. {when(name)}" + (" · эта" if mine else ""), bg=VOID,
                             fg=WHITE if mine else SUB, font=(FONT["ui"], 10), cursor="hand2"))
        pick[-1].pack(side="left")
        for w in pick:
            w.bind("<Button-1>", lambda _, k=k: self.focus_frame(k))
            w.bind("<Enter>", lambda _: self.hint("Показать эту СС в сцене крупно"))
            w.bind("<Leave>", lambda _: self.hint(None))
        for key, text, on, command, tip in (
                ("close", "×", not mine, lambda: self.drop_frame(k), "Убрать из сцены"),
                ("down", "↓", k < count - 1, lambda: self.move_frame(k, 1), "Ниже"),
                ("up", "↑", k > 0, lambda: self.move_frame(k, -1), "Выше"),
                ("crop", "▭", True, lambda: self.edit_frame(name), "Поправить эту СС: кадр, текст, картинки")):
            glyph, face = (ICONS[key], (FONT["icon"], 11)) if FONT["icon"] else (text, (FONT["ui"], 11))
            button = tk.Label(row, text=glyph, font=face, bg=VOID, fg=SUB if on else VOID, width=2,
                              cursor="hand2" if on else "")
            button.pack(side="right")
            if on:
                button.bind("<Button-1>", lambda _, f=command: f())
                button.bind("<Enter>", lambda _, b=button, t=tip: (b.config(fg=WHITE), self.hint(t)))
                button.bind("<Leave>", lambda _, b=button: (b.config(fg=SUB), self.hint(None)))

    def edit_frame(self, name):
        self.part = None if name == self.name else name
        self.toggle_tool("crop")

    def frame_thumb(self, name):
        size = (px(54), px(32))
        if name != self.name:
            return self.thumb(self.shot["out"], name, size)
        bg, edit = self.shot["bg"], self.shot["edit"]
        key = ("bg", id(bg), size, bool(edit.get("mirror")), edit.get("tilt", 0))
        if key not in self.thumbs:
            im = Image.fromarray(compose.bg_part(bg, compose.plan(bg, edit)["rect"], edit.get("mirror")))
            im = compose.tilt_image(im, edit.get("tilt", 0), im.size)
            im.thumbnail(size, Image.BILINEAR, reducing_gap=2.0)
            self.thumbs[key] = ImageTk.PhotoImage(im)
        return self.thumbs[key]

    def sheet_scenepick(self, body):
        self.label(body, "Отметь СС и нажми «Готово». Они встанут по времени съёмки и получат формат кадра этой СС, "
                         f"а строки, которые уже были выше, уберутся сами. До {compose.SCENE_MAX} СС.")
        Pill(body, "Готово", lambda: self.toggle_tool("scene"), kind="ghost").pack(anchor="w", pady=(px(8), 0))

    def scene_lists(self):
        scene = self.shot["edit"].get("scene") or {"shots": [self.name], "seams": []}
        return list(scene["shots"]), [dict(s) for s in scene["seams"]]

    def set_scene(self, shots, seams):
        self.shot["edit"]["scene"] = {"shots": shots, "seams": seams} if len(shots) > 1 else None
        self.schedule_save()

    def toggle_scene(self, name):
        shots, seams = self.scene_lists()
        if name in shots:
            k = shots.index(name)
            shots.pop(k)
            seams.pop(max(k - 1, 0))
        elif len(shots) >= compose.SCENE_MAX:
            self.note = f"в сцену помещается до {compose.SCENE_MAX} СС"
            self.update_meta()
            return
        else:
            k = next((i for i, n in enumerate(shots) if n > name), len(shots))
            shots.insert(k, name)
            self.fetch(name)
            self.added.add(name)
            near = max(k - 1, 0)
            seams.insert(near, dict(seams[min(near, len(seams) - 1)] if seams else compose.SEAM))
        self.set_scene(shots, seams)
        self.draw_donors(self.area())
        self.update_meta()

    def move_frame(self, k, delta):
        shots, seams = self.scene_lists()
        shots[k], shots[k + delta] = shots[k + delta], shots[k]
        self.set_scene(shots, seams)
        self.want_preview()
        self.redraw()

    def drop_frame(self, k):
        shots, seams = self.scene_lists()
        shots.pop(k)
        seams.pop(max(k - 1, 0))
        self.set_scene(shots, seams)
        self.want_preview()
        self.redraw()

    def pick_seam(self, value):
        self.seam = value
        self.redraw()

    def change_seam(self, **values):
        seams = self.shot["edit"]["scene"]["seams"]
        for k in range(len(seams)) if self.seam == "all" else (int(self.seam),):
            seams[k].update(values)
        self.want_preview()
        self.schedule_save()

    def drop_scene(self):
        self.shot["edit"]["scene"] = None
        self.preview = self.preview_info = None
        self.want_preview()
        self.redraw()
        self.schedule_save()
