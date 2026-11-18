use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use image::RgbImage;
use windows::Win32::Graphics::Gdi::{
    BI_RGB, BITMAPINFO, BITMAPINFOHEADER, BitBlt, CAPTUREBLT, CreateCompatibleBitmap, CreateCompatibleDC, DIB_RGB_COLORS,
    DeleteDC, DeleteObject, GetDC, GetDIBits, ReleaseDC, SRCCOPY, SelectObject,
};
use windows::Win32::System::Diagnostics::Debug::Beep;
use windows::Win32::UI::Input::KeyboardAndMouse::{
    GetAsyncKeyState, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBD_EVENT_FLAGS, KEYBDINPUT, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP,
    KEYEVENTF_SCANCODE, MAPVK_VK_TO_VSC, MapVirtualKeyW, SendInput, VIRTUAL_KEY,
};
use windows::Win32::UI::WindowsAndMessaging::{GetSystemMetrics, SM_CXSCREEN, SM_CYSCREEN};

use crate::chat::{self, Mark, Row};
use crate::config::{self, Config, Event};
use crate::edit::{Edit, LAYOUT_KEYS};
use crate::store::{self, Shot};

const EXTENDED_KEYS: [u32; 5] = [0x2D, 0x24, 0x23, 0x21, 0x22];
const POLL: Duration = Duration::from_millis(25);
const KEY_HOLD: Duration = Duration::from_millis(40);
const DARK_TIMEOUT: Duration = Duration::from_secs(2);
const DARK_SETTLE: Duration = Duration::from_millis(60);

pub type Tone = &'static [(u32, u32)];
pub const TONE_STEP: Tone = &[(1000, 70)];
pub const TONE_SS: Tone = &[(1000, 70), (1500, 120)];
pub const TONE_FAIL: Tone = &[(300, 450)];

pub struct Session {
    pub name: String,
    pub bg: Option<RgbImage>,
    pub rows: Vec<Row>,
    pub chats: u32,
    pub mark: Option<Mark>,
}

impl Session {
    pub fn new() -> Session {
        Session { name: chrono::Local::now().format("SS_%Y-%m-%d_%H-%M-%S").to_string(), bg: None, rows: vec![], chats: 0, mark: None }
    }

    pub fn named(name: &str) -> Session {
        Session { name: name.to_string(), ..Session::new() }
    }
}

impl Default for Session {
    fn default() -> Self {
        Session::new()
    }
}

pub fn grab() -> Result<RgbImage, String> {
    unsafe {
        let (w, h) = (GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN));
        if w <= 0 || h <= 0 {
            return Err("Windows не сообщил размер экрана".into());
        }
        let screen = GetDC(None);
        let dc = CreateCompatibleDC(Some(screen));
        let bmp = CreateCompatibleBitmap(screen, w, h);
        let old = SelectObject(dc, bmp.into());
        let copied = BitBlt(dc, 0, 0, w, h, Some(screen), 0, 0, SRCCOPY | CAPTUREBLT);
        let mut info = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: w,
                biHeight: -h,
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB.0,
                ..Default::default()
            },
            ..Default::default()
        };
        let mut buf = vec![0u8; (w * h * 4) as usize];
        let lines = GetDIBits(dc, bmp, 0, h as u32, Some(buf.as_mut_ptr().cast()), &mut info, DIB_RGB_COLORS);
        SelectObject(dc, old);
        let _ = DeleteObject(bmp.into());
        let _ = DeleteDC(dc);
        ReleaseDC(None, screen);
        if copied.is_err() || lines != h {
            return Err("снимок экрана не получился".into());
        }
        let rgb: Vec<u8> = buf.chunks_exact(4).flat_map(|p| [p[2], p[1], p[0]]).collect();
        Ok(RgbImage::from_raw(w as u32, h as u32, rgb).unwrap())
    }
}

pub fn tap(key: &str) -> Result<(), String> {
    let vk = config::keys().into_iter().find(|(k, _)| k == key).map(|(_, v)| v).ok_or(format!("нет клавиши {key}"))?;
    let mut flags = KEYEVENTF_SCANCODE;
    if EXTENDED_KEYS.contains(&vk) {
        flags |= KEYEVENTF_EXTENDEDKEY;
    }
    let scan = unsafe { MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) } as u16;
    for up in [KEYBD_EVENT_FLAGS(0), KEYEVENTF_KEYUP] {
        let input = INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 { ki: KEYBDINPUT { wVk: VIRTUAL_KEY(0), wScan: scan, dwFlags: flags | up, time: 0, dwExtraInfo: 0 } },
        };
        let sent = unsafe { SendInput(&[input], std::mem::size_of::<INPUT>() as i32) };
        if sent != 1 {
            return Err(format!("Windows не дал нажать {key}: {}", std::io::Error::last_os_error()));
        }
        std::thread::sleep(KEY_HOLD);
    }
    Ok(())
}

pub fn handle(img: RgbImage, state: &mut Session, cfg: &Config) -> Result<Tone, String> {
    let key = cfg.key.clone();
    let out = cfg.out.clone();
    if chat::is_chat_shot(&img) {
        let rows = chat::classify(chat::extract_rows(&img), &cfg.keep);
        if rows.is_empty() {
            config::log("Экран чёрный, но чата на нём нет. Если ты не на F2, значит захват не видит игру: \
                         поставь в настройках графики GTA режим «Оконный без рамки».", "fail");
            return Ok(TONE_FAIL);
        }
        let (_, files, meta) = store::shot_files(&out, &state.name);
        if meta.exists() {
            let (loaded, saved, _, _) = store::load_rows(&out, &state.name, cfg)?;
            state.rows = loaded;
            for (i, r) in state.rows.iter_mut().enumerate() {
                r.cut = saved.breaks.contains(&(i as i64));
            }
        }
        state.chats += 1;
        let next = files.iter().map(|p| store::chat_number(p)).max().unwrap_or(0) + 1;
        store::save_src(&img, &out, &format!("{}_chat{next}", state.name), true)?;
        if state.mark.is_none() {
            state.mark = chat::watermark(&img);
        }
        let kept = rows.iter().filter(|r| r.keep).count();
        let count = rows.len();
        state.rows = chat::merge(std::mem::take(&mut state.rows), rows);
        config::log(&format!("Чат #{}: строк {count}, из них в СС {kept}.", state.chats), "info");
    } else {
        if state.bg.is_some() {
            *state = Session::new();
        }
        store::save_src(&img, &out, &format!("{}_bg", state.name), false)?;
        state.bg = Some(img);
        config::log("Фон принят.", "info");
    }
    let Some(bg) = state.bg.as_ref() else {
        config::log(&format!("Чат есть. Теперь фон: {}, затем {key}.", cfg.hud_key), "step");
        return Ok(TONE_STEP);
    };
    if state.rows.is_empty() {
        config::log(&format!("Фон есть. Теперь чат: {}, затем {key}.", cfg.dark_key), "step");
        return Ok(TONE_STEP);
    }
    if !state.rows.iter().any(|r| r.keep) {
        config::log("В чате нет реплик для СС: только системные строки и OOC.", "fail");
        return Ok(TONE_FAIL);
    }
    let old = store::saved_edit(&out, &state.name);
    let mut edit = Edit::with_keys(Edit::new(cfg, &state.rows).with_style(cfg), &old, &LAYOUT_KEYS);
    edit.breaks = state.rows.iter().enumerate().filter(|(i, r)| r.cut && *i > 0).map(|(i, _)| i as i64).collect();
    if cfg.hide_names {
        crate::compose::auto_hide(&mut state.rows, true);
    }
    edit.hidden = crate::edit::spans_of(&state.rows, false);
    edit.dropped = crate::edit::spans_of(&state.rows, true);
    let shot = Shot {
        name: Some(state.name.clone()),
        out: out.clone(),
        bg: std::sync::Arc::new(chat::clean_bg(bg, state.mark.as_ref())),
        rows: state.rows.clone(),
        edit,
        legacy: false,
        cfg: Some(cfg.clone()),
        members: Default::default(),
    };
    let had = old.as_object().is_some_and(|o| !o.is_empty());
    let (img, painted) = store::save_shot(&shot, had)?;
    let kept = state.rows.iter().filter(|r| r.keep).count();
    let tail = if painted == kept { String::new() } else { format!(" Влезло {painted} строк из {kept}.") };
    config::log(&format!("СС готова: {}.{}, {}×{}.{tail}", state.name, shot.edit.file, img.width(), img.height()), "ok");
    config::emit(Event::Shot(state.name.clone()));
    Ok(TONE_SS)
}

fn wait_dark() -> Result<Option<RgbImage>, String> {
    let end = Instant::now() + DARK_TIMEOUT;
    while Instant::now() < end {
        if chat::is_chat_shot(&grab()?) {
            std::thread::sleep(DARK_SETTLE);
            return grab().map(Some);
        }
        std::thread::sleep(POLL);
    }
    Ok(None)
}

fn hud_grab(cfg: &Config) -> Result<RgbImage, String> {
    tap(&cfg.hud_key)?;
    std::thread::sleep(Duration::from_secs_f64(cfg.hud_delay));
    let bg = grab();
    tap(&cfg.hud_key)?;
    bg
}

fn auto_shot(state: &mut Session, cfg: &Config) -> Result<Tone, String> {
    let bg = hud_grab(cfg)?;
    tap(&cfg.dark_key)?;
    let Some(shot) = wait_dark()? else {
        config::log(&format!("Игра не затемнилась по {} за {} с. Проверь клавишу затемнения; если FiveM запущен от \
                              администратора, запусти и программу от администратора.", cfg.dark_key, DARK_TIMEOUT.as_secs()), "fail");
        return Ok(TONE_FAIL);
    };
    tap(&cfg.dark_key)?;
    *state = Session::new();
    store::save_src(&bg, &cfg.out, &format!("{}_bg", state.name), false)?;
    state.bg = Some(bg);
    handle(shot, state, cfg)
}

fn scene_shot(state: &mut Session, cfg: &Config) -> Result<Tone, String> {
    let bg = if cfg.auto { hud_grab(cfg)? } else { grab()? };
    *state = Session::new();
    store::save_src(&bg, &cfg.out, &format!("{}_bg", state.name), false)?;
    let mark = store::recent_mark(&cfg.out);
    let mut shot = Shot {
        name: Some(state.name.clone()),
        out: cfg.out.clone(),
        bg: std::sync::Arc::new(chat::clean_bg(&bg, mark.as_ref())),
        rows: vec![],
        edit: Edit::new(cfg, &[]).with_style(cfg),
        legacy: false,
        cfg: Some(cfg.clone()),
        members: Default::default(),
    };
    store::use_log(&mut shot, cfg, &[])?;
    let (img, _) = store::save_shot(&shot, false)?;
    config::emit(Event::Shot(state.name.clone()));
    config::log(&format!("СС готова: {}.{}, {}×{}. Чат пока пустой: строки выбери в «Строках» из чатлога.",
                         state.name, shot.edit.file, img.width(), img.height()), "ok");
    Ok(TONE_SS)
}

pub fn on_hotkey(state: &mut Session, cfg: &Config) -> Result<Tone, String> {
    if cfg.source == "log" {
        return scene_shot(state, cfg);
    }
    let img = grab()?;
    if cfg.auto && !chat::is_chat_shot(&img) {
        return auto_shot(state, cfg);
    }
    handle(img, state, cfg)
}

pub fn play(tone: Tone, cfg: &Config) {
    if cfg.sound {
        for &(freq, ms) in tone {
            let _ = unsafe { Beep(freq, ms) };
        }
    }
}

pub fn run(get_cfg: impl Fn() -> Config, stop: Arc<AtomicBool>, paused: impl Fn() -> bool, error_log: PathBuf) {
    let mut state = Session::new();
    let mut was_down = false;
    while !stop.load(Ordering::Relaxed) {
        let cfg = get_cfg();
        let down = unsafe { GetAsyncKeyState(cfg.vk as i32) } as u16 & 0x8000 != 0;
        if down && !was_down && !paused() {
            config::emit(Event::Busy(true));
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| on_hotkey(&mut state, &cfg)));
            let tone = match result {
                Ok(Ok(tone)) => tone,
                Ok(Err(e)) => {
                    let blocked = e.contains("(os error 5)");
                    config::log(&if blocked { store::explain(&e, Some(&cfg.out), &cfg) } else { format!("Не получилось: {e}") }, "fail");
                    TONE_FAIL
                }
                Err(panic) => {
                    let text = panic.downcast_ref::<String>().cloned().or_else(|| panic.downcast_ref::<&str>().map(|s| s.to_string())).unwrap_or_default();
                    let _ = std::fs::OpenOptions::new().create(true).append(true).open(&error_log).and_then(|mut f| {
                        use std::io::Write;
                        writeln!(f, "{}\n{text}\n", chrono::Local::now())
                    });
                    config::log(&format!("Ошибка программы, подробности в {}", error_log.display()), "fail");
                    state = Session::new();
                    TONE_FAIL
                }
            };
            config::emit(Event::Busy(false));
            play(tone, &cfg);
        }
        was_down = down;
        std::thread::sleep(POLL);
    }
}
