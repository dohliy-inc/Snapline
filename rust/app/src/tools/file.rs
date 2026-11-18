use eframe::egui::{self, Id, Ui};

use crate::feed::Feed;
use crate::theme::{self, WHITE};
use crate::widgets;

impl Feed {
    pub fn sheet_file(&mut self, ui: &mut Ui, w: f32) {
        let Some(shot) = self.shot.as_ref() else { return };
        let edit = shot.edit.clone();
        widgets::field(ui, "Формат", 0.0);
        if let Some(v) = widgets::choice(ui, Id::unique("file-type"), theme::FILES, &edit.file, w) {
            self.change(|e| e.file = v);
        }
        if edit.file == "jpg" {
            widgets::field(ui, "Качество фона", 14.0);
            let q = widgets::slider(ui, Id::unique("quality"), 10.0, 100.0, edit.quality as f64, 1.0, &|v| format!("{v:.0}"), w);
            if q.moved {
                self.change(|e| e.quality = q.value as i64);
            }
            widgets::label(ui, "Сжимается только фон, текст чата всегда остаётся чётким.", 4.0);
        }
        ui.add_space(18.0);
        let info = self.preview_info.clone().unwrap_or_else(|| "считаю размер…".into());
        ui.label(egui::RichText::new(info).font(theme::semi(12.0)).color(WHITE));
        ui.add_space(2.0);
        widgets::label(ui, "Размер кадра — в «Кадре», цвет и стиль — в «Стиле».", 0.0);
    }
}
