use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicIsize, Ordering};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use eframe::egui::{self, Align2, Color32, CornerRadius, Id, Pos2, Rect, Sense, Stroke, ViewportCommand, vec2};
use engine::config::{self, Config, Event, Raw};
use engine::store::Shot;
use image::RgbImage;

use crate::feed::Feed;
use crate::settings::{Action, Settings};
use crate::theme::{self, BAR_H, MIST, PAD, SUB, VOID, WHITE};
use crate::win::{self, TrayEvent};

pub enum Msg {
    Loaded(String, Option<Shot>),
    Saved(String, Option<String>),
    Deleted(String, Result<Vec<String>, String>),
    Copied(String, Option<String>),
    Duplicated(Result<String, String>),
    Update(String, String),
    Previewed((String, u64), Result<(RgbImage, usize, Option<engine::compose::Layout>), String>),
    Media(String, Option<RgbImage>),
    SampleLoaded(Option<Shot>),
    Estimated(u64, Option<(RgbImage, usize)>),
}

pub struct Shared {
    pub cfg: Mutex<Config>,
    pub hwnd: AtomicIsize,
    pub stop: Arc<AtomicBool>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Feed,
    Settings,
}

pub struct App {
    pub raw: Raw,
    pub cfg: Config,
    pub config_path: PathBuf,
    pub error_log: PathBuf,
    pub tab: Tab,
    pub feed: Feed,
    pub settings: Settings,
    pub tx: Sender<Msg>,
    rx: Receiver<Msg>,
    tray_rx: Receiver<TrayEvent>,
    pub shared: Arc<Shared>,
    pub update: Option<(String, String)>,
    pub hidden: bool,
    framed: bool,
    pub probe: Option<Probe>,
    frames: u32,
    probe_done: Arc<AtomicBool>,
    probe_index: usize,
    probe_at: u32,
    probe_sent: bool,
    test_steps: Vec<crate::uitest::Step>,
    test_errors: Vec<String>,
    test_due: std::time::Instant,
    splash: Option<(std::time::Instant, egui::TextureHandle, Option<std::time::Instant>)>,
    probe_point: Option<Pos2>,
}

#[derive(Clone)]
pub struct Probe {
    pub shot: PathBuf,
    pub frames: u32,
    pub script: Vec<String>,
    pub test: Option<PathBuf>,
}

pub fn app_dir() -> PathBuf {
    if let Some(home) = std::env::var_os("SNAPLINE_HOME") {
        return PathBuf::from(home);
    }
    std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())).unwrap_or_else(|| PathBuf::from("."))
}

impl App {
    pub fn new(cc: &eframe::CreationContext<'_>, probe: Option<Probe>) -> App {
        theme::install_fonts(&cc.egui_ctx);
        theme::style(&cc.egui_ctx);
        let config_path = app_dir().join("config.ini");
        let error_log = app_dir().join("error.log");
        let (raw, cfg, problem) = match config::load_config(&config_path) {
            Ok((raw, cfg)) => (raw, cfg, None),
            Err(e) => {
                let raw = Raw::default();
                let cfg = config::parse_config(&raw).expect("defaults parse");
                (raw, cfg, Some(format!("config.ini не прочитан ({e}), взяты настройки по умолчанию")))
            }
        };
        let (tx, rx) = channel();
        let (tray_tx, tray_rx) = channel();
        let icon = crate::art::make_icon(32);
        if probe.is_none() {
            win::start_tray(tray_tx, cc.egui_ctx.clone(), crate::art::png(&icon), 32);
        }
        let shared = Arc::new(Shared { cfg: Mutex::new(cfg.clone()), hwnd: AtomicIsize::new(0), stop: Arc::new(AtomicBool::new(false)) });
        if probe.is_none() {
            let (a, b, log) = (shared.clone(), shared.clone(), error_log.clone());
            let stop = shared.stop.clone();
            std::thread::spawn(move || {
                engine::capture::run(move || a.cfg.lock().unwrap().clone(), stop,
                                     move || win::foreground_is(b.hwnd.load(Ordering::Relaxed)), log);
            });
        }
        if probe.is_none() {
            let tx = tx.clone();
            let ctx = cc.egui_ctx.clone();
            std::thread::spawn(move || {
                if let Some((version, url)) = win::latest_release() {
                    let _ = tx.send(Msg::Update(version, url));
                    ctx.request_repaint();
                }
            });
        }
        let mut feed = Feed::new(&cfg, tx.clone(), cc.egui_ctx.clone());
        feed.news = cfg.seen != config::VERSION && !feed.names.is_empty();
        let fresh = cfg.seen != config::VERSION && feed.names.is_empty();
        if let Some(p) = problem.or_else(|| engine::store::check_out(&cfg)) {
            feed.message = Some(("fail".into(), p));
        }
        let mut settings = Settings::new(tx.clone(), cc.egui_ctx.clone());
        if cfg.chatlog && probe.is_none() {
            settings.toggle_chatlog(true, &cfg.out);
        }
        let app = App { raw, cfg, config_path, error_log, tab: Tab::Feed, feed, settings, tx, rx, tray_rx, shared, update: None, hidden: false,
                        framed: false, probe, frames: 0, probe_done: Arc::new(AtomicBool::new(false)), probe_index: 0, probe_at: 10, probe_sent: false, test_steps: crate::uitest::steps(), test_errors: vec![], test_due: std::time::Instant::now() + Duration::from_millis(300), splash: None, probe_point: None };
        let mut app = app;
        if app.probe.is_none() && theme::animations_on() {
            let icon = crate::art::make_icon(96);
            let color = egui::ColorImage::from_rgba_unmultiplied([96, 96], icon.as_raw());
            app.splash = Some((std::time::Instant::now(), cc.egui_ctx.load_texture("splash", color, egui::TextureOptions::LINEAR), None));
        }
        if app.cfg.tray && app.probe.is_none() {
            win::tray_show(true);
        }
        if fresh && app.probe.is_none() {
            app.set("seen", config::VERSION);
        }
        app
    }

    pub fn set(&mut self, key: &str, value: &str) -> bool {
        let mut raw = self.raw.clone();
        raw.set(key, value);
        let Ok(cfg) = config::parse_config(&raw) else { return false };
        self.raw = raw;
        self.cfg = cfg.clone();
        *self.shared.cfg.lock().unwrap() = cfg.clone();
        self.feed.cfg = cfg;
        if let Err(e) = config::write_raw(&self.config_path, &self.raw) {
            self.feed.message = Some(("fail".into(), format!("Не удалось сохранить настройки: {e}")));
        }
        true
    }

    fn hide(&mut self, ctx: &egui::Context) {
        self.feed.flush_save();
        self.feed.commit_delete();
        self.hidden = true;
        ctx.send_viewport_cmd(ViewportCommand::Visible(false));
        if self.cfg.tray_hint {
            win::tray_tell("Snapline работает в трее", &format!("{} в игре снимает СС и так. Открыть окно или выйти — через этот значок.", self.cfg.key));
            self.set("tray_hint", "no");
        }
    }

    fn reveal(&mut self, ctx: &egui::Context) {
        self.hidden = false;
        ctx.send_viewport_cmd(ViewportCommand::Visible(true));
        ctx.send_viewport_cmd(ViewportCommand::Minimized(false));
        ctx.send_viewport_cmd(ViewportCommand::Focus);
        win::raise(self.shared.hwnd.load(Ordering::Relaxed));
    }

    fn quit(&mut self, ctx: &egui::Context) {
        self.feed.finish();
        win::tray_show(false);
        self.shared.stop.store(true, Ordering::Relaxed);
        self.cfg.tray = false;
        ctx.send_viewport_cmd(ViewportCommand::Close);
    }

    fn close_window(&mut self, ctx: &egui::Context) {
        if win::tray_on() && self.cfg.tray {
            self.hide(ctx);
        } else {
            self.quit(ctx);
        }
    }

    fn pump(&mut self, ctx: &egui::Context) {
        for event in config::drain_events() {
            match event {
                Event::Busy(on) => {
                    self.feed.busy = on;
                    if on {
                        self.feed.flush_save();
                    }
                }
                Event::Log { msg, level, .. } => {
                    if level == "fail" || level == "step" {
                        self.feed.message = Some((level, msg));
                        if self.feed.drag.is_none() {
                            self.feed.go(0);
                        }
                    } else if level == "ok" {
                        self.feed.message = None;
                    }
                }
                Event::Shot(name) => {
                    self.feed.new_shot(&name);
                    self.settings.forget_sample();
                    let unseen = self.hidden || ctx.input(|i| i.viewport().minimized.unwrap_or(false));
                    self.announce(&name, self.cfg.autocopy, self.cfg.notify && unseen && win::tray_on());
                }
                Event::Chatlog(msg) => self.settings.chatlog_note(&msg),
            }
        }
        while let Ok(msg) = self.rx.try_recv() {
            match msg {
                Msg::Update(version, url) => self.update = Some((version, url)),
                Msg::SampleLoaded(shot) => self.settings.sample_loaded(shot),
                Msg::Estimated(rev, value) => self.settings.estimated(rev, value),
                other => self.feed.receive(other),
            }
        }
        while let Ok(event) = self.tray_rx.try_recv() {
            match event {
                TrayEvent::Show => self.reveal(ctx),
                TrayEvent::Folder => self.feed.open_folder(),
                TrayEvent::Quit => self.quit(ctx),
            }
        }
    }

    fn bar(&mut self, ui: &mut egui::Ui, rect: Rect) {
        let ctx = ui.ctx().clone();
        let drag = ui.interact(rect, Id::unique("bar"), Sense::click_and_drag());
        if drag.drag_started() {
            ctx.send_viewport_cmd(ViewportCommand::StartDrag);
        }
        if drag.double_clicked() {
            let max = ctx.input(|i| i.viewport().maximized.unwrap_or(false));
            ctx.send_viewport_cmd(ViewportCommand::Maximized(!max));
        }
        let p = ui.painter().clone();
        theme::wordmark(&p, Pos2::new(rect.left() + PAD + 12.0, rect.center().y), Align2::LEFT_CENTER, 15.0, WHITE);
        let mut x = rect.right() - 10.0;
        let max = ctx.input(|i| i.viewport().maximized.unwrap_or(false));
        for key in ["chrome-close", if max { "restore" } else { "max" }, "min"] {
            let r = Rect::from_min_size(Pos2::new(x - 44.0, rect.center().y - 16.0), vec2(44.0, 32.0));
            let resp = ui.interact(r, Id::unique(("chrome", key)), Sense::click());
            if resp.hovered() {
                p.rect_filled(r, CornerRadius::same(8), if key == "chrome-close" { theme::DANGER } else { MIST });
            }
            p.text(r.center(), Align2::CENTER_CENTER, theme::icon(key), theme::glyph(9.0),
                   if resp.hovered() { WHITE } else { Color32::from_rgb(0xc9, 0xcc, 0xd2) });
            if resp.clicked() {
                match key {
                    "chrome-close" => self.close_window(&ctx),
                    "min" => ctx.send_viewport_cmd(ViewportCommand::Minimized(true)),
                    _ => ctx.send_viewport_cmd(ViewportCommand::Maximized(!max)),
                }
            }
            x -= 46.0;
        }
        let mut right = rect.right() - (10.0 + 3.0 * 46.0 + 28.0);
        for (tab, text) in [(Tab::Settings, "Настройки"), (Tab::Feed, "Съёмка")] {
            let w = crate::widgets::text_width(ui, text, theme::semi(12.0));
            let r = Rect::from_min_size(Pos2::new(right - w, rect.center().y - 14.0), vec2(w, 28.0));
            let resp = ui.interact(r, Id::unique(("tab", text)), Sense::click());
            let on = self.tab == tab;
            p.text(Pos2::new(r.center().x, r.top() + 10.0), Align2::CENTER_CENTER, text, theme::semi(12.0),
                   if on || resp.hovered() { WHITE } else { SUB });
            if on {
                let y = r.top() + 24.0;
                p.line_segment([Pos2::new(r.center().x - 11.0, y), Pos2::new(r.center().x + 11.0, y)], Stroke::new(2.0, WHITE));
            }
            if resp.hovered() {
                ctx.set_cursor_icon(egui::CursorIcon::PointingHand);
            }
            if resp.clicked() {
                self.tab = tab;
            }
            right -= w + 32.0;
        }
    }

    fn grips(&self, ui: &mut egui::Ui, full: Rect) {
        let ctx = ui.ctx().clone();
        if ctx.input(|i| i.viewport().maximized.unwrap_or(false)) {
            return;
        }
        use egui::ResizeDirection as D;
        let e = 6.0;
        let c = 12.0;
        let zones = [
            (Rect::from_min_max(full.min, Pos2::new(full.left() + c, full.top() + c)), D::NorthWest, egui::CursorIcon::ResizeNwSe),
            (Rect::from_min_max(Pos2::new(full.right() - c, full.top()), Pos2::new(full.right(), full.top() + c)), D::NorthEast, egui::CursorIcon::ResizeNeSw),
            (Rect::from_min_max(Pos2::new(full.left(), full.bottom() - c), Pos2::new(full.left() + c, full.bottom())), D::SouthWest, egui::CursorIcon::ResizeNeSw),
            (Rect::from_min_max(Pos2::new(full.right() - c, full.bottom() - c), full.max), D::SouthEast, egui::CursorIcon::ResizeNwSe),
            (Rect::from_min_max(full.min, Pos2::new(full.left() + e, full.bottom())), D::West, egui::CursorIcon::ResizeHorizontal),
            (Rect::from_min_max(Pos2::new(full.right() - e, full.top()), full.max), D::East, egui::CursorIcon::ResizeHorizontal),
            (Rect::from_min_max(full.min, Pos2::new(full.right(), full.top() + e)), D::North, egui::CursorIcon::ResizeVertical),
            (Rect::from_min_max(Pos2::new(full.left(), full.bottom() - e), full.max), D::South, egui::CursorIcon::ResizeVertical),
        ];
        for (k, (rect, dir, cursor)) in zones.into_iter().enumerate() {
            let resp = ui.interact(rect, Id::unique(("grip", k)), Sense::drag());
            if resp.hovered() {
                ctx.set_cursor_icon(cursor);
            }
            if resp.drag_started() {
                ctx.send_viewport_cmd(ViewportCommand::BeginResize(dir));
            }
        }
    }
}

impl App {
    fn run_test(&mut self, ctx: &egui::Context, probe: &Probe) {
        if std::time::Instant::now() < self.test_due {
            return;
        }
        if self.probe_index >= self.test_steps.len() {
            if !self.probe_sent {
                self.probe_sent = true;
                self.feed.save_sync();
                if let Err(e) = crate::uitest::verify(probe.test.as_ref().unwrap()) {
                    self.test_errors.push(e);
                }
                if self.settings_chatlog_on() {
                    self.test_errors.push("chatlog started during the UI test".into());
                }
                for e in &self.test_errors {
                    eprintln!("FAIL: {e}");
                }
                crate::uitest::EXIT.store(if self.test_errors.is_empty() { 0 } else { 1 }, Ordering::Relaxed);
                if self.test_errors.is_empty() {
                    println!("ui ok");
                }
                ctx.send_viewport_cmd(ViewportCommand::Close);
            }
            return;
        }
        let k = self.probe_index;
        let step = std::mem::replace(&mut self.test_steps[k], crate::uitest::Step::Wait("done", Box::new(|_| true)));
        let advance = match &step {
            crate::uitest::Step::Wait(name, cond) => {
                if cond(self) {
                    true
                } else if self.test_due.elapsed().as_secs() > 20 {
                    self.test_errors.push(format!("timed out waiting for {name}"));
                    true
                } else {
                    false
                }
            }
            crate::uitest::Step::Do(name, act, frames) => {
                if let Err(e) = act(self) {
                    self.test_errors.push(format!("{name}: {e}"));
                }
                self.test_due = std::time::Instant::now() + Duration::from_millis(*frames as u64 * 16);
                true
            }
        };
        self.test_steps[k] = step;
        if advance {
            self.probe_index += 1;
        }
    }

    fn draw_splash(&mut self, ui: &mut egui::Ui, full: Rect) {
        let warmed = self.feed.warmed();
        let Some((start, tex, done)) = self.splash.as_mut() else { return };
        if done.is_none() && warmed && start.elapsed().as_secs_f32() > 0.45 {
            *done = Some(std::time::Instant::now());
        }
        let alpha = match done {
            Some(t) => 1.0 - theme::ease(t.elapsed().as_secs_f32() / 0.3),
            None => 1.0,
        };
        if alpha <= 0.0 {
            self.splash = None;
            return;
        }
        let slow = done.is_none() && start.elapsed().as_secs_f32() > 1.0;
        let tex = tex.clone();
        let p = ui.ctx().layer_painter(egui::LayerId::new(egui::Order::Foreground, Id::unique("splash")));
        p.rect_filled(full, CornerRadius::ZERO, VOID.gamma_multiply(alpha));
        let c = full.center();
        let rise = 6.0 * (1.0 - alpha);
        p.image(tex.id(), Rect::from_center_size(Pos2::new(c.x, c.y - 40.0 - rise), vec2(96.0, 96.0)), Rect::from_min_max(Pos2::ZERO, Pos2::new(1.0, 1.0)),
                Color32::WHITE.gamma_multiply(alpha));
        theme::wordmark(&p, Pos2::new(c.x, c.y + 32.0 - rise), Align2::CENTER_CENTER, 15.0, WHITE.gamma_multiply(alpha));
        if slow {
            p.text(Pos2::new(c.x, c.y + 62.0), Align2::CENTER_CENTER, "Загружаю СС…", theme::ui(10.0), SUB.gamma_multiply(alpha));
        }
        ui.ctx().request_repaint();
    }

    fn announce(&self, name: &str, copy: bool, notify: bool) {
        if !copy && !notify {
            return;
        }
        let (path, tx, ctx, name) = (engine::store::shot_image(&self.cfg.out, name), self.tx.clone(), self.feed.ctx.clone(), name.to_string());
        std::thread::spawn(move || {
            let img = engine::store::read_image(&path);
            if copy {
                let result = img.clone().and_then(|i| win::copy_image(&i));
                let _ = tx.send(Msg::Copied(name, result.err()));
                ctx.request_repaint();
            }
            if notify {
                let thumb = img.ok().map(|i| {
                    let side = i.width().min(i.height());
                    let square = image::imageops::crop_imm(&i, (i.width() - side) / 2, (i.height() - side) / 2, side, side).to_image();
                    let small = image::imageops::resize(&square, 96, 96, image::imageops::FilterType::Triangle);
                    crate::art::png(&image::DynamicImage::ImageRgb8(small).to_rgba8())
                });
                let text = if copy { "Уже в буфере обмена, вставляй через Ctrl+V. Нажми, чтобы открыть" } else { "Нажми, чтобы открыть и поправить" };
                win::tray_tell_picture("СС готова", text, thumb.as_deref());
            }
        });
    }

    fn settings_chatlog_on(&self) -> bool {
        self.settings.chatlog_running()
    }

    fn apply(&mut self, actions: Vec<Action>) {
        for action in actions {
            match action {
                Action::Set(key, value) => {
                    if self.set(key, &value) && key == "chatlog" {
                        let out = self.cfg.out.clone();
                        self.settings.toggle_chatlog(self.cfg.chatlog && self.probe.is_none(), &out);
                    }
                }
                Action::Tray(on) => {
                    self.set("tray", if on { "yes" } else { "no" });
                    if self.probe.is_none() {
                        win::tray_show(on);
                    }
                }
                Action::OpenFolder => self.feed.open_folder(),
                Action::Tour => {
                    self.set("tour", "yes");
                    self.tab = Tab::Feed;
                    self.feed.tour_done = false;
                    self.feed.start_tour();
                }
                Action::Folder(path) => {
                    self.feed.commit_delete();
                    self.set("output", &path.to_string_lossy());
                    self.feed.message = engine::store::check_out(&self.cfg).map(|p| ("fail".to_string(), p));
                    self.feed.cache.clear();
                    self.feed.refresh_names();
                    self.feed.index = 0;
                    self.feed.shot = None;
                    self.settings.forget_sample();
                }
                Action::Cleared => {
                    self.feed.cache.clear();
                    if self.feed.index > 0 {
                        self.feed.open_current();
                    }
                    self.settings.forget_sample();
                }
            }
        }
    }

    fn run_probe(&mut self, ctx: &egui::Context, probe: &Probe) {
        if self.frames >= self.probe_at && self.probe_index < probe.script.len() {
            let cmd = probe.script[self.probe_index].clone();
            let loading = self.feed.index > 0 && (self.feed.shot.is_none() || self.feed.preview_due.is_some()
                || (self.feed.previewing() && self.feed.preview.is_none()));
            if cmd == "wait" && loading && self.frames < 900 {
                return;
            }
            self.probe_step(&cmd);
            self.probe_index += 1;
            self.probe_at = self.frames + 8;
            return;
        }
        if self.probe_done.load(Ordering::Relaxed) {
            ctx.send_viewport_cmd(ViewportCommand::Close);
            return;
        }
        if self.probe_index >= probe.script.len() && self.frames >= self.probe_at + probe.frames && !self.probe_sent {
            self.probe_sent = true;
            let (path, done, repaint) = (probe.shot.clone(), self.probe_done.clone(), ctx.clone());
            ctx.send_viewport_cmd(ViewportCommand::Screenshot(egui::ScreenshotCallback::new(move |img| {
                let [w, h] = img.size;
                let rgba: Vec<u8> = img.pixels.iter().flat_map(|c| c.to_array()).collect();
                if let Some(buf) = image::RgbaImage::from_raw(w as u32, h as u32, rgba) {
                    let _ = buf.save(&path);
                }
                done.store(true, Ordering::Relaxed);
                repaint.request_repaint();
            })));
        }
    }

    fn probe_step(&mut self, cmd: &str) {
        let (head, arg) = cmd.split_once(':').unwrap_or((cmd, ""));
        match head {
            "go" => self.feed.go(arg.parse().unwrap_or(0)),
            "tab" => self.tab = if arg == "settings" { Tab::Settings } else { Tab::Feed },
            "tool" => self.feed.probe_tool(arg),
            "msg" => self.feed.message = Some(("fail".into(), arg.to_string())),
            "menu" => {
                let area = self.feed.last_area;
                self.feed.open_menu(area.center(), area);
            }
            "toast" => self.feed.tell(arg.to_string(), Some(("Вернуть", crate::assist::Remedy::Restore))),
            "news" => self.feed.news = true,
            "point" => {
                let (x, y) = arg.split_once('x').unwrap_or(("0", "0"));
                self.probe_point = Some(Pos2::new(x.parse().unwrap_or(0.0), y.parse().unwrap_or(0.0)));
            }
            "fold" => {
                let ctx = self.feed.ctx.clone();
                let mut state = egui::collapsing_header::CollapsingState::load_with_default_open(&ctx, Id::new(("settings-fold", arg)), false);
                state.set_open(!state.is_open());
                state.store(&ctx);
            }
            _ => {}
        }
    }
}

impl eframe::App for App {
    fn raw_input_hook(&mut self, _ctx: &egui::Context, raw: &mut egui::RawInput) {
        if let Some(p) = self.probe_point {
            raw.events.push(egui::Event::PointerMoved(p));
        }
    }

    fn logic(&mut self, ctx: &egui::Context, frame: &mut eframe::Frame) {
        if !self.framed {
            use raw_window_handle::{HasWindowHandle, RawWindowHandle};
            if let Ok(handle) = frame.window_handle() {
                if let RawWindowHandle::Win32(h) = handle.as_raw() {
                    let hwnd = h.hwnd.get();
                    self.shared.hwnd.store(hwnd, Ordering::Relaxed);
                    win::frame_window(hwnd);
                    if self.probe.is_some() {
                        win::ghost(hwnd);
                    }
                }
            }
            self.framed = true;
        }
        if ctx.input(|i| i.viewport().close_requested()) && self.cfg.tray && win::tray_on() {
            ctx.send_viewport_cmd(ViewportCommand::CancelClose);
            self.hide(ctx);
        }
        self.pump(ctx);
        if std::env::var_os("SNAPLINE_TIMING").is_some() && self.probe.is_some() {
            if let Some(t) = crate::START.get() {
                println!("first frame after {:?}", t.elapsed());
            }
            std::process::exit(0);
        }
        if let Some(probe) = self.probe.clone() {
            self.frames += 1;
            if std::env::var_os("SNAPLINE_FRAMES").is_some() {
                static LAST: std::sync::Mutex<Option<std::time::Instant>> = std::sync::Mutex::new(None);
                let now = std::time::Instant::now();
                if let Some(last) = LAST.lock().unwrap().replace(now) {
                    let dt = now - last;
                    if dt > Duration::from_millis(20) {
                        println!("frame {} step {} took {:?}", self.frames, self.probe_index, dt);
                    }
                }
            }
            if probe.test.is_some() {
                self.run_test(ctx, &probe);
                ctx.request_repaint();
                return;
            }
            self.run_probe(ctx, &probe);
            ctx.request_repaint();
            return;
        }
        ctx.request_repaint_after(Duration::from_millis(100));
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let full = ui.max_rect();
        ui.painter().rect_filled(full, CornerRadius::ZERO, VOID);
        let bar = Rect::from_min_size(full.min, vec2(full.width(), BAR_H));
        let body = Rect::from_min_max(Pos2::new(full.left(), full.top() + BAR_H), full.max);
        self.bar(ui, bar);
        match self.tab {
            Tab::Feed => self.feed.show(ui, body, self.update.as_ref()),
            Tab::Settings => {
                let cached = self.feed.names.first().and_then(|n| self.feed.cache.get(n)).and_then(|s| s.clone());
                let actions = self.settings.show(ui, body, &self.cfg, &self.raw, cached.as_ref(), self.update.as_ref());
                self.apply(actions);
            }
        }
        if std::mem::take(&mut self.feed.want_settings) {
            self.tab = Tab::Settings;
        }
        if let Some(tour) = self.feed.news_closed.take() {
            self.set("seen", config::VERSION);
            if tour {
                self.apply(vec![Action::Tour]);
            } else {
                self.set("tour", "no");
            }
        }
        self.grips(ui, full);
        self.draw_splash(ui, full);
        let keyed = self.settings.keys(ui.ctx(), &self.cfg);
        if !keyed.is_empty() {
            self.apply(keyed);
        } else if self.tab == Tab::Feed {
            self.feed.keys(ui.ctx());
        }
        if self.feed.tour_done {
            self.feed.tour_done = false;
            self.set("tour", "no");
        }
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        self.feed.finish();
        win::tray_show(false);
        self.shared.stop.store(true, Ordering::Relaxed);
    }
}
