use std::path::{Path, PathBuf};

use engine::chat::{self, Kind, Row};
use image::{RgbImage, RgbaImage};
use serde_json::Value;

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..")
}

fn reference() -> Option<PathBuf> {
    let p = root().join("rust").join("target").join("ref");
    if p.join("index.json").exists() {
        Some(p)
    } else {
        eprintln!("no Python reference in rust/target/ref, parity checks skipped");
        None
    }
}

fn read(p: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(p).unwrap()).unwrap()
}

fn load(p: &Path) -> RgbImage {
    image::open(p).unwrap_or_else(|e| panic!("{}: {e}", p.display())).to_rgb8()
}

fn spans(v: &Value) -> Vec<(usize, usize)> {
    v.as_array().unwrap().iter().map(|s| (s[0].as_u64().unwrap() as usize, s[1].as_u64().unwrap() as usize)).collect()
}

fn rows_of(p: &Path) -> Vec<Row> {
    chat::classify(chat::extract_rows(&load(p)), &[Kind::Speech, Kind::Action])
}

#[test]
fn rows_match_python() {
    let Some(r) = reference() else { return };
    let index = read(&r.join("index.json"));
    let mut checked = 0;
    for (tag, path) in index.as_object().unwrap() {
        if !Path::new(path.as_str().unwrap()).exists() {
            continue;
        }
        let want = read(&r.join("rows").join(format!("{tag}.json")));
        let want = want.as_array().unwrap();
        let rows = rows_of(Path::new(path.as_str().unwrap()));
        assert_eq!(rows.len(), want.len(), "{tag}: row count");
        let nicks = chat::nick_spans(&rows);
        for (k, (row, w)) in rows.iter().zip(want).enumerate() {
            let at = format!("{tag} row {k}");
            assert_eq!(row.y0 as u64, w["y0"].as_u64().unwrap(), "{at}: y0");
            assert_eq!(row.base as u64, w["base"].as_u64().unwrap(), "{at}: base");
            assert!((row.pitch - w["pitch"].as_f64().unwrap()).abs() < 1e-9, "{at}: pitch");
            assert_eq!(row.h as u64, w["h"].as_u64().unwrap(), "{at}: height");
            assert_eq!(row.glyphs, spans(&w["glyphs"]), "{at}: glyphs");
            assert_eq!(row.kind.label(), w["kind"].as_str().unwrap(), "{at}: kind");
            assert_eq!(row.keep, w["keep"].as_bool().unwrap(), "{at}: keep");
            assert_eq!(row.cont, w["cont"].as_bool().unwrap(), "{at}: cont");
            assert_eq!(row.mark.map(|c| c.to_string()), w["mark"].as_str().map(|s| s.to_string()), "{at}: mark");
            for c in 0..3 {
                assert!((row.body[c] as f64 - w["body"][c].as_f64().unwrap()).abs() < 0.01, "{at}: body");
            }
            assert_eq!(chat::words(row), spans(&w["words"]), "{at}: words");
            assert_eq!(nicks[k], spans(&w["nicks"]), "{at}: nicks");
        }
        checked += 1;
    }
    assert!(checked >= 7, "only {checked} images checked");
}

fn diff(a: &RgbaImage, b: &RgbaImage) -> (f64, u8, f64) {
    assert_eq!(a.dimensions(), b.dimensions(), "layer size");
    let mut total = 0f64;
    let mut worst = 0u8;
    let mut loud = 0usize;
    for (p, q) in a.pixels().zip(b.pixels()) {
        for c in 0..4 {
            let (x, y) = if c == 3 {
                (p[3] as f64, q[3] as f64)
            } else {
                (p[c] as f64 * p[3] as f64 / 255.0, q[c] as f64 * q[3] as f64 / 255.0)
            };
            let d = (x - y).abs().round() as u8;
            total += d as f64;
            worst = worst.max(d);
            loud += (d > 16) as usize;
        }
    }
    let n = (a.width() * a.height() * 4) as f64;
    (total / n, worst, loud as f64 / n)
}

#[test]
fn layers_match_python() {
    let Some(r) = reference() else { return };
    let index = read(&r.join("index.json"));
    for (tag, path) in index.as_object().unwrap() {
        if tag.starts_with("extra_") || !Path::new(path.as_str().unwrap()).exists() {
            continue;
        }
        let mut rows = rows_of(Path::new(path.as_str().unwrap()));
        for row in rows.iter_mut() {
            row.keep = true;
        }
        for (scale, outline) in [(1.0, 2), (0.5555, 2), (1.25, 1), (0.8, 0)] {
            let name = format!("{tag}_{scale:?}_{outline}");
            let want = image::open(r.join("layers").join(format!("{name}.png"))).unwrap().to_rgba8();
            let meta = read(&r.join("layers").join(format!("{name}.json")));
            let layer = chat::chat_layer(&rows, outline, scale, None).unwrap();
            assert_eq!(layer.painted as u64, meta[0].as_u64().unwrap(), "{name}: painted");
            assert_eq!(layer.pad as u64, meta[1].as_u64().unwrap(), "{name}: pad");
            let (mean, worst, loud) = diff(&layer.image, &want);
            let ok = if scale == 1.0 { mean <= 0.01 && worst <= 1 } else { mean <= 0.5 && loud <= 0.005 };
            assert!(ok, "{name}: mean {mean:.3} worst {worst} loud {:.4}%", loud * 100.0);
        }
    }
}

#[test]
fn merge_matches_python() {
    let Some(r) = reference() else { return };
    let want: Vec<u64> = read(&r.join("rows").join("merged.json")).as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
    let mut merged = vec![];
    for n in ["chat1", "chat2", "chat3"] {
        merged = chat::merge(merged, rows_of(&root().join("tests").join("fixtures").join(format!("{n}.webp"))));
    }
    assert_eq!(merged.iter().map(|r| r.y0 as u64).collect::<Vec<_>>(), want);
}

#[test]
fn watermark_matches_python() {
    let Some(r) = reference() else { return };
    let fixtures = root().join("tests").join("fixtures");
    let want = read(&r.join("marks").join("mark.json"));
    let mark = chat::watermark(&load(&fixtures.join("real_chat_ic.png"))).expect("watermark");
    assert_eq!((mark.x as u64, mark.w as u64, mark.h as u64),
               (want["x"].as_u64().unwrap(), want["w"].as_u64().unwrap(), want["h"].as_u64().unwrap()));
    let clean = chat::clean_bg(&load(&fixtures.join("real_bg.webp")), Some(&mark));
    let expect = load(&r.join("marks").join("clean.png"));
    let worst = clean.as_raw().iter().zip(expect.as_raw()).map(|(a, b)| a.abs_diff(*b)).max().unwrap();
    assert!(worst <= 2, "clean_bg differs by {worst}");
}
