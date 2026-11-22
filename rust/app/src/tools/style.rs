use std::time::{Duration, Instant};

use eframe::egui::{self, Id, Ui, vec2};
use engine::compose;

use crate::feed::Feed;
use crate::theme::{self, ROW, WHITE};
use crate::widgets;

impl Feed {
    pub fn sheet_style(&mut self, ui: &mut Ui, w: f32) {
        let Some(shot) = self.shot.as_ref() else { return };
        let edit = shot.edit.clone();
        let out = shot.out.clone();
        let whole = if self.scene_names().is_empty() { "" } else { " · вся сцена" };
        widgets::field(ui, &format!("Пресет{whole}"), 0.0);
        let preset = edit.preset.clone().filter(|p| theme::PRESET_NAMES.iter().any(|(k, _)| k == p)).unwrap_or("none".into());
        if let Some(v) = widgets::choice(ui, Id::unique("preset"), theme::PRESET_NAMES, &preset, w) {
            self.change(|e| e.preset = Some(v));
        }
        widgets::field(ui, &format!("Коррекция{whole}"), 14.0);
        let look = edit.look.clone().unwrap_or_default();
        for (key, title) in theme::LOOK_NAMES {
            widgets::label(ui, title, 2.0);
            let value = look.get(*key).copied().unwrap_or(0.0);
            let lo = theme::look_range(key);
            let bar = widgets::slider(ui, Id::unique(("look", *key)), lo, 100.0, value, 1.0, &|v| theme::look_value(v, lo), w);
            if bar.moved {
                let k = key.to_string();
                let v = bar.value.round();
                self.change(|e| {
                    let mut look = e.look.clone().unwrap_or_default();
                    look.insert(k, v);
                    look.retain(|_, v| *v != 0.0);
                    e.look = Some(look);
                });
            }
        }
        if widgets::buttons(ui, Id::unique("look-reset"), &["Сбросить коррекцию"], 8.0).is_some() {
            self.change(|e| e.look = Some(Default::default()));
        }
        widgets::field(ui, &format!("LUT{whole}"), 14.0);
        let lut = edit.lut.clone();
        let labels: Vec<&str> = if lut.is_some() { vec!["Загрузить .cube", "Убрать"] } else { vec!["Загрузить .cube"] };
        match widgets::buttons(ui, Id::unique("lut"), &labels, 0.0) {
            Some(0) => {
                if let Some(path) = rfd::FileDialog::new().set_title("LUT для Snapline").add_filter("LUT", &["cube"]).add_filter("Все файлы", &["*"]).pick_file() {
                    match compose::add_lut(&out, &path) {
                        Ok(name) => self.change(|e| e.lut = Some(name)),
                        Err(e) => self.note = format!("LUT не загрузился: {e}"),
                    }
                }
            }
            Some(1) => self.change(|e| e.lut = None),
            _ => {}
        }
        widgets::label(ui, &match &lut {
            Some(l) => format!("Сейчас: {l}"),
            None => "Свой цветокор из .cube — тот же, что в ReShade или видеоредакторе.".into(),
        }, 6.0);
        let style = edit.style.clone().filter(|s| theme::STYLES.iter().any(|(k, _)| k == s)).unwrap_or("none".into());
        widgets::field(ui, "Камера · тест", 14.0);
        if let Some(v) = widgets::choice(ui, Id::unique("camera"), theme::STYLES, &style, w) {
            self.style_text = engine::styles::label(&v).unwrap_or("").to_string();
            self.change(|e| {
                e.style = Some(v);
                e.style_text = None;
            });
        }
        if style != "none" {
            widgets::field(ui, "Надпись", 14.0);
            if self.style_due.is_none() {
                self.style_text = edit.style_text.clone().unwrap_or_else(|| engine::styles::label(&style).unwrap_or("").to_string());
            }
            let resp = ui.add(egui::TextEdit::singleline(&mut self.style_text).desired_width(w).font(theme::ui(10.0))
                .text_color(WHITE).background_color(ROW).margin(vec2(6.0, 5.0)));
            if resp.changed() {
                self.style_due = Some(Instant::now() + Duration::from_millis(300));
            }
            widgets::label(ui, "Дата и время — из момента съёмки. Чат остаётся чётким и обходит надписи.", 6.0);
        }
    }
}
