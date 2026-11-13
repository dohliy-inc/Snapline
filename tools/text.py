import tkinter as tk

import chat
import compose
from theme import FONT, OUTLINES, SCALES, VIEWS, VOID, WHITE, place_name, px
from widgets import Corners


class TextTool:
    def sheet_text(self, body):
        shot, names = self.target, self.scene_names()
        edit = shot["edit"]
        whole = " · вся сцена" if names else ""
        if names:
            self.field(body, "Показывать", 0)
            self.choice(body, VIEWS, "all" if self.whole else "one", self.set_whole)
            if self.whole:
                self.label(body, "Тяни чат любой СС мышью прямо по сцене: на переход, на соседнюю СС или в её угол. "
                                 "Колесо — прокрутка, Ctrl + колесо — масштаб.", 8)
        self.field(body, "Размер текста" + whole, 14 if names else 0)
        self.choice(body, SCALES, edit["text_scale"], lambda v: self.change_text(text_scale=float(v)))
        self.field(body, "Обводка" + whole)
        self.choice(body, OUTLINES, edit["outline"], lambda v: self.change_text(outline=int(v)))
        self.field(body, "Отступ от края" + whole)
        margin = self.slider(body, 0, 96, edit["margin"], lambda v: self.change_text(margin=int(v)), step=2,
                             fmt=lambda v: f"{v:.0f} px")
        self.sliders["margin"] = (margin, lambda: shot["edit"]["margin"])
        spots = [pos for _, pos in compose.parts(shot["rows"], edit)]
        self.field(body, "Где чат" if len(spots) == 1 else "Где части чата")
        for k, pos in enumerate(spots):
            row = tk.Frame(body, bg=VOID)
            row.pack(anchor="w", pady=(0, px(6)))
            Corners(row, pos if isinstance(pos, str) else None, lambda v, k=k: self.pick_place(k, v)).pack(side="left")
            text = ("" if len(spots) == 1 else f"Часть {k + 1} · ") + place_name(pos)
            tk.Label(row, text=text, bg=VOID, fg=WHITE, font=(FONT["ui"], 10)).pack(side="left", padx=(px(10), 0))
        self.label(body, "Клик по углу ставит туда чат. Его можно и тянуть мышью по картинке.", 6)

    def change_text(self, **values):
        shots = [s for _, s in self.members() if s] if self.scene_names() else [self.target]
        for shot in shots:
            shot["edit"].update(values)
            self.schedule_save(shot)
        self.media_redraw()
        if self.previewing():
            self.want_preview()

    def set_whole(self, value):
        self.whole = value == "all"
        if self.whole:
            self.fetch_scene()
            self.preview = self.preview_info = None
            self.want_preview()
        self.redraw()

    def chat_spot(self, part, x, y):
        geo = self.painter.geo
        ix, iy = geo["img"][:2]
        d, pad, margin = geo["d"], geo["pad"], geo["plan"]["margin"]
        (W, H), (it, ib) = geo["out"], geo["inset"]
        inner = H - it - ib
        lw, lh = geo["chats"][part]["lw"], geo["chats"][part]["lh"]
        left, top = (x - ix) / d + pad, (y - iy) / d - it + pad
        near = margin + 0.04 * min(W, inner)
        hx = "left" if left < near else "right" if left + lw - 2 * pad > W - near else round(left / W, 4)
        vy = "top" if top < near else "bottom" if top + lh - 2 * pad > inner - near else round(top / inner, 4)
        pos = f"{vy}-{hx}" if isinstance(hx, str) and isinstance(vy, str) else [hx, vy]
        left, top = chat.place(W, inner, lw, lh, pad, pos, margin)
        return pos, ix + left * d, iy + (top + it) * d

    def scene_chat_at(self, e):
        if not self.view_box or not self.layout or not self.layout.get("chats"):
            return None
        x0, y0, d = self.view_box
        x, y = x0 + (e.x - self.preview_rect[0]) / d, y0 + (e.y - self.preview_rect[1]) / d
        return next((c for c in reversed(self.layout["chats"])
                     if c[2] <= x <= c[2] + c[4] and c[3] <= y <= c[3] + c[5]), None)

    def drop_scene_chat(self, drag, e):
        k, part, left, top, lw, lh = drag["hit"]
        layout, d = self.layout, self.view_box[2]
        names = layout.get("names") or [n for n, _ in self.loaded_members()]
        if k >= len(names) or max(abs(e.x - drag["x"]), abs(e.y - drag["y"])) < px(4):
            return
        name, shot = names[k], self.member(names[k])
        if shot is None:
            self.note = "эта СС не открылась, чат не перенёсся"
            self.update_meta()
            return
        pad, margin, W = layout["pads"][k], layout["margins"][k], self.preview.shape[1]
        left, top = left + (e.x - drag["x"]) / d + pad, top + (e.y - drag["y"]) / d + pad
        w, h = lw - 2 * pad, lh - 2 * pad
        mid = top + h / 2
        j = next((n for n, (a, b) in enumerate(layout["spans"]) if mid < b), len(layout["spans"]) - 1)
        a, b = layout["spans"][j]
        inner, top = b - a, top - a
        near = margin + 0.04 * min(W, inner)
        hx = "left" if left < near else "right" if left + w > W - near else None
        vy = None if top < 0 or top + h > inner else "top" if top < near else "bottom" if top + h > inner - near else None
        if hx and vy:
            pos = f"{vy}-{hx}"
        else:
            x = {"left": margin, "right": W - margin - w}.get(hx, left)
            y = {"top": margin, "bottom": inner - margin - h}.get(vy, top)
            pos = [round(min(max(x, 0), W - w) / W, 4), round(y / inner, 4)]
        edit = shot["edit"]
        if part == 0:
            edit["pos"] = pos
        else:
            spots = compose.places(edit, len(compose.parts(shot["rows"], edit)))[1:]
            spots[part - 1] = pos
            edit["places"] = spots
        edit["home"] = None if j == k else names[j]
        self.schedule_save(shot)
        self.want_preview()
        self.note = f"чат СС {k + 1} теперь на СС {j + 1}" if j != k else ""
        self.update_meta()
