import tkinter as tk
from tkinter import filedialog

import core
import styles
from theme import FONT, LINE, LOOK_NAMES, PRESET_NAMES, ROW, STYLES, WHITE, px


class StyleTool:
    def sheet_style(self, body):
        edit = self.shot["edit"]
        whole = " · вся сцена" if self.scene_names() else ""
        self.field(body, "Пресет" + whole, 0)
        self.choice(body, PRESET_NAMES, edit.get("preset") if edit.get("preset") in PRESET_NAMES else "none",
                    lambda v: self.change(preset=v))
        self.field(body, "Коррекция" + whole)
        look = edit.get("look") or {}
        for key, title in LOOK_NAMES.items():
            self.label(body, title, 2)
            bar = self.slider(body, -100, 100, look.get(key, 0), lambda v, key=key: self.change_look(key, int(v)),
                              fmt=lambda v: f"{v:+.0f}" if round(v) else "0")
            self.sliders["look_" + key] = (bar, lambda key=key: (self.shot["edit"].get("look") or {}).get(key, 0))
        self.buttons(body, (("Сбросить коррекцию", lambda: self.change(look={})),), 8)
        self.field(body, "LUT" + whole)
        lut = edit.get("lut")
        self.buttons(body, (("Загрузить .cube", self.pick_lut),) + ((("Убрать", lambda: self.set_lut(None)),) if lut else ()))
        self.label(body, f"Сейчас: {lut}" if lut else "Свой цветокор из .cube — тот же, что в ReShade или видеоредакторе.", 6)
        style = edit.get("style") if edit.get("style") in STYLES else "none"
        self.field(body, "Камера · тест")
        self.choice(body, STYLES, style, self.set_style)
        if style != "none":
            self.field(body, "Надпись")
            entry = tk.Entry(body, bg=ROW, fg=WHITE, insertbackground=WHITE, relief="flat", font=(FONT["ui"], 10),
                             highlightthickness=1, highlightbackground=LINE, highlightcolor=WHITE)
            text = edit.get("style_text")
            entry.insert(0, styles.LABELS[style] if text is None else text)
            entry.pack(fill="x", ipady=px(4))
            entry.bind("<KeyRelease>", lambda _: self.typed_style(entry))
            self.label(body, "Дата и время — из момента съёмки. Чат остаётся чётким и обходит надписи.", 6)

    def change_look(self, key, value):
        look = dict(self.shot["edit"].get("look") or {}, **{key: value})
        self.change(look={k: v for k, v in look.items() if v})

    def pick_lut(self):
        path = filedialog.askopenfilename(title="LUT для Snapline", filetypes=[("LUT", "*.cube"), ("Все файлы", "*.*")])
        if path:
            try:
                self.set_lut(core.add_lut(self.shot["out"], path))
            except (OSError, ValueError) as e:
                self.note = f"LUT не загрузился: {e}"
                self.update_meta()

    def set_lut(self, name):
        self.change(lut=name)
        self.redraw()

    def set_style(self, value):
        self.change(style=value, style_text=None)
        self.redraw()

    def typed_style(self, entry):
        if self.style_job:
            self.c.after_cancel(self.style_job)
        self.style_job = self.c.after(300, lambda: entry.winfo_exists() and self.change(
            style_text=entry.get().strip()[:styles.TEXT_MAX]))
