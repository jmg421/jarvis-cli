#!/usr/bin/env python3
"""Tests for daemon functionality."""

import json
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the functions we're testing
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from jarvis_cli.main import (
    enqueue_task, load_queue, save_queue, log_completed_task,
    daemon_status, _format_elapsed_time, QUEUE_FILE, COMPLETED_FILE, DAEMON_PID_FILE
)


@pytest.fixture
def temp_config_dir(monkeypatch, tmp_path):
    """Create a temporary config directory for testing."""
    config_dir = tmp_path / ".jarvis_cli"
    config_dir.mkdir()
    
    # Patch the global file paths
    monkeypatch.setattr('jarvis_cli.main.QUEUE_FILE', config_dir / "queue.json")
    monkeypatch.setattr('jarvis_cli.main.COMPLETED_FILE', config_dir / "completed.json")
    monkeypatch.setattr('jarvis_cli.main.DAEMON_PID_FILE', config_dir / "daemon.pid")
    
    return config_dir


def test_enqueue_task(temp_config_dir, monkeypatch, capsys):
    """Test enqueuing a task."""
    # Patch the file paths for this test
    queue_file = temp_config_dir / "queue.json"
    monkeypatch.setattr('jarvis_cli.main.QUEUE_FILE', queue_file)
    
    # Enqueue a task
    task = "test task"
    enqueue_task(task)
    
    # Check the queue file was created
    assert queue_file.exists()
    
    # Check the task was added
    queue = json.loads(queue_file.read_text())
    assert len(queue) == 1
    assert queue[0]["task"] == task
    assert queue[0]["status"] == "queued"
    assert "id" in queue[0]
    assert "created_at" in queue[0]
    
    # Check output
    captured = capsys.readouterr()
    assert "Task queued:" in captured.out
    assert task in captured.out


def test_load_save_queue(temp_config_dir, monkeypatch):
    """Test loading and saving the queue."""
    queue_file = temp_config_dir / "queue.json"
    monkeypatch.setattr('jarvis_cli.main.QUEUE_FILE', queue_file)
    
    # Test loading empty queue
    queue = load_queue()
    assert queue == []
    
    # Test saving and loading queue
    test_queue = [
        {
            "id": str(uuid.uuid4()),
            "task": "test task",
            "created_at": datetime.now().isoformat(),
            "status": "queued"
        }
    ]
    save_queue(test_queue)
    
    loaded_queue = load_queue()
    assert loaded_queue == test_queue


def test_log_completed_task(temp_config_dir, monkeypatch):
    """Test logging a completed task."""
    completed_file = temp_config_dir / "completed.json"
    monkeypatch.setattr('jarvis_cli.main.COMPLETED_FILE', completed_file)
    
    task_entry = {
        "id": str(uuid.uuid4()),
        "task": "test task",
        "created_at": datetime.now().isoformat(),
        "status": "processing"
    }
    
    response = "Task completed successfully"
    elapsed_time = 5.5  # 5.5 seconds
    log_completed_task(task_entry, response, elapsed_time=elapsed_time)
    
    # Check the completed file was created
    assert completed_file.exists()
    
    # Check the task was logged
    completed = json.loads(completed_file.read_text())
    assert len(completed) == 1
    assert completed[0]["task"] == task_entry["task"]
    assert completed[0]["response"] == response
    assert completed[0]["status"] == "completed"
    assert completed[0]["elapsed_time"] == elapsed_time
    assert "completed_at" in completed[0]
    

def test_log_failed_task(temp_config_dir, monkeypatch):
    """Test logging a failed task."""
    completed_file = temp_config_dir / "completed.json"
    monkeypatch.setattr('jarvis_cli.main.COMPLETED_FILE', completed_file)
    
    task_entry = {
        "id": str(uuid.uuid4()),
        "task": "test task",
        "created_at": datetime.now().isoformat(),
        "status": "processing"
    }
    
    error = "Task failed with error"
    elapsed_time = 2.3  # 2.3 seconds
    log_completed_task(task_entry, None, error, elapsed_time)
    
    # Check the task was logged as failed
    completed = json.loads(completed_file.read_text())
    assert len(completed) == 1
    assert completed[0]["error"] == error
    assert completed[0]["status"] == "failed"
    assert completed[0]["elapsed_time"] == elapsed_time


@patch('jarvis_cli.main.os.kill')
def test_daemon_status_stopped(mock_kill, temp_config_dir, monkeypatch, capsys):
    """Test daemon status when daemon is stopped."""
    # Patch file paths
    monkeypatch.setattr('jarvis_cli.main.QUEUE_FILE', temp_config_dir / "queue.json")
    monkeypatch.setattr('jarvis_cli.main.COMPLETED_FILE', temp_config_dir / "completed.json")
    monkeypatch.setattr('jarvis_cli.main.DAEMON_PID_FILE', temp_config_dir / "daemon.pid")
    
    # Mock os.kill to raise ProcessLookupError (process not found)
    mock_kill.side_effect = ProcessLookupError()
    
    daemon_status()
    
    captured = capsys.readouterr()
    assert "🔴 Stopped" in captured.out
    assert "Queue:" in captured.out


@patch('jarvis_cli.main.os.kill')
def test_daemon_status_running(mock_kill, temp_config_dir, monkeypatch, capsys):
    """Test daemon status when daemon is running."""
    # Patch file paths
    pid_file = temp_config_dir / "daemon.pid"
    monkeypatch.setattr('jarvis_cli.main.DAEMON_PID_FILE', pid_file)
    monkeypatch.setattr('jarvis_cli.main.QUEUE_FILE', temp_config_dir / "queue.json")
    monkeypatch.setattr('jarvis_cli.main.COMPLETED_FILE', temp_config_dir / "completed.json")
    
    # Create a fake PID file
    pid_file.write_text("12345")
    
    # Mock os.kill to not raise an exception (process exists)
    mock_kill.return_value = None
    
    daemon_status()
    
    captured = capsys.readouterr()
    assert "🟢 Running" in captured.out
    assert "PID: 12345" in captured.out


def test_queue_with_tasks(temp_config_dir, monkeypatch, capsys):
    """Test daemon status with tasks in queue."""
    queue_file = temp_config_dir / "queue.json"
    monkeypatch.setattr('jarvis_cli.main.QUEUE_FILE', queue_file)
    monkeypatch.setattr('jarvis_cli.main.COMPLETED_FILE', temp_config_dir / "completed.json")
    monkeypatch.setattr('jarvis_cli.main.DAEMON_PID_FILE', temp_config_dir / "daemon.pid")
    
    # Create a queue with some tasks
    queue = [
        {
            "id": str(uuid.uuid4()),
            "task": "first task",
            "created_at": datetime.now().isoformat(),
            "status": "queued"
        },
        {
            "id": str(uuid.uuid4()),
            "task": "second task",
            "created_at": datetime.now().isoformat(),
            "status": "processing"
        }
    ]
    queue_file.write_text(json.dumps(queue, indent=2))
    
    daemon_status()
    
    captured = capsys.readouterr()
    assert "📝 Queued: 1" in captured.out
    assert "⚡ Processing: 1" in captured.out
    assert "first task" in captured.out


def test_format_elapsed_time():
    """Test the elapsed time formatting function."""
    # Test milliseconds
    assert _format_elapsed_time(0.5) == "500ms"
    assert _format_elapsed_time(0.123) == "123ms"
    
    # Test seconds
    assert _format_elapsed_time(1.0) == "1.0s"
    assert _format_elapsed_time(5.7) == "5.7s"
    assert _format_elapsed_time(59.9) == "59.9s"
    
    # Test minutes
    assert _format_elapsed_time(60) == "1m0s"
    assert _format_elapsed_time(125) == "2m5s"
    assert _format_elapsed_time(3599) == "59m59s"
    
    # Test hours
    assert _format_elapsed_time(3600) == "1h0m"
    assert _format_elapsed_time(3665) == "1h1m"
    assert _format_elapsed_time(7325) == "2h2m"


if __name__ == "__main__":
    pytest.main([__file__])