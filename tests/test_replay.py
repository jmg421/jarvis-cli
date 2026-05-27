"""Tests for replay functionality."""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

from jarvis_cli.main import replay_last_task, _format_tool_input, _format_tool_result, COMPLETED_FILE


@pytest.fixture
def sample_completed_tasks():
    """Sample completed tasks with various tool calls."""
    return [
        {
            "id": "task1",
            "task": "Read a file",
            "created_at": "2023-01-01T10:00:00",
            "completed_at": "2023-01-01T10:00:05",
            "status": "completed",
            "tool_calls": [
                {
                    "name": "file_read",
                    "input": {"path": "test.txt", "limit": 10},
                    "result": "Hello\nWorld\nTest file content"
                }
            ],
            "elapsed_time": 5.2
        },
        {
            "id": "task2", 
            "task": "Write and patch files",
            "created_at": "2023-01-01T10:05:00",
            "completed_at": "2023-01-01T10:05:15",
            "status": "completed",
            "tool_calls": [
                {
                    "name": "file_write",
                    "input": {"path": "new.py", "content": "print('hello')\nprint('world')\n"},
                    "result": "File written successfully"
                },
                {
                    "name": "file_patch",
                    "input": {"path": "old.py", "old_str": "print('old')", "new_str": "print('new')"},
                    "result": "Patched successfully"
                },
                {
                    "name": "execute_bash",
                    "input": {"command": "ls -la", "working_dir": "/tmp"},
                    "result": "total 0\ndrwxr-xr-x  2 user  user  64 Jan  1 10:05 ."
                }
            ],
            "elapsed_time": 15.7
        },
        {
            "id": "task3",
            "task": "Failed task",
            "created_at": "2023-01-01T10:10:00", 
            "completed_at": "2023-01-01T10:10:02",
            "status": "failed",
            "error": "Some error occurred",
            "tool_calls": []
        }
    ]


def test_format_tool_input():
    """Test formatting of various tool inputs."""
    # file_read
    assert _format_tool_input("file_read", {"path": "test.txt"}) == "path='test.txt'"
    assert _format_tool_input("file_read", {"path": "test.txt", "limit": 10}) == "path='test.txt' limit=10"
    assert _format_tool_input("file_read", {"path": "test.txt", "offset": 5}) == "path='test.txt' offset=5"
    
    # file_write
    content = "print('hello')\nprint('world')"
    expected = "path='new.py' content='print('hello')\\nprint('world')' (2 lines)"
    assert _format_tool_input("file_write", {"path": "new.py", "content": content}) == expected
    
    # file_patch
    inp = {"path": "old.py", "old_str": "print('old')", "new_str": "print('new')"}
    assert _format_tool_input("file_patch", inp) == "path='old.py' old='print('old')...' new='print('new')...'"
    
    # execute_bash
    assert _format_tool_input("execute_bash", {"command": "ls -la"}) == "command='ls -la'"
    assert _format_tool_input("execute_bash", {"command": "ls", "working_dir": "/tmp"}) == "command='ls' (in /tmp)"
    
    # list_directory
    assert _format_tool_input("list_directory", {"path": "/tmp"}) == "path='/tmp' depth=1"
    assert _format_tool_input("list_directory", {"path": "/tmp", "depth": 3}) == "path='/tmp' depth=3"
    
    # glob_search
    assert _format_tool_input("glob_search", {"pattern": "*.py"}) == "pattern='*.py'"
    assert _format_tool_input("glob_search", {"pattern": "*.py", "path": "/src"}) == "pattern='*.py' in /src"
    
    # grep_search
    assert _format_tool_input("grep_search", {"pattern": "test"}) == "pattern='/test/'"
    inp = {"pattern": "test", "path": "/src", "include": "*.py"}
    expected = "pattern='/test/' path='/src' include='*.py'"
    assert _format_tool_input("grep_search", inp) == expected
    
    # web_search
    assert _format_tool_input("web_search", {"query": "python tutorial"}) == "query='python tutorial'"
    
    # web_fetch
    assert _format_tool_input("web_fetch", {"url": "https://example.com"}) == "url='https://example.com'"
    
    # symbol_search
    assert _format_tool_input("symbol_search", {"name": "main"}) == "name='main'"
    assert _format_tool_input("symbol_search", {"name": "main", "path": "/src"}) == "name='main' in /src"
    
    # git
    assert _format_tool_input("git", {"args": "status"}) == "args='status'"
    assert _format_tool_input("git", {"args": "commit -m 'fix'", "working_dir": "/repo"}) == "args='commit -m 'fix'' (in /repo)"
    
    # dev_pipeline
    inp = {"action": "start", "branch": "feat/new"}
    assert _format_tool_input("dev_pipeline", inp) == "action='start' branch='feat/new'"
    
    inp = {"action": "commit", "branch": "feat/new", "message": "Add feature"}
    expected = "action='commit' branch='feat/new' message='Add feature'"
    assert _format_tool_input("dev_pipeline", inp) == expected
    
    # synthesize
    question = "What is the best approach for this task? Should I use X or Y?"
    expected = "question='What is the best approach for this task? Should I use X or Y...'"
    assert _format_tool_input("synthesize", {"question": question}) == expected
    
    # auto_fix
    assert _format_tool_input("auto_fix", {"command": "pytest"}) == "command='pytest'"
    assert _format_tool_input("auto_fix", {"command": "npm test", "working_dir": "/app"}) == "command='npm test' (in /app)"
    
    # clipboard_paste
    assert _format_tool_input("clipboard_paste", {"text": "some text"}) == "text='some text...'"
    assert _format_tool_input("clipboard_paste", {"text": "text", "paste": True}) == "text='text...' +paste"


def test_format_tool_result():
    """Test formatting of tool results."""
    # Empty result
    assert "(no output)" in _format_tool_result("")
    
    # Short result
    result = _format_tool_result("Success")
    assert "Success" in result
    
    # Long result (truncated)
    long_text = "A" * 300
    result = _format_tool_result(long_text)
    assert "..." in result
    assert len(result) < len(long_text)
    
    # Multiline result (converted to arrows)
    result = _format_tool_result("Line 1\nLine 2\nLine 3")
    assert "↵" in result


@patch('jarvis_cli.main.time.sleep')  # Skip delays in tests
def test_replay_no_completed_file(mock_sleep, tmp_path):
    """Test replay when no completed file exists."""
    with patch('jarvis_cli.main.COMPLETED_FILE', tmp_path / "nonexistent.json"):
        with patch('builtins.print') as mock_print:
            replay_last_task()
            mock_print.assert_called()
            # Should print message about no completed tasks


@patch('jarvis_cli.main.time.sleep')  # Skip delays in tests  
def test_replay_empty_completed_file(mock_sleep, tmp_path):
    """Test replay when completed file is empty."""
    completed_file = tmp_path / "completed.json"
    completed_file.write_text("[]")
    
    with patch('jarvis_cli.main.COMPLETED_FILE', completed_file):
        with patch('builtins.print') as mock_print:
            replay_last_task()
            mock_print.assert_called()


@patch('jarvis_cli.main.time.sleep')  # Skip delays in tests
def test_replay_no_tool_calls(mock_sleep, tmp_path, sample_completed_tasks):
    """Test replay when last task has no tool calls."""
    # Only include the failed task (no tool calls)
    tasks = [sample_completed_tasks[2]]
    completed_file = tmp_path / "completed.json" 
    completed_file.write_text(json.dumps(tasks))
    
    with patch('jarvis_cli.main.COMPLETED_FILE', completed_file):
        with patch('builtins.print') as mock_print:
            replay_last_task()
            mock_print.assert_called()


@patch('jarvis_cli.main.time.sleep')  # Skip delays in tests
def test_replay_successful_task(mock_sleep, tmp_path, sample_completed_tasks):
    """Test replaying a successful task with tool calls."""
    completed_file = tmp_path / "completed.json"
    completed_file.write_text(json.dumps(sample_completed_tasks))
    
    with patch('jarvis_cli.main.COMPLETED_FILE', completed_file):
        with patch('builtins.print') as mock_print:
            replay_last_task()
            
            # Check that print was called multiple times for the replay
            assert mock_print.call_count > 5  # Header + tool calls + footer
            
            # Check that specific content was printed
            printed_text = ' '.join(str(call) for call in mock_print.call_args_list)
            assert "Replay Mode" in printed_text
            assert "Write and patch files" in printed_text  # Task name from last successful task
            assert "file_write" in printed_text  # Tool name
            assert "file_patch" in printed_text  # Tool name  
            assert "execute_bash" in printed_text  # Tool name


@patch('jarvis_cli.main.time.sleep')  # Skip delays in tests
def test_replay_finds_last_successful_with_tool_calls(mock_sleep, tmp_path, sample_completed_tasks):
    """Test that replay finds the last successful task with tool calls, skipping failed ones."""
    # Add a failed task at the end
    tasks = sample_completed_tasks + [{
        "id": "task4",
        "task": "Another failed task", 
        "created_at": "2023-01-01T10:15:00",
        "completed_at": "2023-01-01T10:15:01", 
        "status": "failed",
        "error": "Failed",
        "tool_calls": []
    }]
    
    completed_file = tmp_path / "completed.json"
    completed_file.write_text(json.dumps(tasks))
    
    with patch('jarvis_cli.main.COMPLETED_FILE', completed_file):
        with patch('builtins.print') as mock_print:
            replay_last_task()
            
            # Should replay the multi-tool task (task2), not the failed tasks
            printed_text = ' '.join(str(call) for call in mock_print.call_args_list)
            assert "Write and patch files" in printed_text  # Should find task2
            assert "Another failed task" not in printed_text  # Should skip failed task4


def test_replay_interrupted(tmp_path, sample_completed_tasks):
    """Test replay behavior when interrupted with Ctrl+C."""
    completed_file = tmp_path / "completed.json"
    completed_file.write_text(json.dumps(sample_completed_tasks))
    
    with patch('jarvis_cli.main.COMPLETED_FILE', completed_file):
        with patch('builtins.print') as mock_print:
            with patch('jarvis_cli.main.time.sleep', side_effect=KeyboardInterrupt):
                replay_last_task()
                
                # Should handle interrupt gracefully
                printed_text = ' '.join(str(call) for call in mock_print.call_args_list)
                assert "stopped" in printed_text.lower()