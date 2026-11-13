import re
import tkinter as tk
import tkinter.font as tkfont

import numpy as np
from PIL import Image, ImageTk

import chat
import compose
import config
import store
from theme import BLACK, DIM, ERR, FONT, HAIR, ICONS, LINE, MIST, ROW, SLATE, SUB, VOID, WHITE, px, rounded, tick, when
from widgets import Pill


class LinesTool:
    def sheet_lines(self, body):
        names, shot = self.scene_names(), self.target
        log = store.log_path(shot["out"], shot["name"]).exists()
        self.count = tk.Label(body, text=self.count_text(), bg=VOID, fg=WHITE, font=(FONT["semi"], 12), anchor="w")
        self.count.pack(fill="x", pady=(0, px(10)))
        self.buttons(body, (("Как после съёмки", self.reset_lines),) +
                     ((("Чат из другой СС", lambda: self.toggle_tool("carry")),) if not log else ()))
        source = (("С экрана", self.from_screen),) if log and store.screen_chats(shot["out"], shot["name"]) else ()
        self.buttons(body, (("Из чатлога", lambda: self.toggle_tool("logpick")),) + source +
                     ((("Убрать повторы", self.drop_repeats),) if names else ()), 6)
        self.label(body, ("Чат этой СС собран из чатлога. " if log else "") +
                   "Галочка — строка в СС, мышью можно провести по нескольким. Клик по слову — закрыть его "
                   "плашкой или удалить. Ножницы делят чат на части." +
                   (" Здесь строки всех СС сцены, повторы из СС выше убираются сами." if names else ""), 16)

    def sheet_carry(self, body):
        names = self.scene_names()
        mine = f"к СС {names.index(self.current()) + 1} сцены" if names else "к этой"
        self.label(body, f"Нажми на СС справа — её строки добавятся {mine}, повторы склеятся сами.")
        Pill(body, "Назад к строкам", lambda: self.toggle_tool("lines"), kind="ghost").pack(anchor="w", pady=(px(8), 0))

    def line_items(self):
        if not self.scene_names():
            return [(self.shot, i, 0, self.name) for i in range(len(self.shot["rows"]))]
        items = []
        for k, (name, shot) in enumerate(self.members()):
            items.append((shot, None, k, name))
            items += [(shot, i, k, name) for i in range(len(shot["rows"]))] if shot else []
        return items

    def draw_lines(self, area):
        self.c.delete("shot")
        ax, ay, aw, ah = area
        items = self.items = self.line_items()
        rows = [shot["rows"][i] for shot, i, _, _ in items if i is not None]
        widest = max((r["glyphs"][-1][1] + 8 for r in rows), default=1)
        s = min(1.0, (aw - px(104)) / widest)
        self.lines_x0, self.lines_s = ax + px(48), s
        slot = max(px(28), round(max((r["pitch"] for r in rows), default=0) * s) + px(12))
        self.offset = max(0, min(self.offset, max(0, slot * len(items) + px(24) - ah)))
        self.c.create_rectangle(ax, ay, ax + aw, ay + ah, fill=BLACK, outline="", tags=("shot",))
        if not items:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="Строк нет. Выбери их в чатлоге: кнопка «Из чатлога» "
                               "слева.", fill=SUB, font=(FONT["ui"], 12), tags=("shot",))
        y = ay + px(12) - self.offset
        self.lines_top, self.lines_slot = y, slot
        self.row_photos = []
        on, off = ImageTk.PhotoImage(tick(px(18), True)), ImageTk.PhotoImage(tick(px(18), False))
        self.row_photos += [on, off]
        current, breaks = self.current(), {}
        for j, (shot, i, k, name) in enumerate(items):
            if y + slot > ay and y < ay + ah and i is None:
                tag = f"head{j}"
                state = "" if shot else " · не открылась" if self.cache.get(name) is False else " · загружаю…"
                text = f"СС {k + 1} · {when(name)}" + (" · эта" if name == self.name else "") + state
                if j:
                    self.c.create_line(ax + px(16), y + px(4), ax + aw - px(16), y + px(4), fill=MIST, tags=("shot",))
                self.c.create_rectangle(ax, y + px(5), ax + aw, y + slot, fill=BLACK, outline="", tags=("shot", tag))
                self.c.create_text(ax + px(16), y + slot / 2 + px(2), text=text, anchor="w", font=(FONT["semi"], 10),
                                   fill=WHITE if name == current else SUB, tags=("shot", tag))
                if shot and shot["rows"]:
                    names, home = self.scene_names(), f"home{j}"
                    at = shot["edit"].get("home")
                    n = names.index(at) + 1 if at in names else k + 1
                    self.c.create_text(ax + aw - px(16), y + slot / 2 + px(2), text=f"чат на СС {n}", anchor="e",
                                       font=(FONT["semi"], 9), fill=WHITE if n != k + 1 else SUB, tags=("shot", home))
                    self.c.tag_bind(home, "<Enter>", lambda _, t=home: (self.c.itemconfig(t, fill=WHITE),
                                                                        self.c.config(cursor="hand2")))
                    self.c.tag_bind(home, "<Leave>", lambda _, t=home, c=WHITE if n != k + 1 else SUB: (
                        self.c.itemconfig(t, fill=c), self.c.config(cursor="")))
                self.c.tag_bind(tag, "<Enter>", lambda _: self.c.config(cursor="hand2"))
                self.c.tag_bind(tag, "<Leave>", lambda _: self.c.config(cursor=""))
            elif y + slot > ay and y < ay + ah:
                r = shot["rows"][i]
                if id(shot) not in breaks:
                    breaks[id(shot)] = compose.cuts(shot["rows"], shot["edit"])
                cuts = breaks[id(shot)]
                tag = f"row{j}"
                self.c.create_rectangle(ax, y, ax + aw, y + slot, fill=BLACK, outline="",
                                        tags=("shot", tag, tag + "-bg"))
                crop = chat.masked(r, preview=True)[:, :r["glyphs"][-1][1] + 8] * (1.0 if r["keep"] else 0.3)
                img = Image.fromarray(np.uint8(np.clip(crop, 0, 255)))
                if s < 1:
                    img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.row_photos.append(photo)
                self.c.create_image(ax + px(16), y + slot / 2, anchor="w", image=on if r["keep"] else off,
                                    tags=("shot", tag))
                self.c.create_image(ax + px(48), y + slot / 2, anchor="w", image=photo, tags=("shot", tag))
                if not r["keep"]:
                    self.c.create_line(ax + px(48), y + slot / 2, ax + px(48) + img.width, y + slot / 2, fill=LINE,
                                       tags=("shot", tag))
                for a, b in r.get("drop", []):
                    self.c.create_line(ax + px(48) + a * s, y + slot / 2, ax + px(48) + (b + 1) * s, y + slot / 2,
                                       fill=ERR, width=max(1, px(2)), tags=("shot", tag))
                cut, idle = f"cut{j}", WHITE if i in cuts else DIM
                if i in cuts:
                    self.c.create_line(ax + px(16), y, ax + aw - px(16), y, fill=SUB, dash=(4, 3), tags=("shot",))
                    self.c.create_text(ax + aw - px(52), y + px(3), text=f"часть {cuts.index(i) + 2}", fill=WHITE,
                                       anchor="ne", font=(FONT["semi"], 9), tags=("shot",))
                if i:
                    glyph, face = (ICONS["cut"], (FONT["icon"], 12)) if FONT["icon"] else ("✂", (FONT["ui"], 12))
                    self.c.create_text(ax + aw - px(28), y + slot / 2, text=glyph, font=face, tags=("shot", cut),
                                       fill=idle)
                    self.c.tag_bind(cut, "<Enter>", lambda _, t=cut: (self.c.itemconfig(t, fill=WHITE),
                                                                      self.c.config(cursor="hand2")))
                    self.c.tag_bind(cut, "<Leave>", lambda _, t=cut, c=idle: (self.c.itemconfig(t, fill=c),
                                                                              self.c.config(cursor="")))
                self.c.tag_bind(tag, "<Enter>", lambda _, t=tag, c=cut, on=i in cuts: (
                    self.c.itemconfig(t + "-bg", fill=ROW), self.c.itemconfig(c, fill=WHITE if on else SUB),
                    self.c.config(cursor="hand2")))
                self.c.tag_bind(tag, "<Leave>", lambda _, t=tag, c=cut, d=idle: (
                    self.c.itemconfig(t + "-bg", fill=BLACK), self.c.itemconfig(c, fill=d),
                    self.c.config(cursor="")))
            y += slot
        self.c.tag_lower("shot")

    def toggle_word(self, j, word, key):
        shot, i = self.items[j][:2]
        r = shot["rows"][i]
        other = "drop" if key == "hide" else "hide"
        mine = [tuple(span) for span in r.get(key, [])]
        r[other] = [tuple(span) for span in r.get(other, []) if tuple(span) != word]
        r[key] = [span for span in mine if span != word] if word in mine else mine + [word]
        for name, field in compose.MARKS:
            shot["edit"][field] = compose.spans_of(shot["rows"], name)
        self.draw_lines(self.area())
        self.schedule_save(shot)

    def open_popup(self, j, word):
        shot, i = self.items[j][:2]
        r = shot["rows"][i]
        hidden = word in [tuple(span) for span in r.get("hide", [])]
        gone = word in [tuple(span) for span in r.get("drop", [])]
        picks = (("hide", "Убрать плашку" if hidden else "Закрыть плашкой"),
                 ("drop", "Вернуть слово" if gone else "Удалить слово"), ("row", "Убрать строку"))
        s, top = self.lines_s, self.lines_top + j * self.lines_slot
        left, right = self.lines_x0 + word[0] * s, self.lines_x0 + (word[1] + 1) * s
        self.c.create_rectangle(left - px(3), top + px(3), right + px(3), top + self.lines_slot - px(3), outline=WHITE,
                                tags=("popup",))
        font = (FONT["ui"], 10)
        item = px(34)
        w, h = max(tkfont.Font(family=FONT["ui"], size=10).measure(t) for _, t in picks) + px(40), item * 3 + px(8)
        ax, ay, aw, ah = self.area()
        x = min(max(left, ax + px(8)), ax + aw - w - px(8))
        y = top + self.lines_slot if top + self.lines_slot + h < ay + ah - px(8) else top - h
        self.popup_photo = ImageTk.PhotoImage(rounded(w, h, px(10), SLATE, LINE, 1.2))
        self.c.create_image(x, y, anchor="nw", image=self.popup_photo, tags=("popup",))
        for k, (key, text) in enumerate(picks):
            tag, row = f"pop-{key}", y + px(4) + k * item
            self.c.create_rectangle(x + px(4), row, x + w - px(4), row + item, fill=SLATE, outline="",
                                    tags=("popup", tag, tag + "-bg"))
            self.c.create_text(x + px(18), row + item / 2, text=text, anchor="w", fill=WHITE, font=font,
                               tags=("popup", tag))
            self.c.tag_bind(tag, "<Enter>", lambda _, t=tag: (self.c.itemconfig(t + "-bg", fill=MIST),
                                                              self.c.config(cursor="hand2")))
            self.c.tag_bind(tag, "<Leave>", lambda _, t=tag: (self.c.itemconfig(t + "-bg", fill=SLATE),
                                                              self.c.config(cursor="")))
        self.popup = {"j": j, "word": word}

    def close_popup(self):
        self.c.delete("popup")
        self.popup = None

    def popup_pick(self, key):
        j, word = self.popup["j"], self.popup["word"]
        self.close_popup()
        shot, i = self.items[j][:2]
        if key != "row":
            self.toggle_word(j, word, key)
            return
        shot["rows"][i]["keep"] = False
        shot["edit"]["keep"] = [r["keep"] for r in shot["rows"]]
        self.draw_lines(self.area())
        self.count.config(text=self.count_text())
        self.schedule_save(shot)

    def toggle_cut(self, j):
        shot, i = self.items[j][:2]
        rows, edit = shot["rows"], shot["edit"]
        breaks = compose.cuts(rows, edit)
        spots = compose.places(edit, len(breaks) + 1)[1:]
        if i in breaks:
            k = breaks.index(i)
            breaks.pop(k)
            spots.pop(k)
        else:
            k = sorted(breaks + [i]).index(i)
            used = [edit["pos"]] + spots
            order = list(compose.SPARE_PLACES[compose.corner_of(edit["pos"])]) + list(config.CHAT_POSITIONS)
            free = [c for c in order if c not in used]
            breaks.insert(k, i)
            spots.insert(k, free[0] if free else compose.corner_of(used[k]))
        edit["breaks"], edit["places"] = breaks, spots
        self.draw_lines(self.area())
        self.count.config(text=self.count_text())
        self.schedule_save(shot)

    def count_text(self):
        shots = [s for _, s in self.members() if s] if self.scene_names() else [self.shot]
        kept, total = sum(r["keep"] for s in shots for r in s["rows"]), sum(len(s["rows"]) for s in shots)
        if len(shots) > 1:
            return f"В сцене {kept} из {total}"
        n = len(compose.parts(self.shot["rows"], self.shot["edit"]))
        return f"В СС {kept} из {total}" + (f" · частей: {n}" if n > 1 else "")

    def set_place(self, part, pos):
        shot = self.target
        edit = shot["edit"]
        if part == 0:
            edit["pos"] = pos
            return
        spots = compose.places(edit, len(compose.parts(shot["rows"], edit)))[1:]
        spots[part - 1] = pos
        edit["places"] = spots

    def pick_place(self, part, pos):
        if self.target is None:
            return
        self.set_place(part, pos)
        self.redraw()
        self.schedule_save()

    def row_at(self, y):
        return min(max(int((y - self.lines_top) // self.lines_slot), 0), len(self.items) - 1)

    def mark_rows(self, a, b, drag):
        touched = drag["shots"]
        for shot, i, _, name in self.items[min(a, b):max(a, b) + 1]:
            if i is not None:
                shot["rows"][i]["keep"] = drag["keep"]
                touched[name] = shot
        for shot in touched.values():
            shot["edit"]["keep"] = [r["keep"] for r in shot["rows"]]
        self.draw_lines(self.area())
        self.count.config(text=self.count_text())

    def draw_donors(self, area):
        self.c.delete("shot")
        ax, ay, aw, ah = area
        out = self.shot["out"]
        names = store.donors(out, self.name if self.tool == "scenepick" else self.current(), self.names)
        if not names:
            self.c.create_text(ax + aw // 2, ay + ah // 2, text="Других СС с исходными кадрами нет", fill=SUB,
                               font=(FONT["ui"], 12), tags=("shot",))
            return
        picking = self.tool == "scenepick"
        chosen = set(self.scene_names()) | {self.name}
        if picking:
            names = [n for n in reversed(self.names) if n in chosen or n in names]
            ticks = [ImageTk.PhotoImage(tick(px(20), on)) for on in (False, True)]
            self.photos += ticks
        cols = 2 if len(names) <= 4 else 3 if len(names) <= 9 else 4
        lines = -(-len(names) // cols)
        gap, cap = px(16), px(28)
        cw = (aw - gap * (cols - 1)) / cols
        ch = min(cw * 0.75, (ah - gap * (lines - 1)) / lines - cap)
        top = ay + (ah - lines * (ch + cap) - gap * (lines - 1)) / 2
        for k, name in enumerate(names):
            x, y = ax + (k % cols) * (cw + gap), top + (k // cols) * (ch + cap + gap)
            tag = f"donor{k}"
            photo = self.thumb(out, name, (max(1, round(cw)), max(1, round(ch))))
            w, h = (photo.width(), photo.height()) if photo else (round(cw), round(ch))
            left, up = x + (cw - w) / 2, y + (ch - h) / 2
            on = picking and name in chosen
            idle = WHITE if on else HAIR
            if photo:
                self.c.create_image(left, up, anchor="nw", image=photo, tags=("shot", tag))
            self.c.create_rectangle(left - 1, up - 1, left + w, up + h, outline=idle, width=2 if on else 1,
                                    fill="" if photo else ROW, tags=("shot", tag, tag + "-box"))
            if picking:
                self.c.create_image(left + px(8), up + px(8), anchor="nw", image=ticks[on], tags=("shot", tag))
            mine = picking and name == self.name
            self.c.create_text(left, up + h + px(8), text=when(name) + (" · эта СС" if mine else ""), anchor="nw",
                               fill=WHITE if on else SUB, font=(FONT["ui"], 10), tags=("shot", tag, tag + "-label"))
            if mine:
                continue
            self.c.tag_bind(tag, "<Button-1>", lambda _, n=name: self.donor_pick(n))
            self.c.tag_bind(tag, "<Enter>", lambda _, t=tag: (self.c.itemconfig(t + "-box", outline=WHITE),
                                                              self.c.itemconfig(t + "-label", fill=WHITE),
                                                              self.c.config(cursor="hand2")))
            self.c.tag_bind(tag, "<Leave>", lambda _, t=tag, c=idle, f=WHITE if on else SUB: (
                self.c.itemconfig(t + "-box", outline=c), self.c.itemconfig(t + "-label", fill=f),
                self.c.config(cursor="")))

    def thumb(self, out, name, size):
        path = store.shot_image(out, name)
        try:
            key = (path, path.stat().st_mtime_ns, size)
            if key not in self.thumbs:
                with Image.open(path) as im:
                    im.draft("RGB", size)
                    im = im.convert("RGB")
                    im.thumbnail(size, Image.BILINEAR)
                if len(self.thumbs) > 48:
                    self.thumbs.clear()
                self.thumbs[key] = ImageTk.PhotoImage(im)
        except OSError:
            return None
        return self.thumbs[key]

    def donor_pick(self, name):
        if self.tool == "carry":
            self.carry(name)
            return
        if self.tool == "scenepick":
            self.toggle_scene(name)
            return
        self.c.config(cursor="watch")
        self.c.update_idletasks()
        try:
            shot = store.load_shot(self.shot["out"], name, self.app.cfg)
        except (OSError, ValueError):
            shot = None
        self.c.config(cursor="")
        if shot is None:
            self.note = "фон той СС не открылся"
            self.update_meta()
            return
        self.tool = "images"
        self.add_image(Image.fromarray(shot["bg"]))

    def carry(self, name):
        self.c.config(cursor="watch")
        self.c.update_idletasks()
        shot = self.target
        if shot is None:
            return
        try:
            added = store.carry_chat(shot, name, self.app.cfg)
        except (OSError, ValueError) as e:
            self.c.config(cursor="")
            self.note = f"чат не перенёсся: {e}"
            self.update_meta()
            return
        self.c.config(cursor="")
        self.tool = "lines"
        self.redraw()
        if added:
            self.schedule_save(shot)
        self.note = (f"из СС от {when(name)} добавлено строк: {added}" if added
                     else "все строки той СС уже есть в этой")
        self.update_meta()

    def drop_repeats(self):
        missing = [n for n, shot in self.members() if shot is None and self.cache.get(n) is not False]
        if missing:
            self.c.config(cursor="watch")
            self.c.update_idletasks()
        for name in missing:
            try:
                shot = store.load_shot(self.shot["out"], name, self.app.cfg)
            except (OSError, ValueError):
                shot = None
            self.cache[name] = shot or False
            self.remember(shot)
        self.c.config(cursor="")
        shots, gone = [shot for _, shot in self.members()], 0
        for shot, dup in zip(shots, store.repeats(shots)):
            if dup:
                for i in dup:
                    shot["rows"][i]["keep"] = False
                shot["edit"]["keep"] = [r["keep"] for r in shot["rows"]]
                self.schedule_save(shot)
                gone += len(dup)
        self.note = f"убрал повторы из сцены: {gone}" if gone else "повторов в сцене нет"
        if self.tool == "lines":
            self.redraw()
        self.update_meta()

    def reset_lines(self):
        keep = self.app.cfg["keep"]
        for shot in [s for _, s in self.members() if s] if self.scene_names() else [self.shot]:
            log = store.log_path(shot["out"], shot["name"]).exists()
            for r in shot["rows"]:
                r["keep"] = log or r["kind"] in keep
            shot["edit"]["keep"] = [r["keep"] for r in shot["rows"]]
            self.schedule_save(shot)
        self.redraw()

    def next_home(self, j):
        shot, _, k, name = self.items[j]
        names = [n for n, _ in self.loaded_members()]
        if shot is None or len(names) < 2:
            return
        at = shot["edit"].get("home")
        now = names.index(at) if at in names else names.index(name)
        to = names[(now + 1) % len(names)]
        shot["edit"]["home"] = None if to == name else to
        self.schedule_save(shot)
        self.draw_lines(self.area())

    def lines_hint(self, tags, e):
        if "popup" in tags:
            return None
        if any(re.fullmatch(r"cut\d+", t) for t in tags):
            return "Разрезать чат здесь — дальше пойдёт новая часть"
        if any(re.fullmatch(r"home\d+", t) for t in tags):
            return "Клик — перенести чат этой СС на следующую СС сцены"
        if any(re.fullmatch(r"head\d+", t) for t in tags):
            return "Клик — выбрать эту СС"
        row = next((t for t in tags if re.fullmatch(r"row\d+", t)), None)
        if row is None:
            return None
        shot, i = self.items[int(row[3:])][:2]
        if not shot["rows"][i]["keep"]:
            return "Клик — вернуть строку"
        if e.x < self.lines_x0 - px(4):
            return "Клик — убрать строку · веди мышью, чтобы отметить несколько"
        return "Клик по слову — закрыть или удалить его · по галочке — убрать строку"
