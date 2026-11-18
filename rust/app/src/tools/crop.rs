use eframe::egui::{Id, Ui};
use engine::compose;
use engine::edit::Join;

use crate::feed::Feed;
use crate::theme::{self, FIELD_DEFAULT};
use crate::widgets;

impl Feed {
    pub fn sheet_crop(&mut self, ui: &mut Ui, w: f32) {
        let Some(shot) = self.target() else { return };
        let names = self.scene_names();
        let edit = shot.edit.clone();
        let look = self.look(shot).0;
        let base = compose::plan(shot.bg.dimensions(), &look, None).base;
        let whole = if names.is_empty() { "" } else { " · вся сцена" };
        widgets::field(ui, &format!("Формат{whole}"), 0.0);
        let key = format!("crop:{}", self.target_name().unwrap_or_default());
        if self.frame_text_for != key {
            self.frame_text_for = key;
            self.frame_text = (String::new(), String::new());
        }
        let mut text = self.frame_text.clone();
        let picked = crate::tools::frame_pick(ui, Id::unique("crop-format"), theme::FORMATS, &look.format, &mut text, base, w,
                                              engine::config::FRAME_RANGE);
        self.frame_text = text;
        if let Some(v) = picked {
            self.set_frame(&v);
        }
        widgets::field(ui, &format!("Размер{whole}"), 14.0);
        if engine::config::exact_of(&look.format).is_some() {
            widgets::label(ui, "Задан шириной и высотой кадра", 0.0);
        } else {
            let mut options: Vec<(&str, &str)> = theme::SIZES.to_vec();
            let size = look.size.clone();
            if !theme::SIZES.iter().any(|(k, _)| *k == size) {
                options.push((size.as_str(), size.as_str()));
            }
            if let Some(v) = widgets::choice(ui, Id::unique("crop-size"), &options, &size, w) {
                self.set_size(&v);
            }
        }
        widgets::field(ui, "Приближение", 14.0);
        let zoom = widgets::slider(ui, Id::unique("zoom"), 1.0, 3.0, edit.zoom, 0.05, &|v| format!("{v:.2}×"), w);
        if zoom.moved {
            self.change(|e| e.zoom = zoom.value);
        }
        widgets::field(ui, "Наклон", 14.0);
        let tilt = widgets::slider(ui, Id::unique("tilt"), -compose::TILT_MAX, compose::TILT_MAX, edit.tilt(), 1.0, &|v| format!("{v:.0}°"), w);
        if tilt.moved {
            self.change(|e| e.tilt = Some(tilt.value.round()));
        }
        match widgets::buttons(ui, Id::unique("crop-buttons"), &["По центру", "Отразить"], 12.0) {
            Some(0) => self.change(|e| e.center = [0.5, 0.5]),
            Some(1) => self.mirror_frame(),
            _ => {}
        }
        if !names.is_empty() {
            widgets::label(ui, "Тёмные полосы сверху и снизу — переходы между СС, чат на них не заходит.", 12.0);
            return;
        }
        let side = edit.join.as_ref().map(|j| j.side.clone()).filter(|s| compose::JOIN_SIDES.contains(&s.as_str())).unwrap_or("none".into());
        widgets::field(ui, "Расширить поле кадра", 18.0);
        if let Some(v) = widgets::choice(ui, Id::unique("field-side"), theme::SIDES, &side, w) {
            self.set_field_side(&v);
        }
        if side == "none" {
            widgets::label(ui, "Место сбоку для второго ракурса или чата, СС остаётся своего размера.", 4.0);
            return;
        }
        let join = edit.join.clone().unwrap();
        widgets::field(ui, "Насколько", 14.0);
        let size = widgets::slider(ui, Id::unique("field-size"), 10.0, 100.0, (join.size * 100.0).round(), 1.0, &|v| format!("{v:.0}%"), w);
        if size.moved {
            self.change(|e| if let Some(j) = e.join.as_mut() { j.size = size.value / 100.0 });
        }
        widgets::field(ui, "Мягкий край СС", 14.0);
        let fade = widgets::slider(ui, Id::unique("field-fade"), 0.0, 100.0, (join.fade * 100.0).round(), 1.0, &|v| format!("{v:.0}%"), w);
        if fade.moved {
            self.change(|e| if let Some(j) = e.join.as_mut() { j.fade = fade.value / 100.0 });
        }
        widgets::label(ui, "Новое место заполнено размытым продолжением СС.", 10.0);
    }

    pub fn mirror_frame(&mut self) {
        let Some(shot) = self.target() else { return };
        let look = self.look(shot).0;
        let p = compose::plan(shot.bg.dimensions(), &look, None);
        let blurs = compose::mirror_blurs(shot.edit.blurs.as_deref().unwrap_or(&[]), &p);
        self.change(|e| {
            e.mirror = !e.mirror;
            e.center = [engine::py::round_to(1.0 - e.center[0], 5), e.center[1]];
            e.tilt = Some(-e.tilt());
            if !blurs.is_empty() {
                e.blurs = Some(blurs);
            }
        });
    }

    pub fn set_field_side(&mut self, side: &str) {
        let side = side.to_string();
        self.change(|e| {
            let (size, fade) = e.join.as_ref().map(|j| (j.size, j.fade)).unwrap_or(FIELD_DEFAULT);
            e.join = Some(Join { side, size, fade, extra: Default::default() });
        });
        self.painter.forget();
    }

    pub fn set_frame(&mut self, value: &str) {
        let value = value.to_string();
        if self.scene_names().is_empty() {
            self.change(|e| {
                e.format = value;
                e.center = [0.5, 0.5];
            });
            return;
        }
        let Some(name) = self.name() else { return };
        if let Some(shot) = self.shot.as_mut() {
            shot.edit.format = value;
        }
        self.schedule_save(&name);
        if self.previewing() {
            self.want_preview();
        }
    }

    pub fn set_size(&mut self, value: &str) {
        let value = value.to_string();
        if self.scene_names().is_empty() {
            self.change(|e| e.size = value);
            return;
        }
        let Some(name) = self.name() else { return };
        if let Some(shot) = self.shot.as_mut() {
            shot.edit.size = value;
        }
        self.schedule_save(&name);
    }
}
