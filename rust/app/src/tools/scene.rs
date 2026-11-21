use eframe::egui::{self, Align2, Color32, CornerRadius, CursorIcon, Id, Pos2, Rect, Sense, Stroke, TextureHandle, Ui, vec2};
use engine::compose;
use engine::edit::{Scene, Seam, SeamPart};
use engine::store;

use crate::feed::{Feed, full_uv, texture};
use crate::theme::{self, SUB, VOID, WHITE};
use crate::widgets;

impl Feed {
    pub fn seams(&self) -> Vec<Seam> {
        let Some(scene) = self.shot.as_ref().and_then(|s| s.edit.scene.as_ref()) else { return vec![] };
        let n = self.scene_names().len().saturating_sub(1);
        (0..n).map(|k| scene.seams.get(k).map(|s| s.full()).unwrap_or_default()).collect()
    }

    pub fn scene_plan(&self) -> (u32, Vec<u32>, Vec<u32>) {
        let shot = self.shot.as_ref().unwrap();
        let head = &shot.edit;
        let width = compose::plan(shot.bg.dimensions(), &compose::framed(head, head), None).size.0;
        let hs: Vec<Option<u32>> = self.members().iter().map(|(_, s)| {
            s.map(|s| compose::plan(s.bg.dimensions(), &compose::framed(&s.edit, head), Some(width)).size.1)
        }).collect();
        let names = self.scene_names();
        let mine = shot.name.as_ref().and_then(|n| names.iter().position(|x| x == n)).and_then(|k| hs[k]).unwrap_or(width);
        let hs: Vec<u32> = hs.into_iter().map(|h| h.unwrap_or(mine)).collect();
        let laps = compose::laps_of(&hs, &self.seams());
        (width, hs, laps)
    }

    pub fn scene_size(&self) -> (u32, u32) {
        let (w, hs, laps) = self.scene_plan();
        (w, hs.iter().sum::<u32>() - laps.iter().sum::<u32>())
    }

    pub fn draw_scene(&mut self, ui: &Ui, area: Rect) {
        if self.tool.is_none() {
            let name = self.name().unwrap_or_default();
            self.draw_saved(ui, area, &name);
            return;
        }
        let Some((img, tex)) = self.preview.clone() else {
            ui.painter().text(area.center(), Align2::CENTER_CENTER, "Собираю сцену…", theme::ui(12.0), SUB);
            return;
        };
        let (w, h) = (img.width() as f64, img.height() as f64);
        let (aw, ah) = (area.width() as f64, area.height() as f64);
        let fit = (aw / w).min(ah / h);
        self.view.0 = self.view.0.clamp(1.0, (4.0 / fit).max(1.0));
        let d = fit * self.view.0;
        let vw = (w * d).round().min(aw).max(1.0);
        let vh = (h * d).round().min(ah).max(1.0);
        let (sw, sh) = (w.min(vw / d), h.min(vh / d));
        let x0 = (self.view.1 * w - sw / 2.0).min(w - sw).max(0.0);
        let y0 = (self.view.2 * h - sh / 2.0).min(h - sh).max(0.0);
        self.view.1 = (x0 + sw / 2.0) / w;
        self.view.2 = (y0 + sh / 2.0) / h;
        let rect = Rect::from_min_size(Pos2::new(area.left() + ((aw - vw) / 2.0).floor() as f32, area.top() + ((ah - vh) / 2.0).floor() as f32),
                                       vec2(vw as f32, vh as f32));
        self.view_box = Some((x0, y0, d));
        self.preview_rect = Some(rect);
        let uv = Rect::from_min_max(Pos2::new((x0 / w) as f32, (y0 / h) as f32), Pos2::new(((x0 + sw) / w) as f32, ((y0 + sh) / h) as f32));
        ui.painter().image(tex.id(), rect, uv, Color32::WHITE);
        let Some(layout) = &self.layout else { return };
        let Ok(k) = self.seam.parse::<usize>() else { return };
        if k >= layout.laps.len() {
            return;
        }
        let top = layout.tops[k + 1] as f64;
        let mut edges = vec![top, top + layout.laps[k] as f64];
        edges.dedup();
        for y in &edges {
            let sy = rect.top() + ((y - y0) * d) as f32;
            if sy >= rect.top() && sy <= rect.bottom() {
                ui.painter().line_segment([Pos2::new(rect.left(), sy + 1.0), Pos2::new(rect.right(), sy + 1.0)], Stroke::new(2.0, VOID));
                crate::tools::dashed_line(ui.painter(), Pos2::new(rect.left(), sy), Pos2::new(rect.right(), sy), WHITE, 6.0, 4.0);
            }
        }
        let label = format!("переход {}–{}", k + 1, k + 2);
        let ly = (rect.top() + ((edges[0] - y0) * d) as f32 - 24.0).max(rect.top() + 4.0).min(rect.bottom() - 24.0);
        let tw = widgets::text_width(ui, &label, theme::semi(9.0)) + 16.0;
        let r = Rect::from_min_size(Pos2::new(rect.left() + 6.0, ly), vec2(tw, 20.0));
        ui.painter().rect_filled(r, CornerRadius::ZERO, VOID);
        ui.painter().text(r.center(), Align2::CENTER_CENTER, label, theme::semi(9.0), WHITE);
    }

    pub fn seam_at(&self, y: f32) -> Option<usize> {
        let (_, y0, d) = self.view_box?;
        let layout = self.layout.as_ref()?;
        let rect = self.preview_rect?;
        let sy = y0 + (y - rect.top()) as f64 / d;
        let near = 8.0 / d;
        layout.laps.iter().enumerate().find(|(k, lap)| {
            let top = layout.tops[k + 1] as f64;
            top - near <= sy && sy <= top + **lap as f64 + near
        }).map(|(k, _)| k)
    }

    pub fn sheet_scene(&mut self, ui: &mut Ui, w: f32) {
        let names = self.scene_names();
        widgets::label(ui, "Несколько СС одна под другой с плавными переходами — раскадровка для форума. Чат можно тянуть мышью прямо здесь: на переход или на другую СС.", 0.0);
        let labels: Vec<&str> = if names.is_empty() { vec!["Выбрать СС"] } else { vec!["Выбрать СС", "Разобрать"] };
        match widgets::buttons(ui, Id::unique("scene-buttons"), &labels, 0.0) {
            Some(0) => {
                self.toggle_tool("scenepick");
                return;
            }
            Some(1) => {
                self.drop_scene();
                return;
            }
            _ => {}
        }
        if names.is_empty() {
            return;
        }
        widgets::field(ui, "Порядок", 18.0);
        let mine = self.name().unwrap_or_default();
        let count = names.len();
        let mut action: Option<(&str, usize)> = None;
        for (k, name) in names.iter().enumerate() {
            let (row, _) = ui.allocate_exact_size(vec2(w, 36.0), Sense::hover());
            let mut x = row.left();
            if let Some(t) = self.frame_thumb(name) {
                let size = self.shown(&t);
                let r = Rect::from_min_size(self.snap(Pos2::new(x, row.center().y - size.y / 2.0)), size);
                let resp = ui.interact(r, Id::unique(("scene-thumb", k)), Sense::click());
                ui.painter().image(t.id(), r, full_uv(), Color32::WHITE);
                if resp.clicked() {
                    action = Some(("focus", k));
                }
                if resp.hovered() {
                    self.hint_text = Some("Показать эту СС в сцене крупно".into());
                }
                x += size.x + 8.0;
            }
            let text = format!("{}. {}{}", k + 1, theme::when(name), if *name == mine { " · эта" } else { "" });
            let tr = ui.painter().text(Pos2::new(x, row.center().y), Align2::LEFT_CENTER, text, theme::ui(10.0), if *name == mine { WHITE } else { SUB });
            if ui.interact(tr, Id::unique(("scene-name", k)), Sense::click()).clicked() {
                action = Some(("focus", k));
            }
            let mut bx = row.right();
            for (key, on, tip) in [("close", *name != mine, "Убрать из сцены"), ("down", k + 1 < count, "Ниже"), ("up", k > 0, "Выше"),
                                   ("crop", true, "Поправить эту СС: кадр, текст, картинки")] {
                let r = Rect::from_center_size(Pos2::new(bx - 12.0, row.center().y), vec2(24.0, 24.0));
                bx -= 26.0;
                if !on {
                    continue;
                }
                let resp = ui.interact(r, Id::unique(("scene-act", key, k)), Sense::click());
                ui.painter().text(r.center(), Align2::CENTER_CENTER, theme::icon(key), theme::glyph(11.0), if resp.hovered() { WHITE } else { SUB });
                if resp.hovered() {
                    ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
                    self.hint_text = Some(tip.into());
                }
                if resp.clicked() {
                    action = Some((key, k));
                }
            }
            ui.add_space(4.0);
        }
        if let Some((what, k)) = action {
            match what {
                "close" => self.drop_frame(k),
                "down" => self.move_frame(k, 1),
                "up" => self.move_frame(k, -1),
                "crop" => {
                    let n = names[k].clone();
                    self.part = if Some(&n) == self.name().as_ref() { None } else { Some(n) };
                    self.toggle_tool("crop");
                }
                _ => {
                    if let Some(layout) = self.layout.clone() {
                        if let (Some((img, _)), true) = (&self.preview, k < layout.tops.len()) {
                            let (iw, ih) = (img.width() as f64, img.height() as f64);
                            let top = layout.tops[k] as f64;
                            let hh = layout.heights[k] as f64;
                            self.view.1 = 0.5;
                            self.view.2 = (top + hh / 2.0) / ih;
                            let area = self.preview_rect.unwrap_or(Rect::from_min_size(Pos2::ZERO, vec2(800.0, 800.0)));
                            let _ = iw;
                            self.view.0 = (area.width() as f64 / iw).min(area.height() as f64 / hh) / (area.width() as f64 / iw).min(area.height() as f64 / ih);
                        }
                    }
                }
            }
            return;
        }
        let mut options: Vec<(String, String)> = vec![("all".into(), "Все".into())];
        for k in 0..count - 1 {
            options.push((k.to_string(), format!("{}–{}", k + 1, k + 2)));
        }
        if !options.iter().any(|(k, _)| *k == self.seam) {
            self.seam = "all".into();
        }
        let seams = self.seams();
        let look = seams.get(self.seam.parse::<usize>().unwrap_or(0)).copied().unwrap_or_default();
        widgets::field(ui, "Переход", 10.0);
        let refs: Vec<(&str, &str)> = options.iter().map(|(a, b)| (a.as_str(), b.as_str())).collect();
        if let Some(v) = widgets::choice(ui, Id::unique("seam-pick"), &refs, &self.seam.clone(), w) {
            self.seam = v;
        }
        let pct = |v: f64| format!("{v:.0}%");
        widgets::field(ui, "Плавность", 14.0);
        let fade = widgets::slider(ui, Id::unique("seam-fade"), 0.0, 50.0, (look.fade * 100.0).round(), 1.0, &pct, w);
        if fade.moved {
            self.change_seam(|s| s.fade = fade.value / 100.0);
        }
        widgets::field(ui, "Размытие", 14.0);
        let blur = widgets::slider(ui, Id::unique("seam-blur"), 0.0, 100.0, (look.blur * 100.0).round(), 1.0, &pct, w);
        if blur.moved {
            self.change_seam(|s| s.blur = blur.value / 100.0);
        }
        widgets::field(ui, "Затемнение", 14.0);
        let dark = widgets::slider(ui, Id::unique("seam-dark"), 0.0, 100.0, (look.dark * 100.0).round(), 1.0, &pct, w);
        if dark.moved {
            self.change_seam(|s| s.dark = dark.value / 100.0);
        }
        widgets::field(ui, "Просмотр", 10.0);
        if let Some(i) = widgets::buttons(ui, Id::unique("view-fit"), &["Целиком", "По ширине", "1:1"], 0.0) {
            let area = self.preview_rect.map(|r| {
                let (cx, cy) = (r.center().x, r.center().y);
                Rect::from_center_size(Pos2::new(cx, cy), r.size())
            });
            if let Some(a) = area {
                self.view_fit(["all", "width", "real"][i], a);
            }
        }
        ui.add_space(14.0);
        let info = self.preview_info.clone().unwrap_or_else(|| "собираю…".into());
        ui.label(egui::RichText::new(info).font(theme::semi(12.0)).color(WHITE));
    }

    pub fn thumb(&mut self, out: &std::path::Path, name: &str, size: (u32, u32)) -> Option<TextureHandle> {
        let ppp = self.ctx.pixels_per_point();
        let size = ((size.0 as f32 * ppp).round() as u32, (size.1 as f32 * ppp).round() as u32);
        let path = store::shot_image(out, name);
        let key = format!("thumb:{}:{:?}:{}x{}", path.display(), crate::feed::stamp(&path), size.0, size.1);
        if let Some(t) = self.thumbs.get(&key) {
            return Some(t.clone());
        }
        let img = image::open(&path).ok()?.to_rgb8();
        let k = (size.0 as f32 / img.width() as f32).min(size.1 as f32 / img.height() as f32).min(1.0);
        let small = engine::img::resize(&img, ((img.width() as f32 * k).round() as u32).max(1), ((img.height() as f32 * k).round() as u32).max(1),
                                        engine::img::Filter::Bilinear);
        if self.thumbs.len() > 48 {
            self.thumbs.clear();
        }
        let t = texture(&self.ctx, "thumb", &small);
        self.thumbs.insert(key, t.clone());
        Some(t)
    }

    pub fn frame_thumb(&mut self, name: &str) -> Option<TextureHandle> {
        let size = (54, 32);
        let ppp = self.ctx.pixels_per_point();
        let shot = self.shot.as_ref()?;
        if Some(name) != shot.name.as_deref() {
            let out = shot.out.clone();
            return self.thumb(&out, name, size);
        }
        let edit = &shot.edit;
        let key = format!("bg:{}:{}:{}:{}", std::sync::Arc::as_ptr(&shot.bg) as usize, edit.mirror, edit.tilt(), ppp);
        if let Some(t) = self.thumbs.get(&key) {
            return Some(t.clone());
        }
        let p = compose::plan(shot.bg.dimensions(), edit, None);
        let part = compose::bg_part(&shot.bg, p.rect, edit.mirror);
        let dims = part.dimensions();
        let part = compose::tilt_image(&part, edit.tilt(), dims);
        let k = (size.0 as f32 * ppp / part.width() as f32).min(size.1 as f32 * ppp / part.height() as f32);
        let small = engine::img::resize(&part, ((part.width() as f32 * k).round() as u32).max(1), ((part.height() as f32 * k).round() as u32).max(1),
                                        engine::img::Filter::Bilinear);
        let t = texture(&self.ctx, "frame-thumb", &small);
        self.thumbs.insert(key, t.clone());
        Some(t)
    }

    pub fn sheet_scenepick(&mut self, ui: &mut Ui) {
        widgets::label(ui, &format!("Отметь СС и нажми «Готово». Они встанут по времени съёмки и получат формат кадра этой СС, а строки, которые уже были выше, уберутся сами. До {} СС.", compose::SCENE_MAX), 0.0);
        if widgets::buttons(ui, Id::unique("scenepick-done"), &["Готово"], 8.0).is_some() {
            self.toggle_tool("scene");
        }
    }

    fn scene_lists(&self) -> (Vec<String>, Vec<SeamPart>) {
        let shot = self.shot.as_ref().unwrap();
        match &shot.edit.scene {
            Some(s) => (s.shots.clone(), s.seams.clone()),
            None => (vec![shot.name.clone().unwrap_or_default()], vec![]),
        }
    }

    pub fn set_scene(&mut self, shots: Vec<String>, seams: Vec<SeamPart>) {
        let Some(name) = self.name() else { return };
        if let Some(shot) = self.shot.as_mut() {
            shot.edit.scene = if shots.len() > 1 { Some(Scene { shots, seams, extra: Default::default() }) } else { None };
        }
        self.schedule_save(&name);
    }

    pub fn toggle_scene(&mut self, name: &str) {
        let (mut shots, mut seams) = self.scene_lists();
        if let Some(k) = shots.iter().position(|n| n == name) {
            shots.remove(k);
            if !seams.is_empty() {
                seams.remove(k.saturating_sub(1).min(seams.len() - 1));
            }
        } else if shots.len() >= compose::SCENE_MAX {
            self.note = format!("в сцену помещается до {} СС", compose::SCENE_MAX);
            return;
        } else {
            let k = shots.iter().position(|n| n.as_str() > name).unwrap_or(shots.len());
            shots.insert(k, name.to_string());
            self.fetch(name);
            self.added.insert(name.to_string());
            let near = k.saturating_sub(1);
            let copy = if seams.is_empty() { SeamPart::of(Seam::default()) } else { seams[near.min(seams.len() - 1)].clone() };
            seams.insert(near.min(seams.len()), copy);
        }
        self.set_scene(shots, seams);
    }

    pub fn move_frame(&mut self, k: usize, delta: isize) {
        let (mut shots, seams) = self.scene_lists();
        let j = (k as isize + delta) as usize;
        shots.swap(k, j);
        self.set_scene(shots, seams);
        self.want_preview();
    }

    pub fn drop_frame(&mut self, k: usize) {
        let (mut shots, mut seams) = self.scene_lists();
        shots.remove(k);
        if !seams.is_empty() {
            seams.remove(k.saturating_sub(1).min(seams.len() - 1));
        }
        self.set_scene(shots, seams);
        self.want_preview();
    }

    pub fn change_seam(&mut self, f: impl Fn(&mut Seam)) {
        let Some(name) = self.name() else { return };
        let one = self.seam.parse::<usize>().ok();
        let count = self.scene_names().len().saturating_sub(1);
        if let Some(scene) = self.shot.as_mut().and_then(|s| s.edit.scene.as_mut()) {
            while scene.seams.len() < count {
                scene.seams.push(SeamPart::of(Seam::default()));
            }
            for (k, s) in scene.seams.iter_mut().enumerate() {
                if one.is_none_or(|o| o == k) {
                    let mut full = s.full();
                    f(&mut full);
                    let extra = s.extra.clone();
                    *s = SeamPart { extra, ..SeamPart::of(full) };
                }
            }
        }
        self.want_preview();
        self.schedule_save(&name);
    }

    pub fn drop_scene(&mut self) {
        let Some(name) = self.name() else { return };
        if let Some(shot) = self.shot.as_mut() {
            shot.edit.scene = None;
        }
        self.preview = None;
        self.preview_info = None;
        self.want_preview();
        self.schedule_save(&name);
    }
}
