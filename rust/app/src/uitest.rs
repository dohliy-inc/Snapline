use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicI32, Ordering};

use eframe::egui::Pos2;
use engine::chat::{self, Kind};
use engine::config::Raw;
use engine::edit::{Seam, SeamPart};
use serde_json::Value;

use crate::app::{App, Tab};

pub static EXIT: AtomicI32 = AtomicI32::new(1);
pub const NAMES: [&str; 2] = ["SS_2026-01-01_12-00-00", "SS_2026-01-01_12-05-00"];
pub const DOOMED: &str = "SS_2026-01-01_11-00-00";
const LOG: [(&str, &str, &str); 4] = [
    ("11:58:10", "* Malachy Doyle стоит возле своего автомобиля.", "#c2a2da"),
    ("11:59:02", "Mia Lopez говорит: Ты видел, кто к нам заехал?", "#e6e6e6"),
    ("12:01:30", "Victor Hale говорит (тихо): Видел. Не смотри туда.", "#e6e6e6"),
    ("12:04:12", "(( Victor Hale: щас вернусь ))", "#afafaf"),
];

fn fixtures() -> PathBuf {
    let mut dir = std::env::current_exe().unwrap_or_default();
    for _ in 0..8 {
        dir = dir.parent().map(|p| p.to_path_buf()).unwrap_or_default();
        if dir.join("tests").join("fixtures").exists() {
            return dir.join("tests").join("fixtures");
        }
    }
    PathBuf::from(r"D:\Work\lspscreen\tests\fixtures")
}

pub fn prepare() -> PathBuf {
    let work = std::env::temp_dir().join(format!("snapline_rs_ui_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&work);
    let shots = work.join("out");
    std::fs::create_dir_all(shots.join("chatlog")).unwrap();
    let mut raw = Raw::default();
    for (k, v) in [("sound", "no"), ("chatlog", "no"), ("source", "screen"), ("file", "jpg"), ("tray", "no"), ("tour", "no"),
                   ("seen", engine::config::VERSION)] {
        raw.set(k, v);
    }
    raw.set("output", shots.to_string_lossy().to_string());
    engine::config::write_raw(&work.join("config.ini"), &raw).unwrap();
    let cfg = engine::config::parse_config(&raw).unwrap();
    let bg = image::open(fixtures().join("real_bg.webp")).unwrap().to_rgb8();
    let frame = image::open(fixtures().join("real_chat_ic.png")).unwrap().to_rgb8();
    for name in NAMES.iter().chain(std::iter::once(&DOOMED)) {
        let mut state = engine::capture::Session::named(name);
        engine::capture::handle(bg.clone(), &mut state, &cfg).unwrap();
        engine::capture::handle(frame.clone(), &mut state, &cfg).unwrap();
    }
    let log: String = LOG.iter().map(|(t, text, color)| format!("{}\n", serde_json::json!({"time": t, "parts": [[text, color]]}))).collect();
    std::fs::write(shots.join("chatlog").join("2026-01-01.jsonl"), log).unwrap();
    engine::config::drain_events();
    crate::win::TEST_RECYCLE.store(true, Ordering::Relaxed);
    work
}

type Act = Box<dyn Fn(&mut App) -> Result<(), String>>;

pub enum Step {
    Do(&'static str, Act, u32),
    Wait(&'static str, Box<dyn Fn(&App) -> bool>),
}

fn expect(ok: bool, what: &str) -> Result<(), String> {
    if ok { Ok(()) } else { Err(what.to_string()) }
}

fn at(app: &App, fx: f32, fy: f32) -> Pos2 {
    let img = app.feed.geo.as_ref().map(|g| g.img).unwrap_or(eframe::egui::Rect::NOTHING);
    Pos2::new(img.left() + fx * img.width(), img.top() + fy * img.height())
}

fn drag(app: &mut App, a: (f32, f32), b: (f32, f32)) -> Result<(), String> {
    let area = app.feed.last_area;
    let (p, q) = (at(app, a.0, a.1), at(app, b.0, b.1));
    app.feed.press(p, false, area);
    app.feed.motion(Pos2::new((p.x + q.x) / 2.0, (p.y + q.y) / 2.0), area);
    app.feed.motion(q, area);
    app.feed.release(q, area);
    Ok(())
}

fn edit_of(app: &App) -> engine::edit::Edit {
    app.feed.shot.as_ref().map(|s| s.edit.clone()).unwrap()
}

fn loaded(app: &App) -> bool {
    app.feed.shot.is_some()
}

pub fn steps() -> Vec<Step> {
    use Step::{Do, Wait};
    vec![
        Do("open", Box::new(|a| {
            a.tab = Tab::Feed;
            a.feed.go(1);
            Ok(())
        }), 10),
        Wait("shot loaded", Box::new(loaded)),
        Do("lines", Box::new(|a| {
            a.feed.toggle_tool("lines");
            Ok(())
        }), 10),
        Do("hide a word", Box::new(|a| {
            let items = a.feed.line_items();
            a.feed.items = items.clone();
            let shot = a.feed.shot.as_ref().unwrap();
            let j = items.iter().position(|it| it.row.is_some_and(|i| shot.rows[i].kind == Kind::Speech)).ok_or("no speech row")?;
            let row = &shot.rows[items[j].row.unwrap()];
            let word = chat::words(row)[0];
            a.feed.popup = Some(crate::feed::Popup { j, word });
            a.feed.popup_pick("hide");
            expect(!edit_of(a).hidden.is_empty(), "word was not hidden")
        }), 8),
        Do("logpick", Box::new(|a| {
            a.feed.toggle_tool("logpick");
            expect(a.feed.logview.as_ref().is_some_and(|v| v.lines.len() == 4), "chatlog lines did not load")
        }), 8),
        Do("crop", Box::new(|a| {
            a.feed.toggle_tool("crop");
            a.feed.set_frame("800x800");
            Ok(())
        }), 8),
        Do("undo frame", Box::new(|a| {
            a.feed.undo(true);
            expect(edit_of(a).format != "800x800", "Ctrl+Z did not undo the frame")
        }), 6),
        Do("redo frame", Box::new(|a| {
            a.feed.undo(false);
            expect(edit_of(a).format == "800x800", "Ctrl+Y did not redo the frame")
        }), 6),
        Do("mirror", Box::new(|a| {
            a.feed.set_frame("square");
            a.feed.mirror_frame();
            expect(edit_of(a).mirror, "mirror did not turn on")
        }), 6),
        Do("tilt", Box::new(|a| {
            a.feed.mirror_frame();
            a.feed.change(|e| {
                e.zoom = 1.5;
                e.tilt = Some(30.0);
            });
            Ok(())
        }), 10),
        Do("tilted pan", Box::new(|a| {
            let [cx, cy] = edit_of(a).center;
            drag(a, (0.5, 0.5), (0.6, 0.5))?;
            let [nx, ny] = edit_of(a).center;
            expect(nx < cx - 0.01 && ny > cy + 0.005, &format!("pan under tilt went the wrong way: {cx},{cy} -> {nx},{ny}"))
        }), 8),
        Do("mirror keeps tilt mirrored", Box::new(|a| {
            a.feed.mirror_frame();
            let e = edit_of(a);
            expect(e.tilt() == -30.0 && e.mirror, "mirror kept the tilt sign")
        }), 6),
        Do("reset frame", Box::new(|a| {
            a.feed.mirror_frame();
            a.feed.change(|e| {
                e.zoom = 1.0;
                e.tilt = Some(0.0);
                e.center = [0.5, 0.5];
            });
            Ok(())
        }), 8),
        Do("text burst", Box::new(|a| {
            a.feed.toggle_tool("text");
            for v in [1.1, 1.2, 1.3] {
                a.feed.change_text(move |e| e.text_scale = v);
            }
            a.feed.undo(true);
            let s = edit_of(a).text_scale;
            expect(![1.1, 1.2, 1.3].contains(&s), "slider burst is not one undo step")
        }), 8),
        Do("text redo", Box::new(|a| {
            a.feed.undo(false);
            Ok(())
        }), 6),
        Do("images", Box::new(|a| {
            a.feed.toggle_tool("images");
            a.feed.add_image(image::RgbaImage::from_pixel(400, 300, image::Rgba([40, 120, 200, 255])));
            a.feed.change_ov(|o| o.alpha = 0.8);
            Ok(())
        }), 10),
        Do("flip and turn", Box::new(|a| {
            a.feed.change_ov(engine::compose::flip_overlay);
            a.feed.change_ov(|o| o.angle = Some(engine::compose::wrap_angle(o.turn() + 90.0)));
            let ov = edit_of(a).overlays[0].clone();
            expect(ov.flipped() && ov.turn() == 90.0, "flip or turn did not apply to the picture")
        }), 10),
        Do("crop turned", Box::new(|a| {
            let geo = a.feed.geo.clone().ok_or("no geo")?;
            let b = geo.overlays[0].clone().ok_or("no overlay geo")?;
            let ov = edit_of(a).overlays[0].clone();
            let size = a.feed.source_size(&ov).ok_or("no source")?;
            let (x0, y0) = (ov.x, ov.y);
            a.feed.drag = Some(crate::feed::Drag::Crop { handle: "r".into(), part: 0, x: 500.0, y: 500.0, crop: ov.crop, b: b.clone(), size });
            a.feed.drag_crop(Pos2::new(500.0, 500.0 - b.w / 4.0));
            a.feed.drag = None;
            let ov = edit_of(a).overlays[0].clone();
            expect(ov.crop[2] < 0.9 && ov.y < y0 - 0.01 && (ov.x - x0).abs() < 0.002, &format!("cropping a turned picture went the wrong way: {:?}", ov.crop))
        }), 8),
        Do("grab picture", Box::new(|a| {
            a.feed.change_ov(|o| o.angle = Some(30.0));
            Ok(())
        }), 8),
        Do("drag picture", Box::new(|a| {
            let geo = a.feed.geo.clone().ok_or("no geo")?;
            let b = geo.overlays[0].clone().ok_or("no overlay geo")?;
            let x0 = edit_of(a).overlays[0].x;
            let c = b.b.center();
            let area = a.feed.last_area;
            a.feed.press(c, false, area);
            a.feed.motion(Pos2::new(c.x + 40.0, c.y), area);
            a.feed.release(Pos2::new(c.x + 40.0, c.y), area);
            let x1 = edit_of(a).overlays[0].x;
            expect(x1 > x0 + 0.01, &format!("the picture did not follow the mouse: {x0} -> {x1}"))
        }), 8),
        Do("remove picture", Box::new(|a| {
            a.feed.remove_ov();
            Ok(())
        }), 8),
        Do("style", Box::new(|a| {
            a.feed.toggle_tool("style");
            a.feed.change(|e| e.preset = Some("film".into()));
            a.feed.change(|e| e.style = Some("cctv".into()));
            Ok(())
        }), 30),
        Do("style off", Box::new(|a| {
            a.feed.change(|e| {
                e.style = Some("none".into());
                e.style_text = None;
                e.look = Some(Default::default());
                e.preset = Some("none".into());
            });
            Ok(())
        }), 20),
        Do("blur", Box::new(|a| {
            a.feed.toggle_tool("blur");
            Ok(())
        }), 10),
        Do("blur new", Box::new(|a| {
            drag(a, (0.3, 0.3), (0.6, 0.5))?;
            expect(edit_of(a).blurs.as_ref().is_some_and(|b| b.len() == 1), "drag did not add a blur area")
        }), 6),
        Do("blur move", Box::new(|a| {
            drag(a, (0.45, 0.4), (0.5, 0.45))?;
            let x = edit_of(a).blurs.unwrap()[0].x;
            expect((x - 0.35).abs() < 0.02, &format!("drag did not move the area: {x}"))
        }), 6),
        Do("blur tiny", Box::new(|a| {
            a.feed.set_blur(|b| {
                b.mode = "pixel".into();
                b.power = 0.9;
            });
            drag(a, (0.1, 0.1), (0.102, 0.102))?;
            expect(edit_of(a).blurs.unwrap().len() == 1, "a tiny drag left an area")
        }), 70),
        Do("blur delete", Box::new(|a| {
            a.feed.remove_blur();
            expect(edit_of(a).blurs.unwrap_or_default().is_empty(), "Delete did not remove the area")
        }), 6),
        Do("blur undo", Box::new(|a| {
            a.feed.undo(true);
            expect(edit_of(a).blurs.as_ref().and_then(|b| b.first()).is_some_and(|b| b.mode == "pixel"), "undo did not bring the area back")
        }), 6),
        Do("file", Box::new(|a| {
            a.feed.toggle_tool("file");
            a.feed.change(|e| e.file = "png".into());
            a.feed.change(|e| e.file = "jpg".into());
            Ok(())
        }), 20),
        Do("scene", Box::new(|a| {
            let shots: Vec<String> = NAMES.iter().rev().map(|s| s.to_string()).collect();
            a.feed.set_scene(shots, vec![SeamPart::of(Seam::default())]);
            a.feed.toggle_tool("scene");
            Ok(())
        }), 40),
        Do("text whole", Box::new(|a| {
            a.feed.toggle_tool("text");
            a.feed.set_whole("all");
            Ok(())
        }), 40),
        Do("text one", Box::new(|a| {
            a.feed.set_whole("one");
            a.feed.toggle_tool("text");
            Ok(())
        }), 10),
        Do("tour", Box::new(|a| {
            a.tab = Tab::Settings;
            a.feed.start_tour();
            a.tab = Tab::Feed;
            expect(a.feed.tour == Some(0), "tour did not start")
        }), 8),
        Do("tour next", Box::new(|a| {
            a.feed.tour = Some(1);
            a.feed.toggle_tool("lines");
            Ok(())
        }), 8),
        Do("tour moved", Box::new(|a| {
            expect(a.feed.tour == Some(2), &format!("tour did not move on after opening Lines: {:?}", a.feed.tour))
        }), 2),
        Do("tour end", Box::new(|a| {
            a.feed.finish_tour();
            Ok(())
        }), 6),
        Do("tour saved", Box::new(|a| {
            expect(a.feed.tour.is_none() && !a.cfg.tour, "finishing the tour did not save it as done")
        }), 2),
        Do("lines off", Box::new(|a| {
            a.feed.toggle_tool("lines");
            a.feed.go(2);
            Ok(())
        }), 10),
        Wait("second shot", Box::new(loaded)),
        Do("go 3", Box::new(|a| {
            a.feed.go(3);
            Ok(())
        }), 10),
        Wait("third shot", Box::new(loaded)),
        Do("duplicate", Box::new(|a| {
            a.feed.duplicate();
            Ok(())
        }), 40),
        Wait("copy", Box::new(|a| a.feed.names.len() == 4 && a.feed.shot.is_some() && a.feed.name().as_deref() != Some(DOOMED))),
        Do("copy files", Box::new(|a| {
            let copy = a.feed.name().unwrap_or_default();
            let out = a.cfg.out.clone();
            let json = std::fs::read_to_string(out.join("src").join(format!("{copy}.json"))).unwrap_or_default();
            expect(out.join(format!("{copy}.jpg")).exists() && !json.is_empty() && !json.contains(DOOMED),
                   &format!("copy {copy} is incomplete"))
        }), 4),
        Do("delete copy", Box::new(|a| {
            let copy = a.feed.name().unwrap_or_default();
            a.feed.delete();
            let out = a.cfg.out.clone();
            expect(!a.feed.names.contains(&copy) && out.join(format!("{copy}.jpg")).exists() && a.feed.pending.is_some(),
                   "delete did not wait for the undo window")
        }), 10),
        Do("restore copy", Box::new(|a| {
            let copy = a.feed.pending.as_ref().map(|p| p.0.clone()).unwrap_or_default();
            a.feed.restore();
            expect(a.feed.names.contains(&copy) && a.feed.name().as_deref() == Some(copy.as_str()), "Вернуть did not bring the shot back")
        }), 10),
        Wait("copy back", Box::new(loaded)),
        Do("delete copy again", Box::new(|a| {
            a.feed.delete();
            a.feed.commit_delete();
            Ok(())
        }), 60),
        Do("copy gone", Box::new(|a| {
            let left: Vec<String> = std::fs::read_dir(&a.cfg.out).map(|d| d.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_string())
                .filter(|n| n.ends_with(".jpg")).collect()).unwrap_or_default();
            expect(left.len() == 3 && a.feed.name().as_deref() == Some(DOOMED), &format!("copy was not deleted: {left:?}"))
        }), 4),
        Wait("doomed", Box::new(loaded)),
        Do("delete", Box::new(|a| {
            a.feed.delete();
            a.feed.commit_delete();
            Ok(())
        }), 60),
        Do("deleted", Box::new(|a| {
            let out = a.cfg.out.clone();
            let gone = !a.feed.names.contains(&DOOMED.to_string()) && a.feed.index == 2 && !out.join(format!("{DOOMED}.jpg")).exists();
            expect(gone, &format!("delete left the shot behind: index {}", a.feed.index))
        }), 4),
    ]
}

pub fn verify(work: &Path) -> Result<(), String> {
    let name = NAMES[1];
    let text = std::fs::read_to_string(work.join("out").join("src").join(format!("{name}.json"))).map_err(|e| e.to_string())?;
    let e: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let ok = e["format"] == "square" && e["file"] == "jpg" && e["style"] == "none" && !e["hidden"].as_array().unwrap().is_empty()
        && e["text_scale"].as_f64() == Some(1.3) && e["overlays"].as_array().unwrap().is_empty() && e.get("mirror").is_none_or(|m| m == false)
        && e["blurs"][0]["mode"] == "pixel" && e["blurs"][0]["power"].as_f64() == Some(0.9)
        && e["scene"]["shots"] == serde_json::json!([NAMES[1], NAMES[0]]);
    expect(ok, &format!("saved edit is wrong: {text}"))
}

pub fn selftest_home() -> Result<PathBuf, String> {
    let work = std::env::temp_dir().join(format!("snapline_rs_self_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&work);
    let shots = work.join("out");
    std::fs::create_dir_all(&shots).map_err(|e| e.to_string())?;
    let mut raw = Raw::default();
    for (k, v) in [("sound", "no"), ("chatlog", "no"), ("tray", "no"), ("tour", "no")] {
        raw.set(k, v);
    }
    raw.set("output", shots.to_string_lossy().to_string());
    engine::config::write_raw(&work.join("config.ini"), &raw).map_err(|e| e.to_string())?;
    let cfg = engine::config::parse_config(&raw)?;
    let bg = image::load_from_memory(crate::settings::SAMPLE_BG).map_err(|e| e.to_string())?.to_rgb8();
    let frame = image::load_from_memory(crate::settings::SAMPLE_CHAT).map_err(|e| e.to_string())?.to_rgb8();
    let mut state = engine::capture::Session::named("SS_2026-01-01_00-00-00");
    engine::capture::handle(bg, &mut state, &cfg)?;
    engine::capture::handle(frame, &mut state, &cfg)?;
    engine::config::drain_events();
    if engine::store::list_shots(&shots).len() != 1 {
        return Err("selftest shot was not saved".into());
    }
    Ok(work)
}
