"""Test configuration and fixtures for Jarvis CLI tests."""

import tempfile
import shutil
import os
from pathlib import Path
import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def temp_git_repo(temp_dir):
    """Create a temporary git repository for testing git operations."""
    repo_path = temp_dir / "test_repo"
    repo_path.mkdir()
    
    # Initialize git repo
    os.system(f"cd {repo_path} && git init")
    os.system(f"cd {repo_path} && git config user.email 'test@example.com'")
    os.system(f"cd {repo_path} && git config user.name 'Test User'")
    
    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repository")
    os.system(f"cd {repo_path} && git add README.md && git commit -m 'Initial commit'")
    
    yield repo_path


@pytest.fixture
def sample_file_content():
    """Sample content for testing file operations."""
    return """# Sample File
This is a test file with multiple lines.

def hello_world():
    print("Hello, World!")

if __name__ == "__main__":
    hello_world()
"""


@pytest.fixture
def sample_patch_content():
    """Sample content for testing file patching."""
    return """# Updated Sample File
This is a test file with multiple lines.

def hello_world():
    print("Hello, Updated World!")

def new_function():
    return "This is new!"

if __name__ == "__main__":
    hello_world()
    print(new_function())
"""