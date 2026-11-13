from PIL import ImageTk

from theme import FONT, LINE, SLATE, SUB, WHITE, px, rounded

STEPS = (
    ("media", "Это твоя СС", "Так она и сохранится в папку с СС. Любая правка сохраняется сама, Ctrl+Z — отменить, "
                             "Ctrl+Y — вернуть.", None),
    ("rail-lines", "Строки · клавиша 1", "Отметь, какие реплики попадут на СС. Клик по слову — закрыть его плашкой "
                                         "или удалить. Открой, чтобы идти дальше.", "lines"),
    ("rail-crop", "Кадр · клавиша 2", "Формат и размер: квадрат, 16:9 или свой W×H. Тяни картинку, чтобы выбрать, "
                                      "что попадёт в кадр.", "crop"),
    ("rail-text", "Текст · клавиша 3", "Размер текста, обводка и угол чата. Сам чат можно тянуть мышью.", "text"),
    ("rail-style", "Стиль · клавиша 7", "Пресеты цвета, коррекция и свой LUT — например, тот же, что в ReShade.",
     "style"),
    ("rail-blur", "Размытие · клавиша 8", "Обведи мышью номер машины, лицо или ник — на СС оно размоется.", "blur"),
    ("rail-copy", "Готово", "«Копировать» кладёт СС в буфер, на форуме вставляй через Ctrl+V. Обучение можно "
                            "пройти ещё раз в настройках.", None),
)
CARD_W = 320


class Tour:
    def __init__(self, feed, done):
        self.feed, self.done, self.k, self.photos = feed, done, 0, []

    def target(self):
        key = STEPS[self.k][0]
        if key == "media":
            geo = self.feed.painter.geo
            if not geo:
                return None
            ix, iy, dw, dh = geo["img"]
            return ix, iy, ix + dw, iy + dh
        box = self.feed.c.bbox(f"{key}-label", f"{key}-ink", f"{key}-on")
        if box is None:
            return None
        x0, y0, x1, y1 = box
        return x0 - px(10), y0 - px(6), x1 + px(10), y1 + px(2)

    def draw(self):
        feed, c = self.feed, self.feed.c
        c.delete("tour")
        self.photos = []
        while STEPS[self.k][3] and feed.tool == STEPS[self.k][3]:
            self.k += 1
        box = self.target()
        if feed.shot is None or feed.index == 0 or box is None:
            return
        _, title, text, _ = STEPS[self.k]
        pad, gap = px(16), px(8)
        x0, y0, x1, y1 = box
        ring = rounded(x1 - x0 + 2 * gap, y1 - y0 + 2 * gap, px(12), None, WHITE, 2)
        self.photos.append(ImageTk.PhotoImage(ring))
        c.create_image(x0 - gap, y0 - gap, anchor="nw", image=self.photos[-1], tags=("tour",))
        w = px(CARD_W)
        media = STEPS[self.k][0] == "media"
        left = x0 + px(20) if media else x0 - gap - px(14) - w
        head = c.create_text(left + pad, 0, text=title, anchor="nw", font=(FONT["semi"], 12), fill=WHITE,
                             width=w - 2 * pad, tags=("tour",))
        body = c.create_text(left + pad, 0, text=text, anchor="nw", font=(FONT["ui"], 10), fill=SUB,
                             width=w - 2 * pad, tags=("tour",))
        th = c.bbox(head)[3] - c.bbox(head)[1]
        bh = c.bbox(body)[3] - c.bbox(body)[1]
        h = pad + th + px(6) + bh + px(18) + px(22) + pad
        top = y1 - h - px(20) if media else min(max((y0 + y1) / 2 - h / 2, px(12)), c.winfo_height() - h - px(12))
        c.coords(head, left + pad, top + pad)
        c.coords(body, left + pad, top + pad + th + px(6))
        card = rounded(w, h, px(14), SLATE, LINE, 1)
        self.photos.append(ImageTk.PhotoImage(card))
        bg = c.create_image(left, top, anchor="nw", image=self.photos[-1], tags=("tour",))
        c.tag_lower(bg, head)
        last = self.k == len(STEPS) - 1
        y = top + h - pad - px(11)
        c.create_text(left + pad, y, text=f"{self.k + 1} из {len(STEPS)}", anchor="w", font=(FONT["ui"], 9), fill=SUB,
                      tags=("tour",))
        nxt = c.create_text(left + w - pad, y, text="Готово" if last else "Далее", anchor="e",
                            font=(FONT["semi"], 10), fill=WHITE, tags=("tour", "tour-next"))
        if not last:
            c.create_text(c.bbox(nxt)[0] - px(18), y, text="Пропустить", anchor="e", font=(FONT["ui"], 10),
                          fill=SUB, tags=("tour", "tour-skip"))
        for tag, action in (("tour-next", self.next), ("tour-skip", self.finish)):
            c.tag_bind(tag, "<Button-1>", lambda _, f=action: f())
            c.tag_bind(tag, "<Enter>", lambda _: c.config(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda _: c.config(cursor=""))
        c.tag_raise("tour")

    def next(self):
        self.k += 1
        if self.k >= len(STEPS):
            self.finish()
        else:
            self.draw()

    def finish(self):
        self.feed.c.delete("tour")
        self.feed.tour = None
        self.done()
