use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

const EDGE: &str = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe";
const PORT: u16 = 9333;

const ROOT: &str = r##"<!DOCTYPE html><html><body><iframe src="cfx-nui-lspr/chat.html"></iframe><iframe src="cfx-nui-lspr_pool/sound.html"></iframe></body></html>"##;
const POOL: &str = r##"<!DOCTYPE html><html><body><audio></audio></body></html>"##;
const CHAT: &str = r##"<!DOCTYPE html><html><body><div id="box"></div><script>
const box = document.getElementById("box");
const lines = [
  ["Clyde Maddox говорит: Добро.", "#e6e6e6"],
  ["* Clyde Maddox закуривает сигарету", "#c2a2da"],
  ["Craig Rivers говорит: Ща я наберу Фланки.", "#e6e6e6"],
  ["(( Clyde Maddox: ахаха ))", "#afafaf"],
];
let k = 0;
function add() {
  const [text, color] = lines[k % lines.length];
  const row = document.createElement("span");
  row.className = "message-x";
  const font = document.createElement("font");
  font.style.color = color;
  font.textContent = text + " #" + k;
  row.appendChild(font);
  box.appendChild(row);
  k++;
}
add(); add();
setInterval(add, 300);
</script></body></html>"##;

struct Edge(Child);

impl Drop for Edge {
    fn drop(&mut self) {
        let _ = self.0.kill();
    }
}

#[test]
#[ignore]
fn worker_logs_a_live_page() {
    let work = std::env::temp_dir().join(format!("snapline_cdp_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&work);
    let site = work.join("site");
    for (dir, file, html) in [("cfx-nui-lspr", "chat.html", CHAT), ("cfx-nui-lspr_pool", "sound.html", POOL)] {
        std::fs::create_dir_all(site.join(dir)).unwrap();
        std::fs::write(site.join(dir).join(file), html).unwrap();
    }
    std::fs::write(site.join("root.html"), ROOT).unwrap();
    let url = format!("file:///{}", site.join("root.html").to_string_lossy().replace('\\', "/"));
    let _edge = Edge(
        Command::new(EDGE)
            .args(["--headless=new", "--disable-gpu", "--no-first-run", "--allow-file-access-from-files",
                   &format!("--remote-debugging-port={PORT}"), &format!("--user-data-dir={}", work.join("profile").display()), &url])
            .spawn()
            .expect("edge"),
    );
    std::thread::sleep(Duration::from_secs(3));
    if let Err((lookup, e)) = engine::cdp::attach(PORT, "cfx-nui-lspr") {
        eprintln!("attach failed (lookup {lookup}): {e}");
    }
    let folder: PathBuf = work.join("chatlog");
    let stop = Arc::new(AtomicBool::new(false));
    let notes = Arc::new(Mutex::new(Vec::<String>::new()));
    let worker = {
        let (stop, folder, notes) = (stop.clone(), folder.clone(), notes.clone());
        std::thread::spawn(move || {
            engine::cdp::run(PORT, "cfx-nui-lspr", &folder, stop, &|m| notes.lock().unwrap().push(m.to_string()))
        })
    };
    std::thread::sleep(Duration::from_secs(8));
    stop.store(true, Ordering::Relaxed);
    worker.join().unwrap();
    let day = chrono::Local::now().format("%Y-%m-%d").to_string();
    let txt = std::fs::read_to_string(folder.join(format!("{day}.txt"))).unwrap_or_default();
    let jsonl = std::fs::read_to_string(folder.join(format!("{day}.jsonl"))).unwrap_or_default();
    let notes = notes.lock().unwrap().clone();
    eprintln!("notes: {notes:?}\n{txt}");
    let numbers: Vec<u32> = txt.lines().filter_map(|l| l.rsplit('#').next()?.trim().parse().ok()).collect();
    assert!(numbers.len() >= 15, "too few lines: {}", numbers.len());
    assert!(numbers.windows(2).all(|w| w[1] == w[0] + 1), "lines skipped or repeated: {numbers:?}");
    assert!(jsonl.contains("#c2a2da") && jsonl.contains("#e6e6e6"), "colours missing: {jsonl}");
    assert!(notes.iter().any(|n| n.starts_with("Чат найден")), "{notes:?}");
    let _ = std::fs::remove_dir_all(&work);
}

#[test]
fn chat_frame_needs_the_exact_resource() {
    assert!(engine::cdp::owns("https://cfx-nui-lspr/html/index.html#/hud", "cfx-nui-lspr"));
    assert!(engine::cdp::owns("https://cfx-nui-lspr", "cfx-nui-lspr"));
    assert!(engine::cdp::owns("file:///C:/Temp/site/cfx-nui-lspr/chat.html", "cfx-nui-lspr"));
    assert!(!engine::cdp::owns("file:///C:/Temp/site/cfx-nui-lspr_pool/sound.html", "cfx-nui-lspr"));
    assert!(!engine::cdp::owns("https://cfx-nui-lspr_pool/client/html/sound.html", "cfx-nui-lspr"));
    assert!(!engine::cdp::owns("nui://lspr/html/posters/dui.html", "cfx-nui-lspr"));
}
