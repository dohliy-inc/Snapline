import os
import re
import threading
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk

import chatlog
import core
import theme
from theme import (
    DISCORD, ERR, FILES, FONT, HAIR, KINDS, LINE, MODES, NICKS, OUTLINES, POSITIONS, SCALES, SITE, SOUND, SOURCES,
    SUB, TK_KEYS, VOID, WHITE, megabytes, px, when
)
from widgets import Choice, FramePick, Loupe, Painter, Pill, SizePick, Slider


def chatlog_worker(folder, stop):
    report = lambda msg: core.EVENTS.put(("chatlog", msg))
    try:
        chatlog.run(chatlog.PORT, f"cfx-nui-{chatlog.RESOURCE}", folder, stop, report)
    except Exception as e:
        with open(core.ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()}\n{traceback.format_exc()}\n")
        report(f"Чатлог остановился из-за ошибки: {e}. Подробности в {core.ERROR_LOG}")


class Settings:
    def __init__(self, app, parent):
        self.app = app
        self.f = tk.Frame(parent, bg=VOID)
        self.list_w = px(640)
        self.label_w = px(220)
        holder = tk.Frame(self.f, bg=VOID, width=self.list_w + px(14), height=parent.winfo_screenheight())
        holder.pack(side="left", anchor="n", padx=(theme.PAD + px(12), px(24)), pady=(px(8), 0))
        holder.pack_propagate(False)
        self.f.bind("<Configure>", lambda _: self.relayout())
        self.view = tk.Frame(holder, bg=VOID)
        self.view.pack(side="left", fill="both", expand=True)
        self.thumb = tk.Canvas(holder, bg=VOID, highlightthickness=0, bd=0, width=px(4))
        self.thumb.pack(side="right", fill="y")
        left = tk.Frame(self.view, bg=VOID)
        left.place(x=0, y=0, width=self.list_w)
        self.list, self.offset = left, 0
        left.bind("<Configure>", lambda _: self.relayout())
        self.view.bind("<Configure>", lambda _: self.relayout())
        right = tk.Frame(self.f, bg=VOID)
        right.pack(side="left", fill="both", expand=True, padx=(0, theme.PAD), pady=(px(8), theme.PAD))
        self.credits(right)
        self.example = tk.Canvas(right, bg=VOID, highlightthickness=0, bd=0)
        self.example.pack(fill="both", expand=True)
        self.example_job = None
        self.example.bind("<Configure>", lambda _: self.settle())
        self.example.bind("<Motion>", self.example_hover)
        self.example.bind("<Leave>", lambda _: self.loupe.hide())
        self.painter = Painter(self.example)
        self.loupe = Loupe(self.example)
        self.example_geo = None
        self.encoded_arr = None
        self.encoded_photo = None
        self.estimate_job = None
        self.estimate_rev = 0
        self.sample = None
        self.sample_loading = False
        self.sample_missing = False
        self.capturing = False
        self.chatlog_stop = None
        self.chatlog_folder = None
        self.build(left)
        self.bind_wheel(holder)

    def credits(self, parent):
        box = tk.Frame(parent, bg=VOID)
        box.pack(side="bottom", fill="x")
        tk.Frame(box, bg=HAIR, height=1).pack(fill="x", pady=(0, px(14)))
        line = tk.Frame(box, bg=VOID)
        line.pack(fill="x")
        text = tk.Frame(line, bg=VOID)
        text.pack(side="left", anchor="w")
        tk.Label(text, text=f"Snapline {core.VERSION}", bg=VOID, fg=WHITE, font=(FONT["semi"], 11), bd=0, padx=0,
                 anchor="w").pack(fill="x")
        who = tk.Frame(text, bg=VOID)
        who.pack(fill="x", pady=(px(2), 0))
        self.discord = self.link(who, "Дохлый", lambda: os.startfile(DISCORD))
        tk.Label(who, text=" для ", bg=VOID, fg=SUB, font=(FONT["ui"], 9), bd=0, padx=0, pady=0).pack(side="left")
        self.site = self.link(who, "ls-project.com", lambda: os.startfile(SITE))
        self.update_link = tk.Label(text, bg=VOID, fg=WHITE, font=(FONT["semi"], 9), bd=0, padx=0, cursor="hand2",
                                    anchor="w")
        try:
            with Image.open(core.RES_DIR / "assets" / "ls_project.png") as im:
                im = im.convert("RGBA")
                h = px(44)
                im = im.resize((round(im.width * h / im.height), h), Image.LANCZOS)
                ground = Image.new("RGBA", im.size, VOID)
                ground.alpha_composite(im)
                self.logo = ImageTk.PhotoImage(ground.convert("RGB"))
            tk.Label(line, image=self.logo, bg=VOID, bd=0).pack(side="right", anchor="e")
        except OSError:
            self.logo = None

    def show_update(self):
        version, url = self.app.update
        self.update_link.config(text=f"Вышла версия {version} — скачать")
        self.update_link.bind("<Button-1>", lambda _: os.startfile(url))
        self.update_link.pack(fill="x", pady=(px(6), 0))

    def link(self, parent, text, action):
        label = tk.Label(parent, text=text, bg=VOID, fg=WHITE, font=(FONT["ui"], 9), bd=0, padx=0, pady=0,
                         cursor="hand2")
        label.pack(side="left")
        label.bind("<Enter>", lambda _: label.config(font=(FONT["ui"], 9, "underline")))
        label.bind("<Leave>", lambda _: label.config(font=(FONT["ui"], 9)))
        label.bind("<Button-1>", lambda _: action())
        return label

    def bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self.wheel, add="+")
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def wheel(self, e):
        self.scroll_to(self.offset + (-px(72) if e.delta > 0 else px(72)))

    def seen(self):
        return max(1, self.f.winfo_height() - px(8) - theme.PAD)

    def scroll_to(self, offset):
        spare = max(0, self.list.winfo_reqheight() - self.seen())
        offset = max(0, min(offset, spare))
        if offset != self.offset:
            self.offset = offset
            self.list.place_configure(y=-offset)
        self.draw_thumb()

    def relayout(self):
        self.scroll_to(self.offset)

    def draw_thumb(self):
        self.thumb.delete("all")
        full, seen = self.list.winfo_reqheight(), self.seen()
        if full <= seen:
            return
        top, bottom = self.offset / full, (self.offset + seen) / full
        self.thumb.create_line(px(2), top * seen + px(2), px(2), bottom * seen - px(2), fill=LINE, width=px(3),
                               capstyle="round")

    def row(self, parent, title, sub=None):
        line = tk.Frame(parent, bg=VOID)
        line.pack(fill="x")
        line.columnconfigure(0, minsize=self.label_w)
        text = tk.Frame(line, bg=VOID)
        text.grid(row=0, column=0, sticky="nw", pady=px(12))
        tk.Label(text, text=title, bg=VOID, fg=WHITE, font=(FONT["semi"], 11), anchor="w").pack(fill="x")
        subl = None
        if sub is not None:
            subl = tk.Label(text, text=sub, bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w", justify="left",
                            wraplength=self.label_w - px(20))
            subl.pack(fill="x", pady=(px(2), 0))
        control = tk.Frame(line, bg=VOID)
        control.grid(row=0, column=1, sticky="w", pady=px(10))
        hair = tk.Frame(parent, bg=HAIR, height=1)
        hair.pack(fill="x")
        self.last_row = (line, hair)
        return control, subl, text

    def choice(self, control, options, value, on_pick, **kw):
        choice = Choice(control, options, value, on_pick, wrap=self.list_w - self.label_w, **kw)
        choice.pack(anchor="w")
        return choice

    def section(self, parent, title, first=False):
        tk.Label(parent, text=title.upper(), bg=VOID, fg=SUB, font=(FONT["semi"], 9), anchor="w").pack(
            fill="x", pady=(px(4) if first else px(30), px(6)))
        tk.Frame(parent, bg=HAIR, height=1).pack(fill="x")

    def build(self, f):
        cfg, raw = self.app.cfg, self.app.raw
        self.section(f, "Съёмка", first=True)
        control, self.key_sub, text = self.row(f, "Клавиша съёмки", "Нажми и выбери новую")
        self.key_pill = Pill(control, cfg["key"], self.capture_key, kind="ghost", size=12, height=36, padx=18)
        self.key_pill.pack(anchor="w")
        control, self.mode_sub, text = self.row(f, "Режим", self.mode_text())
        self.choice(control, MODES, "yes" if cfg["auto"] else "no", self.set_mode)
        control, _, _ = self.row(f, "Чат", "Из чатлога — F11 снимает только сцену, строки потом выбираешь из записи "
                                           "чата")
        self.source_pick = self.choice(control, SOURCES, cfg["source"], self.set_source)
        control, _, _ = self.row(f, "Звук", "Сигнал, когда СС готова")
        self.choice(control, SOUND, "yes" if cfg["sound"] else "no", lambda v: self.app.set("sound", v))
        control, _, _ = self.row(f, "Трей", "Крестик прячет окно в трей, съёмка работает. Выход — через значок")
        self.choice(control, SOUND, "yes" if cfg["tray"] else "no", self.app.set_tray)
        self.section(f, "Новые СС: кадр и файл")
        control, _, _ = self.row(f, "Кадр", "Свой — ширина и высота в пикселях")
        FramePick(control, cfg["format"], self.set_frame, self.frame_now, self.list_w - self.label_w).pack(anchor="w")
        control, _, _ = self.row(f, "Размер файла", "По короткой стороне, в пикселях")
        self.size_pick = SizePick(control, cfg["size"], lambda v: self.app.set("size", v), self.list_w - self.label_w)
        self.size_pick.pack(anchor="w")
        self.size_pick.show(cfg["format"])
        control, _, _ = self.row(f, "Файл", "JPG весит примерно втрое меньше PNG, чат остаётся чётким")
        self.choice(control, FILES, cfg["file"], self.set_file)
        self.file_row = self.last_row
        control, _, _ = self.row(f, "Качество JPG", "Сжимается только фон, чат всегда чёткий. Наведи на пример — "
                                                    "лупа покажет пиксели 1:1")
        self.quality = Slider(control, 10, 100, cfg["quality"], lambda v: self.estimate(),
                              lambda v: self.app.set("quality", str(int(v))), width=self.list_w - self.label_w - px(20),
                              fmt=lambda v: f"{v:.0f}")
        self.quality.pack(anchor="w")
        self.quality_row = self.last_row
        self.show_quality()
        self.section(f, "Новые СС: чат")
        control, _, _ = self.row(f, "Текст чата")
        self.choice(control, SCALES, raw["text_scale"], lambda v: self.app.set("text_scale", v))
        control, _, _ = self.row(f, "Обводка")
        self.choice(control, OUTLINES, raw["outline"], lambda v: self.app.set("outline", v))
        control, _, _ = self.row(f, "Угол чата")
        self.choice(control, POSITIONS, cfg["chat_pos"], lambda v: self.app.set("chat_pos", v), cols=2)
        control, _, _ = self.row(f, "Отступ от края", "Чат у края кадра встаёт на этот отступ. В редакторе — «Текст»")
        Slider(control, 0, 96, cfg["margin"], lambda v: None, lambda v: self.app.set("margin", str(int(v))),
               width=self.list_w - self.label_w - px(20), step=2, fmt=lambda v: f"{v:.0f} px").pack(anchor="w")
        control, _, _ = self.row(f, "Ники", "В новых СС. В редакторе — инструмент «Строки»")
        self.choice(control, NICKS, "yes" if cfg["hide_names"] else "no", lambda v: self.app.set("hide_names", v))
        control, _, _ = self.row(f, "Строки в СС", "Остальные можно вернуть в редакторе")
        self.kind_pills = {}
        for i, (kind, label) in enumerate(KINDS.items()):
            if i % 3 == 0:
                line = tk.Frame(control, bg=VOID)
                line.pack(anchor="w", pady=(0, px(6)))
            pill = Pill(line, label, lambda k=kind: self.toggle_kind(k))
            pill.pack(side="left", padx=(0, px(6)))
            pill.set_kind("on" if kind in cfg["keep"] else "chip")
            self.kind_pills[kind] = pill
        self.section(f, "Файлы")
        control, _, _ = self.row(f, "Папка")
        self.out_label = tk.Label(control, text=str(cfg["out"]), bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w",
                                  justify="left", wraplength=self.list_w - self.label_w - px(10))
        self.out_label.pack(fill="x")
        buttons = tk.Frame(control, bg=VOID)
        buttons.pack(anchor="w", pady=(px(8), 0))
        Pill(buttons, "Изменить", self.pick_folder, kind="ghost").pack(side="left", padx=(0, px(6)))
        Pill(buttons, "Открыть", self.app.feed.open_folder, kind="ghost").pack(side="left")
        control, _, _ = self.row(f, "Исходники", "Кадры, из которых собрана СС. Без них СС не поправить в редакторе")
        self.src_label = tk.Label(control, bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w")
        self.src_label.pack(fill="x")
        Pill(control, "Очистить", self.clear_src, kind="ghost").pack(anchor="w", pady=(px(8), 0))
        self.update_src()
        self.section(f, "Чатлог")
        control, _, _ = self.row(f, "Запись чата", "Каждая строка чата с временем, по файлу на день")
        self.chatlog_pick = self.choice(control, SOUND, "yes" if cfg["chatlog"] else "no", self.set_chatlog)
        self.chatlog_state = tk.Label(control, text="Выключен", bg=VOID, fg=SUB, font=(FONT["ui"], 9), anchor="w",
                                      justify="left", wraplength=self.list_w - self.label_w - px(10))
        self.chatlog_state.pack(fill="x", pady=(px(4), 0))
        Pill(control, "Открыть", self.open_chatlog, kind="ghost").pack(anchor="w", pady=(px(8), 0))
        self.section(f, "Помощь")
        control, _, _ = self.row(f, "Обучение", "Короткий тур по редактору на последней СС")
        Pill(control, "Показать", self.app.start_tour, kind="ghost").pack(anchor="w")

    def set_chatlog(self, value):
        self.app.set("chatlog", value)
        self.toggle_chatlog(value)
        if value == "no" and self.app.cfg["source"] == "log":
            self.app.set("source", "screen")
            self.source_pick.set("screen")
            self.mode_sub.config(text=self.mode_text())

    def set_source(self, value):
        self.app.set("source", value)
        self.mode_sub.config(text=self.mode_text())
        if value == "log" and not self.app.cfg["chatlog"]:
            self.chatlog_pick.set("yes")
            self.set_chatlog("yes")

    def toggle_chatlog(self, value):
        if value == "yes" and self.chatlog_stop is None:
            self.chatlog_stop = threading.Event()
            self.chatlog_folder = self.app.cfg["out"] / "chatlog"
            threading.Thread(target=chatlog_worker, args=(self.chatlog_folder, self.chatlog_stop), daemon=True).start()
            self.chatlog_note("Запускаю…")
        elif value == "no" and self.chatlog_stop is not None:
            self.chatlog_stop.set()
            self.chatlog_stop = None
            self.chatlog_state.config(text="Выключен", fg=SUB)

    def chatlog_note(self, msg):
        if self.chatlog_stop is not None:
            self.chatlog_state.config(text=msg, fg=WHITE)

    def open_chatlog(self):
        folder = self.chatlog_folder or self.app.cfg["out"] / "chatlog"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as e:
            self.chatlog_state.config(text=f"Папка не открылась: {e}", fg=ERR)

    def set_frame(self, value):
        self.app.set("format", value)
        self.size_pick.show(value)

    def set_file(self, value):
        self.app.set("file", value)
        self.show_quality()

    def show_quality(self):
        line, hair = self.quality_row
        if self.app.cfg["file"] == "jpg":
            line.pack(fill="x", after=self.file_row[1])
            hair.pack(fill="x", after=line)
        else:
            line.pack_forget()
            hair.pack_forget()

    def frame_now(self):
        shot = self.sample or core.sample_shot(self.app.cfg)
        return core.plan(shot["bg"], core.new_edit(self.app.cfg, shot["rows"]))["base"]

    def update_src(self):
        try:
            size, count = core.src_size(self.app.cfg["out"])
        except OSError:
            size, count = 0, 0
        self.src_label.config(text=f"{count} СС · {megabytes(size)}" if size else "Пусто")
        return size, count

    def clear_src(self):
        size, count = self.update_src()
        if not size:
            return
        question = (f"Удалить исходники {count} СС ({megabytes(size)})?\n\n"
                    "Готовые СС останутся в папке, но поправить их в редакторе будет нельзя.")
        if not messagebox.askyesno("Snapline", question, parent=self.app.root):
            return
        core.clear_src(self.app.cfg["out"])
        feed = self.app.feed
        feed.cache.clear()
        if feed.index:
            feed.open_current()
        self.sample = None
        self.update_src()
        self.draw_example()

    def mode_text(self):
        cfg = self.app.cfg
        keys = cfg["hud_key"] if cfg["source"] == "log" else f"{cfg['hud_key']} и {cfg['dark_key']}"
        if cfg["auto"]:
            return f"Программа сама жмёт {keys}."
        return f"Сам жмёшь {keys} перед {cfg['key']}."

    def set_mode(self, value):
        self.app.set("auto", value)
        self.mode_sub.config(text=self.mode_text())

    def toggle_kind(self, kind):
        pill = self.kind_pills[kind]
        pill.set_kind("chip" if pill.kind == "on" else "on")
        self.app.set("keep", ", ".join(k for k, p in self.kind_pills.items() if p.kind == "on"))

    def capture_key(self):
        self.capturing = True
        self.key_pill.set_text("Нажми клавишу…")
        self.key_sub.config(text="Esc — отмена", fg=SUB)
        self.app.root.focus_set()

    def on_key(self, e):
        if not self.capturing:
            return False
        if e.keysym == "Escape":
            self.capturing = False
            self.key_pill.set_text(self.app.cfg["key"])
            self.key_sub.config(text="Нажми и выбери новую", fg=SUB)
            return True
        key = e.keysym.upper() if re.fullmatch(r"F\d{1,2}", e.keysym) else TK_KEYS.get(e.keysym)
        if key not in core.KEYS:
            self.key_sub.config(text="Не подойдёт: нужна F1–F24, Pause, Insert, Home, End, PgUp или PgDn", fg=ERR)
            return True
        self.capturing = False
        if self.app.set("hotkey", key):
            self.key_sub.config(text="Нажми и выбери новую", fg=SUB)
        else:
            self.key_sub.config(text=f"{key} занята игрой, выбери другую", fg=ERR)
        self.key_pill.set_text(self.app.cfg["key"])
        return True

    def pick_folder(self):
        path = filedialog.askdirectory(initialdir=self.app.cfg["out"], title="Куда сохранять СС")
        if path:
            self.app.set("output", path)
            self.out_label.config(text=str(self.app.cfg["out"]))
            problem = core.check_out(self.app.cfg)
            self.app.feed.message = ("fail", problem) if problem else None
            self.update_src()
            self.app.feed.refresh_names()
            self.app.feed.index = 0
            self.sample = None
            self.draw_example()

    def settle(self):
        if self.example_job:
            self.example.after_cancel(self.example_job)
        self.example_job = self.example.after(110, self.settled)

    def settled(self):
        self.example_job = None
        self.draw_example()

    def load_sample(self):
        feed = self.app.feed
        cached = feed.cache.get(feed.names[0]) if feed.names else None
        if cached:
            self.sample = {**cached, "rows": [dict(r) for r in cached["rows"]]}
            return True
        if not self.sample_loading and not self.sample_missing:
            self.sample_loading = True
            cfg = self.app.cfg

            def work():
                try:
                    shot = core.sample_shot(cfg)
                except (OSError, ValueError):
                    shot = None
                self.app.inbox.put(("sample_loaded", None, shot))

            threading.Thread(target=work, daemon=True).start()
        return False

    def sample_loaded(self, _, shot):
        self.sample_loading = False
        self.sample_missing = shot is None
        if self.sample is None:
            self.sample = shot
        self.draw_example()

    def draw_example(self):
        W, H = self.example.winfo_width(), self.example.winfo_height()
        if W < 50 or H < 50:
            return
        cfg = self.app.cfg
        self.example.delete("all")
        if self.sample is None and not self.load_sample():
            text = ("Пример не загрузился: нет ни своих СС, ни встроенного кадра." if self.sample_missing
                    else "Загружаю пример…")
            self.example.create_text(0, 0, anchor="nw", fill=SUB, font=(FONT["ui"], 10), text=text)
            return
        shot = self.sample
        for r in shot["rows"]:
            r["keep"] = r["kind"] in cfg["keep"]
            r["hide"] = []
        if cfg["hide_names"]:
            core.auto_hide(shot["rows"])
        shot["edit"] = core.new_edit(cfg, shot["rows"])
        out_w, out_h = core.plan(shot["bg"], shot["edit"])["size"]
        d = min(W / out_w, (H - px(72)) / out_h)
        geo = self.painter.draw(shot, (0, 0, round(out_w * d), round(out_h * d)))
        self.example_geo, self.encoded_arr = geo, None
        self.loupe.hide()
        self.example.create_text(geo["img"][0], geo["img"][1] + geo["img"][3] + px(14), anchor="nw", fill=SUB,
                                 font=(FONT["ui"], 10), width=geo["img"][2], text=self.caption(), tags=("caption",))
        self.estimate()

    def caption(self, size=None):
        shot = self.sample
        out_w, out_h = core.plan(shot["bg"], shot["edit"])["size"]
        weight = f", ≈ {megabytes(size)}" if size else ""
        source = f"твоя СС от {when(shot['name'])}" if shot["name"] else "встроенный кадр"
        return (f"Так будет выглядеть новая СС: {out_w} × {out_h}{weight}. Пример — {source}. "
                f"Каждую готовую СС можно поправить в редакторе.")

    def estimate(self):
        if self.estimate_job:
            self.example.after_cancel(self.estimate_job)
        self.estimate_job = self.example.after(150, self.run_estimate)

    def run_estimate(self):
        self.estimate_job = None
        if self.sample is None or self.example_geo is None:
            return
        shot = self.sample
        edit = dict(shot["edit"], quality=int(self.quality.value))
        snap = {**shot, "rows": [dict(r) for r in shot["rows"]], "edit": edit,
                "out": shot.get("out") or self.app.cfg["out"]}
        self.estimate_rev += 1
        rev = self.estimate_rev

        def work():
            try:
                img, _, data = core.encoded(snap)
                arr = core.decoded(data) if edit["file"] == "jpg" else img
                self.app.inbox.put(("estimated", rev, (arr, len(data))))
            except Exception:
                self.app.inbox.put(("estimated", rev, None))

        threading.Thread(target=work, daemon=True).start()

    def estimated(self, rev, value):
        if rev != self.estimate_rev or value is None or self.example_geo is None:
            return
        self.encoded_arr, size = value
        ix, iy, dw, dh = self.example_geo["img"]
        img = Image.fromarray(self.encoded_arr).resize((dw, dh), Image.BILINEAR, reducing_gap=2.0)
        self.encoded_photo = ImageTk.PhotoImage(img)
        self.example.delete("encoded")
        self.example.create_image(ix, iy, anchor="nw", image=self.encoded_photo, tags=("encoded",))
        self.example.itemconfig("caption", text=self.caption(size))

    def example_hover(self, e):
        geo = self.example_geo
        if self.encoded_arr is None or geo is None:
            return
        ix, iy, dw, dh = geo["img"]
        if ix <= e.x <= ix + dw and iy <= e.y <= iy + dh:
            self.loupe.show(e.x, e.y, geo["img"], self.encoded_arr)
        else:
            self.loupe.hide()
