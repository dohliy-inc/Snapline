use std::collections::VecDeque;
use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::io::{Read, Seek, SeekFrom, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use regex::Regex;
use serde_json::{Value, json};

use crate::chatlog::{self, MATCH, Parts, RECENT};

const POLL: Duration = Duration::from_millis(500);
const RETRY: Duration = Duration::from_secs(3);
const TIMEOUT: Duration = Duration::from_secs(5);
const RESCAN: Duration = Duration::from_secs(10);

pub const INJECT: &str = r##"
(() => {
  if (window.__snaplog && window.__snaplog.v === 3) return "ready";
  const talk = /говорит|кричит|шепч|^\s*\*|^\s*>|\(\(/;
  const flat = s => s.replace(/\s*\n\s*/g, " ").trim();
  const runs = el => {
    const out = [];
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const s = n.nodeValue.replace(/\s+/g, " ");
      if (!s || !n.parentElement) continue;
      const c = getComputedStyle(n.parentElement).color;
      if (out.length && out[out.length - 1][1] === c) out[out.length - 1][0] += s;
      else out.push([s, c]);
    }
    return out;
  };
  const score = el => {
    let n = 0;
    for (const c of el.children) if (talk.test(c.textContent || "")) n++;
    return n;
  };
  const path = el => {
    const parts = [];
    for (; el && el !== document.body; el = el.parentElement) {
      const cls = typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\s+/).join(".") : "";
      parts.unshift(el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + cls);
    }
    return parts.join(" > ");
  };
  window.__snaplog = {
    v: 3,
    box: null,
    looked: 0,
    token: null,
    nodes: [],
    texts: new WeakMap(),
    find() {
      if (this.box && this.box.isConnected) return this.box;
      if (Date.now() - this.looked < 3000) return null;
      this.looked = Date.now();
      let best = null, top = 1;
      for (const el of document.querySelectorAll("body *")) {
        if (el.children.length < 2) continue;
        const s = score(el);
        if (s > top) { best = el; top = s; }
      }
      this.box = best;
      return best;
    },
    drain(token, have) {
      const box = this.find();
      if (!box) return null;
      const nodes = [], old = this.nodes;
      let same = token === this.token && have === old.length;
      for (const c of box.children) {
        const raw = c.textContent || "";
        let hit = this.texts.get(c);
        if (!hit || hit.raw !== raw) {
          hit = {raw, text: flat(c.innerText || raw)};
          this.texts.set(c, hit);
          if (nodes.length < have) same = false;
        }
        if (!hit.text) continue;
        if (nodes.length < have && old[nodes.length] !== c) same = false;
        nodes.push(c);
      }
      const base = same && nodes.length >= have ? have : 0;
      this.token = token;
      this.nodes = nodes;
      return {base, lines: nodes.slice(base).map(c => ({text: this.texts.get(c).text, parts: runs(c)}))};
    },
    dump() {
      this.looked = 0;
      const box = this.find();
      return box ? {path: path(box), html: box.outerHTML.slice(0, 300000)}
                 : {path: null, html: document.body.outerHTML.slice(0, 600000)};
    },
  };
  return "injected";
})()
"##;

fn random_bytes(n: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(n);
    while out.len() < n {
        let mut h = RandomState::new().build_hasher();
        h.write_u128(Instant::now().elapsed().as_nanos() ^ out.len() as u128);
        out.extend_from_slice(&h.finish().to_le_bytes());
    }
    out.truncate(n);
    out
}

fn base64(data: &[u8]) -> String {
    const A: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for chunk in data.chunks(3) {
        let b = [chunk[0], *chunk.get(1).unwrap_or(&0), *chunk.get(2).unwrap_or(&0)];
        let n = (b[0] as u32) << 16 | (b[1] as u32) << 8 | b[2] as u32;
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(A[(n >> (18 - 6 * i) & 63) as usize] as char);
            } else {
                out.push('=');
            }
        }
    }
    out
}

pub type Fail = String;

fn fail<E: std::fmt::Display>(e: E) -> Fail {
    e.to_string()
}

struct Socket {
    sock: TcpStream,
    buf: Vec<u8>,
}

impl Socket {
    fn open(url: &str) -> Result<Socket, Fail> {
        let re = Regex::new(r"^wss?://([^/:]+):(\d+)(/.*)?$").unwrap();
        let m = re.captures(url).ok_or_else(|| format!("непонятный адрес отладчика: {url}"))?;
        let host = &m[1];
        let port: u16 = m[2].parse().map_err(fail)?;
        let target = m.get(3).map(|p| p.as_str()).unwrap_or("/");
        let addr: SocketAddr = format!("{}:{port}", if host == "localhost" { "127.0.0.1" } else { host }).parse().map_err(fail)?;
        let sock = TcpStream::connect_timeout(&addr, TIMEOUT).map_err(fail)?;
        sock.set_read_timeout(Some(TIMEOUT)).map_err(fail)?;
        let key = base64(&random_bytes(16));
        let mut s = Socket { sock, buf: Vec::new() };
        let head = format!("GET {target} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\
                            Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n");
        s.sock.write_all(head.as_bytes()).map_err(fail)?;
        while !s.buf.windows(4).any(|w| w == b"\r\n\r\n") {
            s.fill()?;
        }
        let end = s.buf.windows(4).position(|w| w == b"\r\n\r\n").unwrap() + 4;
        let status = String::from_utf8_lossy(&s.buf[..end]).lines().next().unwrap_or("").to_string();
        s.buf.drain(..end);
        if !status.contains(" 101 ") {
            return Err(format!("отладчик не принял подключение: {status}"));
        }
        Ok(s)
    }

    fn fill(&mut self) -> Result<(), Fail> {
        let mut chunk = [0u8; 65536];
        let n = self.sock.read(&mut chunk).map_err(fail)?;
        if n == 0 {
            return Err("отладчик закрыл соединение".into());
        }
        self.buf.extend_from_slice(&chunk[..n]);
        Ok(())
    }

    fn take(&mut self, n: usize) -> Result<Vec<u8>, Fail> {
        while self.buf.len() < n {
            self.fill()?;
        }
        Ok(self.buf.drain(..n).collect())
    }

    fn frame(&mut self, opcode: u8, data: &[u8]) -> Result<(), Fail> {
        let mask = random_bytes(4);
        let n = data.len();
        let mut out = vec![0x80 | opcode];
        if n < 126 {
            out.push(0x80 | n as u8);
        } else if n < 65536 {
            out.push(0x80 | 126);
            out.extend_from_slice(&(n as u16).to_be_bytes());
        } else {
            out.push(0x80 | 127);
            out.extend_from_slice(&(n as u64).to_be_bytes());
        }
        out.extend_from_slice(&mask);
        out.extend(data.iter().enumerate().map(|(i, b)| b ^ mask[i & 3]));
        self.sock.write_all(&out).map_err(fail)
    }

    fn send(&mut self, text: &str) -> Result<(), Fail> {
        self.frame(0x1, text.as_bytes())
    }

    fn recv(&mut self) -> Result<String, Fail> {
        let mut parts = Vec::new();
        loop {
            let head = self.take(2)?;
            let (b0, b1) = (head[0], head[1]);
            let mut n = (b1 & 0x7F) as usize;
            if n == 126 {
                let v = self.take(2)?;
                n = u16::from_be_bytes([v[0], v[1]]) as usize;
            } else if n == 127 {
                let v = self.take(8)?;
                n = u64::from_be_bytes(v.try_into().unwrap()) as usize;
            }
            let mask = if b1 & 0x80 != 0 { Some(self.take(4)?) } else { None };
            let mut data = self.take(n)?;
            if let Some(m) = mask {
                for (i, b) in data.iter_mut().enumerate() {
                    *b ^= m[i & 3];
                }
            }
            match b0 & 0x0F {
                0x8 => return Err("отладчик закрыл соединение".into()),
                0x9 => self.frame(0xA, &data)?,
                0x0..=0x2 => {
                    parts.extend(data);
                    if b0 & 0x80 != 0 {
                        return Ok(String::from_utf8_lossy(&parts).into_owned());
                    }
                }
                _ => {}
            }
        }
    }
}

pub struct Page {
    ws: Socket,
    next: u64,
    contexts: Vec<Value>,
}

impl Page {
    fn open(url: &str) -> Result<Page, Fail> {
        Ok(Page { ws: Socket::open(url)?, next: 0, contexts: vec![] })
    }

    fn call(&mut self, method: &str, params: Value) -> Result<Value, Fail> {
        self.next += 1;
        self.ws.send(&json!({"id": self.next, "method": method, "params": params}).to_string())?;
        loop {
            let msg: Value = serde_json::from_str(&self.ws.recv()?).map_err(fail)?;
            if msg.get("id").and_then(|v| v.as_u64()) == Some(self.next) {
                if let Some(e) = msg.get("error") {
                    return Err(format!("{method}: {}", e.get("message").and_then(|m| m.as_str()).unwrap_or("")));
                }
                return Ok(msg.get("result").cloned().unwrap_or(Value::Null));
            }
            if msg.get("method").and_then(|m| m.as_str()) == Some("Runtime.executionContextCreated") {
                if let Some(c) = msg.pointer("/params/context") {
                    self.contexts.push(c.clone());
                }
            }
        }
    }

    fn evaluate(&mut self, expr: &str, context: Option<i64>) -> Result<Value, Fail> {
        let mut params = json!({"expression": expr, "returnByValue": true});
        if let Some(c) = context {
            params["contextId"] = json!(c);
        }
        let result = self.call("Runtime.evaluate", params)?;
        if let Some(d) = result.get("exceptionDetails") {
            return Err(format!("скрипт в странице упал: {}", d.get("text").and_then(|t| t.as_str()).unwrap_or("")));
        }
        Ok(result.pointer("/result/value").cloned().unwrap_or(Value::Null))
    }

    fn find_context(&mut self, mark: &str) -> Result<Option<i64>, Fail> {
        let tree = self.call("Page.getFrameTree", json!({}))?;
        let mut frames = Vec::new();
        let mut stack = vec![tree.get("frameTree").cloned().unwrap_or(Value::Null)];
        while let Some(node) = stack.pop() {
            if node.pointer("/frame/url").and_then(|u| u.as_str()).is_some_and(|u| owns(u, mark)) {
                if let Some(id) = node.pointer("/frame/id").and_then(|v| v.as_str()) {
                    frames.push(id.to_string());
                }
            }
            if let Some(kids) = node.get("childFrames").and_then(|v| v.as_array()) {
                stack.extend(kids.iter().cloned());
            }
        }
        if frames.is_empty() {
            return Ok(None);
        }
        self.contexts.clear();
        self.call("Runtime.enable", json!({}))?;
        self.call("Runtime.disable", json!({}))?;
        let hits: Vec<i64> = self
            .contexts
            .iter()
            .filter(|c| {
                let frame = c.pointer("/auxData/frameId").and_then(|v| v.as_str()).unwrap_or("");
                frames.iter().any(|f| f == frame) && c.pointer("/auxData/isDefault").and_then(|v| v.as_bool()) == Some(true)
            })
            .filter_map(|c| c.get("id").and_then(|v| v.as_i64()))
            .collect();
        Ok(hits.last().copied())
    }
}

const HEAD_END: &[u8] = b"\r\n\r\n";

fn http_get(port: u16, path: &str) -> Result<String, Fail> {
    let addr: SocketAddr = format!("127.0.0.1:{port}").parse().map_err(fail)?;
    let mut sock = TcpStream::connect_timeout(&addr, Duration::from_secs(2)).map_err(fail)?;
    sock.set_read_timeout(Some(Duration::from_secs(2))).map_err(fail)?;
    sock.write_all(format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n").as_bytes()).map_err(fail)?;
    let mut raw = Vec::new();
    let mut chunk = [0u8; 65536];
    let done = |raw: &[u8]| -> bool {
        let Some(end) = raw.windows(4).position(|w| w == HEAD_END) else { return false };
        let head = String::from_utf8_lossy(&raw[..end]).to_lowercase();
        let body = &raw[end + 4..];
        if let Some(n) = head.lines().find_map(|l| l.strip_prefix("content-length:")).and_then(|v| v.trim().parse::<usize>().ok()) {
            return body.len() >= n;
        }
        head.contains("transfer-encoding: chunked") && body.ends_with(b"0\r\n\r\n")
    };
    while !done(&raw) {
        match sock.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => raw.extend_from_slice(&chunk[..n]),
            Err(e) if raw.is_empty() => return Err(fail(e)),
            Err(_) => break,
        }
    }
    let end = raw.windows(4).position(|w| w == HEAD_END).ok_or("пустой ответ отладчика")? + 4;
    let head = String::from_utf8_lossy(&raw[..end]).to_lowercase();
    let body = &raw[end..];
    if !head.contains("transfer-encoding: chunked") {
        return Ok(String::from_utf8_lossy(body).into_owned());
    }
    let mut out = Vec::new();
    let mut rest = body;
    while let Some(line_end) = rest.windows(2).position(|w| w == b"\r\n") {
        let size = usize::from_str_radix(String::from_utf8_lossy(&rest[..line_end]).trim(), 16).unwrap_or(0);
        if size == 0 {
            break;
        }
        let start = line_end + 2;
        out.extend_from_slice(&rest[start..(start + size).min(rest.len())]);
        rest = &rest[(start + size + 2).min(rest.len())..];
    }
    Ok(String::from_utf8_lossy(&out).into_owned())
}

pub struct Target {
    page: Page,
    context: Option<i64>,
    url: String,
}

pub fn owns(url: &str, mark: &str) -> bool {
    let Some(rest) = url.split("//").nth(1) else { return false };
    if url.starts_with("file:") {
        return rest.split(['/', '?', '#']).any(|part| part == mark);
    }
    rest.split(['/', '?', '#', ':']).next() == Some(mark)
}

pub fn attach(port: u16, mark: &str) -> Result<Vec<Target>, (bool, Fail)> {
    let list: Value = serde_json::from_str(&http_get(port, "/json/list").map_err(|e| (false, e))?).map_err(|e| (false, e.to_string()))?;
    let mut found: Vec<Value> = list.as_array().cloned().unwrap_or_default()
        .into_iter().filter(|t| t.get("webSocketDebuggerUrl").is_some()).collect();
    let url_of = |t: &Value| t.get("url").and_then(|u| u.as_str()).unwrap_or("").to_string();
    found.sort_by_key(|t| owns(&url_of(t), mark));
    let mut pages = Vec::new();
    for t in found {
        let url = url_of(&t);
        let Ok(mut page) = Page::open(t["webSocketDebuggerUrl"].as_str().unwrap_or("")) else { continue };
        let direct = owns(&url, mark);
        let context = if direct { None } else {
            match page.find_context(mark) {
                Ok(c) => c,
                Err(_) => continue,
            }
        };
        if context.is_none() && !direct {
            continue;
        }
        pages.push(Target { page, context, url });
    }
    if pages.is_empty() {
        return Err((true, format!("FiveM запущен, но страницы {mark} нет: зайди на сервер")));
    }
    Ok(pages)
}

fn drain(target: &mut Target, token: &str, have: usize) -> Result<Option<Value>, Fail> {
    let expr = format!("window.__snaplog && window.__snaplog.v === 3 ? window.__snaplog.drain({}, {have}) : false",
                       Value::String(token.to_string()));
    let mut got = target.page.evaluate(&expr, target.context)?;
    if got == Value::Bool(false) {
        target.page.evaluate(INJECT, target.context)?;
        got = target.page.evaluate(&expr, target.context)?;
    }
    Ok(if got.is_null() { None } else { Some(got) })
}

fn look(targets: &mut [&mut Target]) -> Vec<(Value, String)> {
    targets
        .iter_mut()
        .map(|t| {
            let view = t.page.evaluate("window.__snaplog && window.__snaplog.dump()", t.context)
                .unwrap_or_else(|e| json!({"path": format!("не прочиталось: {e}")}));
            (if view.is_null() { json!({}) } else { view }, t.url.clone())
        })
        .collect()
}

pub fn parts(line: &Value) -> Parts {
    let text = line.get("text").and_then(|t| t.as_str()).unwrap_or("");
    let mut out: Parts = line
        .get("parts")
        .and_then(|p| p.as_array())
        .map(|a| a.iter().filter_map(|p| {
            let t = p.get(0)?.as_str()?.to_string();
            let c = p.get(1).map(|c| c.as_str().map(|s| s.to_string()).unwrap_or_else(|| c.to_string()))?;
            if t.is_empty() { None } else { Some((t, chatlog::hex_color(&c))) }
        }).collect())
        .unwrap_or_default();
    let flat = |s: &str| s.split_whitespace().collect::<Vec<_>>().join(" ");
    let joined: String = out.iter().map(|(t, _)| t.as_str()).collect();
    if out.is_empty() || flat(&joined) != flat(text) {
        return chatlog::guess_parts(text);
    }
    let last = out.len() - 1;
    out[0].0 = out[0].0.trim_start().to_string();
    out[last].0 = out[last].0.trim_end().to_string();
    out.retain(|(t, _)| !t.is_empty());
    out
}

pub struct Log {
    folder: PathBuf,
    status_path: PathBuf,
}

impl Log {
    pub fn new(folder: &Path) -> Log {
        let _ = std::fs::create_dir_all(folder);
        let status_path = folder.join("status.log");
        if std::fs::metadata(&status_path).map(|m| m.len() > chatlog::STATUS_MAX).unwrap_or(false) {
            if let Ok(text) = std::fs::read(&status_path) {
                let text = String::from_utf8_lossy(&text);
                let lines: Vec<&str> = text.lines().collect();
                let keep = &lines[lines.len().saturating_sub(2000)..];
                let _ = std::fs::write(&status_path, keep.join("\n") + "\n");
            }
        }
        Log { folder: folder.to_path_buf(), status_path }
    }

    pub fn tail(&self, n: usize) -> Vec<String> {
        let re = Regex::new(r"^\[\d\d:\d\d:\d\d\] (.*)$").unwrap();
        let day = Regex::new(r"^\d{4}-\d\d-\d\d\.txt$").unwrap();
        let mut days: Vec<PathBuf> = std::fs::read_dir(&self.folder).into_iter().flatten().filter_map(|e| e.ok())
            .map(|e| e.path()).filter(|p| p.file_name().is_some_and(|f| day.is_match(&f.to_string_lossy()))).collect();
        days.sort();
        let Some(last) = days.last() else { return vec![] };
        let Ok(mut f) = std::fs::File::open(last) else { return vec![] };
        let size = f.seek(SeekFrom::End(0)).unwrap_or(0);
        let _ = f.seek(SeekFrom::Start(size.saturating_sub(chatlog::TAIL_BYTES)));
        let mut raw = Vec::new();
        let _ = f.read_to_end(&mut raw);
        let text = String::from_utf8_lossy(&raw);
        let lines: Vec<&str> = text.lines().collect();
        lines[lines.len().saturating_sub(n)..].iter().filter_map(|l| re.captures(l).map(|m| m[1].to_string())).collect()
    }

    pub fn write(&self, lines: &[Value]) {
        let now = chrono::Local::now();
        let stamp = now.format("%H:%M:%S").to_string();
        let day = now.format("%Y-%m-%d").to_string();
        let mut txt = String::new();
        let mut jsonl = String::new();
        for line in lines {
            let text = line.get("text").and_then(|t| t.as_str()).unwrap_or("");
            txt.push_str(&format!("[{stamp}] {text}\n"));
            let p: Vec<Value> = parts(line).into_iter().map(|(t, c)| json!([t, c])).collect();
            jsonl.push_str(&json!({"time": stamp, "parts": p}).to_string());
            jsonl.push('\n');
        }
        for (ext, body) in [("txt", txt), ("jsonl", jsonl)] {
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(self.folder.join(format!("{day}.{ext}"))) {
                let _ = f.write_all(body.as_bytes());
            }
        }
    }

    pub fn status(&self, msg: &str) {
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&self.status_path) {
            let _ = writeln!(f, "[{}] {msg}", chrono::Local::now().format("%Y-%m-%d %H:%M:%S"));
        }
    }

    pub fn dump(&self, views: &[(Value, String)]) -> PathBuf {
        let path = self.folder.join("dom.html");
        let text: Vec<String> = views
            .iter()
            .map(|(info, url)| {
                let p = info.get("path").map(|v| v.as_str().map(|s| s.to_string()).unwrap_or_else(|| v.to_string())).unwrap_or("None".into());
                format!("<!-- {url}\n{p} -->\n{}", info.get("html").and_then(|h| h.as_str()).unwrap_or(""))
            })
            .collect();
        let _ = std::fs::write(&path, text.join("\n"));
        path
    }
}

fn wait(stop: &AtomicBool, d: Duration) {
    let end = Instant::now() + d;
    while Instant::now() < end && !stop.load(Ordering::Relaxed) {
        std::thread::sleep(Duration::from_millis(50));
    }
}

pub fn run(port: u16, mark: &str, folder: &Path, stop: Arc<AtomicBool>, report: &dyn Fn(&str)) {
    let log = Log::new(folder);
    let mut recent: VecDeque<String> = log.tail(RECENT).into_iter().collect();
    let mut total = 0usize;
    let mut last: Option<String> = None;
    let note = |status: &str, last: &mut Option<String>| {
        if last.as_deref() != Some(status) {
            report(status);
            log.status(status);
            *last = Some(status.to_string());
        }
    };
    while !stop.load(Ordering::Relaxed) {
        let mut pages = match attach(port, mark) {
            Ok(p) => p,
            Err((lookup, e)) => {
                note(if lookup { &e } else { "Жду FiveM: зайди в игру" }, &mut last);
                wait(&stop, RETRY);
                continue;
            }
        };
        let token: String = random_bytes(6).iter().map(|b| format!("{b:02x}")).collect();
        let mut chat: Option<usize> = None;
        let since = Instant::now();
        let mut seen: Option<Vec<String>> = None;
        let outcome: Result<(), Fail> = (|| {
            while !stop.load(Ordering::Relaxed) {
                let got = match chat {
                    None => {
                        let mut hit = None;
                        for (i, t) in pages.iter_mut().enumerate() {
                            if let Some(g) = drain(t, &token, 0)? {
                                hit = Some((i, g));
                                break;
                            }
                        }
                        let Some((i, g)) = hit else {
                            note("Чат пока не найден: напиши что-нибудь в игре, чтобы появились строки", &mut last);
                            if since.elapsed() > RESCAN {
                                let mut all: Vec<&mut Target> = pages.iter_mut().collect();
                                log.dump(&look(&mut all));
                                return Ok(());
                            }
                            wait(&stop, POLL);
                            continue;
                        };
                        let keep = pages.swap_remove(i);
                        pages.clear();
                        pages.push(keep);
                        chat = Some(0);
                        let mut one: Vec<&mut Target> = pages.iter_mut().collect();
                        log.dump(&look(&mut one));
                        log.status(&format!("Страница чата: {}", pages[0].url));
                        note(&format!("Чат найден, пишу. Строк в логе: {total}"), &mut last);
                        Some(g)
                    }
                    Some(_) => drain(&mut pages[0], &token, seen.as_ref().map(|s| s.len()).unwrap_or(0))?,
                };
                let Some(got) = got else {
                    wait(&stop, POLL);
                    continue;
                };
                let lines: Vec<Value> = got.get("lines").and_then(|l| l.as_array()).cloned().unwrap_or_default();
                let texts: Vec<String> = lines.iter().map(|l| l.get("text").and_then(|t| t.as_str()).unwrap_or("").to_string()).collect();
                let base = got.get("base").and_then(|b| b.as_u64()).unwrap_or(0);
                let new = match &seen {
                    None => {
                        let known: Vec<String> = recent.iter().cloned().collect();
                        let n = chatlog::fresh(&texts, &known[known.len().saturating_sub(MATCH)..]);
                        seen = Some(texts.clone());
                        n
                    }
                    Some(prev) if base > 0 => {
                        let mut all = prev.clone();
                        all.extend(texts.iter().cloned());
                        seen = Some(all);
                        texts.clone()
                    }
                    Some(prev) => {
                        let n = chatlog::grown(prev, &texts);
                        seen = Some(texts.clone());
                        n
                    }
                };
                if !new.is_empty() {
                    log.write(&lines[lines.len() - new.len()..]);
                    for t in &new {
                        if recent.len() >= RECENT {
                            recent.pop_front();
                        }
                        recent.push_back(t.clone());
                    }
                    total += new.len();
                    report(&format!("Чат найден, пишу. Строк в логе: {total}"));
                }
                wait(&stop, POLL);
            }
            Ok(())
        })();
        if let Err(e) = outcome {
            note(&format!("Связь потеряна ({e}), переподключаюсь"), &mut last);
            wait(&stop, RETRY);
        }
    }
}
