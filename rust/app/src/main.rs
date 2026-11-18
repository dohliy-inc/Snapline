#![windows_subsystem = "windows"]

mod app;
mod assist;
mod art;
mod feed;
mod painter;
mod settings;
mod side;
mod theme;
mod tools;
mod tour;
mod uitest;
mod widgets;
mod win;

use eframe::egui;

fn probe() -> Option<app::Probe> {
    let args: Vec<String> = std::env::args().collect();
    let at = args.iter().position(|a| a == "--shot")?;
    let shot = std::path::PathBuf::from(args.get(at + 1)?);
    let script = args.iter().position(|a| a == "--do").and_then(|i| args.get(i + 1))
        .map(|s| s.split(',').map(|x| x.to_string()).collect()).unwrap_or_default();
    Some(app::Probe { shot, frames: 12, script, test: None })
}

pub static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();

fn main() -> eframe::Result {
    START.get_or_init(std::time::Instant::now);
    let mut probe = probe();
    let selftest = std::env::args().any(|a| a == "--selftest");
    if selftest {
        match uitest::selftest_home() {
            Ok(work) => {
                unsafe { std::env::set_var("SNAPLINE_HOME", &work) };
                probe = Some(app::Probe { shot: work.join("self.png"), frames: 12, script: vec!["go:1".into(), "wait".into()], test: None });
            }
            Err(e) => {
                eprintln!("selftest: {e}");
                std::process::exit(2);
            }
        }
    }
    if std::env::args().any(|a| a == "--uitest") {
        let work = uitest::prepare();
        unsafe { std::env::set_var("SNAPLINE_HOME", &work) };
        probe = Some(app::Probe { shot: work.join("ui.png"), frames: 12, script: vec![], test: Some(work) });
    }
    if probe.is_none() && win::already_running() {
        win::wake_other();
        return Ok(());
    }
    let icon = art::make_icon(64);
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Snapline")
            .with_inner_size([1360.0, 880.0])
            .with_min_inner_size([1100.0, 700.0])
            .with_decorations(false)
            .with_icon(egui::IconData { rgba: icon.into_raw(), width: 64, height: 64 })
            .with_active(probe.is_none())
            .with_taskbar(probe.is_none()),
        centered: true,
        ..Default::default()
    };
    let testing = probe.as_ref().is_some_and(|p| p.test.is_some());
    let shot = probe.as_ref().map(|p| p.shot.clone());
    let result = eframe::run_native("Snapline", options, Box::new(move |cc| Ok(Box::new(app::App::new(cc, probe)))));
    if testing {
        std::process::exit(uitest::EXIT.load(std::sync::atomic::Ordering::Relaxed));
    }
    if selftest {
        let ok = shot.is_some_and(|p| p.exists());
        std::process::exit(if ok { 0 } else { 2 });
    }
    result
}
