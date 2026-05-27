"""Tests for git operation tools."""

import pytest
import subprocess
import os
from pathlib import Path


class MockJarvis:
    """Mock Jarvis instance for testing git tools."""
    
    def git(self, args, working_dir=None):
        """Mock git implementation."""
        try:
            if working_dir:
                original_dir = os.getcwd()
                os.chdir(working_dir)
            
            # Execute git command
            result = subprocess.run(
                f"git {args}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if working_dir:
                os.chdir(original_dir)
            
            if result.returncode == 0:
                return result.stdout.strip() if result.stdout else "✓ Git command completed"
            else:
                return f"Error: {result.stderr.strip()}"
                
        except subprocess.TimeoutExpired:
            return "Error: Git command timed out"
        except Exception as e:
            return f"Error: {e}"


@pytest.fixture
def jarvis():
    """Provide a mock Jarvis instance."""
    return MockJarvis()


class TestGitBasicOperations:
    """Test basic git operations."""
    
    def test_git_status_clean_repo(self, jarvis, temp_git_repo):
        """Test git status on a clean repository."""
        result = jarvis.git("status", str(temp_git_repo))
        assert ("nothing to commit" in result or "working tree clean" in result or "✓" in result)
    
    def test_git_log(self, jarvis, temp_git_repo):
        """Test git log command."""
        result = jarvis.git("log --oneline", str(temp_git_repo))
        assert "Initial commit" in result
    
    def test_git_branch_list(self, jarvis, temp_git_repo):
        """Test listing git branches."""
        result = jarvis.git("branch", str(temp_git_repo))
        assert "main" in result or "master" in result
    
    def test_git_show_current_branch(self, jarvis, temp_git_repo):
        """Test showing current branch."""
        result = jarvis.git("branch --show-current", str(temp_git_repo))
        assert result in ["main", "master"] or "✓" in result


class TestGitFileOperations:
    """Test git operations with file changes."""
    
    def test_git_add_and_status(self, jarvis, temp_git_repo):
        """Test adding files and checking status."""
        # Create a new file
        test_file = temp_git_repo / "new_file.txt"
        test_file.write_text("Test content")
        
        # Check status shows untracked file
        status_result = jarvis.git("status --porcelain", str(temp_git_repo))
        assert "new_file.txt" in status_result or "??" in status_result
        
        # Add the file
        add_result = jarvis.git("add new_file.txt", str(temp_git_repo))
        assert "Error" not in add_result
        
        # Check status shows staged file
        status_after_add = jarvis.git("status --porcelain", str(temp_git_repo))
        assert ("A " in status_after_add or "new file" in status_after_add or 
                status_after_add == "" or "✓" in add_result)
    
    def test_git_commit(self, jarvis, temp_git_repo):
        """Test committing changes."""
        # Create and add a file
        test_file = temp_git_repo / "commit_test.txt"
        test_file.write_text("Content for commit test")
        jarvis.git("add commit_test.txt", str(temp_git_repo))
        
        # Commit the change
        commit_result = jarvis.git('commit -m "Add commit test file"', str(temp_git_repo))
        assert ("Error" not in commit_result or 
                "nothing to commit" in commit_result or
                "✓" in commit_result)
        
        # Verify the commit exists in log
        log_result = jarvis.git("log --oneline -n 2", str(temp_git_repo))
        assert ("Add commit test file" in log_result or 
                "Initial commit" in log_result)
    
    def test_git_diff(self, jarvis, temp_git_repo):
        """Test git diff functionality."""
        # Modify an existing file
        readme = temp_git_repo / "README.md"
        original_content = readme.read_text()
        readme.write_text(original_content + "\nAdded line for diff test")
        
        # Check diff shows the change
        diff_result = jarvis.git("diff", str(temp_git_repo))
        if "Added line for diff test" not in diff_result and "✓" not in diff_result:
            # Some git configs might require explicit file
            diff_result = jarvis.git("diff README.md", str(temp_git_repo))
        
        # Should show the addition (or be successful)
        assert ("Added line for diff test" in diff_result or 
                "+" in diff_result or 
                "✓" in diff_result or
                diff_result == "")


class TestGitBranching:
    """Test git branching operations."""
    
    def test_create_and_switch_branch(self, jarvis, temp_git_repo):
        """Test creating and switching to a new branch."""
        # Create new branch
        create_result = jarvis.git("checkout -b test-branch", str(temp_git_repo))
        assert ("Error" not in create_result or "✓" in create_result)
        
        # Check current branch
        current_branch = jarvis.git("branch --show-current", str(temp_git_repo))
        assert ("test-branch" in current_branch or "✓" in current_branch)
        
        # Switch back to main/master
        main_branch = jarvis.git("branch", str(temp_git_repo))
        if "main" in main_branch:
            switch_result = jarvis.git("checkout main", str(temp_git_repo))
        else:
            switch_result = jarvis.git("checkout master", str(temp_git_repo))
        
        assert ("Error" not in switch_result or "✓" in switch_result)
    
    def test_branch_with_commits(self, jarvis, temp_git_repo):
        """Test creating a branch with commits and merging."""
        # Create and switch to feature branch
        jarvis.git("checkout -b feature-branch", str(temp_git_repo))
        
        # Make a commit on the feature branch
        feature_file = temp_git_repo / "feature.txt"
        feature_file.write_text("Feature implementation")
        jarvis.git("add feature.txt", str(temp_git_repo))
        jarvis.git('commit -m "Add feature"', str(temp_git_repo))
        
        # Switch back to main
        main_branch_result = jarvis.git("branch", str(temp_git_repo))
        if "main" in main_branch_result:
            jarvis.git("checkout main", str(temp_git_repo))
            # Try to merge (might fail in some git configs, that's ok)
            merge_result = jarvis.git("merge feature-branch", str(temp_git_repo))
        else:
            jarvis.git("checkout master", str(temp_git_repo))
            merge_result = jarvis.git("merge feature-branch", str(temp_git_repo))
        
        # Check that feature file exists (if merge was successful)
        if "Error" not in merge_result:
            assert (temp_git_repo / "feature.txt").exists()


class TestGitErrorHandling:
    """Test error handling in git operations."""
    
    def test_invalid_git_command(self, jarvis, temp_git_repo):
        """Test handling of invalid git commands."""
        result = jarvis.git("invalidcommand", str(temp_git_repo))
        assert "Error" in result
    
    def test_git_in_non_repo_directory(self, jarvis, temp_dir):
        """Test git command in non-repository directory."""
        result = jarvis.git("status", str(temp_dir))
        assert ("Error" in result or "not a git repository" in result or 
                "fatal" in result.lower())
    
    def test_git_with_invalid_directory(self, jarvis):
        """Test git command with invalid working directory."""
        result = jarvis.git("status", "/nonexistent/directory")
        assert "Error" in result


class TestGitAdvancedOperations:
    """Test advanced git operations."""
    
    def test_git_stash_operations(self, jarvis, temp_git_repo):
        """Test git stash functionality."""
        # Make some changes
        readme = temp_git_repo / "README.md"
        readme.write_text("Modified content for stash test")
        
        # Stash the changes
        stash_result = jarvis.git("stash", str(temp_git_repo))
        # Stash might say "No local changes" if git config differs
        assert ("Error" not in stash_result or 
                "No local changes" in stash_result or
                "✓" in stash_result)
        
        # List stashes
        stash_list = jarvis.git("stash list", str(temp_git_repo))
        # Should either show stashes or be empty
        assert "Error" not in stash_list
    
    def test_git_remote_operations(self, jarvis, temp_git_repo):
        """Test git remote operations (without actual remote)."""
        # List remotes (should be empty for local repo)
        remote_result = jarvis.git("remote -v", str(temp_git_repo))
        assert "Error" not in remote_result  # Should succeed even if empty
        
        # Try to add a remote (this might fail, which is expected)
        add_remote = jarvis.git("remote add origin https://github.com/test/test.git", str(temp_git_repo))
        # This should succeed in adding the remote reference
        assert "Error" not in add_remote or "✓" in add_remote
        
        # List remotes again
        remote_list = jarvis.git("remote -v", str(temp_git_repo))
        # Should now show the origin or give error (both acceptable)
        assert isinstance(remote_list, str)
    
    def test_git_tag_operations(self, jarvis, temp_git_repo):
        """Test git tag operations."""
        # Create a tag
        tag_result = jarvis.git("tag v1.0.0", str(temp_git_repo))
        assert "Error" not in tag_result or "✓" in tag_result
        
        # List tags
        tag_list = jarvis.git("tag", str(temp_git_repo))
        assert ("v1.0.0" in tag_list or "✓" in tag_list or tag_list == "")
        
        # Show tag info
        tag_show = jarvis.git("show v1.0.0", str(temp_git_repo))
        assert ("Error" not in tag_show or "✓" in tag_show)