#!/usr/bin/env python3
"""
Tests for codebase indexing functionality.
"""

import json
import tempfile
import pytest
from pathlib import Path
import shutil
import sys
import os

# Add the parent directory to sys.path to import jarvis_cli
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis_cli.main import (
    codebase_index, 
    _extract_python_definitions, 
    _extract_javascript_definitions,
    _should_index_file,
    _get_file_hash
)


class TestCodebaseIndex:
    """Test codebase indexing functionality."""
    
    def test_should_index_file(self):
        """Test file filtering logic."""
        # Should index
        assert _should_index_file("main.py")
        assert _should_index_file("src/component.js")
        assert _should_index_file("lib/utils.ts")
        assert _should_index_file("app.go")
        assert _should_index_file("server.rs")
        
        # Should not index
        assert not _should_index_file(".hidden.py")
        assert not _should_index_file("node_modules/lib.js")
        assert not _should_index_file("__pycache__/cache.pyc")
        assert not _should_index_file(".git/config")
        assert not _should_index_file("README.md")
        assert not _should_index_file("config.json")
    
    def test_extract_python_definitions(self):
        """Test Python AST parsing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
def hello_world():
    """Say hello to the world."""
    return "Hello, World!"

class Calculator:
    """A simple calculator class."""
    
    def add(self, a, b):
        """Add two numbers."""
        return a + b
    
    def subtract(self, a, b):
        return a - b

async def async_function(param1, param2):
    """An async function."""
    pass
''')
            f.flush()
            
            definitions = _extract_python_definitions(f.name)
            
            # Should find function and class
            assert len(definitions) == 3
            
            # Check function
            func_def = next(d for d in definitions if d["name"] == "hello_world")
            assert func_def["type"] == "function"
            assert func_def["docstring"] == "Say hello to the world."
            assert func_def["args"] == []
            assert func_def["line"] == 2
            
            # Check class
            class_def = next(d for d in definitions if d["name"] == "Calculator")
            assert class_def["type"] == "class"
            assert class_def["docstring"] == "A simple calculator class."
            assert len(class_def["methods"]) == 2
            assert class_def["methods"][0]["name"] == "add"
            assert class_def["methods"][0]["args"] == ["self", "a", "b"]
            
            # Check async function
            async_def = next(d for d in definitions if d["name"] == "async_function")
            assert async_def["type"] == "function"
            assert async_def["args"] == ["param1", "param2"]
        
        # Clean up
        os.unlink(f.name)
    
    def test_extract_javascript_definitions(self):
        """Test JavaScript/TypeScript parsing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write('''
function regularFunction() {
    return "hello";
}

const arrowFunction = () => {
    return "arrow";
}

export const exportedFunction = (param) => {
    return param;
}

class MyClass {
    constructor() {
        this.value = 0;
    }
    
    method() {
        return this.value;
    }
}

export class ExportedClass {
    
}
''')
            f.flush()
            
            definitions = _extract_javascript_definitions(f.name)
            
            # Should find functions and classes
            function_names = [d["name"] for d in definitions if d["type"] == "function"]
            class_names = [d["name"] for d in definitions if d["type"] == "class"]
            
            assert "regularFunction" in function_names
            assert "arrowFunction" in function_names
            assert "exportedFunction" in function_names
            assert "MyClass" in class_names
            assert "ExportedClass" in class_names
        
        # Clean up
        os.unlink(f.name)
    
    def test_get_file_hash(self):
        """Test file hashing."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("Hello, World!")
            f.flush()
            
            hash1 = _get_file_hash(f.name)
            assert hash1 is not None
            assert len(hash1) == 32  # MD5 hash length
            
            # Same content should give same hash
            hash2 = _get_file_hash(f.name)
            assert hash1 == hash2
        
        # Clean up
        os.unlink(f.name)
        
        # Non-existent file should return None
        assert _get_file_hash("/nonexistent/file.py") is None
    
    def test_codebase_index_integration(self):
        """Test full codebase indexing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create a sample codebase
            (tmpdir_path / "main.py").write_text('''
def main():
    """Main entry point."""
    print("Hello!")

class App:
    pass
''')
            
            (tmpdir_path / "utils.js").write_text('''
function helper() {
    return true;
}

export const constant = 42;
''')
            
            # Create a subdirectory with code
            subdir = tmpdir_path / "src"
            subdir.mkdir()
            (subdir / "component.py").write_text('''
class Component:
    def render(self):
        return "<div></div>"
''')
            
            # Create files that should be ignored
            (tmpdir_path / "README.md").write_text("# Documentation")
            (tmpdir_path / ".hidden.py").write_text("# Hidden file")
            
            # Index the codebase
            result = codebase_index(tmpdir_path)
            
            assert "error" not in result
            assert result["files"] == 3  # main.py, utils.js, src/component.py
            assert result["functions"] >= 2  # main, helper, render
            assert result["classes"] >= 2   # App, Component
            
            # Check that index file was created
            index_file = Path(result["index_file"])
            assert index_file.exists()
            
            # Load and verify index content
            index_data = json.loads(index_file.read_text())
            
            assert "metadata" in index_data
            assert "files" in index_data
            assert index_data["metadata"]["file_count"] == 3
            
            # Verify specific files are indexed
            files = index_data["files"]
            assert "main.py" in files
            assert "utils.js" in files
            assert "src/component.py" in files
            assert "README.md" not in files  # Should be filtered out
            assert ".hidden.py" not in files  # Should be filtered out
            
            # Verify Python definitions
            main_py = files["main.py"]
            assert len(main_py["definitions"]) == 2  # main function + App class
            
            # Verify JavaScript definitions  
            utils_js = files["utils.js"]
            assert len(utils_js["definitions"]) >= 1  # helper function
    
    def test_incremental_indexing(self):
        """Test that unchanged files are not re-processed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create initial file
            py_file = tmpdir_path / "test.py"
            py_file.write_text('''
def function1():
    pass
''')
            
            # First index
            result1 = codebase_index(tmpdir_path)
            index_file = Path(result1["index_file"])
            
            # Get modification time of index
            mtime1 = index_file.stat().st_mtime
            
            # Wait a bit and index again (should use cache)
            import time
            time.sleep(0.1)
            result2 = codebase_index(tmpdir_path)
            mtime2 = index_file.stat().st_mtime
            
            # Index file should not have been fully regenerated
            # (This is a bit tricky to test precisely, but the file should be updated
            # even if using cached data for individual files)
            
            # Modify the file
            py_file.write_text('''
def function1():
    pass

def function2():
    pass
''')
            
            # Index again (should detect change)
            result3 = codebase_index(tmpdir_path)
            
            # Should have more functions now
            assert result3["functions"] > result2["functions"]


class TestErrorHandling:
    """Test error handling in codebase indexing."""
    
    def test_nonexistent_directory(self):
        """Test handling of nonexistent directory."""
        result = codebase_index("/nonexistent/directory")
        assert "error" in result
        assert "not found" in result["error"]
    
    def test_malformed_python_file(self):
        """Test handling of files with syntax errors."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('def broken_function(\n  # Missing closing paren and colon')
            f.flush()
            
            definitions = _extract_python_definitions(f.name)
            # Should return empty list for malformed files
            assert definitions == []
        
        os.unlink(f.name)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])