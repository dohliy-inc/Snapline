import styles
from theme import BLUR_NAMES, VOID, WHITE, px

CORNERS = ("lt", "rt", "lb", "rb")


class BlurTool:
    def sheet_blur(self, body):
        k, b = self.current_blur()
        self.label(body, "Обведи мышью по кадру, что нужно спрятать: номер машины, лицо, ник или кусок интерфейса.", 0)
        if b is None:
            return
        count = len(self.target["edit"]["blurs"])
        self.field(body, f"Область {k + 1} из {count}")
        self.choice(body, BLUR_NAMES, b.get("mode", "blur"), lambda v: self.set_blur(mode=v))
        self.field(body, "Сила")
        bar = self.slider(body, 10, 100, round(b.get("power", 0.6) * 100),
                          lambda v: self.set_blur(power=round(v / 100, 2)), fmt=lambda v: f"{v:.0f}%")
        self.sliders["blur"] = (bar, lambda: round((self.current_blur()[1] or {}).get("power", 0.6) * 100))
        self.buttons(body, (("Удалить область", self.remove_blur),) +
                     ((("Удалить все", self.clear_blurs),) if count > 1 else ()), 12)
        self.label(body, "Клик по области выбирает её, тяни углы — размер, Delete — удалить.", 6)

    def current_blur(self):
        blurs = (self.target or {}).get("edit", {}).get("blurs") or []
        if not blurs:
            return None, None
        self.active_blur = min(max(self.active_blur, 0), len(blurs) - 1)
        return self.active_blur, blurs[self.active_blur]

    def set_blur(self, **values):
        k, b = self.current_blur()
        if b is not None:
            blurs = [dict(x) for x in self.target["edit"]["blurs"]]
            blurs[k].update(values)
            self.change(blurs=blurs)

    def remove_blur(self):
        k, b = self.current_blur()
        if b is not None:
            blurs = [dict(x) for i, x in enumerate(self.target["edit"]["blurs"]) if i != k]
            self.active_blur = max(0, k - 1)
            self.change(blurs=blurs)
            self.redraw()

    def clear_blurs(self):
        self.change(blurs=[])
        self.redraw()

    def blur_point(self, e, geo):
        ix, iy, dw, dh = geo["img"]
        return (round(min(max((e.x - ix) / dw, 0.0), 1.0), 4), round(min(max((e.y - iy) / dh, 0.0), 1.0), 4))

    def blur_at(self, e, geo):
        boxes = geo.get("blurs") or []
        if self.active_blur < len(boxes):
            x0, y0, x1, y1 = boxes[self.active_blur]
            for name, (cx, cy) in zip(CORNERS, ((x0, y0), (x1, y0), (x0, y1), (x1, y1))):
                if abs(e.x - cx) <= px(8) and abs(e.y - cy) <= px(8):
                    return "handle", name
        for k in range(len(boxes) - 1, -1, -1):
            x0, y0, x1, y1 = boxes[k]
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return "box", k
        return None

    def draw_blurs(self, geo):
        ix, iy, dw, dh = geo["img"]
        geo["blurs"] = []
        blurs = self.target["edit"].get("blurs") or []
        for k, b in enumerate(blurs):
            x0, y0 = ix + b["x"] * dw, iy + b["y"] * dh
            x1, y1 = x0 + b["w"] * dw, y0 + b["h"] * dh
            geo["blurs"].append((x0, y0, x1, y1))
            on = k == self.active_blur
            self.c.create_rectangle(x0, y0, x1, y1, outline=VOID, width=3, tags=("shot",))
            self.c.create_rectangle(x0, y0, x1, y1, outline=WHITE, width=1, dash=() if on else (4, 3), tags=("shot",))
            if on:
                r = px(4)
                for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                    self.c.create_rectangle(cx - r, cy - r, cx + r, cy + r, fill=WHITE, outline=VOID, tags=("shot",))

    def blur_press(self, e):
        geo, shot = self.painter.geo, self.target
        if not geo or shot is None or not self.inside(e, geo):
            return
        before = shot["edit"].get("blurs")
        blurs = before or []
        hit = self.blur_at(e, geo)
        at = self.blur_point(e, geo)
        if hit and hit[0] == "handle":
            self.drag = {"kind": "bsize", "k": self.active_blur, "corner": hit[1], "box": dict(blurs[self.active_blur])}
        elif hit:
            self.active_blur = hit[1]
            self.drag = {"kind": "bmove", "k": hit[1], "at": at, "box": dict(blurs[hit[1]])}
            self.c.config(cursor="fleur")
        elif len(blurs) < styles.BLUR_MAX:
            _, last = self.current_blur()
            last = last or {}
            shot["edit"]["blurs"] = blurs + [{"x": at[0], "y": at[1], "w": 0.0, "h": 0.0,
                                               "mode": last.get("mode", "blur"), "power": last.get("power", 0.6)}]
            self.active_blur = len(blurs)
            self.drag = {"kind": "bnew", "k": self.active_blur, "at": at, "before": before}
        else:
            self.note = f"больше {styles.BLUR_MAX} областей не поместится"
            self.update_meta()

    def blur_motion(self, e):
        geo, drag = self.painter.geo, self.drag
        b = self.target["edit"]["blurs"][drag["k"]]
        fx, fy = self.blur_point(e, geo)
        if drag["kind"] == "bnew":
            sx, sy = drag["at"]
            l, t, r, bottom = min(sx, fx), min(sy, fy), max(sx, fx), max(sy, fy)
        elif drag["kind"] == "bmove":
            o, (ax, ay) = drag["box"], drag["at"]
            l = min(max(o["x"] + fx - ax, 0.0), 1.0 - o["w"])
            t = min(max(o["y"] + fy - ay, 0.0), 1.0 - o["h"])
            r, bottom = l + o["w"], t + o["h"]
        else:
            o, c = drag["box"], drag["corner"]
            l, t, r, bottom = o["x"], o["y"], o["x"] + o["w"], o["y"] + o["h"]
            l, r = (fx, r) if "l" in c else (l, fx)
            t, bottom = (fy, bottom) if "t" in c else (t, fy)
            l, r, t, bottom = min(l, r), max(l, r), min(t, bottom), max(t, bottom)
        b.update(x=round(l, 4), y=round(t, 4), w=round(r - l, 4), h=round(bottom - t, 4))
        if not self.pending_media:
            self.pending_media = True
            self.c.after(16, self.flush_media)

    def blur_release(self, drag):
        edit, geo = self.target["edit"], self.painter.geo
        b = edit["blurs"][drag["k"]]
        if drag["kind"] == "bnew" and (b["w"] * geo["img"][2] < px(6) or b["h"] * geo["img"][3] < px(6)):
            if drag["before"] is None:
                edit.pop("blurs", None)
            else:
                edit["blurs"] = drag["before"]
            self.active_blur = max(0, drag["k"] - 1)
            self.redraw()
            return
        self.redraw()
        self.schedule_save()

    def blur_hover(self, e):
        geo = self.painter.geo
        hit = self.blur_at(e, geo) if geo else None
        if hit and hit[0] == "handle":
            self.c.config(cursor="sizing")
            self.hint("Тяни — изменить размер области")
        elif hit:
            self.c.config(cursor="fleur")
            self.hint("Тяни — двигать · Delete — удалить")
        elif geo and self.inside(e, geo):
            self.c.config(cursor="crosshair")
            self.hint("Обведи мышью, что спрятать")
        else:
            self.c.config(cursor="")
            self.hint(None)
