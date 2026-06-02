#!/usr/bin/env python3
"""
Jarvis CLI — Self-improving agentic CLI.

The loop:
  1. `jarvis-cli --help` shows current capabilities
  2. Multi-LLM synthesis prioritizes what to build next
  3. Writes the prioritized feature to /tmp/jarvis-cli-task.txt
  4. pbcopy + osascript pastes into kiro-cli terminal
  5. Kiro builds it, jarvis-cli gains new capabilities
  6. Repeat
"""

import sys
import os
import json
import subprocess
import time
import readline
import signal
import threading
import uuid
import ast
import hashlib
from datetime import datetime
from pathlib import Path

# Agent code lives in the nodes-bio repo
AGENT_BACKEND = Path.home() / "repos" / "jarvis-agent"

API_URL = os.environ.get("JARVIS_CLI_API", "http://localhost:8000/api/jarvis-cli")
TASK_FILE = Path("/tmp/jarvis-cli-task.txt")
LOOP_STATE = Path.home() / ".jarvis_cli_state.json"
QUEUE_FILE = Path.home() / ".jarvis_cli" / "queue.json"
COMPLETED_FILE = Path.home() / ".jarvis_cli" / "completed.json"
DAEMON_PID_FILE = Path.home() / ".jarvis_cli" / "daemon.pid"

CYAN = "\033[1;36m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
DIM = "\033[2m"
BOLD = "\033[1m"
MAGENTA = "\033[1;35m"
RESET = "\033[0m"

CAPABILITIES = {
    "file_read": "Read file contents",
    "file_write": "Create/overwrite files",
    "execute_bash": "Run shell commands (sandboxed)",
    "glob_search": "Find files by pattern",
    "grep_search": "Regex search in files",
    "web_search": "Search the web (Perplexity)",
    "web_fetch": "Fetch URL content",
    "list_directory": "Explore project structure",
    "symbol_search": "Find function/class definitions",
    "clipboard_paste": "Copy to clipboard / paste into apps",
    "synthesize": "Poll 5 LLMs for consensus answers",
    "auto_fix": "Run build/tests, fix errors, repeat until green",
    "file_patch": "Edit files by replacing specific strings (safe partial edits)",
    "git": "Git operations (status, diff, log, add, commit, branch)",
    "dev_pipeline": "Full dev cycle (branch → commit → test → merge → cleanup)",
    "codebase_index": "Build JSON map of files, functions, and classes",
    "qpu_submit": "Submit quantum circuits to IonQ/AWS Braket QPUs",
    "qpu_poll": "Poll QPU job status and retrieve results",
    "test_runner": "Run tests, parse failures into structured results",
}

BACKLOG = [
    "test runner tool (run tests, parse failures)",
    "image/screenshot analysis tool",
    "database query tool (read-only SQL)",
    "semantic search over codebase indexes (embedding-based)",
    "multi-file refactor (rename across codebase)",
]


def _scan_inventory():
    """Scan the actual agent backend to get live tool names and descriptions.

    Returns (live_tools: dict[name->description], filtered_backlog: list[str])
    where filtered_backlog excludes features already implemented.
    """
    live_tools = dict(CAPABILITIES)  # fallback

    try:
        sys.path.insert(0, str(AGENT_BACKEND))
        from jarvis_agent.tools import TOOLS as LIVE_TOOLS
        from jarvis_agent.executor import EXECUTORS as LIVE_EXECUTORS

        # Build live tool map from schema definitions (authoritative)
        live_tools = {t["name"]: t["description"].split(".")[0] for t in LIVE_TOOLS}

        # Only keep tools that also have an executor wired up
        live_tools = {k: v for k, v in live_tools.items() if k in LIVE_EXECUTORS}
    except Exception:
        pass  # fall back to hardcoded CAPABILITIES

    # Filter backlog: remove items whose keywords match a live tool name
    # or that appear in state['built']
    implemented_names = set(live_tools.keys())
    state = get_state()
    built_lower = {b.lower().strip() for b in state.get("built", [])}
    filtered_backlog = []
    for item in BACKLOG:
        item_lower = item.lower()
        already_built = any(
            tool_name.replace("_", " ") in item_lower
            or tool_name.replace("_", "") in item_lower.replace(" ", "")
            for tool_name in implemented_names
        )
        if not already_built and item_lower.strip() not in built_lower:
            filtered_backlog.append(item)

    return live_tools, filtered_backlog


def get_state():
    if LOOP_STATE.exists():
        return json.loads(LOOP_STATE.read_text())
    return {"iteration": 0, "built": [], "next_priority": None, "pending_session": None}


def save_state(state):
    LOOP_STATE.write_text(json.dumps(state, indent=2))


def show_help():
    state = get_state()
    live_tools, filtered_backlog = _scan_inventory()
    print(f"""
  {CYAN}╭{'─' * 56}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI{RESET} — Self-Improving Agentic Development         {CYAN}│{RESET}
  {CYAN}│{RESET} {DIM}iteration #{state['iteration']} • {len(live_tools)} tools active{RESET}              {CYAN}│{RESET}
  {CYAN}╰{'─' * 56}╯{RESET}

  {GREEN}Current Tools:{RESET}""")
    for name, desc in live_tools.items():
        print(f"    {CYAN}•{RESET} {name:<20} {DIM}{desc}{RESET}")

    print(f"""
  {GREEN}Backlog ({len(filtered_backlog)} features):{RESET}""")
    for i, feat in enumerate(filtered_backlog[:5], 1):
        marker = f"{MAGENTA}→{RESET}" if i == 1 else " "
        print(f"   {marker} {i}. {feat}")
    if len(filtered_backlog) > 5:
        print(f"     {DIM}... +{len(filtered_backlog) - 5} more{RESET}")

    if state.get("next_priority"):
        print(f"""
  {YELLOW}Next priority (via synthesis):{RESET}
    {BOLD}{state['next_priority']}{RESET}""")

    print(f"""
  {GREEN}Commands:{RESET}
    jarvis-cli                 Interactive agent mode (improved Ctrl-C handling)
    jarvis-cli --help          Show this + trigger priority loop
    jarvis-cli --prioritize    Synthesize next feature priority
    jarvis-cli --build         Send priority to kiro-cli for building
    jarvis-cli --loop          Full cycle: prioritize → build → repeat
    jarvis-cli --status        Show iteration count, tools available, last 5 tasks
    jarvis-cli --daemon        Start daemon mode (polls queue, executes tasks)
    jarvis-cli --enqueue "task" Add task to daemon queue
    jarvis-cli --daemon-status Show daemon status and queue
    jarvis-cli --clear-queue   Empty the task queue
    jarvis-cli --replay        Replay last completed task's tool calls (animated)
    jarvis-cli --index <dir>   Build codebase index for directory
    jarvis-cli --index-force <dir> Force rebuild codebase index
    jarvis-cli --log [N]       Show last N completed tasks (default: 5)
    jarvis-cli --watch [dir]   Watch dir for .py changes, auto-run pytest
    jarvis-cli --dashboard [port] Serve dashboard (default port 7294)
    jarvis-cli --sessions      List recent conversation sessions
    jarvis-cli --continue <id> "prompt"  Continue an existing session

  {GREEN}Shell Passthrough:{RESET}
    {CYAN}!<command>{RESET}           Run any shell command inline (e.g. !pwd, !ls, !git status)
    {CYAN}!cd <path>{RESET}           Change working directory (persists across prompts)

  {GREEN}Pattern Interrupts:{RESET}
    {CYAN}Ctrl-C once{RESET}         Cancel current operation (input/generation)
    {CYAN}Ctrl-C twice (2s){RESET}    Exit gracefully
""")


def _scan_py_files(root: Path):
    """Return {path: mtime} for all .py files under root (skips junk dirs)."""
    skip = {".git", ".venv", "venv", "__pycache__", ".pytest_cache",
            "node_modules", ".mypy_cache", ".ruff_cache", "dist", "build",
            ".tox", ".eggs"}
    snapshot = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # prune in-place
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                p = Path(dirpath) / fn
                try:
                    snapshot[str(p)] = p.stat().st_mtime
                except OSError:
                    pass
    return snapshot


def _run_pytest(directory: Path):
    """Run pytest in the given directory, stream output."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n  {CYAN}▶ [{ts}] running pytest in {directory}...{RESET}")
    start = time.time()
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", "-q", "--color=yes"],
            cwd=str(directory),
        )
        rc = result.returncode
    except FileNotFoundError:
        print(f"  {YELLOW}pytest not available (python3 missing){RESET}")
        return
    elapsed = time.time() - start
    if rc == 0:
        print(f"  {GREEN}✓ pytest passed{RESET} {DIM}({elapsed:.2f}s){RESET}")
    else:
        print(f"  {YELLOW}✗ pytest failed (exit {rc}){RESET} {DIM}({elapsed:.2f}s){RESET}")


def watch_directory(directory: str = ".", interval: float = 1.0):
    """Watch a directory for .py file changes; re-run pytest on change."""
    root = Path(directory).expanduser().resolve()
    if not root.exists():
        print(f"  {YELLOW}Directory not found: {root}{RESET}")
        return
    if not root.is_dir():
        print(f"  {YELLOW}Not a directory: {root}{RESET}")
        return

    print(f"  {CYAN}╭{'─' * 56}╮{RESET}")
    print(f"  {CYAN}│{RESET} {BOLD}Watch Mode{RESET} — auto-pytest on .py changes              {CYAN}│{RESET}")
    print(f"  {CYAN}╰{'─' * 56}╯{RESET}")
    print(f"  {DIM}watching:{RESET} {root}")
    print(f"  {DIM}interval:{RESET} {interval}s   {DIM}(Ctrl+C to stop){RESET}")

    snapshot = _scan_py_files(root)
    print(f"  {DIM}tracking {len(snapshot)} .py file(s){RESET}")

    # initial run
    _run_pytest(root)

    try:
        while True:
            time.sleep(interval)
            current = _scan_py_files(root)
            changed = []
            for path, mtime in current.items():
                if path not in snapshot:
                    changed.append(("+", path))
                elif snapshot[path] != mtime:
                    changed.append(("M", path))
            for path in snapshot:
                if path not in current:
                    changed.append(("-", path))

            if changed:
                print(f"\n  {MAGENTA}⚡ detected {len(changed)} change(s):{RESET}")
                for sym, path in changed[:5]:
                    rel = os.path.relpath(path, root)
                    color = GREEN if sym == "+" else (YELLOW if sym == "M" else DIM)
                    print(f"    {color}{sym}{RESET} {rel}")
                if len(changed) > 5:
                    print(f"    {DIM}... +{len(changed) - 5} more{RESET}")
                snapshot = current
                _run_pytest(root)
    except KeyboardInterrupt:
        print(f"\n  {DIM}watch mode stopped{RESET}")


def prioritize():
    """Use multi-LLM synthesis to pick the highest-value next feature."""
    import urllib.request

    state = get_state()
    live_tools, filtered_backlog = _scan_inventory()
    current_tools = ", ".join(live_tools.keys())
    backlog_text = "\n".join(f"- {f}" for f in filtered_backlog)
    built_text = ", ".join(state["built"]) if state["built"] else "none yet"

    if not filtered_backlog:
        print(f"  {GREEN}✓ All backlog items are already implemented!{RESET}")
        print(f"  {DIM}Live tools ({len(live_tools)}): {current_tools}{RESET}\n")
        return None

    question = f"""You are prioritizing features for an AI coding agent called Jarvis CLI.

Current tools: {current_tools}
Already built: {built_text}

Remaining backlog:
{backlog_text}

Strategic context: The top use cases for quantum computers are HCLS (healthcare/life sciences), finance, and materials science. This agent supports quantum circuit submission (qpu_submit/qpu_poll) and bioinformatics workflows.

Which ONE feature should be built next to maximize the agent's usefulness for a solo developer building a SaaS product? Consider:
1. What unlocks the most new workflows
2. What has the highest daily-use frequency
3. What's fastest to implement correctly

Reply with ONLY the feature name from the backlog, then a one-sentence justification."""

    print(f"  {MAGENTA}⚡ Synthesizing priority across 5 models...{RESET}\n")

    payload = json.dumps({"prompt": f"Use the synthesize tool to answer: {question}"}).encode()
    try:
        req = urllib.request.Request(
            f"{API_URL}/run",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        response = result.get("response", "")
    except Exception:
        response = filtered_backlog[0] if filtered_backlog else BACKLOG[0]
        print(f"  {DIM}(API unavailable, using default priority){RESET}")

    state["next_priority"] = response.strip()[:200]
    state["iteration"] += 1
    save_state(state)

    print(f"  {GREEN}✓ Priority set:{RESET}")
    print(f"    {BOLD}{state['next_priority']}{RESET}\n")
    return state["next_priority"]


def build():
    """Execute the prioritized task using the agent backend."""
    state = get_state()
    priority = state.get("next_priority")
    if not priority:
        print(f"  {YELLOW}No priority set. Run: jarvis-cli --prioritize{RESET}")
        return

    # Resume existing session if task was previously attempted but didn't land
    resume_sid = state.get("pending_session")
    if resume_sid:
        task = "Continue where you left off. The previous attempt did not merge to main. Finish the implementation, ensure tests pass, and merge."
        print(f"  {GREEN}✓ Resuming task:{RESET} {DIM}(session {resume_sid}){RESET}")
        print(f"    {DIM}{priority[:80]}{RESET}\n")
    else:
        task = f"Build this feature for Jarvis Agent (in ~/repos/jarvis-agent/jarvis_agent/): {priority}"
        print(f"  {GREEN}✓ Executing task:{RESET}")
        print(f"    {DIM}{task[:100]}{RESET}\n")

    TASK_FILE.write_text(task)

    response, error, elapsed_time, tool_calls, session_id = execute_task(task, session_id=resume_sid)

    elapsed_str = _format_elapsed_time(elapsed_time) if elapsed_time else ""
    if error:
        print(f"  {YELLOW}❌ Failed ({elapsed_str}):{RESET} {error}")
        # Save session for resume on next run
        if session_id:
            state["pending_session"] = session_id
            save_state(state)
        return

    print(f"  {GREEN}✅ Completed ({elapsed_str}){RESET}")
    if response:
        for line in response.split('\n')[:5]:
            if line.strip():
                print(f"  {DIM}  {line[:200]}{RESET}")

    # Verify the feature actually landed on main
    if _feature_on_main(priority):
        state["built"].append(priority)
        state["pending_session"] = None
        state["next_priority"] = None
        save_state(state)
    else:
        # Didn't land — save session for resume
        print(f"  {YELLOW}  ⚠ Feature not detected on main. Will resume next run.{RESET}")
        state["pending_session"] = session_id
        save_state(state)


def loop():
    """Full self-improvement cycle."""
    print(f"  {CYAN}Starting self-improvement loop...{RESET}\n")
    state = get_state()
    if state.get("pending_session") and state.get("next_priority"):
        print(f"  {CYAN}⟳ Resuming incomplete task...{RESET}\n")
    else:
        prioritize()
    build()
    print(f"  {DIM}Kiro is building. Run 'jarvis-cli --help' to check progress.{RESET}")


def _show_sessions():
    """Display recent sessions."""
    sys.path.insert(0, str(AGENT_BACKEND))
    try:
        from jarvis_agent.memory import list_sessions
    except ImportError:
        print(f"  {YELLOW}Cannot load session memory module{RESET}\n")
        return
    sessions = list_sessions()
    if not sessions:
        print(f"  {DIM}No sessions found.{RESET}\n")
        return
    print(f"  {GREEN}Recent sessions:{RESET}")
    for s in sessions[:10]:
        ts = datetime.fromtimestamp(s["updated_at"]).strftime("%m/%d %H:%M") if s["updated_at"] else "?"
        preview = s.get("preview", "")[:50]
        print(f"    {CYAN}{s['session_id']}{RESET}  {DIM}{ts}  ({s['message_count']} msgs){RESET}  {preview}")
    print()


def interactive():
    """Interactive agent mode with multi-turn memory and improved Ctrl-C handling."""
    import urllib.request
    import threading

    # Set up graceful interrupt handling
    interrupt_count = [0]
    interrupt_time = [0.0]
    cancelled = [False]
    
    def signal_handler(signum, frame):
        """Handle Ctrl-C with different behaviors based on context."""
        current_time = time.time()
        interrupt_count[0] += 1
        
        # Reset counter if more than 2 seconds since last interrupt
        if current_time - interrupt_time[0] > 2.0:
            interrupt_count[0] = 1
            
        interrupt_time[0] = current_time
        
        if interrupt_count[0] == 1:
            print(f"\n  {YELLOW}⚡ Interrupt received - press Ctrl-C again within 2s to exit{RESET}")
            cancelled[0] = True
        elif interrupt_count[0] >= 2:
            print(f"\n  {DIM}Exiting gracefully...{RESET}")
            try:
                readline.write_history_file(histfile)
            except:
                pass
            sys.exit(0)
    
    # Install signal handler
    signal.signal(signal.SIGINT, signal_handler)

    histfile = Path.home() / ".jarvis_cli" / "history"
    histfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        readline.read_history_file(histfile)
    except (FileNotFoundError, PermissionError, OSError):
        pass
    readline.set_history_length(500)

    prompt_queue = []
    last_response = [""]

    def _streamdeck_server():
        import http.server

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                action = body.get("action", "prompt")

                if action == "prompt":
                    prompt_queue.append(body.get("prompt", ""))
                elif action == "focus":
                    app = body.get("app", "Terminal")
                    subprocess.run(["osascript", "-e", f'tell application "{app}" to activate'], capture_output=True)
                elif action == "copy_to_jarvis":
                    subprocess.run(["osascript", "-e",
                        'tell application "System Events" to keystroke "c" using command down'], capture_output=True)
                    time.sleep(0.2)
                    result = subprocess.run(["pbpaste"], capture_output=True, text=True)
                    if result.stdout.strip():
                        prompt_queue.append(result.stdout.strip())
                elif action == "paste_last":
                    if last_response[0]:
                        subprocess.run(["pbcopy"], input=last_response[0].encode(), check=True)
                        time.sleep(0.1)
                        subprocess.run(["osascript", "-e",
                            'tell application "System Events" to keystroke "v" using command down'], capture_output=True)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def log_message(self, *a): pass

        try:
            http.server.HTTPServer(("127.0.0.1", 7293), Handler).serve_forever()
        except OSError:
            pass

    sd_thread = threading.Thread(target=_streamdeck_server, daemon=True)
    sd_thread.start()

    session_id = None
    local_mode = not _api_reachable()

    # Initialize bracketed paste support
    _enable_bracketed_paste()

    if local_mode:
        print(f"  {YELLOW}● Local mode{RESET} {DIM}(API unreachable, running in-process){RESET}")
        api_key = _get_local_key()
        if not api_key:
            print(f"  {YELLOW}❌ Set ANTHROPIC_API_KEY env var or ~/.jarvis_cli/api_key{RESET}")
            return
    else:
        api_key = None
        print(f"  {GREEN}● Connected{RESET} {DIM}({API_URL}){RESET}")

    print(f"""
  {CYAN}╭{'─' * 50}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI{RESET} — Agentic Development                 {CYAN}│{RESET}
  {CYAN}│{RESET} {DIM}introspect • synthesize • build{RESET}                  {CYAN}│{RESET}
  {CYAN}╰{'─' * 50}╯{RESET}

  {DIM}cwd: {os.getcwd()}{RESET}
  {DIM}Multi-turn memory active. /new for fresh session.{RESET}
  {DIM}Multiline: paste directly, use triple quotes or empty line, or \\ continuation{RESET}
  {DIM}Improved interrupts: Ctrl-C once cancels operation, twice exits{RESET}
""")

    def _enable_bracketed_paste():
        """Enable bracketed paste mode for better paste handling."""
        try:
            # Enable bracketed paste mode (if terminal supports it)
            sys.stdout.write("\033[?2004h")
            sys.stdout.flush()
        except:
            pass
    
    def _disable_bracketed_paste():
        """Disable bracketed paste mode."""
        try:
            sys.stdout.write("\033[?2004l") 
            sys.stdout.flush()
        except:
            pass

    def _read_multiline_input():
        """Read input with multi-line support and improved interrupt handling.
        
        Supports multiple input modes:
        1. Automatic detection of pasted multiline content (contains newlines)
        2. Explicit multi-line mode: start with triple quotes
        3. Line continuation with trailing backslash
        4. Empty line to continue multiline input
        5. Robust inline paste handling (preserves typed prompt + pasted content)
        6. Graceful Ctrl-C handling during input
        """
        try:
            # Enable bracketed paste for better handling of mixed typed/pasted input
            _enable_bracketed_paste()
            
            # Check for cancellation before reading input
            if cancelled[0]:
                return ""
            
            first_line = input(f"  {GREEN}❯{RESET} ")
            
            # Check for cancellation after input
            if cancelled[0]:
                return ""
            
            # Clean up bracketed paste markers if present
            if first_line.startswith('\033[200~') and first_line.endswith('\033[201~'):
                # Remove bracketed paste markers
                first_line = first_line[6:-6]
                print(f"  {DIM}(cleaned paste markers){RESET}")
            
            # Debug: show what we actually received for long inputs
            if len(first_line) > 100:
                print(f"  {DIM}(received {len(first_line)} chars){RESET}")
            
            # Check if the input contains newlines (multiline pasted content)
            if '\n' in first_line:
                lines = first_line.splitlines()
                print(f"  {DIM}(detected multiline paste: {len(lines)} lines){RESET}")
                return first_line.strip()
            
            # Explicit multi-line mode: start with triple quotes
            if first_line.strip() in ('"""', "'''", '```'):
                delimiter = first_line.strip()
                print(f"  {DIM}(multi-line mode, end with {delimiter}){RESET}")
                lines = []
                while True:
                    try:
                        if cancelled[0]:
                            print(f"  {DIM}Multi-line input cancelled{RESET}")
                            return ""
                        line = input(f"  {DIM}…{RESET} ")
                        if line.strip() == delimiter:
                            break
                        lines.append(line)
                    except (EOFError, KeyboardInterrupt):
                        break
                result = '\n'.join(lines).strip()
                if lines and not cancelled[0]:
                    print(f"  {DIM}({len(lines)} lines){RESET}")
                return result if not cancelled[0] else ""
            
            # Check for empty line to start multiline input mode
            if not first_line.strip():
                print(f"  {DIM}(multiline mode - empty line to finish){RESET}")
                lines = []
                while True:
                    try:
                        if cancelled[0]:
                            print(f"  {DIM}Multi-line input cancelled{RESET}")
                            return ""
                        line = input(f"  {DIM}…{RESET} ")
                        if not line.strip():  # Empty line ends multiline input
                            break
                        lines.append(line)
                    except (EOFError, KeyboardInterrupt):
                        break
                result = '\n'.join(lines).strip()
                if lines and not cancelled[0]:
                    print(f"  {DIM}({len(lines)} lines){RESET}")
                return result if not cancelled[0] else ""
            
            # Line continuation with trailing backslash
            lines = [first_line]
            while lines and lines[-1].endswith('\\') and not cancelled[0]:
                lines[-1] = lines[-1][:-1]  # strip the backslash
                try:
                    continuation = input(f"  {DIM}…{RESET} ")
                    lines.append(continuation)
                except (EOFError, KeyboardInterrupt):
                    break
            
            return '\n'.join(lines).strip() if not cancelled[0] else ""
            
        except KeyboardInterrupt:
            # Let signal handler manage this
            return ""
        except Exception as e:
            print(f"  {YELLOW}Input error: {e}{RESET}")
            return ""
        finally:
            # Always disable bracketed paste when done
            _disable_bracketed_paste()

    while True:
        try:
            # Reset cancellation flag for each new input
            cancelled[0] = False
            interrupt_count[0] = 0
            
            if prompt_queue:
                prompt = prompt_queue.pop(0)
                print(f"  {GREEN}❯{RESET} {DIM}(stream deck){RESET} {prompt}")
            else:
                prompt = _read_multiline_input()
                
            # Check if cancelled during input
            if cancelled[0]:
                print(f"  {DIM}Input cancelled{RESET}")
                continue
                
        except (EOFError, KeyboardInterrupt):
            # This catches Ctrl-C during input() - let signal handler manage it
            continue
        except Exception as e:
            print(f"  {YELLOW}Input error: {e}{RESET}")
            continue
        if not prompt:
            continue
        if prompt in ("/quit", "/exit", "/q"):
            readline.write_history_file(histfile)
            _disable_bracketed_paste()
            break
        if prompt == "/new":
            session_id = None
            print(f"  {DIM}New session started.{RESET}\n")
            continue
        if prompt == "/sessions":
            _show_sessions()
            continue
        if prompt.startswith("/resume"):
            parts = prompt.split(None, 1)
            if len(parts) < 2:
                print(f"  {YELLOW}Usage: /resume <session_id>{RESET}\n")
            else:
                session_id = parts[1].strip()
                print(f"  {DIM}Resumed session: {session_id}{RESET}\n")
            continue

        # --- ! shell passthrough ---
        # Any input starting with ! is executed directly as a shell command.
        # Examples: !pwd  !ls -la  !git status  !cd ~/repos/nodes-bio
        # Special: !cd <path> updates the process working directory.
        if prompt.startswith("!"):
            shell_cmd = prompt[1:].strip()
            if not shell_cmd:
                print(f"  {YELLOW}Usage: !<command>  e.g. !pwd, !ls, !git status{RESET}\n")
                continue
            # Handle cd specially — subprocess cwd changes don't persist
            if shell_cmd.startswith("cd ") or shell_cmd == "cd":
                target = shell_cmd[3:].strip() or str(Path.home())
                target = str(Path(target).expanduser().resolve())
                try:
                    os.chdir(target)
                    print(f"  {DIM}{target}{RESET}\n")
                except Exception as e:
                    print(f"  {YELLOW}cd: {e}{RESET}\n")
                continue
            try:
                result_proc = subprocess.run(
                    shell_cmd,
                    shell=True,
                    text=True,
                    capture_output=False,   # stream directly to terminal
                )
                if result_proc.returncode != 0:
                    print(f"  {DIM}[exit {result_proc.returncode}]{RESET}")
            except Exception as e:
                print(f"  {YELLOW}Error: {e}{RESET}")
            print()
            continue

        print()

        # Check for cancellation before processing
        if cancelled[0]:
            continue
            
        if local_mode:
            result = _run_local(prompt, api_key, session_id, cancelled)
        else:
            result = _run_remote(prompt, session_id, cancelled)

        if not result or cancelled[0]:
            continue

        session_id = result.get("session_id", session_id)

        response = result.get("response", "")
        last_response[0] = response

        # Both local and remote modes stream output directly to stdout
        if response:
            print()
        print(f"  {DIM}session: {session_id}{RESET}\n")


def _api_reachable():
    import urllib.request
    try:
        urllib.request.urlopen(f"{API_URL.rsplit('/api', 1)[0]}/health", timeout=2)
        return True
    except Exception:
        try:
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            return True
        except Exception:
            return False


def _get_local_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    key_file = Path.home() / ".jarvis_cli" / "api_key"
    if key_file.exists():
        return key_file.read_text().strip()
    return None


def _run_local(prompt, api_key, session_id, cancelled_flag=None):
    """Run agent in-process with streaming text output and cancellation support."""
    import asyncio
    import threading

    if cancelled_flag is None:
        cancelled_flag = [False]

    sys.path.insert(0, str(AGENT_BACKEND))
    try:
        from jarvis_agent.agent import run_agent_stream
    except ImportError as e:
        print(f"  {YELLOW}❌ Cannot import agent: {e}{RESET}")
        print(f"  {DIM}Expected at: {AGENT_BACKEND}/jarvis_agent/{RESET}\n")
        return None

    SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinning = [True]
    got_first_event = [False]
    local_cancelled = [False]

    # ! commands bypass LLM — no thinking spinner
    is_shell_cmd = prompt.strip().startswith("!")

    def spin():
        i = 0
        while spinning[0]:
            if not got_first_event[0] and not is_shell_cmd:
                sys.stdout.write(f"\r  {DIM}{SPINNER[i % len(SPINNER)]} thinking...{RESET}  ")
                sys.stdout.flush()
            i += 1
            time.sleep(0.1)
        # Only clear spinner line if we were still showing it
        if not got_first_event[0] and not is_shell_cmd:
            sys.stdout.write("\r" + " " * 30 + "\r")
            sys.stdout.flush()

    spinner_thread = threading.Thread(target=spin, daemon=True)
    spinner_thread.start()

    result = {"response": "", "tool_calls": [], "session_id": session_id}
    streamed_text = []
    text_started = [False]

    async def _stream():
        async for event in run_agent_stream(prompt, api_key, session_id=session_id):
            # Check both local and global cancellation flags
            if local_cancelled[0] or cancelled_flag[0]:
                break
            etype = event.get("type")

            if not got_first_event[0]:
                got_first_event[0] = True
                sys.stdout.write("\r" + " " * 30 + "\r")
                sys.stdout.flush()

            if etype == "shell_output":
                # ! command — raw output, no divider, no LLM framing
                text = event.get("text", "")
                if text:
                    for line in text.splitlines():
                        sys.stdout.write(f"  {line}\n")
                    sys.stdout.flush()
                # Don't add to streamed_text (no response to track)

            elif etype == "text_delta":
                if not text_started[0]:
                    text_started[0] = True
                    sys.stdout.write(f"  {CYAN}{'━' * 60}{RESET}\n  ")
                sys.stdout.write(event["text"])
                sys.stdout.flush()
                streamed_text.append(event["text"])

            elif etype == "tool_call":
                # If we were streaming text, end that section
                if text_started[0]:
                    sys.stdout.write("\n")
                    text_started[0] = False
                    streamed_text.clear()
                name = event["name"]
                inp = event.get("input", {})
                result["tool_calls"].append({"name": name, "input": inp, "result": ""})
                if name == "file_write":
                    path = inp.get("path", "")
                    lines = inp.get("content", "").count("\n") + 1
                    print(f"  {MAGENTA}✎ {name}{RESET} {path} {DIM}({lines} lines){RESET}")
                elif name == "file_patch":
                    path = inp.get("path", "")
                    old = inp.get("old_str", "")[:80].replace("\n", "↵")
                    new = inp.get("new_str", "")[:80].replace("\n", "↵")
                    print(f"  {MAGENTA}✎ {name}{RESET} {path}")
                    print(f"  {DIM}  - {old}{RESET}")
                    print(f"  {GREEN}  + {new}{RESET}")
                else:
                    summary = _summarize_input(name, inp)
                    print(f"  {MAGENTA}⚡ {name}{RESET} {DIM}{summary}{RESET}")

            elif etype == "tool_result":
                preview = event.get("result", "")[:200].replace("\n", " ")
                print(f"  {DIM}  → {preview}{RESET}")

            elif etype == "done":
                result["session_id"] = event.get("session_id", session_id)
                result["iterations"] = event.get("iterations", 0)
                result["usage"] = event.get("usage", {})

    try:
        asyncio.run(_stream())
        spinning[0] = False
        spinner_thread.join(timeout=1.0)
        # Ensure streamed text ends with a newline
        if text_started[0]:
            sys.stdout.write("\n")
            sys.stdout.flush()
        if local_cancelled[0] or cancelled_flag[0]:
            print(f"\n  {YELLOW}⚡ Cancelled{RESET}\n")
        result["response"] = "".join(streamed_text)
        return result
    except KeyboardInterrupt:
        # Ctrl-C during generation sets local cancellation flag
        local_cancelled[0] = True
        spinning[0] = False
        spinner_thread.join(timeout=0.5)
        if text_started[0]:
            sys.stdout.write("\n")
        print(f"\n  {YELLOW}⚡ Generation cancelled{RESET}\n")
        result["response"] = "".join(streamed_text)
        return result
    except Exception as e:
        spinning[0] = False
        spinner_thread.join(timeout=0.5)
        print(f"  {YELLOW}❌ {e}{RESET}\n")
        return None


def _run_remote(prompt, session_id, cancelled_flag=None):
    """Call the API server with SSE streaming and cancellation support."""
    import urllib.request
    
    if cancelled_flag is None:
        cancelled_flag = [False]
        
    payload = json.dumps({"prompt": prompt, "session_id": session_id, "stream": True}).encode()
    result = {"response": "", "tool_calls": [], "session_id": session_id}
    streamed_text = []
    text_started = False

    try:
        req = urllib.request.Request(
            f"{API_URL}/run",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "event-stream" not in content_type:
                # Fallback: non-streaming JSON response
                data = json.loads(resp.read())
                return data

            # Parse SSE stream
            for raw_line in resp:
                # Check for cancellation during streaming
                if cancelled_flag[0]:
                    print(f"\n  {YELLOW}⚡ Remote streaming cancelled{RESET}")
                    break
                    
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")
                if etype == "shell_output":
                    # ! command — raw output, no divider
                    text = event.get("text", "")
                    if text:
                        for line in text.splitlines():
                            sys.stdout.write(f"  {line}\n")
                        sys.stdout.flush()
                elif etype == "text_delta":
                    if not text_started:
                        text_started = True
                        sys.stdout.write(f"  {CYAN}{'━' * 60}{RESET}\n  ")
                    sys.stdout.write(event["text"])
                    sys.stdout.flush()
                    streamed_text.append(event["text"])
                elif etype == "tool_call":
                    if text_started:
                        sys.stdout.write("\n")
                        text_started = False
                        streamed_text.clear()
                    name = event["name"]
                    inp = event.get("input", {})
                    result["tool_calls"].append({"name": name, "input": inp, "result": ""})
                    summary = _summarize_input(name, inp)
                    print(f"  {MAGENTA}⚡ {name}{RESET} {DIM}{summary}{RESET}")
                elif etype == "tool_result":
                    preview = event.get("result", "")[:200].replace("\n", " ")
                    print(f"  {DIM}  → {preview}{RESET}")
                elif etype == "done":
                    result["session_id"] = event.get("session_id", session_id)

        result["response"] = "".join(streamed_text)
        return result
    except Exception as e:
        print(f"  {YELLOW}❌ {e}{RESET}\n")
        return None


def _summarize_input(name, inp):
    if name == "file_read":
        return inp.get("path", "")
    elif name == "execute_bash":
        return inp.get("command", "")[:200]
    elif name == "glob_search":
        return inp.get("pattern", "")
    elif name == "grep_search":
        return f"/{inp.get('pattern', '')}/ in {inp.get('path', '.')}"
    elif name == "web_search":
        return inp.get("query", "")
    elif name == "list_directory":
        return inp.get("path", "")
    elif name == "symbol_search":
        return inp.get("name", "")
    elif name == "git":
        return inp.get("args", "")
    elif name == "synthesize":
        return inp.get("question", "")[:200]
    return str(inp)[:200]


def _summarize_tc(tc):
    return _summarize_input(tc.get("name", ""), tc.get("input", {}))


def _format_elapsed_time(elapsed_seconds):
    """Format elapsed time in a human-readable way."""
    if elapsed_seconds < 1:
        return f"{elapsed_seconds*1000:.0f}ms"
    elif elapsed_seconds < 60:
        return f"{elapsed_seconds:.1f}s"
    elif elapsed_seconds < 3600:
        minutes = int(elapsed_seconds // 60)
        seconds = int(elapsed_seconds % 60)
        return f"{minutes}m{seconds}s"
    else:
        hours = int(elapsed_seconds // 3600)
        minutes = int((elapsed_seconds % 3600) // 60)
        return f"{hours}h{minutes}m"


def _format_tool_input(name, inp):
    """Format tool input for replay display."""
    if name == "file_write":
        path = inp.get("path", "")
        content = inp.get("content", "")
        lines = content.count("\n") + 1
        preview = content[:100].replace("\n", "\\n") + ("..." if len(content) > 100 else "")
        return f"path='{path}' content='{preview}' ({lines} lines)"
    elif name == "file_patch":
        path = inp.get("path", "")
        old = inp.get("old_str", "")[:30].replace("\n", "\\n")
        new = inp.get("new_str", "")[:30].replace("\n", "\\n")
        return f"path='{path}' old='{old}...' new='{new}...'"
    elif name == "execute_bash":
        cmd = inp.get("command", "")
        wd = inp.get("working_dir", "")
        wd_str = f" (in {wd})" if wd else ""
        return f"command='{cmd}'{wd_str}"
    elif name == "file_read":
        path = inp.get("path", "")
        limit = inp.get("limit", "")
        offset = inp.get("offset", "")
        extras = []
        if limit: extras.append(f"limit={limit}")
        if offset: extras.append(f"offset={offset}")
        extra_str = f" {' '.join(extras)}" if extras else ""
        return f"path='{path}'{extra_str}"
    elif name == "list_directory":
        path = inp.get("path", "")
        depth = inp.get("depth", 1)
        return f"path='{path}' depth={depth}"
    elif name == "glob_search":
        pattern = inp.get("pattern", "")
        path = inp.get("path", "")
        path_str = f" in {path}" if path else ""
        return f"pattern='{pattern}'{path_str}"
    elif name == "grep_search":
        pattern = inp.get("pattern", "")
        path = inp.get("path", "")
        include = inp.get("include", "")
        parts = [f"pattern='/{pattern}/'"]
        if path: parts.append(f"path='{path}'")
        if include: parts.append(f"include='{include}'")
        return " ".join(parts)
    elif name == "web_search":
        query = inp.get("query", "")
        return f"query='{query}'"
    elif name == "web_fetch":
        url = inp.get("url", "")
        return f"url='{url}'"
    elif name == "symbol_search":
        name_arg = inp.get("name", "")
        path = inp.get("path", "")
        path_str = f" in {path}" if path else ""
        return f"name='{name_arg}'{path_str}"
    elif name == "git":
        args = inp.get("args", "")
        wd = inp.get("working_dir", "")
        wd_str = f" (in {wd})" if wd else ""
        return f"args='{args}'{wd_str}"
    elif name == "dev_pipeline":
        action = inp.get("action", "")
        branch = inp.get("branch", "")
        parts = [f"action='{action}'", f"branch='{branch}'"]
        if inp.get("message"): parts.append(f"message='{inp['message']}'")
        if inp.get("test_command"): parts.append(f"test_command='{inp['test_command']}'")
        if inp.get("target_branch"): parts.append(f"target_branch='{inp['target_branch']}'")
        return " ".join(parts)
    elif name == "synthesize":
        question = inp.get("question", "")[:60]
        return f"question='{question}...'"
    elif name == "auto_fix":
        command = inp.get("command", "")
        wd = inp.get("working_dir", "")
        wd_str = f" (in {wd})" if wd else ""
        return f"command='{command}'{wd_str}"
    elif name == "clipboard_paste":
        text = inp.get("text", "")[:40]
        paste = inp.get("paste", False)
        paste_str = " +paste" if paste else ""
        return f"text='{text}...'{paste_str}"
    else:
        # Generic fallback
        return str(inp)[:80]


def _format_tool_result(result):
    """Format tool result for replay display."""
    if not result:
        return f"{DIM}(no output){RESET}"
    
    # Truncate very long results
    if len(result) > 200:
        preview = result[:200].replace("\n", "↵")
        return f"{DIM}{preview}...{RESET}"
    else:
        preview = result.replace("\n", "↵")
        return f"{DIM}{preview}{RESET}"


def replay_last_task():
    """Replay the last completed task's tool calls as an animated demo."""
    if not COMPLETED_FILE.exists():
        print(f"  {YELLOW}No completed tasks found{RESET}")
        return
    
    try:
        completed = json.loads(COMPLETED_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        print(f"  {YELLOW}No completed tasks found{RESET}")
        return
    
    if not completed:
        print(f"  {YELLOW}No completed tasks found{RESET}")
        return
    
    # Find the last successful task with tool calls
    last_task = None
    for task in reversed(completed):
        if task.get("status") == "completed" and task.get("tool_calls"):
            last_task = task
            break
    
    if not last_task:
        print(f"  {YELLOW}No completed tasks with tool calls found{RESET}")
        return
    
    tool_calls = last_task.get("tool_calls", [])
    if not tool_calls:
        print(f"  {YELLOW}Last task has no tool calls to replay{RESET}")
        return
    
    # Show replay header
    task_preview = last_task.get("task", "")[:60] + ("..." if len(last_task.get("task", "")) > 60 else "")
    completed_time = datetime.fromisoformat(last_task["completed_at"]).strftime("%m/%d %H:%M:%S")
    elapsed_time = last_task.get("elapsed_time")
    elapsed_str = f" ({_format_elapsed_time(elapsed_time)})" if elapsed_time else ""
    
    print(f"""
  {CYAN}╭{'─' * 70}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI — Replay Mode{RESET}                                     {CYAN}│{RESET}
  {CYAN}╰{'─' * 70}╯{RESET}

  {GREEN}Replaying:{RESET} {task_preview}
  {GREEN}Completed:{RESET} {completed_time}{elapsed_str}
  {GREEN}Tool calls:{RESET} {len(tool_calls)}

  {DIM}Press Ctrl+C to stop replay{RESET}
""")
    
    try:
        for i, tool_call in enumerate(tool_calls, 1):
            name = tool_call.get("name", "unknown")
            inp = tool_call.get("input", {})
            result = tool_call.get("result", "")
            
            # Show tool call step
            print(f"  {CYAN}[{i}/{len(tool_calls)}]{RESET} {MAGENTA}⚡ {name}{RESET}")
            
            # Show formatted input
            formatted_input = _format_tool_input(name, inp)
            print(f"  {DIM}    {formatted_input}{RESET}")
            
            # Delay before showing result
            time.sleep(0.5)
            
            # Show result preview
            formatted_result = _format_tool_result(result)
            print(f"  {GREEN}    → {formatted_result}{RESET}")
            
            # Delay before next step
            if i < len(tool_calls):  # Don't delay after last step
                time.sleep(0.5)
                print()  # Add spacing between steps
        
        print(f"""
  {GREEN}✓ Replay complete{RESET}
  {DIM}Run 'jarvis-cli --status' to see more completed tasks{RESET}
""")
        
    except KeyboardInterrupt:
        print(f"""

  {YELLOW}⏹ Replay stopped{RESET}
""")
        return


def enqueue_task(task):
    """Add a task to the daemon queue."""
    # Ensure directory exists
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing queue
    queue = []
    if QUEUE_FILE.exists():
        try:
            queue = json.loads(QUEUE_FILE.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            queue = []
    
    # Add new task
    task_entry = {
        "id": str(uuid.uuid4()),
        "task": task,
        "created_at": datetime.now().isoformat(),
        "status": "queued"
    }
    queue.append(task_entry)
    
    # Save queue
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))
    
    print(f"  {GREEN}✓ Task queued:{RESET}")
    print(f"    {DIM}ID: {task_entry['id'][:8]}...{RESET}")
    print(f"    {task}")
    print()


def load_queue():
    """Load the task queue."""
    if not QUEUE_FILE.exists():
        return []
    try:
        return json.loads(QUEUE_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_queue(queue):
    """Save the task queue."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))


def log_completed_task(task_entry, response, error=None, elapsed_time=None, tool_calls=None):
    """Log a completed task to completed.json."""
    COMPLETED_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    completed = []
    if COMPLETED_FILE.exists():
        try:
            completed = json.loads(COMPLETED_FILE.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            completed = []
    
    completion_entry = {
        **task_entry,
        "completed_at": datetime.now().isoformat(),
        "response": response,
        "error": error,
        "elapsed_time": elapsed_time,
        "tool_calls": tool_calls or [],
        "status": "completed" if not error else "failed"
    }
    
    completed.append(completion_entry)
    
    # Keep only last 1000 completed tasks
    if len(completed) > 1000:
        completed = completed[-1000:]
    
    COMPLETED_FILE.write_text(json.dumps(completed, indent=2))


def _feature_on_main(priority: str) -> bool:
    """Check if a feature was actually committed to main by searching recent git log."""
    import subprocess
    try:
        # Check nodes-bio repo for recent commits on main mentioning the feature
        keywords = priority.lower().replace("(", "").replace(")", "").split()
        # Use the most distinctive keyword (longest, not a stop word)
        stop = {"a", "the", "for", "and", "or", "in", "on", "to", "of", "with"}
        search_terms = [w for w in keywords if w not in stop and len(w) > 3]
        if not search_terms:
            return True  # Can't verify, assume success

        # Search last 5 commits on main for any matching term
        r = subprocess.run(
            ["git", "log", "main", "--oneline", "-5"],
            capture_output=True, text=True, timeout=5,
            cwd=str(Path.home() / "repos" / "nodes-bio"),
        )
        if r.returncode != 0:
            return True  # Can't verify, assume success

        log_lower = r.stdout.lower()
        # Also check if EXECUTORS has a matching tool name
        for term in search_terms:
            tool_name = term.replace("-", "_").replace(" ", "_")
            if tool_name in log_lower or term in log_lower:
                return True

        # Also check live tools as a fallback
        live_tools, _ = _scan_inventory()
        for term in search_terms:
            tool_name = term.replace("-", "_").replace(" ", "_")
            if tool_name in live_tools:
                return True

        return False
    except Exception:
        return True  # Can't verify, assume success


def _auto_push_origin_main():
    """After a successful task, push committed changes to origin/main.

    The dev_pipeline tool merges feature branches into main locally; we mirror
    that to GitHub here so the remote stays in sync with autonomous work.
    Silently no-ops if the cwd isn't a git repo, has no 'origin' remote, or
    has nothing to push.
    """
    try:
        # Confirm we're inside a git repo
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return
        # Confirm 'origin' remote exists
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return
        # Push main to origin
        r = subprocess.run(
            ["git", "push", "origin", "main"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            print(f"    {GREEN}↑ pushed origin/main{RESET}")
        else:
            err = (r.stderr or r.stdout).strip().splitlines()[-1:] or [""]
            print(f"    {DIM}↑ push skipped: {err[0]}{RESET}")
    except Exception as e:
        print(f"    {DIM}↑ push error: {e}{RESET}")


def execute_task(task, session_id=None):
    """Execute a single task using the agent. Returns (response, error, elapsed, tool_calls, session_id)."""
    start_time = time.time()
    local_mode = not _api_reachable()
    
    if local_mode:
        api_key = _get_local_key()
        if not api_key:
            return None, "ANTHROPIC_API_KEY not set", 0, [], None
        
        # Import and run agent
        sys.path.insert(0, str(AGENT_BACKEND))
        try:
            from jarvis_agent.agent import run_agent
            import asyncio

            async def on_event(e):
                if e.get("type") == "tool_call":
                    name = e["name"]
                    inp = e.get("input", {})
                    summary = _summarize_input(name, inp)
                    print(f"    {MAGENTA}⚡ {name}{RESET} {DIM}{summary}{RESET}")
                elif e.get("type") == "tool_result":
                    preview = e.get("result", "")[:200].replace("\n", " ")
                    print(f"    {DIM}→ {preview}{RESET}")

            result = asyncio.run(run_agent(task, api_key, session_id=session_id, on_event=on_event))
            elapsed_time = time.time() - start_time
            tool_calls = result.get("tool_calls", [])
            sid = result.get("session_id")
            _auto_push_origin_main()
            return result.get("response", ""), None, elapsed_time, tool_calls, sid
        except Exception as e:
            elapsed_time = time.time() - start_time
            return None, str(e), elapsed_time, [], None
    else:
        # Use API
        import urllib.request
        payload = json.dumps({"prompt": task, "session_id": session_id}).encode()
        try:
            req = urllib.request.Request(
                f"{API_URL}/run",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())
            elapsed_time = time.time() - start_time
            tool_calls = result.get("tool_calls", [])
            sid = result.get("session_id")
            _auto_push_origin_main()
            return result.get("response", ""), None, elapsed_time, tool_calls, sid
        except Exception as e:
            elapsed_time = time.time() - start_time
            return None, str(e), elapsed_time, [], None


def show_log(count=5):
    """Show last N completed tasks in pretty format."""
    if not COMPLETED_FILE.exists():
        print(f"""
  {CYAN}╭{'─' * 50}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI Log{RESET}                                  {CYAN}│{RESET}
  {CYAN}╰{'─' * 50}╯{RESET}

  {DIM}No completed tasks found{RESET}
""")
        return

    try:
        completed = json.loads(COMPLETED_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        print(f"""
  {CYAN}╭{'─' * 50}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI Log{RESET}                                  {CYAN}│{RESET}
  {CYAN}╰{'─' * 50}╯{RESET}

  {DIM}No completed tasks found{RESET}
""")
        return

    if not completed:
        print(f"""
  {CYAN}╭{'─' * 50}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI Log{RESET}                                  {CYAN}│{RESET}
  {CYAN}╰{'─' * 50}╯{RESET}

  {DIM}No completed tasks found{RESET}
""")
        return

    # Get the last N tasks
    recent = completed[-count:] if completed else []
    total_count = len(completed)

    print(f"""
  {CYAN}╭{'─' * 70}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI Log{RESET} — Last {len(recent)} of {total_count} completed tasks{'':>23}{CYAN}│{RESET}
  {CYAN}╰{'─' * 70}╯{RESET}""")

    if not recent:
        print(f"  {DIM}No completed tasks found{RESET}\n")
        return

    for i, task in enumerate(recent, 1):
        # Status and timing info
        status_icon = "✅" if task.get("status") == "completed" else "❌" if task.get("status") == "failed" else "🔄"
        
        completed_time = None
        if task.get("completed_at"):
            try:
                completed_time = datetime.fromisoformat(task["completed_at"]).strftime("%m/%d %H:%M:%S")
            except ValueError:
                completed_time = task["completed_at"][:19]  # Fallback
        
        elapsed_time = task.get("elapsed_time")
        elapsed_str = f" ({_format_elapsed_time(elapsed_time)})" if elapsed_time else ""

        # Task content
        task_content = task.get("task", "")
        
        # Header line with status and time
        print(f"\n  {CYAN}[{len(recent) - i + (total_count - count)}]{RESET} {status_icon} {BOLD}{completed_time}{RESET}{elapsed_str}")
        
        # Task content, wrapped nicely
        if len(task_content) <= 66:
            print(f"      {task_content}")
        else:
            # Wrap long tasks
            words = task_content.split()
            current_line = "      "
            for word in words:
                if len(current_line) + len(word) + 1 > 72:
                    print(current_line)
                    current_line = f"      {word}"
                else:
                    if len(current_line) > 6:
                        current_line += f" {word}"
                    else:
                        current_line += word
            if len(current_line) > 6:
                print(current_line)

        # Tool calls summary
        tool_calls = task.get("tool_calls", [])
        if tool_calls:
            tool_names = [tc.get("name", "unknown") for tc in tool_calls]
            tool_summary = ", ".join(dict.fromkeys(tool_names))  # Remove duplicates, preserve order
            if len(tool_summary) > 60:
                tool_summary = tool_summary[:57] + "..."
            print(f"      {DIM}Tools: {tool_summary}{RESET}")

        # Error message if failed
        if task.get("status") == "failed" and task.get("error"):
            error_msg = task["error"]
            if len(error_msg) > 60:
                error_msg = error_msg[:57] + "..."
            print(f"      {YELLOW}Error: {error_msg}{RESET}")

    print(f"\n  {DIM}Use 'jarvis-cli --log N' to show more tasks{RESET}")
    if total_count > count:
        print(f"  {DIM}Showing {count} of {total_count} total completed tasks{RESET}")
    print()


def status():
    """Show iteration count, tools available, and last 5 completed tasks."""
    state = get_state()
    
    print(f"""
  {CYAN}╭{'─' * 60}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI Status{RESET}                                      {CYAN}│{RESET}
  {CYAN}╰{'─' * 60}╯{RESET}

  {GREEN}Iteration:{RESET} #{state['iteration']}
  {GREEN}Tools Available:{RESET} {len(CAPABILITIES)}""")
    
    # Show tools in a compact grid format
    tools = list(CAPABILITIES.keys())
    cols = 3
    for i in range(0, len(tools), cols):
        row = tools[i:i+cols]
        formatted_row = []
        for tool in row:
            formatted_row.append(f"{tool:<20}")
        print(f"    {CYAN}•{RESET} {' '.join(formatted_row)}")
    
    # Show last 5 completed tasks
    print(f"""
  {GREEN}Last 5 Completed Tasks:{RESET}""")
    
    if COMPLETED_FILE.exists():
        try:
            completed = json.loads(COMPLETED_FILE.read_text())
            recent = completed[-5:] if completed else []
            if recent:
                for i, task in enumerate(recent, 1):
                    status_icon = "✅" if task.get("status") == "completed" else "❌"
                    task_preview = task.get("task", "")[:45] + "..." if len(task.get("task", "")) > 45 else task.get("task", "")
                    completed_time = datetime.fromisoformat(task["completed_at"]).strftime("%m/%d %H:%M")
                    elapsed_time = task.get("elapsed_time")
                    elapsed_str = f" ({_format_elapsed_time(elapsed_time)})" if elapsed_time else ""
                    print(f"    {i}. {status_icon} {completed_time}{elapsed_str} {DIM}{task_preview}{RESET}")
            else:
                print(f"    {DIM}No completed tasks yet{RESET}")
        except (json.JSONDecodeError, ValueError):
            print(f"    {DIM}No completed tasks yet{RESET}")
    else:
        print(f"    {DIM}No completed tasks yet{RESET}")
    
    # Show current priority if any
    if state.get("next_priority"):
        print(f"""
  {GREEN}Current Priority:{RESET}
    {BOLD}{state['next_priority']}{RESET}""")
    
    # Show built features
    if state.get("built"):
        print(f"""
  {GREEN}Built Features ({len(state['built'])}):{RESET}""")
        for i, feature in enumerate(state["built"][-5:], 1):
            print(f"    {i}. {feature}")
        if len(state["built"]) > 5:
            print(f"    {DIM}... +{len(state['built']) - 5} more{RESET}")
    
    print()


def clear_queue():
    """Clear all tasks from the queue."""
    queue = load_queue()
    queued_count = len([t for t in queue if t.get("status") == "queued"])
    processing_count = len([t for t in queue if t.get("status") == "processing"])
    total_count = len(queue)
    
    if total_count == 0:
        print(f"  {DIM}Queue is already empty{RESET}")
        return
    
    # Save current queue as backup in completed.json for audit trail
    if queue:
        COMPLETED_FILE.parent.mkdir(parents=True, exist_ok=True)
        completed = []
        if COMPLETED_FILE.exists():
            try:
                completed = json.loads(COMPLETED_FILE.read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                completed = []
        
        # Mark cleared tasks as cancelled in completed log
        for task in queue:
            if task.get("status") in ("queued", "processing"):
                cancelled_entry = {
                    **task,
                    "cancelled_at": datetime.now().isoformat(),
                    "status": "cancelled",
                    "reason": "queue cleared"
                }
                completed.append(cancelled_entry)
        
        # Keep only last 1000 completed tasks
        if len(completed) > 1000:
            completed = completed[-1000:]
        
        COMPLETED_FILE.write_text(json.dumps(completed, indent=2))
    
    # Clear the queue
    save_queue([])
    
    print(f"  {GREEN}✓ Queue cleared:{RESET}")
    print(f"    📝 {queued_count} queued tasks removed")
    if processing_count > 0:
        print(f"    ⚡ {processing_count} processing tasks removed")
    print(f"    {DIM}Total: {total_count} tasks cleared and logged{RESET}")
    print()


def daemon_status():
    """Show daemon status and queue information."""
    # Check if daemon is running
    daemon_running = False
    if DAEMON_PID_FILE.exists():
        try:
            pid = int(DAEMON_PID_FILE.read_text().strip())
            # Check if process is actually running
            os.kill(pid, 0)  # Doesn't actually kill, just checks if process exists
            daemon_running = True
        except (OSError, ProcessLookupError, ValueError):
            # Process doesn't exist, clean up stale pid file
            DAEMON_PID_FILE.unlink(missing_ok=True)
    
    print(f"""
  {CYAN}╭{'─' * 50}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis Daemon Status{RESET}                            {CYAN}│{RESET}
  {CYAN}╰{'─' * 50}╯{RESET}

  {GREEN}Daemon:{RESET} {'🟢 Running' if daemon_running else '🔴 Stopped'}""")
    
    if daemon_running:
        pid = int(DAEMON_PID_FILE.read_text().strip())
        print(f"  {DIM}PID: {pid}{RESET}")
    
    # Show queue status
    queue = load_queue()
    queued_tasks = [t for t in queue if t.get("status") == "queued"]
    processing_tasks = [t for t in queue if t.get("status") == "processing"]
    
    print(f"""
  {GREEN}Queue:{RESET}
    📝 Queued: {len(queued_tasks)}
    ⚡ Processing: {len(processing_tasks)}""")
    
    # Show recent completed tasks
    if COMPLETED_FILE.exists():
        try:
            completed = json.loads(COMPLETED_FILE.read_text())
            recent = completed[-5:] if completed else []
            if recent:
                print(f"""
  {GREEN}Recent completions:{RESET}""")
                for task in recent:
                    status_icon = "✅" if task.get("status") == "completed" else "❌"
                    task_preview = task.get("task", "")[:45] + "..." if len(task.get("task", "")) > 45 else task.get("task", "")
                    completed_at = task.get("completed_at")
                    if completed_at:
                        completed_time = datetime.fromisoformat(completed_at).strftime("%H:%M:%S")
                    else:
                        completed_time = "unknown"
                    elapsed_time = task.get("elapsed_time")
                    elapsed_str = f" ({_format_elapsed_time(elapsed_time)})" if elapsed_time else ""
                    print(f"    {status_icon} {completed_time}{elapsed_str} {DIM}{task_preview}{RESET}")
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Show next few queued tasks
    if queued_tasks:
        print(f"""
  {GREEN}Next in queue:{RESET}""")
        for i, task in enumerate(queued_tasks[:3]):
            task_preview = task.get("task", "")[:60] + "..." if len(task.get("task", "")) > 60 else task.get("task", "")
            created_time = datetime.fromisoformat(task["created_at"]).strftime("%H:%M")
            print(f"    {i+1}. {created_time} {DIM}{task_preview}{RESET}")
        
        if len(queued_tasks) > 3:
            print(f"    {DIM}... +{len(queued_tasks) - 3} more{RESET}")
    
    print()


def _next_idle_task():
    """Pick the next self-improvement task when queue is empty."""
    # Check what's already been completed to avoid repeats
    completed_tasks = set()
    if COMPLETED_FILE.exists():
        try:
            completed = json.loads(COMPLETED_FILE.read_text())
            completed_tasks = {t.get("task", "")[:50] for t in completed}
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    idle_tasks = [
        "In ~/repos/jarvis-cli, review the test suite and add any missing edge case tests. Use dev_pipeline to ship.",
        "In ~/repos/jarvis-cli, add a --status command that shows iteration count, tools available, and last 5 completed tasks. Use dev_pipeline to ship.",
        "In ~/repos/nodes-bio, run the jarvis_next test suite and fix any failures. Use dev_pipeline to ship.",
        "In ~/repos/jarvis-cli, add elapsed time display to daemon task execution output. Use dev_pipeline to ship.",
        "In ~/repos/jarvis-cli, add a --clear-queue command that empties the queue. Use dev_pipeline to ship.",
    ]

    for task in idle_tasks:
        if task[:50] not in completed_tasks:
            return task
    return None


def _extract_python_definitions(file_path):
    """Extract function and class definitions from a Python file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        definitions = []
        
        # Only process top-level nodes to avoid duplicating class methods
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                definitions.append({
                    "type": "function",
                    "name": node.name,
                    "line": node.lineno,
                    "docstring": ast.get_docstring(node),
                    "args": [arg.arg for arg in node.args.args]
                })
            elif isinstance(node, ast.ClassDef):
                # Get class methods
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append({
                            "name": item.name,
                            "line": item.lineno,
                            "docstring": ast.get_docstring(item),
                            "args": [arg.arg for arg in item.args.args]
                        })
                
                definitions.append({
                    "type": "class",
                    "name": node.name,
                    "line": node.lineno,
                    "docstring": ast.get_docstring(node),
                    "methods": methods
                })
        
        return definitions
    except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
        return []


def _extract_javascript_definitions(file_path):
    """Extract function and class definitions from JavaScript/TypeScript files using simple regex."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        definitions = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines, 1):
            line = line.strip()
            
            # Function declarations: function name() {}
            if line.startswith('function ') and '(' in line:
                func_name = line.split('function ')[1].split('(')[0].strip()
                if func_name:
                    definitions.append({
                        "type": "function",
                        "name": func_name,
                        "line": i
                    })
            
            # Arrow functions: const name = () => {}
            elif ' = (' in line and '=>' in line:
                if line.startswith(('const ', 'let ', 'var ', 'export const ')):
                    func_name = line.split(' = (')[0].split()[-1]
                    if func_name:
                        definitions.append({
                            "type": "function",
                            "name": func_name,
                            "line": i
                        })
            
            # Class declarations: class Name {}
            elif line.startswith(('class ', 'export class ')):
                class_name = line.split('class ')[1].split()[0].strip('{')
                if class_name:
                    definitions.append({
                        "type": "class",
                        "name": class_name,
                        "line": i
                    })
        
        return definitions
    except (UnicodeDecodeError, FileNotFoundError):
        return []


def _should_index_file(file_path):
    """Check if a file should be included in the index."""
    path = Path(file_path)
    
    # Skip hidden files and directories
    if any(part.startswith('.') for part in path.parts):
        return False
    
    # Skip common build/cache directories
    skip_dirs = {
        'node_modules', '__pycache__', '.git', 'build', 'dist', 
        'target', 'venv', '.venv', 'env', '.env', 'coverage',
        '.pytest_cache', '.mypy_cache', '.tox'
    }
    if any(part in skip_dirs for part in path.parts):
        return False
    
    # Only index code files
    code_extensions = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java',
        '.cpp', '.c', '.h', '.hpp', '.php', '.rb', '.swift', '.kt'
    }
    return path.suffix.lower() in code_extensions


def _get_file_hash(file_path):
    """Get MD5 hash of file content to detect changes."""
    try:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except FileNotFoundError:
        return None


def codebase_index(directory_path, force_rebuild=False):
    """Build a JSON map of all files, functions, and classes in a directory."""
    directory_path = Path(directory_path).expanduser().resolve()
    
    if not directory_path.exists():
        return {"error": f"Directory not found: {directory_path}"}
    
    # Create index filename based on directory path
    dir_hash = hashlib.md5(str(directory_path).encode()).hexdigest()[:12]
    index_name = f"{directory_path.name}_{dir_hash}.json"
    index_file = Path.home() / ".jarvis_cli" / "indexes" / index_name
    
    # Load existing index if available
    existing_index = {}
    if index_file.exists() and not force_rebuild:
        try:
            existing_index = json.loads(index_file.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            existing_index = {}
    
    print(f"  {CYAN}📂 Indexing codebase:{RESET} {directory_path}")
    
    # Build file list
    files_to_process = []
    for file_path in directory_path.rglob('*'):
        if file_path.is_file() and _should_index_file(file_path):
            files_to_process.append(file_path)
    
    print(f"  {DIM}Found {len(files_to_process)} code files{RESET}")
    
    index = {
        "metadata": {
            "directory": str(directory_path),
            "indexed_at": datetime.now().isoformat(),
            "file_count": len(files_to_process),
            "jarvis_cli_version": "1.0"
        },
        "files": {}
    }
    
    processed = 0
    for file_path in files_to_process:
        rel_path = str(file_path.relative_to(directory_path))
        
        # Check if file changed since last index
        current_hash = _get_file_hash(file_path)
        if (not force_rebuild and rel_path in existing_index.get("files", {}) and 
            existing_index["files"][rel_path].get("hash") == current_hash):
            # File unchanged, copy existing data
            index["files"][rel_path] = existing_index["files"][rel_path]
            processed += 1
            continue
        
        # Process the file
        file_info = {
            "path": rel_path,
            "absolute_path": str(file_path),
            "hash": current_hash,
            "size": file_path.stat().st_size,
            "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            "definitions": []
        }
        
        # Extract definitions based on file type
        if file_path.suffix == '.py':
            file_info["definitions"] = _extract_python_definitions(file_path)
        elif file_path.suffix in {'.js', '.ts', '.jsx', '.tsx'}:
            file_info["definitions"] = _extract_javascript_definitions(file_path)
        
        index["files"][rel_path] = file_info
        processed += 1
        
        # Show progress for large codebases
        if processed % 50 == 0:
            print(f"  {DIM}  Processed {processed}/{len(files_to_process)} files...{RESET}")
    
    # Save index
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(json.dumps(index, indent=2))
    
    # Generate summary stats
    total_functions = sum(len([d for d in file_info["definitions"] if d["type"] == "function"]) 
                         for file_info in index["files"].values())
    total_classes = sum(len([d for d in file_info["definitions"] if d["type"] == "class"]) 
                       for file_info in index["files"].values())
    
    print(f"""  {GREEN}✓ Index complete:{RESET}
    📁 Files: {len(files_to_process)}
    🔧 Functions: {total_functions}
    📦 Classes: {total_classes}
    💾 Saved: {DIM}~/.jarvis_cli/indexes/{index_name}{RESET}""")
    
    return {
        "index_file": str(index_file),
        "files": len(files_to_process),
        "functions": total_functions,
        "classes": total_classes,
        "directory": str(directory_path)
    }


def daemon_mode():
    """Start daemon mode - polls queue and executes tasks."""
    # Check if already running
    if DAEMON_PID_FILE.exists():
        try:
            pid = int(DAEMON_PID_FILE.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            print(f"  {YELLOW}Daemon already running (PID {pid}){RESET}")
            return
        except (OSError, ProcessLookupError, ValueError):
            # Stale pid file
            DAEMON_PID_FILE.unlink(missing_ok=True)
    
    # Write our PID
    DAEMON_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAEMON_PID_FILE.write_text(str(os.getpid()))
    
    print(f"""
  {CYAN}╭{'─' * 50}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis Daemon Started{RESET}                           {CYAN}│{RESET}
  {CYAN}╰{'─' * 50}╯{RESET}

  {GREEN}●{RESET} Polling: {DIM}~/.jarvis_cli/queue.json{RESET}
  {GREEN}●{RESET} Logging: {DIM}~/.jarvis_cli/completed.json{RESET}
  {GREEN}●{RESET} PID: {DIM}{os.getpid()}{RESET}

  {DIM}Press Ctrl+C to stop{RESET}
""")
    
    # Set up signal handlers for clean shutdown
    shutdown_requested = [False]
    
    def signal_handler(signum, frame):
        if not shutdown_requested[0]:
            print(f"\n  {YELLOW}Graceful shutdown requested... (Ctrl-C again to force){RESET}")
            shutdown_requested[0] = True
        else:
            print(f"\n  {YELLOW}Forcing shutdown...{RESET}")
            DAEMON_PID_FILE.unlink(missing_ok=True)
            sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    last_queue_check = 0
    
    try:
        while not shutdown_requested[0]:
            current_time = time.time()
            
            # Check queue every 2 seconds
            if current_time - last_queue_check >= 2:
                last_queue_check = current_time
                
                queue = load_queue()
                queued_tasks = [t for t in queue if t.get("status") == "queued"]
                
                if not queued_tasks:
                    # Auto-enqueue a self-improvement task when idle
                    idle_task = _next_idle_task()
                    if idle_task:
                        print(f"  {DIM}Queue empty — auto-enqueuing:{RESET}")
                        enqueue_task(idle_task)
                        queue = load_queue()
                        queued_tasks = [t for t in queue if t.get("status") == "queued"]
                
                if queued_tasks:
                    # Process the first queued task
                    task_entry = queued_tasks[0]
                    task_id = task_entry["id"]
                    task = task_entry["task"]
                    
                    print(f"  {MAGENTA}⚡ Processing:{RESET} {task[:60]}{'...' if len(task) > 60 else ''}")
                    print(f"  {DIM}ID: {task_id[:8]}...{RESET}")
                    
                    # Mark as processing
                    for i, t in enumerate(queue):
                        if t["id"] == task_id:
                            queue[i]["status"] = "processing"
                            queue[i]["started_at"] = datetime.now().isoformat()
                            break
                    save_queue(queue)
                    
                    # Execute the task (wrap with action directive to prevent narration)
                    action_task = f"Execute this task completely using tools. Do NOT narrate what you plan to do — just do it. If the task asks you to write a file, call file_write immediately after gathering context. Task: {task}"
                    response, error, elapsed_time, tool_calls, _sid = execute_task(action_task)
                    
                    # Remove from queue and log completion
                    queue = [t for t in queue if t["id"] != task_id]
                    save_queue(queue)
                    log_completed_task(task_entry, response, error, elapsed_time, tool_calls)
                    
                    elapsed_str = _format_elapsed_time(elapsed_time)
                    if error:
                        print(f"  {YELLOW}❌ Failed ({elapsed_str}):{RESET} {error}")
                    else:
                        print(f"  {GREEN}✅ Completed ({elapsed_str}){RESET}")
                        if response:
                            # Show first few lines of response
                            lines = response.split('\n')[:3]
                            for line in lines:
                                if line.strip():
                                    print(f"  {DIM}  {line[:200]}{RESET}")
                            if len(response.split('\n')) > 3:
                                print(f"  {DIM}  ... (response logged){RESET}")
                    print()
            
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print(f"\n  {YELLOW}Daemon stopped{RESET}")
    finally:
        DAEMON_PID_FILE.unlink(missing_ok=True)


def main():
    """Main entry point with improved signal handling."""
    try:
        args = sys.argv[1:]

        if not args:
            interactive()
        elif args[0] in ("-h", "--help"):
            show_help()
        elif args[0] == "--status":
            status()
        elif args[0] == "--prioritize":
            prioritize()
        elif args[0] == "--build":
            build()
        elif args[0] == "--loop":
            loop()
        elif args[0] == "--daemon":
            daemon_mode()
        elif args[0] == "--daemon-status":
            daemon_status()
        elif args[0] == "--clear-queue":
            clear_queue()
        elif args[0] == "--replay":
            replay_last_task()
        elif args[0] == "--enqueue":
            if len(args) < 2:
                print(f"  {YELLOW}Usage: jarvis-cli --enqueue \"task description\"{RESET}")
                return
            task = " ".join(args[1:])
            enqueue_task(task)
        elif args[0] == "--index":
            if len(args) < 2:
                print(f"  {YELLOW}Usage: jarvis-cli --index <directory>{RESET}")
                return
            directory = args[1]
            codebase_index(directory)
        elif args[0] == "--index-force":
            if len(args) < 2:
                print(f"  {YELLOW}Usage: jarvis-cli --index-force <directory>{RESET}")
                return
            directory = args[1]
            codebase_index(directory, force_rebuild=True)
        elif args[0] == "--log":
            count = 5  # default
            if len(args) > 1:
                try:
                    count = int(args[1])
                    if count <= 0:
                        print(f"  {YELLOW}Count must be a positive integer{RESET}")
                        return
                except ValueError:
                    print(f"  {YELLOW}Invalid count: {args[1]}. Must be a number.{RESET}")
                    return
            show_log(count)
        elif args[0] == "--watch":
            directory = args[1] if len(args) > 1 else "."
            interval = 1.0
            if len(args) > 2:
                try:
                    interval = float(args[2])
                    if interval <= 0:
                        print(f"  {YELLOW}Interval must be > 0{RESET}")
                        return
                except ValueError:
                    print(f"  {YELLOW}Invalid interval: {args[2]}{RESET}")
                    return
            watch_directory(directory, interval)
        elif args[0] == "--dashboard":
            from jarvis_cli import dashboard
            port = dashboard.DEFAULT_PORT
            if len(args) > 1:
                try:
                    port = int(args[1])
                except ValueError:
                    print(f"  {YELLOW}Invalid port: {args[1]}{RESET}")
                    return
            dashboard.serve(port=port)
        elif args[0] == "--sessions":
            _show_sessions()
        elif args[0] == "--continue":
            if len(args) < 3:
                print(f"  {YELLOW}Usage: jarvis-cli --continue <session_id> \"prompt\"{RESET}")
                return
            sid = args[1]
            prompt = " ".join(args[2:])
            api_key = _get_local_key()
            if not api_key:
                print(f"  {YELLOW}❌ Set ANTHROPIC_API_KEY or ~/.jarvis_cli/api_key{RESET}")
                return
            result = _run_local(prompt, api_key, sid)
            if result:
                print(f"\n  {DIM}session: {result.get('session_id', sid)}{RESET}")
        else:
            # One-shot
            import urllib.request
            prompt = " ".join(args)
            payload = json.dumps({"prompt": prompt}).encode()
            try:
                req = urllib.request.Request(
                    f"{API_URL}/run", data=payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=300) as resp:
                    result = json.loads(resp.read())
                print(result.get("response", ""))
            except Exception as e:
                print(f"Error: {e}")
    except KeyboardInterrupt:
        print(f"\n  {DIM}Interrupted{RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"  {YELLOW}❌ Error: {e}{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
