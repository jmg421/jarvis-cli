"""Tests for the --clear-queue command."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis_cli.main import clear_queue, load_queue, save_queue, QUEUE_FILE, COMPLETED_FILE


def test_clear_empty_queue(tmpdir):
    """Test clearing an empty queue."""
    with patch('jarvis_cli.main.QUEUE_FILE', Path(tmpdir) / 'queue.json'), \
         patch('jarvis_cli.main.COMPLETED_FILE', Path(tmpdir) / 'completed.json'), \
         patch('builtins.print') as mock_print:
        
        clear_queue()
        
        # Should print that queue is already empty
        mock_print.assert_called()
        args, _ = mock_print.call_args
        assert "already empty" in str(args[0])


def test_clear_queue_with_tasks(tmpdir):
    """Test clearing a queue with tasks."""
    queue_file = Path(tmpdir) / 'queue.json'
    completed_file = Path(tmpdir) / 'completed.json'
    
    with patch('jarvis_cli.main.QUEUE_FILE', queue_file), \
         patch('jarvis_cli.main.COMPLETED_FILE', completed_file), \
         patch('builtins.print') as mock_print:
        
        # Create a queue with some tasks
        test_queue = [
            {
                "id": "task1",
                "task": "Test task 1",
                "created_at": "2024-01-01T10:00:00",
                "status": "queued"
            },
            {
                "id": "task2", 
                "task": "Test task 2",
                "created_at": "2024-01-01T10:05:00",
                "status": "queued"
            },
            {
                "id": "task3",
                "task": "Test task 3", 
                "created_at": "2024-01-01T10:10:00",
                "status": "processing"
            }
        ]
        
        queue_file.write_text(json.dumps(test_queue))
        
        clear_queue()
        
        # Queue should be empty
        assert load_queue() == []
        
        # Tasks should be logged as cancelled in completed.json
        completed = json.loads(completed_file.read_text())
        assert len(completed) == 3
        
        for task in completed:
            assert task["status"] == "cancelled"
            assert task["reason"] == "queue cleared"
            assert "cancelled_at" in task
        
        # Should print success message
        mock_print.assert_called()
        print_calls = [str(call[0][0]) if call[0] else "" for call in mock_print.call_args_list]
        success_found = any("Queue cleared" in msg for msg in print_calls)
        assert success_found


def test_clear_queue_preserves_completed_history(tmpdir):
    """Test that clearing queue preserves existing completed task history."""
    queue_file = Path(tmpdir) / 'queue.json'
    completed_file = Path(tmpdir) / 'completed.json'
    
    with patch('jarvis_cli.main.QUEUE_FILE', queue_file), \
         patch('jarvis_cli.main.COMPLETED_FILE', completed_file), \
         patch('builtins.print'):
        
        # Create existing completed tasks
        existing_completed = [
            {
                "id": "old_task",
                "task": "Old completed task",
                "status": "completed",
                "completed_at": "2024-01-01T09:00:00"
            }
        ]
        completed_file.write_text(json.dumps(existing_completed))
        
        # Create queue with new tasks
        test_queue = [
            {
                "id": "new_task",
                "task": "New task to clear",
                "created_at": "2024-01-01T10:00:00", 
                "status": "queued"
            }
        ]
        queue_file.write_text(json.dumps(test_queue))
        
        clear_queue()
        
        # Check that both old and new tasks are in completed.json
        completed = json.loads(completed_file.read_text())
        assert len(completed) == 2
        
        # Old task should still be there
        old_task = next((t for t in completed if t["id"] == "old_task"), None)
        assert old_task is not None
        assert old_task["status"] == "completed"
        
        # New task should be marked as cancelled
        new_task = next((t for t in completed if t["id"] == "new_task"), None) 
        assert new_task is not None
        assert new_task["status"] == "cancelled"


def test_clear_queue_limits_completed_history(tmpdir):
    """Test that clearing queue respects the 1000 task limit for completed history."""
    queue_file = Path(tmpdir) / 'queue.json'
    completed_file = Path(tmpdir) / 'completed.json'
    
    with patch('jarvis_cli.main.QUEUE_FILE', queue_file), \
         patch('jarvis_cli.main.COMPLETED_FILE', completed_file), \
         patch('builtins.print'):
        
        # Create 999 existing completed tasks
        existing_completed = []
        for i in range(999):
            existing_completed.append({
                "id": f"old_task_{i}",
                "task": f"Old task {i}",
                "status": "completed",
                "completed_at": f"2024-01-01T{i:02d}:00:00"
            })
        completed_file.write_text(json.dumps(existing_completed))
        
        # Create queue with 5 new tasks to clear
        test_queue = []
        for i in range(5):
            test_queue.append({
                "id": f"new_task_{i}",
                "task": f"New task {i}",
                "created_at": "2024-01-01T10:00:00",
                "status": "queued" 
            })
        queue_file.write_text(json.dumps(test_queue))
        
        clear_queue()
        
        # Should have exactly 1000 tasks (999 + 5 = 1004, trimmed to last 1000)
        completed = json.loads(completed_file.read_text())
        assert len(completed) == 1000
        
        # Should have all 5 new cancelled tasks
        cancelled_tasks = [t for t in completed if t.get("status") == "cancelled"]
        assert len(cancelled_tasks) == 5
        
        # Should have 995 old completed tasks (oldest 4 removed)
        old_tasks = [t for t in completed if t.get("status") == "completed"]
        assert len(old_tasks) == 995