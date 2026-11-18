use std::path::{Path, PathBuf};
use std::sync::mpsc::Sender;
use std::sync::OnceLock;

use image::RgbImage;
use windows::Win32::Foundation::{HANDLE, HGLOBAL, HWND, LPARAM, LRESULT, POINT, WPARAM};
use windows::Win32::Graphics::Dwm::{DwmExtendFrameIntoClientArea, DwmSetWindowAttribute};
use windows::Win32::Networking::WinInet::{
    INTERNET_OPTION_CONNECT_TIMEOUT, INTERNET_OPTION_RECEIVE_TIMEOUT, INTERNET_OPTION_SEND_TIMEOUT, INTERNET_OPTION_URL,
    InternetCloseHandle, InternetOpenUrlW, InternetOpenW, InternetQueryOptionW, InternetSetOptionW,
};
use windows::Win32::System::Com::CoInitialize;
use windows::Win32::System::DataExchange::{CloseClipboard, EmptyClipboard, OpenClipboard, SetClipboardData};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::Foundation::GlobalFree;
use windows::Win32::System::Memory::{GMEM_MOVEABLE, GlobalAlloc, GlobalLock, GlobalUnlock};
use windows::Win32::System::Threading::CreateMutexW;
use windows::Win32::UI::Controls::MARGINS;
use windows::Win32::UI::Shell::{
    FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_NOERRORUI, FOF_SILENT, ILCreateFromPathW, ILFree, NIF_ICON, NIF_INFO,
    NIF_MESSAGE, NIF_TIP, NIIF_INFO, NIM_ADD, NIM_DELETE, NIM_MODIFY, NOTIFYICONDATAW, SHFILEOPSTRUCTW, SHFileOperationW,
    SHOpenFolderAndSelectItems, ShellExecuteW, Shell_NotifyIconW,
};
use windows::Win32::UI::WindowsAndMessaging::{
    AppendMenuW, CreateIconFromResourceEx, CreatePopupMenu, CreateWindowExW, DefWindowProcW, DestroyMenu, DispatchMessageW,
    GetCursorPos, GetForegroundWindow, GetMessageW, HICON, LR_DEFAULTCOLOR, MF_SEPARATOR, MF_STRING, MSG, PostMessageW,
    RegisterClassW, RegisterWindowMessageW, SW_SHOWNORMAL, SetForegroundWindow, TPM_NONOTIFY, TPM_RETURNCMD, TPM_RIGHTBUTTON,
    TrackPopupMenu, TranslateMessage, WINDOW_EX_STYLE, WM_APP, WM_LBUTTONDBLCLK, WM_LBUTTONUP, WM_RBUTTONUP, WNDCLASSW, WS_POPUP,
};
use windows::core::{HSTRING, PCWSTR, w};

const CF_DIB: u32 = 8;
pub const HWND_BROADCAST: isize = 0xFFFF;

pub fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

pub fn show_msg() -> u32 {
    static ID: OnceLock<u32> = OnceLock::new();
    *ID.get_or_init(|| unsafe { RegisterWindowMessageW(w!("Snapline.Show")) })
}

pub fn already_running() -> bool {
    unsafe {
        let handle = CreateMutexW(None, false, w!("Local\\Snapline.SingleInstance"));
        let taken = windows::Win32::Foundation::GetLastError() == windows::Win32::Foundation::ERROR_ALREADY_EXISTS;
        if let Ok(h) = handle {
            std::mem::forget(h);
        }
        taken
    }
}

pub fn wake_other() {
    unsafe {
        let _ = PostMessageW(Some(HWND(HWND_BROADCAST as *mut _)), show_msg(), WPARAM(0), LPARAM(0));
    }
}

pub static TEST_RECYCLE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

pub fn recycle(paths: &[PathBuf]) -> Result<(), String> {
    if TEST_RECYCLE.load(std::sync::atomic::Ordering::Relaxed) {
        for p in paths {
            let _ = std::fs::remove_file(p);
        }
        return Ok(());
    }
    let list: Vec<String> = paths.iter().filter(|p| p.exists()).filter_map(|p| p.canonicalize().ok())
        .map(|p| p.to_string_lossy().trim_start_matches(r"\\?\").to_string()).collect();
    if list.is_empty() {
        return Ok(());
    }
    let mut from: Vec<u16> = Vec::new();
    for p in &list {
        from.extend(p.encode_utf16());
        from.push(0);
    }
    from.push(0);
    let mut op = SHFILEOPSTRUCTW {
        wFunc: FO_DELETE,
        pFrom: PCWSTR(from.as_ptr()),
        fFlags: (FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI).0 as u16,
        ..Default::default()
    };
    let code = unsafe { SHFileOperationW(&mut op) };
    if code != 0 || op.fAnyOperationsAborted.as_bool() {
        return Err(format!("Windows не убрал файлы в корзину, код {code:#x}"));
    }
    Ok(())
}

pub fn show_file(path: &Path) -> Result<(), String> {
    unsafe {
        let _ = CoInitialize(None);
        let full = path.canonicalize().map_err(|e| e.to_string())?;
        let text = full.to_string_lossy().trim_start_matches(r"\\?\").to_string();
        let item = ILCreateFromPathW(&HSTRING::from(text.as_str()));
        if item.is_null() {
            return Err(format!("Windows не нашёл {}", path.display()));
        }
        let result = SHOpenFolderAndSelectItems(item, None, 0);
        ILFree(Some(item));
        result.map_err(|e| format!("проводник не открылся: {e}"))
    }
}

pub fn open(target: &str) {
    unsafe {
        ShellExecuteW(None, w!("open"), &HSTRING::from(target), PCWSTR::null(), PCWSTR::null(), SW_SHOWNORMAL);
    }
}

pub fn open_folder(out: &Path, file: Option<&Path>) {
    let _ = std::fs::create_dir_all(out);
    if let Some(f) = file.filter(|f| f.exists()) {
        if show_file(f).is_ok() {
            return;
        }
        let _ = std::process::Command::new("explorer").arg(format!("/select,{}", f.display())).spawn();
        return;
    }
    open(&out.to_string_lossy());
}

pub fn copy_image(img: &RgbImage) -> Result<(), String> {
    let (w, h) = img.dimensions();
    let stride = (w * 3).div_ceil(4) * 4;
    let mut data = Vec::with_capacity(40 + (stride * h) as usize);
    for v in [40u32, w, h.wrapping_neg()] {
        data.extend_from_slice(&v.to_le_bytes());
    }
    data.truncate(4);
    data.extend_from_slice(&(w as i32).to_le_bytes());
    data.extend_from_slice(&(h as i32).to_le_bytes());
    data.extend_from_slice(&1u16.to_le_bytes());
    data.extend_from_slice(&24u16.to_le_bytes());
    data.extend_from_slice(&[0u8; 24]);
    for y in (0..h).rev() {
        let start = data.len();
        for x in 0..w {
            let p = img.get_pixel(x, y);
            data.extend_from_slice(&[p[2], p[1], p[0]]);
        }
        data.resize(start + stride as usize, 0);
    }
    unsafe {
        let handle = GlobalAlloc(GMEM_MOVEABLE, data.len()).map_err(|_| "не хватило памяти для буфера обмена".to_string())?;
        let ptr = GlobalLock(handle);
        std::ptr::copy_nonoverlapping(data.as_ptr(), ptr as *mut u8, data.len());
        let _ = GlobalUnlock(handle);
        let mut opened = false;
        for _ in 0..10 {
            if OpenClipboard(None).is_ok() {
                opened = true;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        if !opened {
            let _ = GlobalFree(Some(handle));
            return Err("буфер обмена занят другой программой".into());
        }
        let _ = EmptyClipboard();
        let set = SetClipboardData(CF_DIB, Some(HANDLE(handle.0)));
        let _ = CloseClipboard();
        if set.is_err() {
            let _ = GlobalFree(Some(HGLOBAL(handle.0)));
            return Err("Windows не принял картинку".into());
        }
    }
    Ok(())
}

pub fn version_key(version: &str) -> Vec<u64> {
    version.split(|c: char| !c.is_ascii_digit()).filter(|s| !s.is_empty()).filter_map(|s| s.parse().ok()).collect()
}

pub fn final_url(url: &str) -> Result<String, String> {
    unsafe {
        let agent = HSTRING::from(format!("Snapline/{}", engine::config::VERSION));
        let session = InternetOpenW(&agent, 0, PCWSTR::null(), PCWSTR::null(), 0);
        if session.is_null() {
            return Err("WinINet не открылся".into());
        }
        let limit: u32 = 5000;
        for option in [INTERNET_OPTION_CONNECT_TIMEOUT, INTERNET_OPTION_SEND_TIMEOUT, INTERNET_OPTION_RECEIVE_TIMEOUT] {
            let _ = InternetSetOptionW(Some(session), option, Some(&limit as *const u32 as *const _), 4);
        }
        let headers: Vec<u16> = "Cache-Control: no-cache\r\n".encode_utf16().collect();
        let handle = InternetOpenUrlW(session, &HSTRING::from(url), Some(&headers), 0x8408_0000, None);
        if handle.is_null() {
            let _ = InternetCloseHandle(session);
            return Err(format!("{url} не открылся"));
        }
        let mut buf = vec![0u16; 2048];
        let mut size = (buf.len() * 2) as u32;
        let ok = InternetQueryOptionW(Some(handle), INTERNET_OPTION_URL, Some(buf.as_mut_ptr() as *mut _), &mut size);
        let _ = InternetCloseHandle(handle);
        let _ = InternetCloseHandle(session);
        ok.map_err(|e| format!("адрес ответа не прочитан: {e}"))?;
        let n = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
        Ok(String::from_utf16_lossy(&buf[..n]))
    }
}

pub fn latest_release() -> Option<(String, String)> {
    let url = final_url(engine::config::RELEASES).ok()?;
    let tag = url.rsplit_once("/releases/tag/")?.1.trim_start_matches('v').to_string();
    if !tag.chars().all(|c| c.is_ascii_digit() || c == '.') || tag.is_empty() {
        return None;
    }
    (version_key(&tag) > version_key(engine::config::VERSION)).then_some((tag, url))
}

pub fn foreground_is(hwnd: isize) -> bool {
    unsafe { GetForegroundWindow().0 as isize == hwnd && hwnd != 0 }
}

pub fn raise(hwnd: isize) {
    unsafe {
        let _ = SetForegroundWindow(HWND(hwnd as *mut _));
    }
}

pub fn frame_window(hwnd: isize) {
    unsafe {
        let h = HWND(hwnd as *mut _);
        for (attr, value) in [(20u32, 1i32), (33, 2), (34, 0x0026201E)] {
            let _ = DwmSetWindowAttribute(h, windows::Win32::Graphics::Dwm::DWMWINDOWATTRIBUTE(attr as i32),
                                          &value as *const i32 as *const _, 4);
        }
        let margins = MARGINS { cxLeftWidth: 0, cxRightWidth: 0, cyTopHeight: 1, cyBottomHeight: 0 };
        let _ = DwmExtendFrameIntoClientArea(h, &margins);
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum TrayEvent {
    Show,
    Folder,
    Quit,
}

const WM_TRAY: u32 = WM_APP + 1;
const BALLOON_CLICK: u32 = 0x0405;
static BALLOON_ICON: std::sync::Mutex<isize> = std::sync::Mutex::new(0);
static TRAY_TX: OnceLock<std::sync::Mutex<Option<(Sender<TrayEvent>, eframe::egui::Context)>>> = OnceLock::new();

fn tray_send(e: TrayEvent) {
    if let Some(Some((tx, ctx))) = TRAY_TX.get().map(|m| m.lock().unwrap().clone()) {
        let _ = tx.send(e);
        ctx.request_repaint();
    }
}

fn icon_handle(png: &[u8], size: i32) -> HICON {
    unsafe { CreateIconFromResourceEx(png, true, 0x0003_0000, size, size, LR_DEFAULTCOLOR).unwrap_or_default() }
}

fn notify_data(hwnd: HWND, icon: HICON) -> NOTIFYICONDATAW {
    let mut data = NOTIFYICONDATAW {
        cbSize: std::mem::size_of::<NOTIFYICONDATAW>() as u32,
        hWnd: hwnd,
        uID: 1,
        uFlags: NIF_ICON | NIF_MESSAGE | NIF_TIP,
        uCallbackMessage: WM_TRAY,
        hIcon: icon,
        ..Default::default()
    };
    for (i, c) in "Snapline".encode_utf16().enumerate() {
        data.szTip[i] = c;
    }
    data
}

struct TrayState {
    hwnd: HWND,
    icon: HICON,
    on: bool,
}

static TRAY: OnceLock<std::sync::Mutex<Option<TrayState>>> = OnceLock::new();

fn tray_state() -> &'static std::sync::Mutex<Option<TrayState>> {
    TRAY.get_or_init(|| std::sync::Mutex::new(None))
}

unsafe impl Send for TrayState {}

unsafe extern "system" fn tray_proc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    let taskbar = unsafe { RegisterWindowMessageW(w!("TaskbarCreated")) };
    if msg == show_msg() {
        tray_send(TrayEvent::Show);
        return LRESULT(0);
    }
    if msg == taskbar {
        if let Some(state) = tray_state().lock().unwrap().as_mut() {
            if state.on {
                let data = notify_data(state.hwnd, state.icon);
                unsafe {
                    let _ = Shell_NotifyIconW(NIM_ADD, &data);
                }
            }
        }
        return LRESULT(0);
    }
    if msg == WM_TRAY {
        let event = (lp.0 & 0xFFFF) as u32;
        if event == WM_LBUTTONUP || event == WM_LBUTTONDBLCLK || event == BALLOON_CLICK {
            tray_send(TrayEvent::Show);
        } else if event == WM_RBUTTONUP {
            unsafe {
                let menu = CreatePopupMenu().unwrap_or_default();
                let _ = AppendMenuW(menu, MF_STRING, 1, w!("Открыть Snapline"));
                let _ = AppendMenuW(menu, MF_STRING, 2, w!("Папка со СС"));
                let _ = AppendMenuW(menu, MF_SEPARATOR, 0, PCWSTR::null());
                let _ = AppendMenuW(menu, MF_STRING, 4, w!("Выход"));
                let mut point = POINT::default();
                let _ = GetCursorPos(&mut point);
                let _ = SetForegroundWindow(hwnd);
                let pick = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON, point.x, point.y, None, hwnd, None);
                let _ = PostMessageW(Some(hwnd), 0, WPARAM(0), LPARAM(0));
                let _ = DestroyMenu(menu);
                match pick.0 {
                    1 => tray_send(TrayEvent::Show),
                    2 => tray_send(TrayEvent::Folder),
                    4 => tray_send(TrayEvent::Quit),
                    _ => {}
                }
            }
        }
        return LRESULT(0);
    }
    unsafe { DefWindowProcW(hwnd, msg, wp, lp) }
}

pub fn start_tray(tx: Sender<TrayEvent>, ctx: eframe::egui::Context, png: Vec<u8>, size: i32) {
    TRAY_TX.get_or_init(|| std::sync::Mutex::new(None)).lock().unwrap().replace((tx, ctx));
    let (ready_tx, ready_rx) = std::sync::mpsc::channel::<()>();
    std::thread::spawn(move || unsafe {
        let instance = GetModuleHandleW(None).unwrap_or_default();
        let class = w!("SnaplineTray");
        let wc = WNDCLASSW { lpfnWndProc: Some(tray_proc), hInstance: instance.into(), lpszClassName: class, ..Default::default() };
        RegisterClassW(&wc);
        let Ok(hwnd) = CreateWindowExW(WINDOW_EX_STYLE(0), class, w!("Snapline"), WS_POPUP, 0, 0, 0, 0, None, None,
                                       Some(instance.into()), None) else { return };
        let _ = windows::Win32::UI::WindowsAndMessaging::ChangeWindowMessageFilterEx(
            hwnd, show_msg(), windows::Win32::UI::WindowsAndMessaging::MSGFLT_ALLOW, None);
        tray_state().lock().unwrap().replace(TrayState { hwnd, icon: icon_handle(&png, size), on: false });
        let _ = ready_tx.send(());
        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    });
    let _ = ready_rx.recv();
}

pub fn tray_show(on: bool) {
    if let Some(state) = tray_state().lock().unwrap().as_mut() {
        if state.on == on {
            return;
        }
        let data = notify_data(state.hwnd, state.icon);
        unsafe {
            let _ = Shell_NotifyIconW(if on { NIM_ADD } else { NIM_DELETE }, &data);
        }
        state.on = on;
    }
}

pub fn tray_on() -> bool {
    tray_state().lock().unwrap().as_ref().is_some_and(|s| s.on)
}

pub fn tray_tell(title: &str, text: &str) {
    if let Some(state) = tray_state().lock().unwrap().as_ref() {
        if !state.on {
            return;
        }
        let mut data = notify_data(state.hwnd, state.icon);
        data.uFlags |= NIF_INFO;
        data.dwInfoFlags = NIIF_INFO;
        for (i, c) in title.encode_utf16().take(63).enumerate() {
            data.szInfoTitle[i] = c;
        }
        for (i, c) in text.encode_utf16().take(255).enumerate() {
            data.szInfo[i] = c;
        }
        unsafe {
            let _ = Shell_NotifyIconW(NIM_MODIFY, &data);
        }
    }
}

pub fn tray_tell_picture(title: &str, text: &str, png: Option<&[u8]>) {
    use windows::Win32::UI::Shell::{NIIF_LARGE_ICON, NIIF_USER};
    use windows::Win32::UI::WindowsAndMessaging::DestroyIcon;
    let Some(png) = png else { return tray_tell(title, text) };
    if let Some(state) = tray_state().lock().unwrap().as_ref() {
        if !state.on {
            return;
        }
        let picture = icon_handle(png, 96);
        let mut data = notify_data(state.hwnd, state.icon);
        data.uFlags |= NIF_INFO;
        data.dwInfoFlags = NIIF_USER | NIIF_LARGE_ICON;
        data.hBalloonIcon = picture;
        for (i, c) in title.encode_utf16().take(63).enumerate() {
            data.szInfoTitle[i] = c;
        }
        for (i, c) in text.encode_utf16().take(255).enumerate() {
            data.szInfo[i] = c;
        }
        unsafe {
            let _ = Shell_NotifyIconW(NIM_MODIFY, &data);
        }
        let mut last = BALLOON_ICON.lock().unwrap();
        if *last != 0 {
            unsafe {
                let _ = DestroyIcon(HICON(*last as *mut _));
            }
        }
        *last = picture.0 as isize;
    }
}

pub fn ghost(hwnd: isize) {
    use windows::Win32::UI::WindowsAndMessaging::{GWL_EXSTYLE, GetWindowLongPtrW, LWA_ALPHA, SetLayeredWindowAttributes, SetWindowLongPtrW,
                                                  WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW};
    unsafe {
        let h = HWND(hwnd as *mut _);
        let style = GetWindowLongPtrW(h, GWL_EXSTYLE);
        SetWindowLongPtrW(h, GWL_EXSTYLE, style | (WS_EX_LAYERED.0 | WS_EX_TOOLWINDOW.0 | WS_EX_NOACTIVATE.0) as isize);
        let _ = SetLayeredWindowAttributes(h, windows::Win32::Foundation::COLORREF(0), 0, LWA_ALPHA);
    }
}

pub fn clipboard_image() -> Option<image::RgbaImage> {
    use windows::Win32::System::DataExchange::{GetClipboardData, IsClipboardFormatAvailable};
    use windows::Win32::System::Memory::GlobalSize;
    use windows::Win32::UI::Shell::{DragQueryFileW, HDROP};
    unsafe {
        OpenClipboard(None).ok()?;
        let mut out = None;
        if IsClipboardFormatAvailable(CF_DIB).is_ok() {
            if let Ok(h) = GetClipboardData(CF_DIB) {
                let g = HGLOBAL(h.0);
                let ptr = GlobalLock(g) as *const u8;
                if !ptr.is_null() {
                    let size = GlobalSize(g);
                    let data = std::slice::from_raw_parts(ptr, size).to_vec();
                    let _ = GlobalUnlock(g);
                    out = dib(&data);
                }
            }
        }
        if out.is_none() && IsClipboardFormatAvailable(15).is_ok() {
            if let Ok(h) = GetClipboardData(15) {
                let drop = HDROP(h.0);
                let n = DragQueryFileW(drop, 0xFFFF_FFFF, None);
                for i in 0..n {
                    let mut buf = vec![0u16; 1024];
                    let len = DragQueryFileW(drop, i, Some(&mut buf)) as usize;
                    let path = String::from_utf16_lossy(&buf[..len]);
                    if let Ok(img) = image::open(&path) {
                        out = Some(img.to_rgba8());
                        break;
                    }
                }
            }
        }
        let _ = CloseClipboard();
        out
    }
}

fn dib(data: &[u8]) -> Option<image::RgbaImage> {
    let u32_at = |o: usize| data.get(o..o + 4).map(|b| u32::from_le_bytes(b.try_into().unwrap()));
    let header = u32_at(0)? as usize;
    let w = u32_at(4)? as i32;
    let h = u32_at(8)? as i32;
    let bits = u16::from_le_bytes(data.get(14..16)?.try_into().ok()?);
    let compression = u32_at(16)?;
    let colors = u32_at(32)? as usize;
    if w <= 0 || h == 0 || !(bits == 24 || bits == 32) {
        return None;
    }
    let masks = if compression == 3 && header == 40 { 12 } else { 0 };
    let start = header + masks + colors * 4;
    let (w, top_down, h) = (w as usize, h < 0, h.unsigned_abs() as usize);
    let stride = (w * bits as usize / 8).div_ceil(4) * 4;
    let mut img = image::RgbaImage::new(w as u32, h as u32);
    let mut any_alpha = false;
    for y in 0..h {
        let src = start + (if top_down { y } else { h - 1 - y }) * stride;
        for x in 0..w {
            let o = src + x * bits as usize / 8;
            let px = data.get(o..o + bits as usize / 8)?;
            let a = if bits == 32 { px[3] } else { 255 };
            any_alpha |= bits == 32 && a != 0;
            img.put_pixel(x as u32, y as u32, image::Rgba([px[2], px[1], px[0], a]));
        }
    }
    if bits == 32 && !any_alpha {
        for p in img.pixels_mut() {
            p[3] = 255;
        }
    }
    Some(img)
}
