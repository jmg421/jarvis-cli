"""Tests for file operation tools: file_read, file_write, file_patch."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import json


class MockJarvis:
    """Mock Jarvis instance for testing tools."""
    
    def file_read(self, path, limit=None, offset=None):
        """Mock file_read implementation."""
        file_path = Path(path)
        if not file_path.exists():
            return f"Error: File {path} not found"
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            if offset:
                lines = lines[offset:]
            if limit:
                lines = lines[:limit]
                
            return ''.join(lines)
        except Exception as e:
            return f"Error reading file: {e}"
    
    def file_write(self, path, content):
        """Mock file_write implementation."""
        try:
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            return f"Wrote {len(content)} chars to {path}"
        except Exception as e:
            return f"Error writing file: {e}"
    
    def file_patch(self, path, old_str, new_str):
        """Mock file_patch implementation."""
        try:
            file_path = Path(path)
            if not file_path.exists():
                return f"Error: File {path} not found"
                
            content = file_path.read_text(encoding='utf-8')
            
            if old_str not in content:
                return f"Error: String not found in file"
            
            if content.count(old_str) > 1:
                return f"Error: String appears multiple times, not unique"
                
            new_content = content.replace(old_str, new_str)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
                
            old_len = len(old_str)
            new_len = len(new_str)
            return f"Patched {path} ({old_len} chars → {new_len} chars)"
            
        except Exception as e:
            return f"Error patching file: {e}"


@pytest.fixture
def jarvis():
    """Provide a mock Jarvis instance."""
    return MockJarvis()


class TestFileRead:
    """Test file_read functionality."""
    
    def test_read_existing_file(self, jarvis, temp_dir, sample_file_content):
        """Test reading an existing file."""
        test_file = temp_dir / "test.py"
        test_file.write_text(sample_file_content)
        
        result = jarvis.file_read(str(test_file))
        assert sample_file_content in result
        assert "Hello, World!" in result
    
    def test_read_nonexistent_file(self, jarvis, temp_dir):
        """Test reading a file that doesn't exist."""
        result = jarvis.file_read(str(temp_dir / "nonexistent.txt"))
        assert "Error: File" in result and "not found" in result
    
    def test_read_with_limit(self, jarvis, temp_dir, sample_file_content):
        """Test reading with line limit."""
        test_file = temp_dir / "test.py"
        test_file.write_text(sample_file_content)
        
        result = jarvis.file_read(str(test_file), limit=2)
        lines = result.split('\n')
        assert len(lines) <= 3  # 2 lines + potential empty line
        assert "# Sample File" in result
    
    def test_read_with_offset(self, jarvis, temp_dir, sample_file_content):
        """Test reading with line offset."""
        test_file = temp_dir / "test.py"
        test_file.write_text(sample_file_content)
        
        result = jarvis.file_read(str(test_file), offset=2)
        assert "# Sample File" not in result  # Should skip first few lines
        assert "def hello_world" in result


class TestFileWrite:
    """Test file_write functionality."""
    
    def test_write_new_file(self, jarvis, temp_dir):
        """Test writing to a new file."""
        test_file = temp_dir / "new_file.txt"
        content = "This is new content."
        
        result = jarvis.file_write(str(test_file), content)
        
        assert f"Wrote {len(content)} chars" in result
        assert test_file.exists()
        assert test_file.read_text() == content
    
    def test_write_nested_directory(self, jarvis, temp_dir):
        """Test writing to a file in a nested directory that doesn't exist."""
        test_file = temp_dir / "nested" / "dir" / "file.txt"
        content = "Nested content"
        
        result = jarvis.file_write(str(test_file), content)
        
        assert "Wrote" in result
        assert test_file.exists()
        assert test_file.read_text() == content
    
    def test_overwrite_existing_file(self, jarvis, temp_dir):
        """Test overwriting an existing file."""
        test_file = temp_dir / "existing.txt"
        original_content = "Original content"
        new_content = "New content"
        
        test_file.write_text(original_content)
        result = jarvis.file_write(str(test_file), new_content)
        
        assert "Wrote" in result
        assert test_file.read_text() == new_content


class TestFilePatch:
    """Test file_patch functionality."""
    
    def test_patch_existing_content(self, jarvis, temp_dir, sample_file_content):
        """Test patching existing content in a file."""
        test_file = temp_dir / "test.py"
        test_file.write_text(sample_file_content)
        
        result = jarvis.file_patch(
            str(test_file),
            'print("Hello, World!")',
            'print("Hello, Patched World!")'
        )
        
        assert "Patched" in result
        content = test_file.read_text()
        assert "Hello, Patched World!" in content
        assert "Hello, World!" not in content
    
    def test_patch_nonexistent_file(self, jarvis, temp_dir):
        """Test patching a file that doesn't exist."""
        result = jarvis.file_patch(
            str(temp_dir / "nonexistent.txt"),
            "old",
            "new"
        )
        assert "Error: File" in result and "not found" in result
    
    def test_patch_nonexistent_string(self, jarvis, temp_dir, sample_file_content):
        """Test patching with a string that doesn't exist in the file."""
        test_file = temp_dir / "test.py"
        test_file.write_text(sample_file_content)
        
        result = jarvis.file_patch(
            str(test_file),
            "this string is not in the file",
            "replacement"
        )
        assert "Error: String not found" in result
    
    def test_patch_non_unique_string(self, jarvis, temp_dir):
        """Test patching with a string that appears multiple times."""
        content = "hello world\nhello world\n"
        test_file = temp_dir / "test.txt"
        test_file.write_text(content)
        
        result = jarvis.file_patch(
            str(test_file),
            "hello",
            "hi"
        )
        assert "Error: String appears multiple times" in result
    
    def test_patch_multiline_content(self, jarvis, temp_dir):
        """Test patching multi-line content."""
        original = """def function():
    print("old")
    return True"""
        
        new_function = """def function():
    print("new")
    print("additional line")
    return True"""
        
        test_file = temp_dir / "test.py"
        test_file.write_text(original)
        
        result = jarvis.file_patch(
            str(test_file),
            'print("old")',
            'print("new")\n    print("additional line")'
        )
        
        assert "Patched" in result
        content = test_file.read_text()
        assert "additional line" in content
        assert 'print("old")' not in content


class TestFileOperationsIntegration:
    """Integration tests combining multiple file operations."""
    
    def test_write_read_patch_cycle(self, jarvis, temp_dir):
        """Test a complete write -> read -> patch -> read cycle."""
        test_file = temp_dir / "integration.py"
        
        # Write initial content
        initial_content = "def greet():\n    return 'Hello'"
        jarvis.file_write(str(test_file), initial_content)
        
        # Read it back
        read_result = jarvis.file_read(str(test_file))
        assert "Hello" in read_result
        
        # Patch it
        patch_result = jarvis.file_patch(
            str(test_file),
            "Hello",
            "Hi there"
        )
        assert "Patched" in patch_result
        
        # Read the patched version
        final_read = jarvis.file_read(str(test_file))
        assert "Hi there" in final_read
        assert "Hello" not in final_read
    
    def test_complex_patch_operation(self, jarvis, temp_dir):
        """Test a complex patch operation with code refactoring."""
        original_code = '''class Calculator:
    def add(self, a, b):
        return a + b
    
    def multiply(self, a, b):
        result = 0
        for i in range(b):
            result += a
        return result'''
        
        test_file = temp_dir / "calculator.py"
        jarvis.file_write(str(test_file), original_code)
        
        # Refactor the multiply method
        old_method = """def multiply(self, a, b):
        result = 0
        for i in range(b):
            result += a
        return result"""
        
        new_method = """def multiply(self, a, b):
        return a * b  # Simplified implementation"""
        
        result = jarvis.file_patch(str(test_file), old_method, new_method)
        assert "Patched" in result
        
        # Verify the change
        final_content = jarvis.file_read(str(test_file))
        assert "Simplified implementation" in final_content
        assert "for i in range(b)" not in final_content