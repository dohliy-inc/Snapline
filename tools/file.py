import tkinter as tk

import store
from theme import FILES, FONT, VOID, WHITE, px


class FileTool:
    def sheet_file(self, body):
        edit = self.shot["edit"]
        self.field(body, "Формат", 0)
        self.choice(body, FILES, edit["file"], self.set_file)
        if edit["file"] == "jpg":
            self.field(body, "Качество фона")
            quality = self.slider(body, 10, 100, edit.get("quality", store.TEXT_QUALITY),
                                  lambda v: self.change(quality=int(v)), fmt=lambda v: f"{v:.0f}")
            self.sliders["quality"] = (quality, lambda: self.shot["edit"].get("quality", store.TEXT_QUALITY))
            self.label(body, "Сжимается только фон, текст чата всегда остаётся чётким.", 4)
        self.file_info = tk.Label(body, text=self.preview_info or "считаю размер…", bg=VOID, fg=WHITE,
                                  font=(FONT["semi"], 12), anchor="w")
        self.file_info.pack(fill="x", pady=(px(18), px(2)))
        self.label(body, "Размер кадра — в «Кадре», цвет и стиль — в «Стиле».")

    def set_file(self, value):
        self.change(file=value)
        self.redraw()
