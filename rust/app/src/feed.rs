use std::collections::{BTreeSet, HashMap, HashSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::mpsc::{Sender, channel};
use std::time::{Duration, Instant, SystemTime};

use eframe::egui::{self, Align2, Color32, ColorImage, CornerRadius, CursorIcon, FontId, Id, Mesh, Pos2, Rect, Sense, Shape,
                   Stroke, StrokeKind, TextureHandle, TextureOptions, Ui, vec2};
use engine::compose::{self, Layout};
use engine::config::Config;
use engine::edit::{Blur, Edit};
use engine::store::{self, Shot};
use image::RgbImage;
use serde_json::Value;

use crate::app::Msg;
use crate::assist::{Toast, remedies};
use crate::painter::{Geo, Painter};
use crate::theme::{self, ERR, LINE, MIST, SLATE, PAD, RAIL_W, SIDE_W, SUB, VOID, WHITE};
use crate::tools::logpick::LogView;
use crate::win;

pub enum Job {
    Save(Vec<Shot>),
    Delete(String, PathBuf, Config),
    Duplicate(String, PathBuf),
}

pub struct Rail {
    pub key: &'static str,
    pub label: String,
    pub active: bool,
}

#[derive(Clone)]
pub enum Drag {
    Chat { part: usize, x: f32, y: f32, at: Pos2 },
    Pan { x: f32, y: f32, center: [f64; 2] },
    Ov { part: usize, x: f32, y: f32, at: (f64, f64), crop: [f64; 4], shift: bool },
    Crop { handle: String, part: usize, x: f32, y: f32, crop: [f64; 4], b: crate::painter::OvGeo, size: (u32, u32) },
    BNew { k: usize, at: (f64, f64), before: Option<Vec<Blur>> },
    BMove { k: usize, at: (f64, f64), b: Blur },
    BSize { k: usize, corner: String, b: Blur },
    Rows { keep: bool, first: usize, last: usize, shots: HashSet<String>, moved: bool },
    Log { on: bool, first: usize, last: usize },
    View { x: f32, y: f32, at: (f64, f64), moved: bool },
    SceneChat { x: f32, y: f32, hit: (usize, usize, f64, f64, f64, f64), now: Pos2 },
}

#[derive(Clone)]
pub struct State {
    pub edit: Value,
    pub marks: Vec<(bool, Vec<(usize, usize)>, Vec<(usize, usize)>)>,
    pub key: String,
}

#[derive(Clone)]
pub struct Item {
    pub name: String,
    pub row: Option<usize>,
    pub k: usize,
}

pub struct Popup {
    pub j: usize,
    pub word: (usize, usize),
}

pub struct Feed {
    pub cfg: Config,
    pub tx: Sender<Msg>,
    pub ctx: egui::Context,
    pub names: Vec<String>,
    pub index: usize,
    pub shot: Option<Shot>,
    pub cache: HashMap<String, Option<Shot>>,
    pub loading: HashSet<String>,
    pub tool: Option<&'static str>,
    pub drag: Option<Drag>,
    pub busy: bool,
    pub message: Option<(String, String)>,
    pub note: String,
    pub saves: HashMap<String, Shot>,
    pub writing: HashSet<String>,
    pub save_due: Option<Instant>,
    pub jobs: Sender<Job>,
    last_wheel: Instant,
    pub hint_text: Option<String>,
    ready: Option<((PathBuf, Option<SystemTime>), TextureHandle)>,
    saved: Option<((PathBuf, Option<SystemTime>, u32, u32), TextureHandle)>,
    pub painter: Painter,
    pub geo: Option<Geo>,
    pub part: Option<String>,
    pub active_ov: usize,
    pub active_blur: usize,
    pub whole: bool,
    pub added: HashSet<String>,
    pub popup: Option<Popup>,
    pub items: Vec<Item>,
    pub offset: f32,
    pub lines_x0: f32,
    pub lines_s: f32,
    pub lines_top: f32,
    pub lines_slot: f32,
    pub logview: Option<LogView>,
    pub preview: Option<(Arc<RgbImage>, TextureHandle)>,
    pub preview_info: Option<String>,
    pub preview_rev: u64,
    pub preview_due: Option<Instant>,
    pub layout: Option<Layout>,
    pub preview_rect: Option<Rect>,
    pub view_box: Option<(f64, f64, f64)>,
    pub view: (f64, f64, f64),
    pub seam: String,
    pub history: Vec<(String, State)>,
    pub future: Vec<(String, State)>,
    pub known: HashMap<String, State>,
    last_push: Option<(String, BTreeSet<String>, Instant)>,
    replaying: bool,
    pub thumbs: HashMap<String, TextureHandle>,
    pub frame_text: (String, String),
    pub frame_text_for: String,
    pub style_text: String,
    pub style_due: Option<Instant>,
    pub sheet_scroll: f32,
    pub zones: Vec<(&'static str, usize, Rect)>,
    pub donor_names: Vec<String>,
    pub tour: Option<usize>,
    pub tour_done: bool,
    pub rail_rects: HashMap<&'static str, Rect>,
    pub last_area: Rect,
    pub switched_at: Instant,
    pub tool_at: Instant,
    pub toast: Option<Toast>,
    pub last_note: String,
    pub toast_rect: Option<Rect>,
    pub pending: Option<(String, Instant)>,
    pub menu: Option<Rect>,
    pub news: bool,
    pub news_closed: Option<bool>,
    pub want_settings: bool,
    sheet_for: Option<&'static str>,
    media_for: String,
}

pub fn texture(ctx: &egui::Context, name: &str, img: &RgbImage) -> TextureHandle {
    let color = ColorImage::from_rgb([img.width() as usize, img.height() as usize], img.as_raw());
    ctx.load_texture(name, color, TextureOptions::LINEAR)
}

pub fn stamp(path: &std::path::Path) -> Option<SystemTime> {
    std::fs::metadata(path).ok()?.modified().ok()
}

pub fn mix(a: Color32, b: Color32, t: f32) -> Color32 {
    let l = |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * t.clamp(0.0, 1.0)).round() as u8;
    Color32::from_rgb(l(a.r(), b.r()), l(a.g(), b.g()), l(a.b(), b.b()))
}

pub fn full_uv() -> Rect {
    Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0))
}

impl Feed {
    pub fn new(cfg: &Config, tx: Sender<Msg>, ctx: egui::Context) -> Feed {
        let (jobs, rx) = channel::<Job>();
        {
            let tx = tx.clone();
            let ctx = ctx.clone();
            std::thread::spawn(move || {
                while let Ok(job) = rx.recv() {
                    match job {
                        Job::Save(snaps) => Feed::store(snaps, &tx),
                        Job::Delete(name, out, cfg) => {
                            let result = store::delete_shot(&out, &name, &cfg, &win::recycle);
                            let _ = tx.send(Msg::Deleted(name, result));
                        }
                        Job::Duplicate(name, out) => {
                            let result = store::duplicate_shot(&out, &name);
                            let _ = tx.send(Msg::Duplicated(result));
                        }
                    }
                    ctx.request_repaint();
                }
            });
        }
        let mut feed = Feed {
            cfg: cfg.clone(),
            tx,
            ctx,
            names: vec![],
            index: 0,
            shot: None,
            cache: HashMap::new(),
            loading: HashSet::new(),
            tool: None,
            drag: None,
            busy: false,
            message: None,
            note: String::new(),
            saves: HashMap::new(),
            writing: HashSet::new(),
            save_due: None,
            jobs,
            last_wheel: Instant::now(),
            hint_text: None,
            ready: None,
            saved: None,
            painter: Painter::default(),
            geo: None,
            part: None,
            active_ov: 0,
            active_blur: 0,
            whole: false,
            added: HashSet::new(),
            popup: None,
            items: vec![],
            offset: 0.0,
            lines_x0: 0.0,
            lines_s: 1.0,
            lines_top: 0.0,
            lines_slot: 28.0,
            logview: None,
            preview: None,
            preview_info: None,
            preview_rev: 0,
            preview_due: None,
            layout: None,
            preview_rect: None,
            view_box: None,
            view: (1.0, 0.5, 0.5),
            seam: "all".into(),
            history: vec![],
            future: vec![],
            known: HashMap::new(),
            last_push: None,
            replaying: false,
            thumbs: HashMap::new(),
            frame_text: (String::new(), String::new()),
            frame_text_for: String::new(),
            style_text: String::new(),
            style_due: None,
            sheet_scroll: 0.0,
            zones: vec![],
            donor_names: vec![],
            tour: None,
            tour_done: false,
            rail_rects: HashMap::new(),
            last_area: Rect::NOTHING,
            switched_at: Instant::now(),
            tool_at: Instant::now(),
            toast: None,
            last_note: String::new(),
            toast_rect: None,
            pending: None,
            menu: None,
            news: false,
            news_closed: None,
            want_settings: false,
            sheet_for: None,
            media_for: String::new(),
        };
        feed.refresh_names();
        feed
    }

    pub fn warmed(&self) -> bool {
        self.names.is_empty() || self.ready.is_some() || self.index != 0
    }

    pub fn refresh_names(&mut self) {
        self.names = store::list_shots(&self.cfg.out);
        if let Some((gone, _)) = &self.pending {
            self.names.retain(|n| n != gone);
        }
        self.ready = None;
    }

    pub fn name(&self) -> Option<String> {
        if self.index >= 1 && self.index <= self.names.len() { Some(self.names[self.index - 1].clone()) } else { None }
    }

    pub fn go(&mut self, index: isize) {
        let index = index.clamp(0, self.names.len() as isize) as usize;
        if index == self.index && (index == 0 || self.shot.is_some()) {
            return;
        }
        self.index = index;
        self.tool = None;
        self.offset = 0.0;
        self.note.clear();
        self.menu = None;
        self.open_current();
    }

    fn sync_current(&mut self) {
        if let Some(shot) = &self.shot {
            if let Some(name) = shot.name.clone() {
                self.cache.insert(name, Some(shot.clone()));
            }
        }
    }

    pub fn open_current(&mut self) {
        self.flush_save();
        self.sync_current();
        self.shot = None;
        self.preview = None;
        self.preview_info = None;
        self.layout = None;
        self.part = None;
        self.view = (1.0, 0.5, 0.5);
        self.seam = "all".into();
        self.painter.forget();
        let Some(name) = self.name() else { return };
        if let Some(hit) = self.cache.get(&name) {
            self.shot = hit.clone();
            self.fetch_next();
            return;
        }
        self.fetch(&name);
    }

    pub fn fetch(&mut self, name: &str) {
        if self.cache.contains_key(name) || self.loading.contains(name) {
            return;
        }
        self.loading.insert(name.to_string());
        let (cfg, tx, ctx, name) = (self.cfg.clone(), self.tx.clone(), self.ctx.clone(), name.to_string());
        std::thread::spawn(move || {
            let shot = std::panic::catch_unwind(|| store::load_shot(&cfg.out, &name, &cfg).ok().flatten()).ok().flatten();
            let _ = tx.send(Msg::Loaded(name, shot));
            ctx.request_repaint();
        });
    }

    fn fetch_next(&mut self) {
        if self.index > 0 && self.index < self.names.len() {
            let next = self.names[self.index].clone();
            self.fetch(&next);
        }
    }

    pub fn fetch_scene(&mut self) {
        for n in self.scene_names() {
            if Some(&n) != self.name().as_ref() {
                self.fetch(&n);
            }
        }
    }

    pub fn receive(&mut self, msg: Msg) {
        match msg {
            Msg::Loaded(name, shot) => {
                self.loading.remove(&name);
                if self.cache.get(&name).is_some_and(|s| s.is_some()) {
                    return;
                }
                self.cache.insert(name.clone(), shot.clone());
                if let Some(s) = &shot {
                    self.remember(s);
                }
                let here = self.name();
                let keep: HashSet<String> = self.scene_names().into_iter().chain(here.clone()).chain(self.saves.keys().cloned()).chain(self.writing.iter().cloned()).collect();
                while self.cache.len() > 6 + keep.len() {
                    let Some(old) = self.cache.keys().find(|n| !keep.contains(*n)).cloned() else { break };
                    self.cache.remove(&old);
                }
                if Some(&name) == here.as_ref() {
                    if shot.is_some() && self.tour.is_none() && self.cfg.tour && !self.tour_done && !self.news {
                        self.tour = Some(0);
                    }
                    self.shot = shot;
                    self.fetch_next();
                }
            }
            Msg::Saved(name, error) => {
                self.writing.remove(&name);
                self.ready = None;
                self.saved = None;
                if Some(&name) == self.name().as_ref() || Some(&name) == self.part.as_ref() {
                    self.note = match error {
                        Some(e) => format!("не сохранилось: {e}"),
                        None => "сохранено".into(),
                    };
                }
                if self.shot.is_some() && self.scene_names().contains(&name) && self.drag.is_none()
                    && self.previewing() && Some(&name) != self.name().as_ref() {
                    self.want_preview();
                }
            }
            Msg::Deleted(name, result) => self.deleted(&name, result),
            Msg::Duplicated(result) => self.duplicated(result),
            Msg::Copied(name, error) => {
                if Some(&name) == self.name().as_ref() {
                    self.note = match error {
                        Some(e) => format!("не скопировалось: {e}"),
                        None => "скопировано, вставляй через Ctrl+V".into(),
                    };
                }
            }
            Msg::Previewed(key, value) => self.previewed(key, value),
            Msg::Media(..) | Msg::Update(..) | Msg::SampleLoaded(..) | Msg::Estimated(..) => {}
        }
    }

    pub fn new_shot(&mut self, name: &str) {
        self.saves.remove(name);
        self.cache.remove(name);
        self.forget(name);
        self.refresh_names();
        if self.drag.is_none() {
            self.index = 1;
            self.tool = None;
            self.offset = 0.0;
            self.note = "только что".into();
            self.open_current();
        }
    }

    pub fn scene_names(&self) -> Vec<String> {
        let Some(shot) = &self.shot else { return vec![] };
        match (&shot.edit.scene, &shot.name) {
            (Some(scene), Some(name)) if scene.shots.contains(name) => scene.shots.clone(),
            _ => vec![],
        }
    }

    pub fn target_name(&self) -> Option<String> {
        let name = self.name()?;
        let edits = self.tool.is_some_and(|t| theme::EDITS.contains(&t));
        match &self.part {
            Some(p) if edits && *p != name && self.scene_names().contains(p) => Some(p.clone()),
            _ => Some(name),
        }
    }

    pub fn shot_of(&self, name: &str) -> Option<&Shot> {
        if self.name().as_deref() == Some(name) {
            return self.shot.as_ref();
        }
        self.cache.get(name).and_then(|s| s.as_ref())
    }

    pub fn shot_mut(&mut self, name: &str) -> Option<&mut Shot> {
        if self.name().as_deref() == Some(name) {
            return self.shot.as_mut();
        }
        self.cache.get_mut(name).and_then(|s| s.as_mut())
    }

    pub fn target(&self) -> Option<&Shot> {
        let n = self.target_name()?;
        self.shot_of(&n)
    }

    pub fn target_mut(&mut self) -> Option<&mut Shot> {
        let n = self.target_name()?;
        self.shot_mut(&n)
    }

    pub fn members(&self) -> Vec<(String, Option<&Shot>)> {
        self.scene_names().into_iter().map(|n| {
            let s = self.shot_of(&n);
            (n, s)
        }).collect()
    }

    pub fn previewing(&self) -> bool {
        self.tool.is_some_and(|t| theme::PREVIEWS.contains(&t)) || (self.tool == Some("text") && self.whole && !self.scene_names().is_empty())
    }

    pub fn member(&mut self, name: &str) -> Option<&mut Shot> {
        if self.name().as_deref() != Some(name) && !self.cache.get(name).is_some_and(|s| s.is_some()) {
            let shot = store::load_shot(&self.cfg.out, name, &self.cfg).ok().flatten();
            if let Some(s) = &shot {
                self.remember(s);
            }
            self.cache.insert(name.to_string(), shot);
        }
        self.shot_mut(name)
    }

    pub fn look(&self, shot: &Shot) -> (Edit, (u32, u32)) {
        let names = self.scene_names();
        let Some(k) = shot.name.as_ref().and_then(|n| names.iter().position(|x| x == n)) else {
            return (shot.edit.clone(), (0, 0));
        };
        let head = &self.shot.as_ref().unwrap().edit;
        let edit = compose::framed(&shot.edit, head);
        let (width, _, laps) = self.scene_plan();
        let f = compose::plan(shot.bg.dimensions(), &edit, None).size.0 as f64 / width as f64;
        let a = if k > 0 { (laps[k - 1] as f64 * f).round() as u32 } else { 0 };
        let b = if k < laps.len() { (laps[k] as f64 * f).round() as u32 } else { 0 };
        (edit, (a, b))
    }

    pub fn current(&self) -> Option<String> {
        let names = self.scene_names();
        match &self.part {
            Some(p) if names.contains(p) => Some(p.clone()),
            _ => self.name(),
        }
    }

    pub fn pick_part(&mut self, name: &str) {
        self.part = if Some(name) == self.name().as_deref() { None } else { Some(name.to_string()) };
        self.fetch(name);
        self.active_ov = 0;
        self.painter.forget();
    }

    pub fn change(&mut self, f: impl FnOnce(&mut Edit)) {
        let Some(name) = self.target_name() else { return };
        let Some(shot) = self.shot_mut(&name) else { return };
        f(&mut shot.edit);
        if self.previewing() {
            self.want_preview();
        }
        self.schedule_save(&name);
    }

    pub fn want_preview(&mut self) {
        self.preview_rev += 1;
        self.preview_due = Some(Instant::now() + Duration::from_millis(150));
    }

    fn encode_preview(&mut self) {
        self.preview_due = None;
        if self.shot.is_none() || !self.previewing() {
            return;
        }
        let snap = self.snapshot(None, true);
        let key = (self.name().unwrap_or_default(), self.preview_rev);
        let (tx, ctx) = (self.tx.clone(), self.ctx.clone());
        std::thread::spawn(move || {
            let mut layout = Layout::default();
            let result = store::encoded(&snap, Some(&mut layout)).map(|(img, _, data)| {
                let shown = if snap.edit.file == "jpg" {
                    image::load_from_memory(&data).map(|i| i.to_rgb8()).unwrap_or(img)
                } else {
                    img
                };
                (shown, data.len(), if layout.tops.is_empty() { None } else { Some(layout) })
            });
            let _ = tx.send(Msg::Previewed(key, result));
            ctx.request_repaint();
        });
    }

    fn previewed(&mut self, key: (String, u64), value: Result<(RgbImage, usize, Option<Layout>), String>) {
        if key != (self.name().unwrap_or_default(), self.preview_rev) || !self.previewing() {
            return;
        }
        match value {
            Err(e) => self.preview_info = Some(format!("размер не посчитался: {e}")),
            Ok((img, size, layout)) => {
                self.preview_info = Some(format!("≈ {} · {} × {}", theme::megabytes(size as u64), img.width(), img.height()));
                let t = texture(&self.ctx, "preview", &img);
                self.preview = Some((Arc::new(img), t));
                self.layout = layout;
            }
        }
    }

    pub fn state_of(shot: &Shot) -> State {
        let edit = serde_json::to_value(&shot.edit).unwrap_or(Value::Null);
        let marks: Vec<_> = shot.rows.iter().map(|r| (r.keep, r.hidden().to_vec(), r.drop.clone())).collect();
        let key = serde_json::to_string(&(&edit, &marks)).unwrap_or_default();
        State { edit, marks, key }
    }

    pub fn remember(&mut self, shot: &Shot) {
        if let Some(n) = &shot.name {
            if !self.known.contains_key(n) {
                self.known.insert(n.clone(), Feed::state_of(shot));
            }
        }
    }

    pub fn forget(&mut self, name: &str) {
        self.known.remove(name);
        self.history.retain(|h| h.0 != name);
        self.future.retain(|h| h.0 != name);
    }

    fn record(&mut self, name: &str) {
        let Some(shot) = self.shot_of(name) else { return };
        let new = Feed::state_of(shot);
        let old = self.known.insert(name.to_string(), new.clone());
        let Some(old) = old else { return };
        if self.replaying || old.key == new.key {
            return;
        }
        if old.marks.len() != new.marks.len() {
            self.forget(name);
            self.known.insert(name.to_string(), new);
            return;
        }
        let mut keys = BTreeSet::new();
        if let (Value::Object(a), Value::Object(b)) = (&old.edit, &new.edit) {
            for k in a.keys().chain(b.keys()) {
                if a.get(k) != b.get(k) {
                    keys.insert(k.clone());
                }
            }
        }
        if old.marks != new.marks {
            keys.insert("marks".into());
        }
        let merge = self.last_push.as_ref().is_some_and(|(n, k, t)| n == name && *k == keys && t.elapsed().as_secs_f64() < theme::UNDO_MERGE_S);
        if !merge {
            self.history.push((name.to_string(), old));
            let extra = self.history.len().saturating_sub(theme::UNDO_MAX);
            self.history.drain(..extra);
        }
        self.last_push = Some((name.to_string(), keys, Instant::now()));
        self.future.clear();
    }

    pub fn undo(&mut self, back: bool) {
        let scope: HashSet<String> = self.scene_names().into_iter().chain(self.name()).collect();
        let src = if back { &self.history } else { &self.future };
        let Some(k) = (0..src.len()).rev().find(|&k| scope.contains(&src[k].0)) else {
            self.note = if back { "нечего отменять".into() } else { "нечего вернуть".into() };
            return;
        };
        let (name, state) = if back { self.history.remove(k) } else { self.future.remove(k) };
        let current = self.known.get(&name).cloned();
        let Some(shot) = self.member(&name) else { return };
        let mine = current.unwrap_or_else(|| Feed::state_of(shot));
        if let Ok(edit) = serde_json::from_value::<Edit>(state.edit.clone()) {
            shot.edit = edit;
        }
        for (r, (keep, hide, drop)) in shot.rows.iter_mut().zip(state.marks.iter()) {
            r.keep = *keep;
            r.hide = Some(hide.clone());
            r.drop = drop.clone();
        }
        if back { self.future.push((name.clone(), mine)) } else { self.history.push((name.clone(), mine)) }
        self.last_push = None;
        self.replaying = true;
        self.schedule_save(&name);
        self.replaying = false;
        self.note = if back { "отменено".into() } else { "возвращено".into() };
        self.popup = None;
        self.painter.forget();
        if self.previewing() {
            self.want_preview();
        }
    }

    pub fn schedule_save(&mut self, name: &str) {
        self.record(name);
        if self.name().as_deref() == Some(name) {
            self.sync_current();
        }
        let Some(shot) = self.shot_of(name) else { return };
        let snap = shot.clone();
        self.note = "сохраняю…".into();
        self.saves.insert(name.to_string(), snap);
        self.save_due = Some(Instant::now() + Duration::from_millis(450));
    }

    pub fn snapshot(&self, shot: Option<&Shot>, deep: bool) -> Shot {
        let shot = shot.or(self.shot.as_ref()).unwrap();
        let mut snap = shot.clone();
        if deep {
            if let Some(scene) = &shot.edit.scene {
                for n in &scene.shots {
                    if Some(n) != shot.name.as_ref() {
                        if let Some(Some(m)) = self.cache.get(n) {
                            snap.members.insert(n.clone(), Arc::new(m.clone()));
                        }
                    }
                }
            }
        }
        snap
    }

    pub fn flush_save(&mut self) {
        if self.save_due.is_some() {
            self.save_now();
        }
    }

    pub fn save_now(&mut self) {
        self.save_due = None;
        let names: Vec<String> = self.saves.keys().cloned().collect();
        let snaps: Vec<Shot> = names.iter().filter_map(|n| self.saves.get(n)).map(|s| self.snapshot(Some(s), true)).collect();
        self.writing.extend(names);
        self.saves.clear();
        if !snaps.is_empty() {
            let _ = self.jobs.send(Job::Save(snaps));
        }
    }

    pub fn save_sync(&mut self) {
        self.save_due = None;
        let snaps: Vec<Shot> = self.saves.values().map(|s| self.snapshot(Some(s), true)).collect();
        self.saves.clear();
        if !snaps.is_empty() {
            let (tx, _rx) = channel();
            Feed::store(snaps, &tx);
        }
    }

    pub fn store(mut snaps: Vec<Shot>, tx: &Sender<Msg>) {
        snaps.sort_by_key(|s| s.edit.scene.is_some());
        let names: Vec<String> = snaps.iter().filter_map(|s| s.name.clone()).collect();
        for snap in &snaps {
            let name = snap.name.clone().unwrap_or_default();
            let error = store::save_shot(snap, false).err();
            let _ = tx.send(Msg::Saved(name, error));
        }
        if let Some(first) = snaps.first() {
            for head in store::refresh_heads(&first.out, &names, first.cfg.as_ref(), &names) {
                let _ = tx.send(Msg::Saved(head, None));
            }
        }
    }

    pub fn copy(&mut self) {
        let Some(name) = self.name() else { return };
        let snap = self.shot.as_ref().map(|_| self.snapshot(None, true));
        let path = store::shot_image(&self.cfg.out, &name);
        self.note = "копирую…".into();
        let (tx, ctx) = (self.tx.clone(), self.ctx.clone());
        std::thread::spawn(move || {
            let result = match snap {
                Some(s) => store::render_shot(&s, None, None).map(|r| r.0),
                None => store::read_image(&path),
            }
            .and_then(|img| win::copy_image(&img));
            let _ = tx.send(Msg::Copied(name, result.err()));
            ctx.request_repaint();
        });
    }

    pub fn open_folder(&self) {
        let file = self.name().map(|n| store::shot_image(&self.cfg.out, &n));
        win::open_folder(&self.cfg.out, file.as_deref());
    }

    pub fn area(&self, body: Rect) -> Rect {
        Rect::from_min_size(Pos2::new(body.left() + SIDE_W, body.top() + 12.0),
                            vec2(body.width() - SIDE_W - RAIL_W, body.height() - 24.0))
    }

    pub fn toggle_tool(&mut self, tool: &str) {
        let mut tool = tool.to_string();
        if tool == "scene" && self.tool != Some("scene") && self.shot.is_some() && self.scene_names().is_empty() {
            tool = "scenepick".into();
        }
        if tool == "lines" && !matches!(self.tool, Some("lines") | Some("logpick")) && self.empty_log() {
            tool = "logpick".into();
        }
        let was = self.previewing();
        self.menu = None;
        let old = self.tool;
        let all = ["lines", "crop", "text", "images", "scene", "file", "style", "blur", "carry", "logpick", "photopick", "scenepick"];
        let next = all.iter().find(|t| **t == tool).copied();
        self.tool = if self.tool == next { None } else { next };
        self.offset = 0.0;
        self.sheet_scroll = 0.0;
        if old == Some("scenepick") && !self.added.is_empty() && !self.scene_names().is_empty() {
            self.drop_repeats();
        }
        self.added.clear();
        if self.tool.is_some_and(|t| theme::EDITS.contains(&t)) {
            self.fetch_scene();
        }
        if self.previewing() {
            if !was {
                self.preview = None;
                self.preview_info = None;
            }
            self.want_preview();
        }
        if self.tool == Some("logpick") {
            self.open_log();
        }
    }

    pub fn show(&mut self, ui: &mut Ui, body: Rect, update: Option<&(String, String)>) {
        if self.save_due.is_some_and(|t| Instant::now() >= t) {
            self.save_now();
        }
        if self.preview_due.is_some_and(|t| Instant::now() >= t) {
            self.encode_preview();
        }
        if self.style_due.is_some_and(|t| Instant::now() >= t) {
            self.style_due = None;
            let text: String = self.style_text.trim().chars().take(engine::styles::TEXT_MAX).collect();
            self.change(|e| e.style_text = Some(text));
        }
        self.hint_text = None;
        if self.note != self.last_note {
            self.last_note = self.note.clone();
            let quiet = ["", "сохраняю…", "сохранено", "копирую…", "удаляю…"];
            if !quiet.contains(&self.note.as_str()) {
                let action = remedies(&self.note).into_iter().next();
                self.toast = Some(Toast { text: self.note.clone(), at: Instant::now(), action });
            }
        }
        if self.pending.as_ref().is_some_and(|(_, at)| at.elapsed() >= crate::assist::UNDO_DELETE) {
            self.commit_delete();
        }
        if self.index == 0 {
            self.draw_ready(ui, body, update);
        } else {
            self.draw_item(ui, body);
            self.pointer(ui, body);
            self.draw_popup(ui, body);
            self.draw_menu(ui);
        }
        self.draw_history(ui, body);
        self.wheel(ui, body);
        self.drops(ui, body);
        self.draw_hint(ui, body);
        self.draw_toast(ui, body);
        self.draw_tour(ui);
        if self.save_due.is_some() || self.preview_due.is_some() || self.style_due.is_some() || self.pending.is_some() {
            ui.ctx().request_repaint_after(Duration::from_millis(60));
        }
    }

    fn pointer(&mut self, ui: &mut Ui, body: Rect) {
        let area = self.area(body);
        self.last_area = area;
        let (pos, pressed, down, released, shift, context) = ui.input(|i| {
            (i.pointer.interact_pos(), i.pointer.primary_pressed(), i.pointer.primary_down(), i.pointer.primary_released(), i.modifiers.shift,
             i.pointer.button_pressed(egui::PointerButton::Secondary))
        });
        let Some(pos) = pos else { return };
        if (pressed || context) && self.menu.is_some_and(|m| !m.contains(pos)) {
            self.menu = None;
            return;
        }
        if context && area.contains(pos) && self.drag.is_none() && self.menu_allowed() {
            self.open_menu(pos, ui.clip_rect());
            return;
        }
        if pressed && area.contains(pos) && !self.over_popup(pos) {
            self.press(pos, shift, area);
        } else if pressed && self.popup.is_some() && !self.over_popup(pos) {
            self.popup = None;
        }
        if self.drag.is_some() && down {
            self.motion(pos, area);
        }
        if released && self.drag.is_some() {
            self.release(pos, area);
        }
        if self.drag.is_none() && area.contains(pos) {
            self.hover(pos, area);
        }
        if let Some(drag) = &self.drag {
            let icon = match drag {
                Drag::Chat { .. } | Drag::Pan { .. } | Drag::Ov { .. } | Drag::BMove { .. } | Drag::SceneChat { .. } => Some(CursorIcon::Move),
                Drag::View { moved: true, .. } => Some(CursorIcon::Move),
                _ => None,
            };
            if let Some(i) = icon {
                ui.ctx().set_cursor_icon(i);
            }
            ui.ctx().request_repaint();
        }
    }

    pub fn press(&mut self, pos: Pos2, shift: bool, area: Rect) {
        if self.shot.is_none() {
            return;
        }
        match self.tool {
            Some("logpick") => return self.log_press(pos),
            Some("lines") => return self.lines_press(pos, area),
            Some("blur") => return self.blur_press(pos),
            Some(t) if theme::DONORS.contains(&t) => return self.donor_press(pos),
            _ => {}
        }
        if self.previewing() {
            if let Some(hit) = self.scene_chat_at(pos) {
                self.drag = Some(Drag::SceneChat { x: pos.x, y: pos.y, hit, now: pos });
                return;
            }
            if self.view_box.is_some() && self.preview_rect.is_some_and(|r| r.contains(pos)) {
                self.drag = Some(Drag::View { x: pos.x, y: pos.y, at: (self.view.1, self.view.2), moved: false });
            }
            return;
        }
        let Some(geo) = self.geo.clone() else { return };
        let Some(target) = self.target().cloned() else { return };
        if self.tool == Some("images") {
            if let Some(handle) = self.handle_at(pos, &geo) {
                let k = self.active_ov;
                if let (Some(Some(b)), Some(ov)) = (geo.overlays.get(k), target.edit.overlays.get(k)) {
                    if let Some(size) = self.source_size(ov) {
                        self.drag = Some(Drag::Crop { handle, part: k, x: pos.x, y: pos.y, crop: ov.crop, b: b.clone(), size });
                    }
                }
                return;
            }
            if let Some(k) = (0..geo.overlays.len()).rev().find(|&k| geo.overlays[k].as_ref().is_some_and(|o| o.b.contains(pos))) {
                self.active_ov = k;
                let ov = &target.edit.overlays[k];
                self.drag = Some(Drag::Ov { part: k, x: pos.x, y: pos.y, at: (ov.x, ov.y), crop: ov.crop, shift });
                return;
            }
        }
        if let Some(part) = (0..geo.chats.len()).rev().find(|&k| geo.chats[k].as_ref().is_some_and(|c| Rect::from_min_size(Pos2::new(c.x, c.y), vec2(c.w, c.h)).contains(pos))) {
            let c = geo.chats[part].as_ref().unwrap();
            self.drag = Some(Drag::Chat { part, x: pos.x, y: pos.y, at: Pos2::new(c.x, c.y) });
            return;
        }
        if self.tool == Some("crop") && geo.img.contains(pos) {
            self.drag = Some(Drag::Pan { x: pos.x, y: pos.y, center: target.edit.center });
        }
    }

    pub fn motion(&mut self, pos: Pos2, area: Rect) {
        let Some(drag) = self.drag.clone() else { return };
        let geo = self.geo.clone();
        match drag {
            Drag::Log { on, first, last } => {
                let j = self.log_item_at(pos.y);
                if j != last {
                    self.drag = Some(Drag::Log { on, first, last: j });
                    self.mark_log(first, j, on);
                }
            }
            Drag::Rows { keep, first, last, mut shots, .. } => {
                let i = self.row_at(pos.y);
                if i != last {
                    self.mark_rows(first, i, keep, &mut shots);
                    self.drag = Some(Drag::Rows { keep, first, last: i, shots, moved: true });
                }
            }
            Drag::Chat { .. } => {}
            Drag::Crop { .. } => self.drag_crop(pos),
            Drag::SceneChat { x, y, hit, .. } => self.drag = Some(Drag::SceneChat { x, y, hit, now: pos }),
            Drag::View { x, y, at, moved } => {
                let (dx, dy) = (pos.x - x, pos.y - y);
                if !moved && dx.abs().max(dy.abs()) < 4.0 {
                    return;
                }
                self.drag = Some(Drag::View { x, y, at, moved: true });
                if let (Some((img, _)), Some((_, _, d))) = (&self.preview, self.view_box) {
                    let (w, h) = (img.width() as f64, img.height() as f64);
                    self.view.1 = at.0 - dx as f64 / d / w;
                    self.view.2 = at.1 - dy as f64 / d / h;
                }
            }
            Drag::BNew { .. } | Drag::BMove { .. } | Drag::BSize { .. } => self.blur_motion(pos),
            Drag::Ov { part, x, y, at, crop, shift } => {
                let Some(geo) = geo else { return };
                let (ow, oh) = (geo.out.0 as f64, geo.out.1 as f64);
                let d = geo.d as f64;
                let b = geo.overlays.get(part).cloned().flatten();
                let snapped = {
                    let Some(shot) = self.target_mut() else { return };
                    let Some(ov) = shot.edit.overlays.get_mut(part) else { return };
                    if !shift {
                        ov.x = engine::py::round_to((at.0 + (pos.x - x) as f64 / d / ow).clamp(0.0, 1.0), 4);
                        ov.y = engine::py::round_to((at.1 + (pos.y - y) as f64 / d / oh).clamp(0.0, 1.0), 4);
                        true
                    } else if let Some(b) = &b {
                        let [l, t, r, bb] = crop;
                        let (mx, my) = compose::turned((pos.x - x) as f64, (pos.y - y) as f64, -ov.turn());
                        let sx = (-mx * (r - l) / b.w as f64).max(-l).min(1.0 - r);
                        let sy = (-my * (bb - t) / b.h as f64).max(-t).min(1.0 - bb);
                        ov.crop = [l + sx, t + sy, r + sx, bb + sy].map(|v| engine::py::round_to(v, 4));
                        false
                    } else {
                        false
                    }
                };
                if snapped {
                    if let Some(b) = b {
                        self.snap_ov(part, &b, &geo);
                    }
                }
            }
            Drag::Pan { x, y, center } => {
                let Some(geo) = geo else { return };
                let Some(shot) = self.target() else { return };
                let (w, h) = (shot.bg.width() as f64, shot.bg.height() as f64);
                let (x0, _, x1, _) = geo.plan.rect;
                let k = (x1 - x0) as f64 / (geo.plan.base.0 as f64 * geo.d as f64);
                let tilt = self.look(shot).0.tilt();
                let (mut mx, mut my) = ((pos.x - x) as f64, (pos.y - y) as f64);
                if tilt != 0.0 {
                    let z = compose::tilt_zoom(geo.plan.base, tilt);
                    let (a, b) = compose::turned(mx, my, -tilt);
                    (mx, my) = (a / z, b / z);
                }
                let c = [center[0] - mx * k / w, center[1] - my * k / h];
                if let Some(shot) = self.target_mut() {
                    shot.edit.center = c;
                }
            }
        }
        let _ = area;
    }

    pub fn release(&mut self, pos: Pos2, area: Rect) {
        let Some(drag) = self.drag.take() else { return };
        match drag {
            Drag::Log { .. } => {}
            Drag::SceneChat { .. } => self.drop_scene_chat(&drag, pos),
            Drag::View { moved, .. } => {
                if !moved && self.tool == Some("scene") {
                    if let Some(k) = self.seam_at(pos.y) {
                        self.seam = if self.seam == k.to_string() { "all".into() } else { k.to_string() };
                    }
                }
            }
            Drag::Rows { first, moved, shots, keep, .. } => {
                if !moved {
                    if let Some(word) = self.word_at(first, pos) {
                        self.popup = Some(Popup { j: first, word });
                        return;
                    }
                    let mut touched = HashSet::new();
                    self.mark_rows(first, first, keep, &mut touched);
                    for n in touched {
                        self.schedule_save(&n);
                    }
                    return;
                }
                for n in shots {
                    self.schedule_save(&n);
                }
            }
            Drag::BNew { .. } | Drag::BMove { .. } | Drag::BSize { .. } => self.blur_release(&drag),
            Drag::Chat { part, x, y, at } => {
                let p = Pos2::new(at.x + pos.x - x, at.y + pos.y - y);
                if let Some((spot, _, _)) = self.chat_spot(part, p.x, p.y) {
                    self.set_place(part, spot);
                }
                if let Some(n) = self.target_name() {
                    self.schedule_save(&n);
                }
            }
            Drag::Ov { .. } | Drag::Crop { .. } => {
                if let Some(n) = self.target_name() {
                    self.schedule_save(&n);
                }
            }
            Drag::Pan { .. } => {
                let Some(name) = self.target_name() else { return };
                let Some(shot) = self.target() else { return };
                let look = self.look(shot).0;
                let (w, h) = (shot.bg.width() as f64, shot.bg.height() as f64);
                let ratio = engine::config::ratio_of(&look.format).unwrap_or(Some(1.0));
                let (x0, y0, x1, y1) = engine::chat::frame_rect(w as i64, h as i64, ratio, look.zoom, look.center);
                let c = [engine::py::round_to((x0 + x1) as f64 / 2.0 / w, 4), engine::py::round_to((y0 + y1) as f64 / 2.0 / h, 4)];
                if let Some(shot) = self.shot_mut(&name) {
                    shot.edit.center = c;
                }
                self.schedule_save(&name);
            }
        }
        let _ = area;
    }

    fn hover(&mut self, pos: Pos2, area: Rect) {
        let ctx = self.ctx.clone();
        match self.tool {
            Some("lines") => {
                self.hint_text = self.lines_hint(pos);
                return;
            }
            Some("logpick") => {
                self.hint_text = self.log_hint(pos);
                return;
            }
            Some(t) if theme::DONORS.contains(&t) => {
                self.hint_text = self.donor_hint(pos);
                return;
            }
            _ => {}
        }
        if self.previewing() {
            let inside = self.preview_rect.is_some_and(|r| r.contains(pos));
            let grab = inside && self.view_box.is_some() && self.scene_chat_at(pos).is_some();
            let seam = inside && self.view_box.is_some() && self.tool == Some("scene") && self.seam_at(pos.y).is_some();
            if inside && self.view_box.is_some() {
                ctx.set_cursor_icon(if seam { CursorIcon::PointingHand } else { CursorIcon::Move });
            }
            self.hint_text = if !inside {
                None
            } else if grab {
                Some("Тяни чат — на переход, на другую СС или в её угол".into())
            } else if seam {
                Some("Клик — настроить только этот переход".into())
            } else if self.view_box.is_some() {
                Some("Тяни — двигать · колесо — прокрутка · Ctrl + колесо — масштаб".into())
            } else {
                Some("Точно как в файле".into())
            };
            return;
        }
        if self.tool == Some("blur") {
            self.blur_hover(pos);
            return;
        }
        let Some(geo) = self.geo.clone() else { return };
        let over_chat = geo.chats.iter().flatten().any(|c| Rect::from_min_size(Pos2::new(c.x, c.y), vec2(c.w, c.h)).contains(pos));
        let images = self.tool == Some("images");
        if over_chat {
            ctx.set_cursor_icon(CursorIcon::Move);
            self.hint_text = Some("Тяни чат мышью — у края он сам встанет на отступ".into());
        } else if images && self.handle_at(pos, &geo).is_some() {
            ctx.set_cursor_icon(CursorIcon::ResizeNwSe);
            self.hint_text = Some("Тяни — обрезать картинку".into());
        } else if images && geo.overlays.iter().flatten().any(|o| o.b.contains(pos)) {
            ctx.set_cursor_icon(CursorIcon::Move);
            self.hint_text = Some("Тяни — двигать · колесо — размер · Shift + тяни — сдвинуть обрезку".into());
        } else if self.tool == Some("crop") && geo.img.contains(pos) {
            ctx.set_cursor_icon(CursorIcon::Move);
            self.hint_text = Some("Тяни — выбрать, что в кадре · колесо — приближение".into());
        }
        let _ = area;
    }

    fn wheel(&mut self, ui: &mut Ui, body: Rect) {
        let Some(pos) = ui.input(|i| i.pointer.hover_pos()) else { return };
        if !body.contains(pos) {
            return;
        }
        let delta = crate::widgets::wheel(ui);
        if delta == 0.0 {
            return;
        }
        let area = self.area(body);
        let step = if delta > 0.0 { -1.0f32 } else { 1.0 };
        let ctrl = ui.input(|i| i.modifiers.ctrl);
        if pos.x < body.left() + SIDE_W && self.tool.is_some() {
            return;
        }
        if self.popup.is_some() {
            self.popup = None;
        }
        if self.tool == Some("logpick") {
            if let Some(v) = self.logview.as_mut() {
                if let Some(o) = v.offset.as_mut() {
                    *o += step * 72.0;
                }
            }
            return;
        }
        if self.view_box.is_some() && self.previewing() {
            if ctrl {
                let z = self.view.0 * if step < 0.0 { 1.25 } else { 0.8 };
                self.zoom_view(z, Some(pos), area);
            } else if let (Some((img, _)), Some(rect), Some((_, _, d))) = (&self.preview, self.preview_rect, self.view_box) {
                self.view.2 += step as f64 * 0.25 * rect.height() as f64 / d / img.height() as f64;
            }
            return;
        }
        if self.tool == Some("lines") && self.shot.is_some() {
            self.offset += step * 72.0;
            return;
        }
        if self.tool == Some("images") {
            if let Some(geo) = self.geo.clone() {
                if let Some(k) = (0..geo.overlays.len()).rev().find(|&k| geo.overlays[k].as_ref().is_some_and(|o| o.b.contains(pos))) {
                    self.active_ov = k;
                    self.change_ov(|ov| ov.w = engine::py::round_to((ov.w * if step < 0.0 { 1.08 } else { 1.0 / 1.08 }).clamp(0.05, 2.0), 4));
                    return;
                }
            }
        }
        if self.tool == Some("crop") && self.shot.is_some() {
            let Some(zoom) = self.target().map(|s| s.edit.zoom) else { return };
            let z = (engine::py::round_to(zoom - step as f64 * 0.1, 2)).clamp(1.0, 3.0);
            self.change(|e| e.zoom = z);
            return;
        }
        if self.tool.is_none() && self.last_wheel.elapsed().as_secs_f64() > 0.25 {
            self.last_wheel = Instant::now();
            self.go(self.index as isize + step as isize);
        }
    }

    pub fn zoom_view(&mut self, zoom: f64, at: Option<Pos2>, area: Rect) {
        let (Some((img, _)), Some((x0, y0, d)), Some(rect)) = (&self.preview, self.view_box, self.preview_rect) else { return };
        let (w, h) = (img.width() as f64, img.height() as f64);
        let fit = (area.width() as f64 / w).min(area.height() as f64 / h);
        let zoom = zoom.clamp(1.0, (4.0 / fit).max(1.0));
        if let Some(p) = at {
            let sx = x0 + (p.x - rect.left()) as f64 / d;
            let sy = y0 + (p.y - rect.top()) as f64 / d;
            let nd = fit * zoom;
            self.view.1 = (sx - (p.x - area.left() - area.width() / 2.0) as f64 / nd) / w;
            self.view.2 = (sy - (p.y - area.top() - area.height() / 2.0) as f64 / nd) / h;
        }
        self.view.0 = zoom;
    }

    pub fn view_fit(&mut self, kind: &str, area: Rect) {
        let Some((img, _)) = &self.preview else { return };
        let (w, h) = (img.width() as f64, img.height() as f64);
        let fit = (area.width() as f64 / w).min(area.height() as f64 / h);
        let z = match kind {
            "width" => area.width() as f64 / w / fit,
            "real" => 1.0 / fit,
            _ => 1.0,
        };
        self.zoom_view(z, None, area);
    }

    pub fn keys(&mut self, ctx: &egui::Context) {
        if ctx.text_edit_focused() {
            return;
        }
        let events = ctx.input(|i| i.events.clone());
        for e in events {
            if matches!(e, egui::Event::Paste(_) | egui::Event::PasteImage(_)) {
                self.paste();
                continue;
            }
            let egui::Event::Key { key, pressed: true, modifiers, .. } = e else { continue };
            use egui::Key;
            let number = [Key::Num1, Key::Num2, Key::Num3, Key::Num4, Key::Num5, Key::Num6, Key::Num7, Key::Num8].iter().position(|k| *k == key);
            match key {
                Key::ArrowUp | Key::PageUp => self.go(self.index as isize - 1),
                Key::ArrowDown | Key::PageDown => self.go(self.index as isize + 1),
                Key::Escape if self.menu.is_some() => self.menu = None,
                Key::Escape if self.tour.is_some() => self.finish_tour(),
                Key::Escape if self.popup.is_some() => self.popup = None,
                Key::Escape if self.tool.is_some() => {
                    let t = self.tool.unwrap();
                    self.toggle_tool(t);
                }
                Key::Delete if self.tool == Some("blur") && self.drag.is_none() => self.remove_blur(),
                Key::Delete if self.tool.is_none() && self.index > 0 && self.drag.is_none() => self.delete(),
                Key::Z if modifiers.ctrl && !modifiers.shift && self.pending.is_some() => self.restore(),
                Key::C if modifiers.ctrl && self.index > 0 => self.copy(),
                Key::Z | Key::Y if modifiers.ctrl && self.shot.is_some() && self.drag.is_none() => {
                    self.undo(key == Key::Z && !modifiers.shift)
                }
                _ if number.is_some() && !modifiers.ctrl && self.shot.is_some() && self.index > 0 => {
                    self.toggle_tool(theme::TOOLS[number.unwrap()]);
                }
                _ => {}
            }
        }
    }

    pub fn block(&self, ui: &Ui, items: &[(String, FontId, Color32, f32)], width: f32) -> Vec<(Arc<egui::Galley>, f32)> {
        items.iter().map(|(text, font, color, gap)| (ui.painter().layout(text.clone(), font.clone(), *color, width), *gap)).collect()
    }

    pub fn draw_block(&self, ui: &Ui, x: f32, bottom: f32, block: Vec<(Arc<egui::Galley>, f32)>) -> f32 {
        let total: f32 = block.iter().map(|(g, gap)| g.size().y + gap).sum();
        let mut y = bottom - total;
        let top = y;
        for (g, gap) in block {
            let h = g.size().y;
            ui.painter().galley(Pos2::new(x, y), g, WHITE);
            y += h + gap;
        }
        top
    }

    fn ready_texture(&mut self, size: egui::Vec2) -> Option<TextureHandle> {
        let newest = self.names.first()?;
        let path = store::shot_image(&self.cfg.out, newest);
        let key = (path.clone(), stamp(&path));
        if let Some((k, t)) = &self.ready {
            if *k == key {
                return Some(t.clone());
            }
        }
        let img = image::open(&path).ok()?.to_rgb8();
        let k = (360.0 / img.width().max(img.height()) as f64).min(1.0);
        let small = engine::img::resize(&img, (img.width() as f64 * k).round().max(1.0) as u32,
                                        (img.height() as f64 * k).round().max(1.0) as u32, engine::img::Filter::Bilinear);
        let scale = (size.x / small.width() as f32).max(size.y / small.height() as f32);
        let mut dark = engine::img::gaussian_blur(&small, (22.0 / scale).max(1.0));
        for v in dark.iter_mut() {
            *v = (*v as f32 * 0.3).round() as u8;
        }
        let t = texture(&self.ctx, "ready", &dark);
        self.ready = Some((key, t.clone()));
        Some(t)
    }

    fn draw_ready(&mut self, ui: &mut Ui, body: Rect, update: Option<&(String, String)>) {
        let (w, h) = (body.width(), body.height());
        if let Some(t) = self.ready_texture(body.size()) {
            let size = t.size_vec2();
            let k = (w / size.x).max(h / size.y);
            let (sw, sh) = (w / k / size.x, h / k / size.y);
            let uv = Rect::from_min_max(Pos2::new((1.0 - sw) / 2.0, (1.0 - sh) / 2.0), Pos2::new((1.0 + sw) / 2.0, (1.0 + sh) / 2.0));
            ui.painter().image(t.id(), body, uv, Color32::WHITE);
            let mut mesh = Mesh::default();
            let top = Color32::from_rgba_unmultiplied(10, 10, 10, 0);
            let bottom = Color32::from_rgba_unmultiplied(10, 10, 10, 217);
            mesh.colored_vertex(body.left_top(), top);
            mesh.colored_vertex(body.right_top(), top);
            mesh.colored_vertex(body.right_bottom(), bottom);
            mesh.colored_vertex(body.left_bottom(), bottom);
            mesh.add_triangle(0, 1, 2);
            mesh.add_triangle(0, 2, 3);
            ui.painter().add(Shape::mesh(mesh));
        }
        let cfg = &self.cfg;
        let (key, hud, dark) = (cfg.key.clone(), cfg.hud_key.clone(), cfg.dark_key.clone());
        let x = body.left() + PAD + 12.0;
        let width = SIDE_W + 120.0;
        let mut title = "Готово к съёмке".to_string();
        let mut level = "info".to_string();
        let mut text: Option<String> = None;
        if self.busy {
            title = "Снимаю…".into();
        } else if let Some((l, m)) = &self.message {
            level = l.clone();
            text = Some(m.clone());
            title = match l.as_str() {
                "fail" => "Не вышло".into(),
                "step" => "Половина есть".into(),
                _ => title,
            };
        }
        let log = cfg.source == "log";
        let text = text.unwrap_or_else(|| {
            if log {
                let first = if cfg.auto { format!("Нажми {key} в игре и программа сама спрячет интерфейс") } else { format!("В игре нажми {hud}, затем {key}") };
                format!("{first}: снимется только сцена, без затемнения. Строки потом отметишь в «Строках» из чатлога. Готовая СС появится здесь или в папке скриншотов.")
            } else if cfg.auto {
                format!("Нажми {key} в игре и программа сама спрячет интерфейс и затемнит экран, а готовая СС появится здесь или в папке скриншотов.")
            } else {
                format!("В игре нажми {hud}, затем {key} — это фон. Потом {dark}, затем {key} — это чат. Готовая СС появится здесь или в папке скриншотов.")
            }
        });
        let tip = if log {
            "Памятка: в чатлоге видны строки за час до и после СС, так что отыграть сцену можно и после снимка.".to_string()
        } else {
            format!("Памятка: если диалог длинный, то нажми {dark} и вновь {key}. Тогда в одной СС будет несколько чатбоксов.")
        };
        let fail = level == "fail";
        let fixes = if fail { remedies(&text) } else { vec![] };
        let mut items = vec![
            (title, theme::display(30.0), WHITE, 12.0),
            (text, theme::ui(13.0), if fail { WHITE } else { SUB }, 14.0),
            (tip, theme::ui(10.0), SUB, 0.0),
        ];
        if let Some((version, _)) = update {
            items.push((format!("Вышла Snapline {version} — скачать"), theme::semi(10.0), WHITE, 0.0));
        }
        let galleys = self.block(ui, &items, width);
        let bottom = body.bottom() - PAD - 12.0;
        let title_h = galleys[0].0.size().y;
        let total: f32 = galleys.iter().map(|(g, gap)| g.size().y + gap).sum::<f32>() + if update.is_some() { 10.0 } else { 0.0 }
            + if fixes.is_empty() { 0.0 } else { 46.0 };
        let mut fixed = None;
        let top = bottom - total;
        let mut y = top;
        for (i, (g, gap)) in galleys.into_iter().enumerate() {
            let hh = g.size().y;
            let gx = if i == 0 && fail { x + 22.0 } else { x };
            if i == 3 {
                y += 10.0;
                let r = Rect::from_min_size(Pos2::new(gx, y), g.size());
                let resp = ui.interact(r, Id::unique("update-link"), Sense::click());
                if resp.hovered() {
                    ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
                }
                if resp.clicked() {
                    if let Some((_, url)) = update {
                        win::open(url);
                    }
                }
            }
            ui.painter().galley(Pos2::new(gx, y), g, WHITE);
            y += hh + gap;
            if i == 1 && !fixes.is_empty() {
                let mut bx = x;
                for (k, (label, remedy)) in fixes.iter().enumerate() {
                    let bw = crate::widgets::text_width(ui, label, theme::semi(10.0)) + 32.0;
                    let kind = if k == 0 { crate::widgets::Kind::Primary } else { crate::widgets::Kind::Ghost };
                    if crate::widgets::pill_at(ui, Rect::from_min_size(Pos2::new(bx, y), vec2(bw, 32.0)), Id::unique(("fix", k)), label, kind, 10.0).clicked() {
                        fixed = Some(remedy.clone());
                    }
                    bx += bw + 8.0;
                }
                y += 46.0;
            }
        }
        if let Some(r) = fixed {
            self.remedy(r);
        }
        if fail {
            ui.painter().circle_filled(Pos2::new(x + 5.0, top + title_h / 2.0 + 2.0), 5.0, ERR);
        }
        let cap_font = theme::display(20.0);
        let cap_w = crate::widgets::text_width(ui, &key, cap_font.clone()) + 44.0;
        let cap = Rect::from_min_size(Pos2::new(x, top - 26.0 - 54.0), vec2(cap_w, 54.0));
        ui.painter().rect_stroke(cap.shrink(0.7), CornerRadius::same(14), Stroke::new(1.4, WHITE), StrokeKind::Middle);
        ui.painter().text(cap.center(), Align2::CENTER_CENTER, &key, cap_font, WHITE);
        if !self.names.is_empty() {
            let cx = (x + width + body.right() - RAIL_W) / 2.0;
            let label = format!("Прошлые СС · {}", self.names.len());
            let r = Rect::from_center_size(Pos2::new(cx, body.bottom() - PAD - 26.0), vec2(160.0, 48.0));
            let resp = ui.interact(r, Id::unique("older"), Sense::click());
            let color = if resp.hovered() { WHITE } else { SUB };
            ui.painter().text(Pos2::new(cx, body.bottom() - PAD - 4.0), Align2::CENTER_BOTTOM, label, theme::ui(10.0), color);
            ui.painter().text(Pos2::new(cx, body.bottom() - PAD - 26.0), Align2::CENTER_BOTTOM, theme::icon("down"), theme::glyph(14.0), color);
            if resp.hovered() {
                ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
            }
            if resp.clicked() {
                self.go(1);
            }
        }
        self.draw_news(ui, body);
        let items = vec![Some(Rail { key: "folder", label: "Папка".into(), active: false })];
        if let Some(k) = self.rail(ui, body, &items) {
            self.rail_action(k);
        }
    }

    pub fn saved_texture(&mut self, name: &str, area: Rect) -> Option<TextureHandle> {
        let path = store::shot_image(&self.cfg.out, name);
        let key = (path.clone(), stamp(&path), area.width() as u32, area.height() as u32);
        if let Some((k, t)) = &self.saved {
            if *k == key {
                return Some(t.clone());
            }
        }
        let img = image::open(&path).ok()?.to_rgb8();
        let ppp = self.ctx.pixels_per_point();
        let k = (area.width() * ppp / img.width() as f32).min(area.height() * ppp / img.height() as f32).min(1.0);
        let small = engine::img::resize(&img, (img.width() as f32 * k).round().max(1.0) as u32,
                                        (img.height() as f32 * k).round().max(1.0) as u32, engine::img::Filter::Bilinear);
        let t = texture(&self.ctx, "saved", &small);
        self.saved = Some((key, t.clone()));
        Some(t)
    }

    pub fn draw_saved(&mut self, ui: &Ui, area: Rect, name: &str) {
        match self.saved_texture(name, area) {
            Some(t) => {
                let ppp = ui.ctx().pixels_per_point();
                let size = t.size_vec2() / ppp;
                let min = ((area.center() - size / 2.0).to_vec2() * ppp).round() / ppp;
                let rect = Rect::from_min_size(min.to_pos2(), size);
                ui.painter().image(t.id(), rect, full_uv(), Color32::WHITE);
            }
            None => {
                ui.painter().text(area.center(), Align2::CENTER_CENTER, "Файл СС не найден", theme::ui(12.0), SUB);
            }
        }
    }

    fn draw_item(&mut self, ui: &mut Ui, body: Rect) {
        let area = self.area(body);
        let name = self.name().unwrap_or_default();
        let view_only = matches!(self.cache.get(&name), Some(None));
        self.geo = None;
        if self.media_for != name {
            self.media_for = name.clone();
            self.switched_at = Instant::now();
        }
        if self.shot.is_none() {
            self.draw_saved(ui, area, &name);
        } else {
            self.draw_media(ui, area);
        }
        let t = self.switched_at.elapsed().as_secs_f32() / 0.18;
        if t < 1.0 && crate::theme::animations_on() {
            let a = ((1.0 - crate::theme::ease(t)) * 255.0) as u8;
            ui.painter().rect_filled(area.expand(2.0), CornerRadius::ZERO, Color32::from_rgba_unmultiplied(10, 10, 10, a));
            ui.ctx().request_repaint();
        }
        if self.tool.is_some() && self.shot.is_some() {
            if self.sheet_for != self.tool {
                self.sheet_for = self.tool;
                self.tool_at = Instant::now();
            }
            self.sheet(ui, body);
        } else {
            self.sheet_for = None;
            self.side(ui, body, &name, view_only);
        }
        let mut items: Vec<Option<Rail>> = vec![];
        if self.shot.is_some() {
            let t = self.tool;
            for (key, label, on) in [
                ("lines", "Строки", matches!(t, Some("lines") | Some("carry") | Some("logpick"))),
                ("text", "Текст", t == Some("text")),
                ("", "", false),
                ("crop", "Кадр", t == Some("crop")),
                ("images", "Картинки", matches!(t, Some("images") | Some("photopick"))),
                ("blur", "Размытие", t == Some("blur")),
                ("", "", false),
                ("style", "Стиль", t == Some("style")),
                ("scene", "Сцена", matches!(t, Some("scene") | Some("scenepick"))),
                ("file", "Файл", t == Some("file")),
            ] {
                items.push(if key.is_empty() { None } else { Some(Rail { key, label: label.into(), active: on }) });
            }
        }
        items.push(None);
        if self.shot.is_some() || view_only {
            items.push(Some(Rail { key: "copy", label: "Копировать".into(), active: false }));
        }
        items.push(Some(Rail { key: "folder", label: "В папке".into(), active: false }));
        items.push(Some(Rail { key: "delete", label: "Удалить".into(), active: false }));
        if let Some(k) = self.rail(ui, body, &items) {
            self.rail_action(k);
        }
    }

    fn draw_media(&mut self, ui: &mut Ui, area: Rect) {
        self.preview_rect = None;
        self.view_box = None;
        match self.tool {
            Some("lines") => return self.draw_lines(ui, area),
            Some("logpick") => return self.draw_log(ui, area),
            Some(t) if theme::DONORS.contains(&t) => return self.draw_donors(ui, area),
            _ => {}
        }
        if (self.tool.is_none() || self.previewing()) && !self.scene_names().is_empty() {
            return self.draw_scene(ui, area);
        }
        let Some(target) = self.target().cloned() else {
            let text = if matches!(self.part.as_ref().and_then(|p| self.cache.get(p)), Some(None)) { "Исходники этой СС не найдены" } else { "Загружаю СС…" };
            ui.painter().text(area.center(), Align2::CENTER_CENTER, text, theme::ui(12.0), SUB);
            return;
        };
        let (edit, laps) = self.look(&target);
        let moving = match &self.drag {
            Some(Drag::Chat { part, x, y, at }) => ui.input(|i| i.pointer.interact_pos()).and_then(|p| {
                let at = Pos2::new(at.x + p.x - x, at.y + p.y - y);
                self.chat_spot(*part, at.x, at.y).map(|(_, qx, qy)| (*part, Pos2::new(qx, qy)))
            }),
            _ => None,
        };
        let geo = self.painter.draw(ui, &target, area, &edit, laps, moving);
        self.geo = Some(geo.clone());
        if let Some((part, _)) = moving {
            self.snap_guides(ui, &geo, part);
        }
        self.decorate(ui, &geo);
    }

    fn decorate(&mut self, ui: &Ui, geo: &Geo) {
        let p = ui.painter();
        match self.tool {
            Some("crop") => {
                p.rect_stroke(geo.img.expand(1.0), CornerRadius::ZERO, Stroke::new(1.0, WHITE), StrokeKind::Inside);
                if let Some(j) = geo.join {
                    crate::tools::dashed_rect(p, j.shrink(0.5), WHITE, 4.0, 3.0);
                }
            }
            Some("file") | Some("style") => self.draw_preview(ui, geo.img),
            Some("blur") => self.draw_blurs(ui),
            _ => {}
        }
        self.mark_overlay(ui, geo);
    }

    pub fn shown(&self, t: &TextureHandle) -> egui::Vec2 {
        t.size_vec2() / self.ctx.pixels_per_point()
    }

    pub fn snap(&self, at: Pos2) -> Pos2 {
        let ppp = self.ctx.pixels_per_point();
        Pos2::new((at.x * ppp).round() / ppp, (at.y * ppp).round() / ppp)
    }

    pub fn draw_preview(&mut self, ui: &Ui, rect: Rect) {
        let Some((_, t)) = &self.preview else { return };
        self.preview_rect = Some(rect);
        ui.painter().image(t.id(), rect, full_uv(), Color32::WHITE);
    }

    pub fn meta(&self) -> String {
        let Some(head) = &self.shot else {
            return if self.name().is_some_and(|n| matches!(self.cache.get(&n), Some(None))) { "только просмотр".into() } else { "загружаю…".into() };
        };
        let scene = self.scene_names();
        let shot = self.target();
        let mut parts: Vec<String> = Vec::new();
        if scene.is_empty() {
            let p = compose::plan(head.bg.dimensions(), &head.edit, None);
            parts.push(format!("{} × {}", p.size.0, p.size.1));
        } else if self.tool.is_some_and(|t| theme::FRAMED.contains(&t)) && shot.is_some() && !self.previewing() {
            let s = shot.unwrap();
            let p = compose::plan(s.bg.dimensions(), &self.look(s).0, None);
            let k = s.name.as_ref().and_then(|n| scene.iter().position(|x| x == n)).unwrap_or(0);
            let (w, h) = self.scene_size();
            parts.push(format!("СС {} из {}", k + 1, scene.len()));
            parts.push(format!("кадр {} × {}", p.size.0, p.size.1));
            parts.push(format!("сцена {w} × {h}"));
        } else {
            parts.push(format!("сцена из {} СС", scene.len()));
            if let (Some((img, _)), true) = (&self.preview, self.previewing()) {
                parts.push(format!("{} × {}", img.width(), img.height()));
            }
            if let Some((_, _, d)) = self.view_box {
                parts.push(format!("масштаб {}%", (d * 100.0).round()));
            }
        }
        let kept = shot.map(|s| s.rows.iter().filter(|r| r.keep).count()).unwrap_or(0);
        let drawn = self.tool.is_some_and(|t| theme::FRAMED.contains(&t)) || (scene.is_empty() && matches!(self.tool, None | Some("file") | Some("style")));
        if let Some(geo) = &self.geo {
            if drawn && geo.painted < kept {
                parts.push(format!("влезло {} из {kept} строк", geo.painted));
            }
        }
        if !self.note.is_empty() {
            parts.push(self.note.clone());
        } else if head.legacy {
            parts.push("старая СС, файл обновится после правки".into());
        }
        parts.join(" · ")
    }

    fn snap_guides(&self, ui: &Ui, geo: &Geo, part: usize) {
        let Some(Drag::Chat { x, y, at, .. }) = &self.drag else { return };
        let Some(p) = ui.input(|i| i.pointer.interact_pos()) else { return };
        let Some((pos, _, _)) = self.chat_spot(part, at.x + p.x - x, at.y + p.y - y) else { return };
        let (cx, cy) = pos.axes();
        let img = geo.img;
        let d = geo.d;
        let m = geo.plan.margin as f32 * d;
        let (it, ib) = (geo.inset.0 as f32 * d, geo.inset.1 as f32 * d);
        let paint = ui.painter();
        let color = WHITE.gamma_multiply(0.7);
        if let engine::edit::Coord::Side(s) = &cx {
            let gx = if s == "left" { img.left() + m } else { img.right() - m };
            crate::tools::dashed_line(paint, Pos2::new(gx, img.top()), Pos2::new(gx, img.bottom()), color, 5.0, 4.0);
        }
        if let engine::edit::Coord::Side(s) = &cy {
            let gy = if s == "top" { img.top() + it + m } else { img.bottom() - ib - m };
            crate::tools::dashed_line(paint, Pos2::new(img.left(), gy), Pos2::new(img.right(), gy), color, 5.0, 4.0);
        }
    }

    fn rail(&mut self, ui: &mut Ui, body: Rect, items: &[Option<Rail>]) -> Option<&'static str> {
        let cx = body.right() - RAIL_W / 2.0;
        let nav = !self.names.is_empty();
        let top = body.top() + 16.0;
        let bottom = body.bottom() - 16.0 - if nav { 112.0 } else { 0.0 };
        let gap = 25.0;
        let count = items.iter().filter(|i| i.is_some()).count() as f32;
        let gaps = items.iter().filter(|i| i.is_none()).count() as f32 * gap;
        let step = ((bottom - top - gaps) / count.max(1.0)).clamp(40.0, 64.0);
        let labels = step >= 50.0;
        let tile = vec2(84.0, step - 6.0);
        let mut y = ((top + bottom) / 2.0 - (step * count + gaps) / 2.0).max(body.top() + 8.0);
        let mut picked = None;
        let mut hint = None;
        let p = ui.painter().clone();
        for item in items {
            let Some(item) = item else {
                let line = (y + gap / 2.0).round() + 0.5;
                p.line_segment([Pos2::new(cx - 18.0, line), Pos2::new(cx + 18.0, line)], Stroke::new(1.0, LINE));
                y += gap;
                continue;
            };
            let block = Rect::from_min_max(Pos2::new(cx - RAIL_W / 2.0 + 4.0, y), Pos2::new(cx + RAIL_W / 2.0 - 4.0, y + step));
            let plate = Rect::from_center_size(block.center(), tile);
            let resp = ui.interact(block, Id::unique(("rail", item.key)), Sense::click());
            self.rail_rects.insert(item.key, plate);
            let on = ui.ctx().animate_bool_responsive(Id::unique(("rail-on", item.key)), item.active);
            let hot = ui.ctx().animate_bool_responsive(Id::unique(("rail-hot", item.key)), resp.hovered());
            let down = resp.is_pointer_button_down_on();
            let radius = CornerRadius::same(12);
            if hot > 0.01 || down {
                p.rect_filled(plate, radius, if down { MIST } else { SLATE.gamma_multiply(hot) });
            }
            if on > 0.01 {
                p.rect_filled(plate, radius, WHITE.gamma_multiply(on));
            }
            let ink = mix(WHITE, VOID, on);
            let text = mix(mix(SUB, WHITE, hot), VOID, on);
            let c = plate.center();
            if labels {
                p.text(Pos2::new(cx, c.y - 8.0), Align2::CENTER_CENTER, theme::icon(item.key), theme::glyph(15.0), ink);
                p.text(Pos2::new(cx, c.y + 13.0), Align2::CENTER_CENTER, &item.label, theme::ui(9.0), text);
            } else {
                p.text(c, Align2::CENTER_CENTER, theme::icon(item.key), theme::glyph(15.0), ink);
            }
            if resp.hovered() {
                ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
                hint = theme::rail_hint(item.key);
            }
            if resp.clicked() {
                picked = Some(item.key);
            }
            y += step;
        }
        if nav {
            let ny = body.bottom() - PAD - 34.0;
            let pos = if self.index == 0 { "съёмка".to_string() } else { format!("{} из {}", self.index, self.names.len()) };
            p.text(Pos2::new(cx, ny), Align2::CENTER_CENTER, pos, theme::ui(9.0), SUB);
            let total = self.names.len() + 1;
            for (key, dy, delta, enabled) in [("up", -30.0, -1isize, self.index > 0), ("down", 30.0, 1, self.index < total - 1)] {
                let r = Rect::from_center_size(Pos2::new(cx, ny + dy), vec2(52.0, 32.0));
                let resp = ui.interact(r, Id::unique(("nav", key)), Sense::click());
                let hot = ui.ctx().animate_bool_responsive(Id::unique(("nav-hot", key)), enabled && resp.hovered());
                if enabled && resp.is_pointer_button_down_on() {
                    p.rect_filled(r, CornerRadius::same(10), MIST);
                } else if hot > 0.01 {
                    p.rect_filled(r, CornerRadius::same(10), SLATE.gamma_multiply(hot));
                }
                let color = if enabled { mix(SUB, WHITE, hot) } else { MIST };
                p.text(r.center(), Align2::CENTER_CENTER, theme::icon(key), theme::glyph(12.0), color);
                if enabled && resp.hovered() {
                    ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
                    hint = Some(if delta < 0 { "Новее · колесо вверх или ↑" } else { "Старше · колесо вниз или ↓" });
                }
                if enabled && resp.clicked() {
                    self.go(self.index as isize + delta);
                }
            }
        }
        if hint.is_some() {
            self.hint_text = hint.map(|s| s.to_string());
        }
        picked
    }

    fn rail_action(&mut self, key: &str) {
        match key {
            "copy" => self.copy(),
            "folder" => self.open_folder(),
            "delete" => self.delete(),
            tool => self.toggle_tool(tool),
        }
    }

    pub fn probe_tool(&mut self, tool: &str) {
        self.toggle_tool(tool);
    }

    fn draw_hint(&self, ui: &Ui, body: Rect) {
        let Some(text) = &self.hint_text else { return };
        if self.index == 0 {
            return;
        }
        let area = self.area(body);
        let w = (area.width() - 20.0).min(crate::widgets::text_width(ui, text, theme::ui(10.0)) + 32.0);
        let h = 32.0;
        let r = Rect::from_min_size(Pos2::new(area.left() + (area.width() - w) / 2.0, area.bottom() - h - 12.0), vec2(w, h));
        let p = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, Id::unique("hint")));
        p.rect_filled(r, CornerRadius::same(16), Color32::from_rgba_unmultiplied(10, 10, 10, 228));
        p.rect_stroke(r, CornerRadius::same(16), Stroke::new(1.0, LINE), StrokeKind::Inside);
        p.text(r.center(), Align2::CENTER_CENTER, text, theme::ui(10.0), WHITE);
    }

    fn sheet(&mut self, ui: &mut Ui, body: Rect) {
        let sheet_w = SIDE_W - 2.0 * PAD - 12.0;
        let rect = Rect::from_min_size(Pos2::new(body.left() + PAD + 12.0, body.top() + PAD), vec2(sheet_w + 12.0, body.height() - 2.0 * PAD));
        let tool = self.tool.unwrap();
        let title = match tool {
            "lines" => "Строки чата",
            "crop" => "Кадр",
            "text" => "Текст",
            "images" => "Картинки",
            "file" => "Файл",
            "style" => "Стиль",
            "blur" => "Размытие",
            "carry" => "Чат из другой СС",
            "logpick" => "Чатлог",
            "photopick" => "Фото из другой СС",
            "scene" => "Сцена",
            _ => "СС для сцены",
        };
        let p = ui.painter().clone();
        let head = p.text(rect.left_top(), Align2::LEFT_TOP, title, theme::display(20.0), WHITE);
        let close = Rect::from_center_size(Pos2::new(rect.right() - 18.0, head.center().y + 3.0), vec2(28.0, 28.0));
        let resp = ui.interact(close, Id::unique("sheet-close"), Sense::click());
        p.text(close.center(), Align2::CENTER_CENTER, theme::icon("close"), theme::glyph(12.0), if resp.hovered() { WHITE } else { SUB });
        if resp.hovered() {
            ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
        }
        if resp.clicked() {
            self.toggle_tool(tool);
            return;
        }
        let mut y = head.bottom();
        if let Some(scope) = self.scope() {
            let r = p.text(Pos2::new(rect.left(), y), Align2::LEFT_TOP, scope, theme::ui(10.0), SUB);
            y = r.bottom() + 22.0;
        } else {
            y += 24.0;
        }
        let meta = p.layout(self.meta(), theme::ui(10.0), SUB, sheet_w);
        let meta_h = meta.size().y;
        p.galley(Pos2::new(rect.left(), rect.bottom() - meta_h), meta, SUB);
        let holder = Rect::from_min_max(Pos2::new(rect.left(), y), Pos2::new(rect.right(), rect.bottom() - meta_h - 8.0));
        let t = if crate::theme::animations_on() { crate::theme::ease(self.tool_at.elapsed().as_secs_f32() / 0.2) } else { 1.0 };
        if t < 1.0 {
            ui.ctx().request_repaint();
        }
        let shifted = holder.translate(vec2(-12.0 * (1.0 - t), 0.0));
        let mut child = ui.new_child(egui::UiBuilder::new().max_rect(shifted).id_salt(("sheet", tool)));
        child.set_clip_rect(holder);
        child.multiply_opacity(t);
        egui::ScrollArea::vertical().id_salt(("sheet-scroll", tool)).max_height(holder.height()).auto_shrink([false, false]).show(&mut child, |ui| {
            ui.set_width(sheet_w);
            ui.spacing_mut().item_spacing = vec2(0.0, 0.0);
            if self.tool.is_some_and(|t| theme::FRAMED.contains(&t)) && !self.scene_names().is_empty() {
                self.frame_strip(ui, sheet_w);
            }
            if self.target().is_none() {
                let text = if self.part.as_ref().and_then(|p| self.cache.get(p)).is_none() { "Загружаю эту СС…" } else { "Исходники этой СС не найдены, её не поправить." };
                crate::widgets::label(ui, text, 0.0);
                return;
            }
            match tool {
                "lines" => self.sheet_lines(ui, sheet_w),
                "carry" => self.sheet_carry(ui),
                "logpick" => self.sheet_logpick(ui, sheet_w),
                "crop" => self.sheet_crop(ui, sheet_w),
                "text" => self.sheet_text(ui, sheet_w),
                "images" => self.sheet_images(ui, sheet_w),
                "photopick" => self.sheet_photopick(ui),
                "scene" => self.sheet_scene(ui, sheet_w),
                "scenepick" => self.sheet_scenepick(ui),
                "file" => self.sheet_file(ui, sheet_w),
                "style" => self.sheet_style(ui, sheet_w),
                "blur" => self.sheet_blur(ui, sheet_w),
                _ => {}
            }
        });
    }

    fn scope(&self) -> Option<String> {
        let names = self.scene_names();
        let tool = self.tool?;
        if tool == "scenepick" || (names.is_empty() && matches!(tool, "scene" | "carry" | "logpick" | "photopick")) {
            return None;
        }
        if names.is_empty() {
            return Some("только эта СС".into());
        }
        if self.previewing() {
            return Some("вся сцена".into());
        }
        if tool == "lines" {
            return Some("все СС сцены".into());
        }
        let cur = self.current().unwrap_or_default();
        Some(format!("СС {} из {} сцены", names.iter().position(|n| *n == cur).unwrap_or(0) + 1, names.len()))
    }

    fn frame_strip(&mut self, ui: &mut Ui, sheet_w: f32) {
        let names = self.scene_names();
        let current = self.current();
        crate::widgets::field(ui, "СС в сцене", 0.0);
        let per = ((sheet_w / (54.0 + 12.0)) as usize).max(1);
        for chunk in names.chunks(per) {
            let (line, _) = ui.allocate_exact_size(vec2(sheet_w, 32.0 + 4.0 + 18.0), Sense::hover());
            let mut x = line.left();
            for name in chunk {
                let on = Some(name) == current.as_ref();
                let k = names.iter().position(|n| n == name).unwrap_or(0);
                let cell = Rect::from_min_size(Pos2::new(x, line.top()), vec2(58.0, 54.0));
                let resp = ui.interact(cell, Id::unique(("strip", name)), Sense::click());
                if let Some(t) = self.frame_thumb(name) {
                    let size = t.size_vec2();
                    let r = Rect::from_min_size(Pos2::new(x + 2.0, line.top() + 2.0), size);
                    ui.painter().image(t.id(), r, full_uv(), Color32::WHITE);
                    if on {
                        ui.painter().rect_stroke(r.expand(1.0), CornerRadius::ZERO, Stroke::new(2.0, WHITE), StrokeKind::Outside);
                    }
                }
                let text = format!("{}{}", k + 1, if Some(name) == self.name().as_ref() { " · эта" } else { "" });
                ui.painter().text(Pos2::new(x, line.top() + 38.0), Align2::LEFT_TOP, text, theme::ui(9.0), if on { WHITE } else { SUB });
                if resp.hovered() {
                    ui.ctx().set_cursor_icon(CursorIcon::PointingHand);
                }
                if resp.clicked() {
                    let n = name.clone();
                    self.pick_part(&n);
                }
                x += 54.0 + 12.0;
            }
            ui.add_space(6.0);
        }
        ui.add_space(4.0);
    }

    fn over_popup(&self, pos: Pos2) -> bool {
        self.popup_rect().is_some_and(|r| r.contains(pos)) || self.menu.is_some_and(|r| r.contains(pos))
            || self.toast_rect.is_some_and(|r| r.contains(pos))
    }
}
