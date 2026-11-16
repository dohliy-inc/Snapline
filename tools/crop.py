import compose
from theme import FIELD_DEFAULT, SIDES
from widgets import FramePick, SizePick


class CropTool:
    def sheet_crop(self, body):
        shot, names = self.target, self.scene_names()
        edit, look = shot["edit"], self.look(shot)[0]
        whole = " · вся сцена" if names else ""
        self.field(body, "Формат" + whole, 0)
        FramePick(body, look["format"], self.set_frame, lambda: compose.plan(shot["bg"], self.look(shot)[0])["base"],
                  self.sheet_w).pack(anchor="w")
        self.field(body, "Размер" + whole)
        self.size_pick = SizePick(body, look["size"], self.set_size, self.sheet_w)
        self.size_pick.pack(fill="x")
        self.size_pick.show(look["format"])
        self.field(body, "Приближение")
        zoom = self.slider(body, 1.0, 3.0, edit["zoom"], lambda v: self.change(zoom=v), step=0.05,
                           fmt=lambda v: f"{v:.2f}×")
        self.sliders["zoom"] = (zoom, lambda: shot["edit"]["zoom"])
        self.field(body, "Наклон")
        tilt = self.slider(body, -compose.TILT_MAX, compose.TILT_MAX, edit.get("tilt", 0),
                           lambda v: self.change(tilt=round(v)), fmt=lambda v: f"{v:.0f}°")
        self.sliders["tilt"] = (tilt, lambda: shot["edit"].get("tilt", 0))
        self.buttons(body, (("По центру", lambda: self.change(center=[0.5, 0.5])), ("Отразить", self.mirror_frame)), 12)
        if names:
            self.label(body, "Тёмные полосы сверху и снизу — переходы между СС, чат на них не заходит.", 12)
            return
        join = edit.get("join") or {}
        side = join.get("side") if join.get("side") in compose.JOIN_SIDES else "none"
        self.field(body, "Расширить поле кадра", 18)
        self.choice(body, SIDES, side, self.set_field_side)
        if side == "none":
            self.label(body, "Место сбоку для второго ракурса или чата, СС остаётся своего размера.", 4)
            return
        pct = lambda v: f"{v:.0f}%"
        self.field(body, "Насколько")
        self.slider(body, 10, 100, round(join["size"] * 100), lambda v: self.change_field(size=v / 100), fmt=pct)
        self.field(body, "Мягкий край СС")
        self.slider(body, 0, 100, round(join["fade"] * 100), lambda v: self.change_field(fade=v / 100), fmt=pct)
        self.label(body, "Новое место заполнено размытым продолжением СС.", 10)

    def mirror_frame(self):
        shot = self.target
        edit = shot["edit"]
        blurs = compose.mirror_blurs(edit.get("blurs") or [], compose.plan(shot["bg"], self.look(shot)[0]))
        self.change(mirror=not edit.get("mirror"), center=[round(1 - edit["center"][0], 5), edit["center"][1]],
                    tilt=-edit.get("tilt", 0), **({"blurs": blurs} if blurs else {}))

    def set_field_side(self, side):
        edit = self.shot["edit"]
        edit["join"] = dict(edit.get("join") or FIELD_DEFAULT, side=side)
        self.redraw()
        self.schedule_save()

    def change_field(self, **values):
        self.shot["edit"]["join"].update(values)
        self.media_redraw()
        self.schedule_save()

    def set_frame(self, value):
        if self.tool == "crop":
            self.size_pick.show(value)
        if not self.scene_names():
            self.change(format=value, center=[0.5, 0.5])
            return
        self.shot["edit"]["format"] = value
        self.schedule_save(self.shot)
        self.media_redraw()

    def set_size(self, value):
        if not self.scene_names():
            self.change(size=value)
            return
        self.shot["edit"]["size"] = value
        self.schedule_save(self.shot)
        self.media_redraw()
