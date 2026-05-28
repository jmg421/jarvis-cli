"""
Jarvis CLI Dashboard — stdlib HTTP server for live queue & task status.

Routes:
  GET /              → HTML dashboard (auto-refreshing)
  GET /api/queue     → JSON list of pending tasks
  GET /api/completed → JSON list of completed tasks
  GET /api/status    → JSON summary {queue, completed, daemon_running, iteration}
  GET /healthz       → "ok"

Backed by the same JSON files used by main.py:
  ~/.jarvis_cli/queue.json
  ~/.jarvis_cli/completed.json
  ~/.jarvis_cli/daemon.pid
  ~/.jarvis_cli_state.json
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_PORT = 7294

QUEUE_FILE = Path.home() / ".jarvis_cli" / "queue.json"
COMPLETED_FILE = Path.home() / ".jarvis_cli" / "completed.json"
DAEMON_PID_FILE = Path.home() / ".jarvis_cli" / "daemon.pid"
LOOP_STATE = Path.home() / ".jarvis_cli_state.json"


# ── data loaders ────────────────────────────────────────────────────────────

def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def load_queue() -> list:
    data = _load_json(QUEUE_FILE, [])
    return data if isinstance(data, list) else []


def load_completed() -> list:
    data = _load_json(COMPLETED_FILE, [])
    return data if isinstance(data, list) else []


def daemon_running() -> bool:
    if not DAEMON_PID_FILE.exists():
        return False
    try:
        pid = int(DAEMON_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def load_status() -> dict:
    state = _load_json(LOOP_STATE, {})
    queue = load_queue()
    completed = load_completed()
    return {
        "queue_count": len(queue),
        "completed_count": len(completed),
        "daemon_running": daemon_running(),
        "iteration": state.get("iteration", 0) if isinstance(state, dict) else 0,
        "next_priority": state.get("next_priority") if isinstance(state, dict) else None,
    }


# ── HTML ────────────────────────────────────────────────────────────────────

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Jarvis CLI — Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root { color-scheme: dark; }
  body { font: 14px/1.5 -apple-system, BlinkMacSystemFont, "SF Mono", Menlo, monospace;
         background:#0b0f14; color:#d6e2ee; margin:0; padding:24px; }
  h1 { font-size:20px; margin:0 0 4px; color:#7fd1ff; }
  .sub { color:#6b7d8f; margin-bottom:24px; font-size:12px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
          gap:12px; margin-bottom:24px; }
  .card { background:#121821; border:1px solid #1e2a37; border-radius:8px;
          padding:14px 16px; }
  .card .label { color:#6b7d8f; font-size:11px; text-transform:uppercase;
                 letter-spacing:0.5px; }
  .card .value { font-size:22px; font-weight:600; color:#e8f1fb; margin-top:4px; }
  .ok { color:#7fd99a; } .off { color:#e07c7c; }
  section { margin-top:20px; }
  section h2 { font-size:13px; color:#9fb3c8; text-transform:uppercase;
               letter-spacing:0.6px; margin:0 0 8px; }
  ul { list-style:none; padding:0; margin:0; }
  li { background:#121821; border:1px solid #1e2a37; border-radius:6px;
       padding:10px 12px; margin-bottom:6px; font-size:13px; }
  li .meta { color:#6b7d8f; font-size:11px; margin-top:2px; }
  .empty { color:#6b7d8f; font-style:italic; padding:8px 0; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%;
         margin-right:6px; vertical-align:middle; }
  .dot.ok { background:#7fd99a; box-shadow:0 0 6px #7fd99a; }
  .dot.off { background:#e07c7c; }
  footer { margin-top:32px; color:#6b7d8f; font-size:11px; }
</style>
</head>
<body>
  <h1>Jarvis CLI — Dashboard</h1>
  <div class="sub">port 7294 · auto-refresh 2s</div>

  <div class="grid">
    <div class="card"><div class="label">Daemon</div>
      <div class="value" id="daemon">—</div></div>
    <div class="card"><div class="label">Queue</div>
      <div class="value" id="queue-count">—</div></div>
    <div class="card"><div class="label">Completed</div>
      <div class="value" id="completed-count">—</div></div>
    <div class="card"><div class="label">Iteration</div>
      <div class="value" id="iteration">—</div></div>
  </div>

  <section>
    <h2>Pending Queue</h2>
    <ul id="queue"></ul>
  </section>

  <section>
    <h2>Recently Completed</h2>
    <ul id="completed"></ul>
  </section>

  <footer>jarvis-cli · stdlib http.server</footer>

<script>
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}

async function tick(){
  try {
    const [s, q, c] = await Promise.all([
      fetch("/api/status").then(r=>r.json()),
      fetch("/api/queue").then(r=>r.json()),
      fetch("/api/completed").then(r=>r.json()),
    ]);
    const dot = s.daemon_running ? '<span class="dot ok"></span>' : '<span class="dot off"></span>';
    const word = s.daemon_running ? '<span class="ok">running</span>' : '<span class="off">stopped</span>';
    document.getElementById("daemon").innerHTML = dot + word;
    document.getElementById("queue-count").textContent = s.queue_count;
    document.getElementById("completed-count").textContent = s.completed_count;
    document.getElementById("iteration").textContent = s.iteration;

    const qList = document.getElementById("queue");
    qList.innerHTML = q.length ? q.map(t => {
      const task = esc(t.task || t.prompt || JSON.stringify(t));
      const id = esc(t.id || "");
      const ts = esc(t.enqueued_at || t.timestamp || "");
      return `<li>${task}<div class="meta">${id}${ts ? " · " + ts : ""}</div></li>`;
    }).join("") : '<div class="empty">queue is empty</div>';

    const cList = document.getElementById("completed");
    const recent = c.slice(-10).reverse();
    cList.innerHTML = recent.length ? recent.map(t => {
      const task = esc(t.task || t.prompt || JSON.stringify(t));
      const ts = esc(t.completed_at || t.timestamp || "");
      const status = esc(t.status || "done");
      return `<li>${task}<div class="meta">${status}${ts ? " · " + ts : ""}</div></li>`;
    }).join("") : '<div class="empty">no completed tasks yet</div>';
  } catch (e) {
    console.error(e);
  }
}
tick();
setInterval(tick, 2000);
</script>
</body>
</html>
"""


# ── HTTP handler ────────────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "JarvisDashboard/1.0"

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body: str, status: int = 200,
                   content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_text(INDEX_HTML, content_type="text/html; charset=utf-8")
        elif path == "/api/queue":
            self._send_json(load_queue())
        elif path == "/api/completed":
            self._send_json(load_completed())
        elif path == "/api/status":
            self._send_json(load_status())
        elif path == "/healthz":
            self._send_text("ok")
        else:
            self._send_json({"error": "not found", "path": path}, status=404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Quiet by default; honor JARVIS_DASHBOARD_VERBOSE=1.
        if os.environ.get("JARVIS_DASHBOARD_VERBOSE"):
            sys.stderr.write("[dashboard] " + (format % args) + "\n")


# ── server entrypoints ──────────────────────────────────────────────────────

def make_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), DashboardHandler)


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    server = make_server(host, port)
    url = f"http://{host}:{port}/"
    print(f"  Jarvis dashboard listening on {url}")
    print("  Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  dashboard stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
