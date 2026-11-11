import argparse
import base64
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime

import core

PORT = 13172
RESOURCE = "lspr"
POLL_S = 0.5
RETRY_S = 3.0
TIMEOUT_S = 5.0
RECENT = 1000
RESCAN_S = 10.0
STATUS_MAX = 512 * 1024
TAIL_BYTES = 1024 * 1024
MATCH = 200

INJECT = r"""
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
"""


class Socket:
    def __init__(self, url):
        u = urllib.parse.urlsplit(url)
        self.sock = socket.create_connection((u.hostname, u.port), TIMEOUT_S)
        key = base64.b64encode(os.urandom(16)).decode()
        target = u.path + ("?" + u.query if u.query else "")
        self.sock.sendall((f"GET {target} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
                          .encode())
        self.buf = bytearray()
        while b"\r\n\r\n" not in self.buf:
            self.fill()
        end = self.buf.index(b"\r\n\r\n") + 4
        status = bytes(self.buf[:end]).split(b"\r\n", 1)[0]
        del self.buf[:end]
        if b" 101 " not in status:
            raise ConnectionError(f"отладчик не принял подключение: {status.decode(errors='replace')}")

    def fill(self):
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError("отладчик закрыл соединение")
        self.buf += chunk

    def take(self, n):
        while len(self.buf) < n:
            self.fill()
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def frame(self, opcode, data):
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            head = bytes([0x80 | opcode, 0x80 | n])
        elif n < 65536:
            head = bytes([0x80 | opcode, 0x80 | 126]) + n.to_bytes(2, "big")
        else:
            head = bytes([0x80 | opcode, 0x80 | 127]) + n.to_bytes(8, "big")
        self.sock.sendall(head + mask + bytes(b ^ mask[i & 3] for i, b in enumerate(data)))

    def send(self, text):
        self.frame(0x1, text.encode())

    def recv(self):
        parts = []
        while True:
            b0, b1 = self.take(2)
            n = b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self.take(2), "big")
            elif n == 127:
                n = int.from_bytes(self.take(8), "big")
            mask = self.take(4) if b1 & 0x80 else None
            data = self.take(n)
            if mask:
                data = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise ConnectionError("отладчик закрыл соединение")
            if opcode == 0x9:
                self.frame(0xA, data)
            elif opcode in (0x0, 0x1, 0x2):
                parts.append(data)
                if b0 & 0x80:
                    return b"".join(parts).decode("utf-8", errors="replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Page:
    def __init__(self, url):
        self.ws = Socket(url)
        self.next = 0
        self.contexts = []

    def call(self, method, **params):
        self.next += 1
        self.ws.send(json.dumps({"id": self.next, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.next:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg["result"]
            if msg.get("method") == "Runtime.executionContextCreated":
                self.contexts.append(msg["params"]["context"])

    def evaluate(self, expr, context=None):
        params = {"expression": expr, "returnByValue": True}
        if context is not None:
            params["contextId"] = context
        result = self.call("Runtime.evaluate", **params)
        if "exceptionDetails" in result:
            raise RuntimeError(f"скрипт в странице упал: {result['exceptionDetails'].get('text')}")
        return result["result"].get("value")

    def find_context(self, mark):
        frames, stack = set(), [self.call("Page.getFrameTree")["frameTree"]]
        while stack:
            node = stack.pop()
            if mark in node["frame"].get("url", ""):
                frames.add(node["frame"]["id"])
            stack.extend(node.get("childFrames", []))
        if not frames:
            return None
        self.contexts = []
        self.call("Runtime.enable")
        self.call("Runtime.disable")
        hits = [c["id"] for c in self.contexts
                if c.get("auxData", {}).get("frameId") in frames and c.get("auxData", {}).get("isDefault")]
        return hits[-1] if hits else None


def targets(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
        return json.load(r)


def attach(port, mark):
    found = [t for t in targets(port) if t.get("webSocketDebuggerUrl")]
    pages = []
    for t in sorted(found, key=lambda t: mark in t.get("url", "")):
        try:
            page = Page(t["webSocketDebuggerUrl"])
        except OSError:
            continue
        try:
            context = None if mark in t.get("url", "") else page.find_context(mark)
        except (OSError, RuntimeError, KeyError, ValueError):
            page.ws.close()
            continue
        if context is None and mark not in t.get("url", ""):
            page.ws.close()
            continue
        pages.append((page, context, t["url"]))
    if not pages:
        raise LookupError(f"FiveM запущен, но страницы {mark} нет: зайди на сервер")
    return pages


def drain(target, token, have=0):
    page, context, _ = target
    expr = (f"window.__snaplog && window.__snaplog.v === 3 ? "
            f"window.__snaplog.drain({json.dumps(token)}, {int(have)}) : false")
    got = page.evaluate(expr, context)
    if got is False:
        page.evaluate(INJECT, context)
        got = page.evaluate(expr, context)
    return got


def fresh(batch, known):
    tail = list(known)[-MATCH:]
    for j in range(len(batch) - 1, -1, -1) if tail else ():
        k = min(j + 1, len(tail))
        if batch[j] == tail[-1] and batch[j + 1 - k:j + 1] == tail[-k:]:
            return batch[j + 1:]
    return batch


def grown(prev, cur):
    return cur[len(prev):] if cur[:len(prev)] == prev else fresh(cur, prev)


class Log:
    def __init__(self, folder):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.status_path = folder / "status.log"
        try:
            if self.status_path.stat().st_size > STATUS_MAX:
                keep = self.status_path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
                self.status_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except OSError:
            pass

    def tail(self, n):
        days = sorted(self.folder.glob("????-??-??.txt"))
        try:
            with open(days[-1], "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - TAIL_BYTES))
                lines = f.read().decode("utf-8", errors="replace").splitlines()[-n:]
        except (OSError, IndexError):
            return []
        return [m[1] for m in (re.fullmatch(r"\[\d\d:\d\d:\d\d\] (.*)", line) for line in lines) if m]

    def write(self, lines):
        now = datetime.now()
        stamp = f"{now:%H:%M:%S}"
        with open(self.folder / f"{now:%Y-%m-%d}.txt", "a", encoding="utf-8", errors="replace") as f:
            for line in lines:
                f.write(f"[{stamp}] {line['text']}\n")
                print(f"[{stamp}] {line['text']}", flush=True)
        with open(self.folder / f"{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8", errors="replace") as f:
            for line in lines:
                f.write(json.dumps({"time": stamp, "parts": parts(line)}, ensure_ascii=False) + "\n")

    def status(self, msg):
        try:
            with open(self.status_path, "a", encoding="utf-8", errors="replace") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
        except OSError:
            pass

    def dump(self, info, url):
        path = self.folder / "dom.html"
        path.write_text(f"<!-- {url}\n{info.get('path')} -->\n{info.get('html') or ''}", encoding="utf-8",
                        errors="replace")
        return path


def parts(line):
    out = [[text, core.hex_color(str(color))] for text, color in line.get("parts") or [] if text]
    flat = lambda text: re.sub(r"\s+", " ", text).strip()
    if not out or flat("".join(t for t, _ in out)) != flat(line["text"]):
        return core.guess_parts(line["text"])
    out[0][0], out[-1][0] = out[0][0].lstrip(), out[-1][0].rstrip()
    return [p for p in out if p[0]]


def say(msg):
    print(f"-- {msg}", flush=True)


def run(port, mark, folder, stop, report=say):
    log = Log(folder)
    recent = deque(log.tail(RECENT), maxlen=RECENT)
    total, last = 0, None

    def note(status):
        nonlocal last
        if status != last:
            report(status)
            log.status(status)
            last = status

    while not stop.is_set():
        try:
            pages = attach(port, mark)
        except (OSError, ConnectionError, RuntimeError, ValueError, LookupError) as e:
            note(str(e) if isinstance(e, LookupError) else "Жду FiveM: зайди в игру")
            stop.wait(RETRY_S)
            continue
        token, chat, since, seen = os.urandom(6).hex(), None, time.monotonic(), None
        try:
            while not stop.is_set():
                if chat is None:
                    for target in pages:
                        got = drain(target, token)
                        if got is not None:
                            chat = target
                            break
                    if chat is None:
                        note("Чат пока не найден: напиши что-нибудь в игре, чтобы появились строки")
                        if time.monotonic() - since > RESCAN_S:
                            break
                        stop.wait(POLL_S)
                        continue
                    for page, _, _ in pages:
                        if page is not chat[0]:
                            page.ws.close()
                    log.dump(chat[0].evaluate("window.__snaplog.dump()", chat[1]), chat[2])
                    log.status(f"Страница чата: {chat[2]}")
                    note(f"Чат найден, пишу. Строк в логе: {total}")
                else:
                    got = drain(chat, token, len(seen))
                if got is None:
                    stop.wait(POLL_S)
                    continue
                lines, texts = got["lines"], [line["text"] for line in got["lines"]]
                if seen is None:
                    new = fresh(texts, recent)
                    seen = texts
                elif got["base"]:
                    new = texts
                    seen = seen + texts
                else:
                    new = grown(seen, texts)
                    seen = texts
                if new:
                    log.write(lines[len(lines) - len(new):])
                    recent.extend(new)
                    total += len(new)
                    report(f"Чат найден, пишу. Строк в логе: {total}")
                stop.wait(POLL_S)
        except (OSError, ConnectionError, RuntimeError, ValueError) as e:
            note(f"Связь потеряна ({e}), переподключаюсь")
            stop.wait(RETRY_S)
        finally:
            for page, _, _ in pages:
                page.ws.close()


def main():
    parser = argparse.ArgumentParser(description="Тестовый чатлог Snapline через отладчик страниц FiveM")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--resource", default=RESOURCE)
    args = parser.parse_args()
    _, cfg = core.load_config()
    folder = cfg["out"] / "chatlog"
    say(f"Лог пишется в {folder}")
    try:
        run(args.port, f"cfx-nui-{args.resource}", folder, threading.Event())
    except KeyboardInterrupt:
        say("остановлено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
