use std::path::{Path, PathBuf};

use chrono::NaiveDateTime;
use engine::chat::{self, Kind};
use engine::compose;
use engine::config::{self, Raw};
use engine::edit::{Edit, Home, Scene, SeamPart};
use engine::store;
use image::RgbImage;
use serde_json::Value;

fn reference() -> Option<PathBuf> {
    let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("target").join("ref");
    if p.join("golden.json").exists() {
        Some(p)
    } else {
        eprintln!("no Python reference in rust/target/ref, parity checks skipped");
        None
    }
}

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("tests").join("fixtures")
}

fn cfg_for(out: &Path) -> config::Config {
    let mut raw = Raw::default();
    for (k, v) in [("format", "square"), ("size", "native"), ("file", "png"), ("quality", "92"), ("chat_pos", "top-left"),
                   ("margin", "24"), ("text_scale", "1.5"), ("outline", "2"), ("keep", "речь, действие"),
                   ("hide_names", "no"), ("sound", "no")] {
        raw.set(k, v);
    }
    raw.set("output", out.to_string_lossy().to_string());
    config::parse_config(&raw).unwrap()
}

pub fn compare(got: &RgbImage, want: &RgbImage) -> (f64, f64, u8) {
    assert_eq!(got.dimensions(), want.dimensions(), "size");
    let mut total = 0f64;
    let mut loud = 0usize;
    let mut worst = 0u8;
    for (a, b) in got.as_raw().iter().zip(want.as_raw()) {
        let d = a.abs_diff(*b);
        total += d as f64;
        loud += (d > 24) as usize;
        worst = worst.max(d);
    }
    let n = got.as_raw().len() as f64;
    (total / n, loud as f64 / n, worst)
}

fn render_case(case: &Value, out: &Path, shot_name: &str) -> RgbImage {
    let cfg = cfg_for(out);
    if let Some(scene) = case.get("scene") {
        let head = scene["head"].as_str().unwrap();
        let mut shot = store::load_shot(out, head, &cfg).unwrap().unwrap();
        shot.edit.scene = Some(Scene {
            shots: scene["shots"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect(),
            seams: serde_json::from_value::<Vec<SeamPart>>(scene["seams"].clone()).unwrap(),
            extra: Default::default(),
        });
        shot.edit.home = Some(Home::One(scene["home"].as_str().unwrap().to_string()));
        return store::render_shot(&shot, None, None).unwrap().0;
    }
    let shot = store::load_shot(out, shot_name, &cfg).unwrap().unwrap();
    let bg = match case.get("bg").and_then(|v| v.as_str()) {
        Some(file) => image::open(fixtures().join(file)).unwrap().to_rgb8(),
        None => shot.bg.as_ref().clone(),
    };
    let mut rows = if case.get("rows").and_then(|v| v.as_str()) == Some("pm") {
        let img = image::open(fixtures().join("real_chat_pm.png")).unwrap().to_rgb8();
        let mut pm = chat::classify(chat::extract_rows(&img), &[Kind::Speech, Kind::Action]);
        for r in pm.iter_mut() {
            r.keep = true;
        }
        pm
    } else {
        shot.rows.clone()
    };
    let mut edit = Edit::merged(Edit::new(&cfg, &rows), &case["edit"]);
    compose::apply_keep(&mut rows, &mut edit);
    let rough = case.get("rough").and_then(|v| v.as_u64()).map(|v| v as u8);
    let when = case.get("when").and_then(|v| v.as_str()).and_then(|s| NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S").ok());
    let src = out.join("src");
    compose::render(&bg, &rows, &edit, Some(&src), rough, None, None, when).unwrap().0
}

#[test]
fn golden_renders_match_python() {
    let Some(r) = reference() else { return };
    let meta: Value = serde_json::from_str(&std::fs::read_to_string(r.join("golden.json")).unwrap()).unwrap();
    let out = r.join("shots");
    let shot_name = meta["shot"].as_str().unwrap();
    let mut bad = Vec::new();
    for case in meta["cases"].as_array().unwrap() {
        let name = case["name"].as_str().unwrap();
        let want = image::open(r.join("golden").join(format!("{name}.png"))).unwrap().to_rgb8();
        let got = render_case(case, &out, shot_name);
        if got.dimensions() != want.dimensions() {
            bad.push(format!("{name}: size {:?} vs {:?}", got.dimensions(), want.dimensions()));
            continue;
        }
        let (mean, loud, worst) = compare(&got, &want);
        eprintln!("{name:10} mean {mean:.3} loud {:.3}% worst {worst}", loud * 100.0);
        let dump = r.join("rust");
        std::fs::create_dir_all(&dump).unwrap();
        got.save(dump.join(format!("{name}.png"))).unwrap();
        if mean > 2.0 || loud > 0.01 {
            bad.push(format!("{name}: mean {mean:.3} loud {:.3}%", loud * 100.0));
        }
    }
    assert!(bad.is_empty(), "renders differ from Python: {bad:?}");
}

#[test]
fn capture_flow_matches_python() {
    let Some(r) = reference() else { return };
    let work = std::env::temp_dir().join(format!("snapline_rs_capture_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&work);
    let cfg = cfg_for(&work);
    let name = "SS_2026-01-01_00-00-00";
    let mut state = engine::capture::Session::named(name);
    let bg = image::open(fixtures().join("real_bg.webp")).unwrap().to_rgb8();
    let shot = image::open(fixtures().join("real_chat_ic.png")).unwrap().to_rgb8();
    assert_eq!(engine::capture::handle(bg, &mut state, &cfg).unwrap(), engine::capture::TONE_STEP);
    assert_eq!(engine::capture::handle(shot, &mut state, &cfg).unwrap(), engine::capture::TONE_SS);
    let got = image::open(work.join(format!("{name}.png"))).unwrap().to_rgb8();
    let want = image::open(r.join("shots").join(format!("{name}.png"))).unwrap().to_rgb8();
    let (mean, loud, _) = compare(&got, &want);
    assert!(mean < 1.0 && loud < 0.001, "capture result differs: mean {mean:.3} loud {:.3}%", loud * 100.0);
    let saved: Value = serde_json::from_str(&std::fs::read_to_string(work.join("src").join(format!("{name}.json"))).unwrap()).unwrap();
    let python: Value = serde_json::from_str(&std::fs::read_to_string(r.join("shots").join("src").join(format!("{name}.json"))).unwrap()).unwrap();
    for key in ["keep", "format", "pos", "hidden", "dropped", "size", "file", "quality", "outline", "margin"] {
        assert_eq!(saved[key], python[key], "edit key {key}");
    }
    let _ = std::fs::remove_dir_all(&work);
}
