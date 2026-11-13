import bisect
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from functools import lru_cache

from PIL import ImageTk

import chat
import chatlog
import compose
import store
from theme import BLACK, FONT, LOG_NAMES, LOG_SHOW, MIST, ROW, SLATE, SUB, VOID, WHITE, px, tick
from widgets import Pill


class LogTool:
    def empty_log(self):
        shot = self.shot
        return (shot is not None and not shot["rows"] and not self.scene_names()
                and store.log_path(shot["out"], shot["name"]).exists())

    def sheet_logpick(self, body):
        shot = self.target
        self.log_count = tk.Label(body, text=self.log_count_text(), bg=VOID, fg=WHITE, font=(FONT["semi"], 12),
                                  anchor="w")
        self.log_count.pack(fill="x", pady=(0, px(10)))
        line = tk.Frame(body, bg=VOID)
        line.pack(anchor="w")
        Pill(line, "На СС", self.apply_log, kind="primary").pack(side="left", padx=(0, px(6)))
        Pill(line, "Назад к строкам", lambda: self.toggle_tool("lines"), kind="ghost").pack(side="left")
        v = self.logview
        if v and v["lines"]:
            self.field(body, "Показывать")
            self.choice(body, LOG_SHOW, "all" if v["all"] else "rp", self.log_show)
            names = self.log_names()
            if names:
                self.field(body, "Чьи строки")
                self.label(body, "Нажми на участников своей сцены — останется только их диалог. Ближе к моменту "
                                 "съёмки — выше.")
                measure = tkfont.Font(family=FONT["ui"], size=10).measure
                line, used = None, 0
                for name, count in names:
                    text = f"{name} · {count}"
                    w = measure(text) + px(13) * 2 + px(6)
                    if line is None or used + w > self.sheet_w:
                        line = tk.Frame(body, bg=VOID)
                        line.pack(anchor="w", pady=(0, px(6)))
                        used = 0
                    pill = Pill(line, text, lambda n=name: self.log_name(n))
                    pill.set_kind("on" if name in v["names"] else "chip")
                    pill.pack(side="left", padx=(0, px(6)))
                    used += w
                if v["names"]:
                    Pill(body, "Показать всех", lambda: self.log_name(None), kind="ghost").pack(anchor="w")
        screen = not store.log_path(shot["out"], shot["name"]).exists()
        self.label(body, "Строки чатлога за час до и после СС, пунктир — момент съёмки. Отметь нужные и нажми "
                         "«На СС»: они встанут в чат тем же шрифтом и цветом, что в игре. Клик по заголовку куска "
                         "отмечает его целиком." +
                   (" Снятый с экрана чат заменится, вернуть его можно кнопкой «С экрана» в «Строках»."
                    if screen else ""), 16)

    def log_names(self):
        v = self.logview
        near, total = {}, {}
        for (when, _), (kind, who, _) in zip(v["lines"], v["who"]):
            if who and kind in (chat.SPEECH, chat.ACTION):
                total[who] = total.get(who, 0) + 1
                if abs((when - v["at"]).total_seconds()) <= chatlog.LOG_NEAR_S:
                    near[who] = near.get(who, 0) + 1
        ranked = sorted(total, key=lambda n: (-near.get(n, 0), -total[n], n))
        keep = [n for n in ranked[:LOG_NAMES]] + [n for n in ranked[LOG_NAMES:] if n in v["names"]]
        return [(n, total[n]) for n in keep]

    def log_show(self, value):
        self.logview["all"] = value == "all"
        self.log_refilter()
        self.log_changed()

    def log_name(self, name):
        names = self.logview["names"]
        if name is None:
            names.clear()
        else:
            names.symmetric_difference_update({name})
        self.log_refilter()
        self.redraw()

    def log_refilter(self):
        v = self.logview
        lines, at, keep = v["lines"], v["at"], self.app.cfg["keep"]
        seen = [k for k, (kind, who, _) in enumerate(v["who"])
                if (v["all"] or kind in keep) and (not v["names"] or who in v["names"])]
        starts = set(chatlog.log_chunks([lines[k] for k in seen]))
        items, mark, bounds, chunk = [], None, {}, None
        for n, k in enumerate(seen):
            if mark is None and lines[k][0] > at:
                mark = len(items)
                items.append(("mark", k))
            if n in starts:
                chunk = k
                bounds[k] = []
                items.append(("head", k))
            bounds[chunk].append(k)
            items.append(("line", k))
        if mark is None:
            mark = len(items)
            items.append(("mark", len(lines)))
        v.update(items=items, mark=mark, bounds=bounds, width=None, offset=None)

    def open_log(self):
        shot, self.logview = self.target, None
        if shot is None:
            return
        at = compose.shot_time(shot["name"]) or datetime.now()
        self.c.config(cursor="watch")
        self.c.update_idletasks()
        lines = chatlog.read_log(shot["out"], at)
        self.c.config(cursor="")
        saved = {chatlog.log_key(*line) for line in chatlog.picked_log(shot["edit"])}
        self.logview = {"name": shot["name"], "at": at, "lines": lines, "who": [chatlog.log_who(p) for _, p in lines],
                        "on": {k for k, line in enumerate(lines) if chatlog.log_key(*line) in saved},
                        "all": False, "names": set()}
        self.log_refilter()

    def log_count_text(self):
        v = self.logview
        return f"Отмечено {len(v['on'])} из {len(v['lines'])}" if v and v["lines"] else "Строк нет"

    def chat_font(self):
        if self.log_font is None:
            self.log_font = tkfont.Font(family="Arial", size=-px(15), weight="bold")
        return self.log_font

    def log_layout(self, width):
        v = self.logview
        if v["width"] == width:
            return
        font = self.chat_font()
        measure = lru_cache(maxsize=None)(font.measure)
        lh = font.metrics("linespace") + px(1)
        tops, wraps, y = [], {}, px(10)
        for kind, k in v["items"]:
            tops.append(y)
            if kind == "line":
                wraps[k] = [row for _, row in chatlog.log_rows([v["lines"][k]], measure, width)] or [[]]
                y += len(wraps[k]) * lh + px(10)
            else:
                y += px(40)
        v.update(width=width, tops=tops, wraps=wraps, lh=lh, full=y + px(10))

    def draw_log(self, area):
        self.c.delete("shot")
        ax, ay, aw, ah = area
        self.c.create_rectangle(ax, ay, ax + aw, ay + ah, fill=BLACK, outline="", tags=("shot",))
        v = self.logview
        if v is None or not v["lines"]:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="В чатлоге нет строк за час до и после этой СС. "
                               "Строки пишутся, пока в настройках включён чатлог.", width=aw - px(80),
                               justify="center", fill=SUB, font=(FONT["ui"], 12), tags=("shot",))
            return
        x0 = ax + px(120)
        self.log_layout(max(px(200), aw - px(148)))
        tops, items, lines, lh = v["tops"], v["items"], v["lines"], v["lh"]
        if v["offset"] is None:
            v["offset"] = tops[v["mark"]] - ah // 2
        v["offset"] = max(0, min(v["offset"], v["full"] - ah))
        v["top"] = top = ay - v["offset"]
        font = self.chat_font()
        ticks = self.row_photos = [ImageTk.PhotoImage(tick(px(18), on)) for on in (False, True)]
        ends = tops[1:] + [v["full"] - px(10)]
        for j in range(max(0, bisect.bisect_right(tops, v["offset"]) - 1), len(items)):
            y, bottom = top + tops[j], top + ends[j]
            if y > ay + ah:
                break
            kind, k = items[j]
            if kind == "mark":
                mid, label = (y + bottom) / 2, f"СС снята · {v['at']:%H:%M:%S}"
                wide = tkfont.Font(family=FONT["semi"], size=9).measure(label) + px(16)
                self.c.create_line(ax + px(16), mid, ax + aw - px(16), mid, fill=SUB, dash=(4, 3), tags=("shot",))
                self.c.create_rectangle(x0 - px(8), mid - px(10), x0 - px(8) + wide, mid + px(10), fill=BLACK,
                                        outline="", tags=("shot",))
                self.c.create_text(x0, mid, text=label, anchor="w", fill=WHITE, font=(FONT["semi"], 9), tags=("shot",))
                continue
            on = k in v["on"]
            if kind == "head":
                span, tag = v["bounds"][k], f"lhead{j}"
                picked = sum(i in v["on"] for i in span)
                on = picked == len(span)
                text = (f"{lines[k][0]:%H:%M}–{lines[span[-1]][0]:%H:%M} · строк: {len(span)}" +
                        (f" · отмечено: {picked}" if picked else ""))
                self.c.create_rectangle(ax, y, ax + aw, bottom, fill=BLACK, outline="", tags=("shot", tag, tag + "-bg"))
                self.c.create_image(ax + px(16), y + px(24), anchor="w", image=ticks[on], tags=("shot", tag))
                self.c.create_text(ax + px(48), y + px(24), text=text, anchor="w", fill=WHITE if picked else SUB,
                                   font=(FONT["semi"], 10), tags=("shot", tag))
                idle, hot = BLACK, ROW
            else:
                tag, first = f"lrow{j}", y + px(5) + lh / 2
                self.c.create_rectangle(ax, y, ax + aw, bottom, fill=SLATE if on else BLACK, outline="",
                                        tags=("shot", tag, tag + "-bg"))
                self.c.create_image(ax + px(16), first, anchor="w", image=ticks[on], tags=("shot", tag))
                self.c.create_text(ax + px(48), first, text=f"{lines[k][0]:%H:%M:%S}", anchor="w", fill=SUB,
                                   font=(FONT["ui"], 9), tags=("shot", tag))
                for n, row in enumerate(v["wraps"][k]):
                    for x, text, color in row:
                        self.c.create_text(x0 + x, y + px(5) + n * lh, text=text.rstrip(), anchor="nw", fill=color,
                                           font=font, tags=("shot", tag))
                idle, hot = (SLATE, MIST) if on else (BLACK, ROW)
            self.c.tag_bind(tag, "<Enter>", lambda _, t=tag, c=hot: (self.c.itemconfig(t + "-bg", fill=c),
                                                                  self.c.config(cursor="hand2")))
            self.c.tag_bind(tag, "<Leave>", lambda _, t=tag, c=idle: (self.c.itemconfig(t + "-bg", fill=c),
                                                                   self.c.config(cursor="")))
        self.c.tag_lower("shot")

    def log_item_at(self, y):
        v = self.logview
        return min(max(bisect.bisect_right(v["tops"], y - v["top"]) - 1, 0), len(v["items"]) - 1)

    def mark_log(self, a, b, on):
        v = self.logview
        for kind, k in v["items"][min(a, b):max(a, b) + 1]:
            if kind == "line":
                (v["on"].add if on else v["on"].discard)(k)
        self.log_changed()

    def toggle_chunk(self, j):
        v = self.logview
        k = v["items"][j][1]
        span = set(v["bounds"][k])
        v["on"] = v["on"] - span if span <= v["on"] else v["on"] | span
        self.log_changed()

    def log_changed(self):
        self.draw_log(self.area())
        if self.sheet is not None and self.log_count.winfo_exists():
            self.log_count.config(text=self.log_count_text())

    def apply_log(self):
        v, shot = self.logview, self.target
        if shot is None or v is None or v["name"] != shot["name"]:
            return
        if not v["on"]:
            self.note = "отметь хотя бы одну строку"
            self.update_meta()
            return
        picked = [v["lines"][k] for k in sorted(v["on"])]
        try:
            store.use_log(shot, self.app.cfg, picked)
        except (OSError, ValueError) as e:
            self.note = f"строки не встали: {e}"
            self.update_meta()
            return
        self.tool, self.offset = "lines", 0
        self.switched(shot, f"строк из чатлога: {len(picked)}")

    def from_screen(self):
        shot = self.target
        try:
            store.use_screen(shot, self.app.cfg)
        except (OSError, ValueError) as e:
            self.note = f"кадры чата не открылись: {e}"
            self.update_meta()
            return
        self.switched(shot, "чат снова с экрана")

    def switched(self, shot, note):
        self.schedule_save(shot)
        self.redraw()
        self.note = note
        self.update_meta()
