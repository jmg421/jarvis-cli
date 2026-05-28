"""Tests for the jarvis_cli.dashboard HTTP server."""

import json
import threading
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis_cli import dashboard


# ── helpers ─────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_state(tmp_path, monkeypatch):
    """Redirect dashboard's state files into a tmp dir."""
    queue = tmp_path / "queue.json"
    completed = tmp_path / "completed.json"
    pid = tmp_path / "daemon.pid"
    state = tmp_path / "state.json"

    monkeypatch.setattr(dashboard, "QUEUE_FILE", queue)
    monkeypatch.setattr(dashboard, "COMPLETED_FILE", completed)
    monkeypatch.setattr(dashboard, "DAEMON_PID_FILE", pid)
    monkeypatch.setattr(dashboard, "LOOP_STATE", state)
    return {"queue": queue, "completed": completed, "pid": pid, "state": state}


@pytest.fixture
def server(fake_state):
    """Start a dashboard server on an ephemeral port."""
    srv = dashboard.make_server(host="127.0.0.1", port=0)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    # give it a moment to bind
    time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def _get(url, path):
    with urllib.request.urlopen(url + path, timeout=5) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


# ── data-loader unit tests ──────────────────────────────────────────────────

def test_load_queue_missing_returns_empty(fake_state):
    assert dashboard.load_queue() == []


def test_load_queue_reads_json(fake_state):
    fake_state["queue"].write_text(json.dumps([{"task": "a"}, {"task": "b"}]))
    assert dashboard.load_queue() == [{"task": "a"}, {"task": "b"}]


def test_load_queue_handles_bad_json(fake_state):
    fake_state["queue"].write_text("not json {{{")
    assert dashboard.load_queue() == []


def test_load_completed_reads_json(fake_state):
    fake_state["completed"].write_text(json.dumps([{"task": "x", "status": "done"}]))
    assert dashboard.load_completed() == [{"task": "x", "status": "done"}]


def test_daemon_running_no_pidfile(fake_state):
    assert dashboard.daemon_running() is False


def test_daemon_running_dead_pid(fake_state):
    # PID 1 is init — os.kill(1, 0) requires root, so use a clearly-dead one.
    fake_state["pid"].write_text("999999")
    assert dashboard.daemon_running() is False


def test_daemon_running_garbage_pidfile(fake_state):
    fake_state["pid"].write_text("not-a-pid")
    assert dashboard.daemon_running() is False


def test_load_status_shape(fake_state):
    fake_state["queue"].write_text(json.dumps([{"task": "a"}]))
    fake_state["completed"].write_text(json.dumps([{"task": "x"}, {"task": "y"}]))
    fake_state["state"].write_text(json.dumps({"iteration": 7, "next_priority": "foo"}))

    s = dashboard.load_status()
    assert s["queue_count"] == 1
    assert s["completed_count"] == 2
    assert s["iteration"] == 7
    assert s["next_priority"] == "foo"
    assert s["daemon_running"] is False


# ── HTTP integration tests ──────────────────────────────────────────────────

def test_index_serves_html(server):
    status, ctype, body = _get(server, "/")
    assert status == 200
    assert "text/html" in ctype
    assert b"Jarvis CLI" in body
    assert b"/api/status" in body  # JS fetches it


def test_healthz(server):
    status, _, body = _get(server, "/healthz")
    assert status == 200
    assert body == b"ok"


def test_api_queue_empty(server):
    status, ctype, body = _get(server, "/api/queue")
    assert status == 200
    assert "application/json" in ctype
    assert json.loads(body) == []


def test_api_queue_populated(server, fake_state):
    fake_state["queue"].write_text(json.dumps([{"task": "build dashboard"}]))
    _, _, body = _get(server, "/api/queue")
    assert json.loads(body) == [{"task": "build dashboard"}]


def test_api_completed(server, fake_state):
    fake_state["completed"].write_text(
        json.dumps([{"task": "ship it", "status": "done"}])
    )
    _, _, body = _get(server, "/api/completed")
    assert json.loads(body) == [{"task": "ship it", "status": "done"}]


def test_api_status(server, fake_state):
    fake_state["queue"].write_text(json.dumps([{"task": "a"}, {"task": "b"}]))
    fake_state["completed"].write_text(json.dumps([{"task": "c"}]))
    fake_state["state"].write_text(json.dumps({"iteration": 3}))

    _, _, body = _get(server, "/api/status")
    data = json.loads(body)
    assert data["queue_count"] == 2
    assert data["completed_count"] == 1
    assert data["iteration"] == 3
    assert data["daemon_running"] is False


def test_unknown_route_returns_404(server):
    try:
        urllib.request.urlopen(server + "/nope", timeout=5)
        pytest.fail("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404
        body = json.loads(e.read())
        assert body["error"] == "not found"


def test_default_port_constant():
    assert dashboard.DEFAULT_PORT == 7294
