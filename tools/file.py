import tkinter as tk

import core
import styles
from theme import FILES, FONT, LINE, ROW, STYLES, VOID, WHITE, px


class FileTool:
    def sheet_file(self, body):
        edit = self.shot["edit"]
        style = edit.get("style") if edit.get("style") in STYLES else "none"
        self.field(body, "Стиль · тест", 0)
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
        self.field(body, "Формат")
        self.choice(body, FILES, edit["file"], self.set_file)
        if edit["file"] == "jpg":
            self.field(body, "Качество фона")
            quality = self.slider(body, 10, 100, edit.get("quality", core.TEXT_QUALITY),
                                  lambda v: self.change(quality=int(v)), fmt=lambda v: f"{v:.0f}")
            self.sliders["quality"] = (quality, lambda: self.shot["edit"].get("quality", core.TEXT_QUALITY))
            self.label(body, "Сжимается только фон, текст чата всегда остаётся чётким.", 4)
        self.file_info = tk.Label(body, text=self.preview_info or "считаю размер…", bg=VOID, fg=WHITE,
                                  font=(FONT["semi"], 12), anchor="w")
        self.file_info.pack(fill="x", pady=(px(18), px(2)))
        self.label(body, "Размер кадра — в «Кадре».")

    def set_file(self, value):
        self.change(file=value)
        self.redraw()

    def set_style(self, value):
        self.change(style=value, style_text=None)
        self.redraw()

    def typed_style(self, entry):
        if self.style_job:
            self.c.after_cancel(self.style_job)
        self.style_job = self.c.after(300, lambda: entry.winfo_exists() and self.change(
            style_text=entry.get().strip()[:styles.TEXT_MAX]))
