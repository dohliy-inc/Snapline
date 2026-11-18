use eframe::egui::{self, Align2, CornerRadius, CursorIcon, Id, Pos2, Rect, Sense, Stroke, StrokeKind, Ui, vec2};

use crate::feed::Feed;
use crate::theme::{self, LINE, SLATE, SUB, WHITE};

pub const STEPS: [(&str, &str, &str, Option<&str>); 7] = [
    ("media", "Это твоя СС", "Так она и сохранится в папку с СС. Любая правка сохраняется сама, Ctrl+Z — отменить, Ctrl+Y — вернуть.", None),
    ("lines", "Строки · клавиша 1", "Отметь, какие реплики попадут на СС. Клик по слову — закрыть его плашкой или удалить. Открой, чтобы идти дальше.", Some("lines")),
    ("text", "Текст · клавиша 2", "Размер текста, обводка и угол чата. Сам чат можно тянуть мышью.", Some("text")),
    ("crop", "Кадр · клавиша 3", "Формат и размер: квадрат, 16:9 или свой W×H. Тяни картинку, чтобы выбрать, что попадёт в кадр.", Some("crop")),
    ("blur", "Размытие · клавиша 5", "Обведи мышью номер машины, лицо или ник — на СС оно размоется.", Some("blur")),
    ("style", "Стиль · клавиша 6", "Пресеты цвета, коррекция и свой LUT — например, тот же, что в ReShade.", Some("style")),
    ("copy", "Готово", "«Копировать» кладёт СС в буфер, на форуме вставляй через Ctrl+V. Правый клик по СС — ещё действия. Обучение можно пройти ещё раз в настройках.", None),
];
const CARD_W: f32 = 320.0;

impl Feed {
    pub fn start_tour(&mut self) {
        if self.names.is_empty() {
            self.note = "Сначала сними СС: обучение проходит по редактору".into();
            return;
        }
        self.tour = Some(0);
        if self.index == 0 {
            self.go(1);
        }
    }

    pub fn finish_tour(&mut self) {
        self.tour = None;
        self.tour_done = true;
    }

    pub fn draw_tour(&mut self, ui: &mut Ui) {
        let Some(mut k) = self.tour else { return };
        while let Some(tool) = STEPS[k].3 {
            if self.tool == Some(tool) && k + 1 < STEPS.len() {
                k += 1;
            } else {
                break;
            }
        }
        self.tour = Some(k);
        if self.shot.is_none() || self.index == 0 {
            return;
        }
        let (key, title, text, _) = STEPS[k];
        let target = if key == "media" { self.geo.as_ref().map(|g| g.img) } else { self.rail_rects.get(key).copied() };
        let Some(b) = target else { return };
        let p = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, Id::unique("tour")));
        let (pad, gap) = (16.0, 8.0);
        p.rect_stroke(b.expand(gap), CornerRadius::same(12), Stroke::new(2.0, WHITE), StrokeKind::Middle);
        let media = key == "media";
        let left = if media { b.left() + 20.0 } else { b.left() - gap - 14.0 - CARD_W };
        let head = p.layout(title.to_string(), theme::semi(12.0), WHITE, CARD_W - 2.0 * pad);
        let body = p.layout(text.to_string(), theme::ui(10.0), SUB, CARD_W - 2.0 * pad);
        let (th, bh) = (head.size().y, body.size().y);
        let h = pad + th + 6.0 + bh + 18.0 + 22.0 + pad;
        let screen = ui.ctx().content_rect();
        let top = if media { b.bottom() - h - 20.0 } else { ((b.top() + b.bottom()) / 2.0 - h / 2.0).max(12.0).min(screen.bottom() - h - 12.0) };
        let card = Rect::from_min_size(Pos2::new(left, top), vec2(CARD_W, h));
        p.rect_filled(card, CornerRadius::same(14), SLATE);
        p.rect_stroke(card, CornerRadius::same(14), Stroke::new(1.0, LINE), StrokeKind::Inside);
        p.galley(Pos2::new(left + pad, top + pad), head, WHITE);
        p.galley(Pos2::new(left + pad, top + pad + th + 6.0), body, SUB);
        let last = k == STEPS.len() - 1;
        let y = top + h - pad - 11.0;
        p.text(Pos2::new(left + pad, y), Align2::LEFT_CENTER, format!("{} из {}", k + 1, STEPS.len()), theme::ui(9.0), SUB);
        let next = p.text(Pos2::new(left + CARD_W - pad, y), Align2::RIGHT_CENTER, if last { "Готово" } else { "Далее" }, theme::semi(10.0), WHITE);
        if ui.interact(next.expand(4.0), Id::unique("tour-next"), Sense::click()).on_hover_cursor(CursorIcon::PointingHand).clicked() {
            if last {
                self.finish_tour();
            } else {
                self.tour = Some(k + 1);
            }
            return;
        }
        if !last {
            let skip = p.text(Pos2::new(next.left() - 18.0, y), Align2::RIGHT_CENTER, "Пропустить", theme::ui(10.0), SUB);
            if ui.interact(skip.expand(4.0), Id::unique("tour-skip"), Sense::click()).on_hover_cursor(CursorIcon::PointingHand).clicked() {
                self.finish_tour();
            }
        }
    }
}
