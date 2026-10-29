import argparse
import base64
import json
import os
import socket
import sys
import threading
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
RECENT = 300

INJECT = r"""
(() => {
  if (window.__snapline) return "ready";
  const talk = /говорит|кричит|шепч|^\s*\*|^\s*>|\(\(/;
  const flat = s => s.replace(/\s*\n\s*/g, " ").trim();
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
  window.__snapline = {
    box: null,
    looked: 0,
    seen: new WeakSet(),
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
    drain() {
      const box = this.find();
      if (!box) return null;
      const out = [];
      for (const c of box.children) {
        if (this.seen.has(c)) continue;
        this.seen.add(c);
        const text = flat(c.innerText || c.textContent || "");
        if (text) out.push(text);
      }
      return out;
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
    direct = [t for t in found if mark in t.get("url", "")]
    if direct:
        return Page(direct[0]["webSocketDebuggerUrl"]), None, direct[0]["url"]
    for t in found:
        page = Page(t["webSocketDebuggerUrl"])
        try:
            context = page.find_context(mark)
        except (RuntimeError, KeyError):
            context = None
        if context is not None:
            return page, context, t["url"]
        page.ws.close()
    raise LookupError(f"FiveM запущен, но страницы {mark} нет: зайди на сервер")


def fresh(batch, recent):
    if len(batch) < 3:
        return batch
    tail = list(recent)
    for k in range(min(len(batch), len(tail)), 0, -1):
        if batch[:k] == tail[-k:]:
            return batch[k:]
    return batch


class Log:
    def __init__(self, folder):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)

    def write(self, lines):
        now = datetime.now()
        path = self.folder / f"{now:%Y-%m-%d}.txt"
        with open(path, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(f"[{now:%H:%M:%S}] {line}\n")
                print(f"[{now:%H:%M:%S}] {line}", flush=True)

    def dump(self, info, url):
        path = self.folder / "dom.html"
        path.write_text(f"<!-- {url}\n{info.get('path')} -->\n{info.get('html') or ''}", encoding="utf-8")
        return path


def say(msg):
    print(f"-- {msg}", flush=True)


def run(port, mark, folder, stop, report=say):
    log = Log(folder)
    recent = deque(maxlen=RECENT)
    total, last = 0, None
    while not stop.is_set():
        try:
            page, context, url = attach(port, mark)
        except (OSError, ConnectionError, RuntimeError, ValueError, LookupError) as e:
            status = str(e) if isinstance(e, LookupError) else "Жду FiveM: зайди в игру"
            if status != last:
                report(status)
                last = status
            stop.wait(RETRY_S)
            continue
        report(f"Подключился к {mark}, ищу чат")
        last, found = None, False
        try:
            while not stop.is_set():
                lines = page.evaluate("window.__snapline ? window.__snapline.drain() : false", context)
                if lines is False:
                    page.evaluate(INJECT, context)
                    found = False
                    continue
                if lines is None:
                    if last != "box":
                        report("Чат пока не найден: напиши что-нибудь в игре, чтобы появились строки")
                        last = "box"
                elif not found:
                    found = True
                    info = page.evaluate("window.__snapline.dump()", context)
                    log.dump(info, url)
                    report(f"Чат найден, пишу. Строк в логе: {total}")
                if lines:
                    new = fresh(lines, recent)
                    recent.extend(new)
                    if new:
                        log.write(new)
                        total += len(new)
                        report(f"Чат найден, пишу. Строк в логе: {total}")
                stop.wait(POLL_S)
        except (OSError, ConnectionError, RuntimeError, ValueError) as e:
            report(f"Связь потеряна ({e}), переподключаюсь")
            last = None
            stop.wait(RETRY_S)
        finally:
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
