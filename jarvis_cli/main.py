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
from datetime import datetime
from pathlib import Path

# Agent code lives in the nodes-bio-clean repo
AGENT_BACKEND = Path.home() / "repos" / "nodes-bio-clean" / "app" / "backend"

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
}

BACKLOG = [
    "streaming output in CLI (SSE display)",
    "conversation memory (multi-turn context)",
    "test runner tool (run tests, parse failures)",
    "image/screenshot analysis tool",
    "database query tool (read-only SQL)",
    "codebase indexing (semantic search over project)",
    "multi-file refactor (rename across codebase)",
]


def get_state():
    if LOOP_STATE.exists():
        return json.loads(LOOP_STATE.read_text())
    return {"iteration": 0, "built": [], "next_priority": None}


def save_state(state):
    LOOP_STATE.write_text(json.dumps(state, indent=2))


def show_help():
    state = get_state()
    print(f"""
  {CYAN}╭{'─' * 56}╮{RESET}
  {CYAN}│{RESET} {BOLD}Jarvis CLI{RESET} — Self-Improving Agentic Development         {CYAN}│{RESET}
  {CYAN}│{RESET} {DIM}iteration #{state['iteration']} • {len(CAPABILITIES)} tools active{RESET}              {CYAN}│{RESET}
  {CYAN}╰{'─' * 56}╯{RESET}

  {GREEN}Current Tools:{RESET}""")
    for name, desc in CAPABILITIES.items():
        print(f"    {CYAN}•{RESET} {name:<20} {DIM}{desc}{RESET}")

    print(f"""
  {GREEN}Backlog ({len(BACKLOG)} features):{RESET}""")
    for i, feat in enumerate(BACKLOG[:5], 1):
        marker = f"{MAGENTA}→{RESET}" if i == 1 else " "
        print(f"   {marker} {i}. {feat}")
    if len(BACKLOG) > 5:
        print(f"     {DIM}... +{len(BACKLOG) - 5} more{RESET}")

    if state.get("next_priority"):
        print(f"""
  {YELLOW}Next priority (via synthesis):{RESET}
    {BOLD}{state['next_priority']}{RESET}""")

    print(f"""
  {GREEN}Commands:{RESET}
    jarvis-cli                 Interactive agent mode
    jarvis-cli --help          Show this + trigger priority loop
    jarvis-cli --prioritize    Synthesize next feature priority
    jarvis-cli --build         Send priority to kiro-cli for building
    jarvis-cli --loop          Full cycle: prioritize → build → repeat
    jarvis-cli --status        Show iteration count, tools available, last 5 tasks
    jarvis-cli --daemon        Start daemon mode (polls queue, executes tasks)
    jarvis-cli --enqueue "task" Add task to daemon queue
    jarvis-cli --daemon-status Show daemon status and queue
""")


def prioritize():
    """Use multi-LLM synthesis to pick the highest-value next feature."""
    import urllib.request

    state = get_state()
    current_tools = ", ".join(CAPABILITIES.keys())
    backlog_text = "\n".join(f"- {f}" for f in BACKLOG)
    built_text = ", ".join(state["built"]) if state["built"] else "none yet"

    question = f"""You are prioritizing features for an AI coding agent called Jarvis CLI.

Current tools: {current_tools}
Already built: {built_text}

Remaining backlog:
{backlog_text}

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
        response = BACKLOG[0]
        print(f"  {DIM}(API unavailable, using default priority){RESET}")

    state["next_priority"] = response.strip()[:200]
    state["iteration"] += 1
    save_state(state)

    print(f"  {GREEN}✓ Priority set:{RESET}")
    print(f"    {BOLD}{state['next_priority']}{RESET}\n")
    return state["next_priority"]


def build():
    """Send the prioritized task to kiro-cli via clipboard → terminal paste."""
    state = get_state()
    priority = state.get("next_priority")
    if not priority:
        print(f"  {YELLOW}No priority set. Run: jarvis-cli --prioritize{RESET}")
        return

    task = f"Build this feature for Jarvis CLI (in ~/repos/nodes-bio-clean/app/backend/nodesbio/services/jarvis_next/): {priority}"

    TASK_FILE.write_text(task)
    subprocess.run(["pbcopy"], input=task.encode(), check=True)

    subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate'], capture_output=True)
    time.sleep(0.3)
    subprocess.run(["osascript", "-e", '''
        tell application "System Events"
            keystroke "v" using command down
            delay 0.1
            keystroke return
        end tell
    '''], capture_output=True)

    print(f"  {GREEN}✓ Task sent to kiro-cli:{RESET}")
    print(f"    {DIM}{task[:100]}{RESET}\n")

    state["built"].append(priority[:50])
    state["next_priority"] = None
    save_state(state)


def loop():
    """Full self-improvement cycle."""
    print(f"  {CYAN}Starting self-improvement loop...{RESET}\n")
    prioritize()
    build()
    print(f"  {DIM}Kiro is building. Run 'jarvis-cli --help' to check progress.{RESET}")


def interactive():
    """Interactive agent mode with multi-turn memory."""
    import urllib.request
    import threading

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
""")

    while True:
        try:
            if prompt_queue:
                prompt = prompt_queue.pop(0)
                print(f"  {GREEN}❯{RESET} {DIM}(stream deck){RESET} {prompt}")
            else:
                prompt = input(f"  {GREEN}❯{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            readline.write_history_file(histfile)
            print(f"\n\n  {DIM}Goodbye.{RESET}\n")
            break
        if not prompt:
            continue
        if prompt in ("/quit", "/exit", "/q"):
            readline.write_history_file(histfile)
            break
        if prompt == "/new":
            session_id = None
            print(f"  {DIM}New session started.{RESET}\n")
            continue

        print()

        if local_mode:
            result = _run_local(prompt, api_key, session_id)
        else:
            result = _run_remote(prompt, session_id)

        if not result:
            continue

        session_id = result.get("session_id", session_id)

        for tc in result.get("tool_calls", []):
            print(f"  {MAGENTA}⚡ {tc['name']}{RESET} {DIM}{_summarize_tc(tc)}{RESET}")

        response = result.get("response", "")
        last_response[0] = response
        print(f"\n  {CYAN}{'━' * 60}{RESET}")
        for line in response.split("\n"):
            print(f"  {line}")
        print(f"\n  {DIM}session: {session_id}{RESET}\n")


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


def _run_local(prompt, api_key, session_id):
    """Run agent in-process with live streaming of tool events."""
    import asyncio
    import threading

    sys.path.insert(0, str(AGENT_BACKEND))
    try:
        from nodesbio.services.jarvis_next.agent import run_agent
    except ImportError as e:
        print(f"  {YELLOW}❌ Cannot import agent: {e}{RESET}")
        print(f"  {DIM}Expected at: {AGENT_BACKEND}/nodesbio/services/jarvis_next/{RESET}\n")
        return None

    SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinning = [True]
    got_first_event = [False]

    def spin():
        i = 0
        while spinning[0]:
            if not got_first_event[0]:
                sys.stdout.write(f"\r  {DIM}{SPINNER[i % len(SPINNER)]} thinking...{RESET}  ")
                sys.stdout.flush()
            i += 1
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * 30 + "\r")
        sys.stdout.flush()

    spinner_thread = threading.Thread(target=spin, daemon=True)
    spinner_thread.start()

    async def on_event(e):
        if not got_first_event[0]:
            got_first_event[0] = True
            sys.stdout.write("\r" + " " * 30 + "\r")
            sys.stdout.flush()
        if e.get("type") == "tool_call":
            name = e["name"]
            inp = e.get("input", {})
            if name == "file_write":
                path = inp.get("path", "")
                lines = inp.get("content", "").count("\n") + 1
                print(f"  {MAGENTA}✎ {name}{RESET} {path} {DIM}({lines} lines){RESET}")
            elif name == "file_patch":
                path = inp.get("path", "")
                old = inp.get("old_str", "")[:40].replace("\n", "↵")
                new = inp.get("new_str", "")[:40].replace("\n", "↵")
                print(f"  {MAGENTA}✎ {name}{RESET} {path}")
                print(f"  {DIM}  - {old}{RESET}")
                print(f"  {GREEN}  + {new}{RESET}")
            else:
                summary = _summarize_input(name, inp)
                print(f"  {MAGENTA}⚡ {name}{RESET} {DIM}{summary}{RESET}")
        elif e.get("type") == "tool_result":
            preview = e.get("result", "")[:100].replace("\n", " ")
            print(f"  {DIM}  → {preview}{RESET}")

    try:
        result = asyncio.run(run_agent(prompt, api_key, session_id=session_id, on_event=on_event))
        spinning[0] = False
        spinner_thread.join(timeout=0.5)
        return result
    except Exception as e:
        spinning[0] = False
        spinner_thread.join(timeout=0.5)
        print(f"  {YELLOW}❌ {e}{RESET}\n")
        return None


def _run_remote(prompt, session_id):
    """Call the API server."""
    import urllib.request
    payload = json.dumps({"prompt": prompt, "session_id": session_id}).encode()
    try:
        req = urllib.request.Request(
            f"{API_URL}/run",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  {YELLOW}❌ {e}{RESET}\n")
        return None


def _summarize_input(name, inp):
    if name == "file_read":
        return inp.get("path", "")
    elif name == "execute_bash":
        return inp.get("command", "")[:80]
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
        return inp.get("question", "")[:60]
    return str(inp)[:60]


def _summarize_tc(tc):
    return _summarize_input(tc.get("name", ""), tc.get("input", {}))


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


def log_completed_task(task_entry, response, error=None):
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
        "status": "completed" if not error else "failed"
    }
    
    completed.append(completion_entry)
    
    # Keep only last 1000 completed tasks
    if len(completed) > 1000:
        completed = completed[-1000:]
    
    COMPLETED_FILE.write_text(json.dumps(completed, indent=2))


def execute_task(task):
    """Execute a single task using the agent."""
    local_mode = not _api_reachable()
    
    if local_mode:
        api_key = _get_local_key()
        if not api_key:
            return None, "ANTHROPIC_API_KEY not set"
        
        # Import and run agent
        sys.path.insert(0, str(AGENT_BACKEND))
        try:
            from nodesbio.services.jarvis_next.agent import run_agent
            import asyncio

            async def on_event(e):
                if e.get("type") == "tool_call":
                    name = e["name"]
                    inp = e.get("input", {})
                    summary = _summarize_input(name, inp)
                    print(f"    {MAGENTA}⚡ {name}{RESET} {DIM}{summary}{RESET}")
                elif e.get("type") == "tool_result":
                    preview = e.get("result", "")[:80].replace("\n", " ")
                    print(f"    {DIM}→ {preview}{RESET}")

            result = asyncio.run(run_agent(task, api_key, on_event=on_event))
            return result.get("response", ""), None
        except Exception as e:
            return None, str(e)
    else:
        # Use API
        import urllib.request
        payload = json.dumps({"prompt": task}).encode()
        try:
            req = urllib.request.Request(
                f"{API_URL}/run",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())
            return result.get("response", ""), None
        except Exception as e:
            return None, str(e)


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
                    task_preview = task.get("task", "")[:50] + "..." if len(task.get("task", "")) > 50 else task.get("task", "")
                    completed_time = datetime.fromisoformat(task["completed_at"]).strftime("%m/%d %H:%M")
                    print(f"    {i}. {status_icon} {completed_time} {DIM}{task_preview}{RESET}")
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
                    task_preview = task.get("task", "")[:50] + "..." if len(task.get("task", "")) > 50 else task.get("task", "")
                    completed_time = datetime.fromisoformat(task["completed_at"]).strftime("%H:%M:%S")
                    print(f"    {status_icon} {completed_time} {DIM}{task_preview}{RESET}")
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
        "In ~/repos/nodes-bio-clean, run the jarvis_next test suite and fix any failures. Use dev_pipeline to ship.",
        "In ~/repos/jarvis-cli, add elapsed time display to daemon task execution output. Use dev_pipeline to ship.",
        "In ~/repos/jarvis-cli, add a --clear-queue command that empties the queue. Use dev_pipeline to ship.",
    ]

    for task in idle_tasks:
        if task[:50] not in completed_tasks:
            return task
    return None


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
    def signal_handler(signum, frame):
        print(f"\n  {YELLOW}Shutting down daemon...{RESET}")
        DAEMON_PID_FILE.unlink(missing_ok=True)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    last_queue_check = 0
    
    try:
        while True:
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
                    
                    # Execute the task
                    response, error = execute_task(task)
                    
                    # Remove from queue and log completion
                    queue = [t for t in queue if t["id"] != task_id]
                    save_queue(queue)
                    log_completed_task(task_entry, response, error)
                    
                    if error:
                        print(f"  {YELLOW}❌ Failed:{RESET} {error}")
                    else:
                        print(f"  {GREEN}✅ Completed{RESET}")
                        if response:
                            # Show first few lines of response
                            lines = response.split('\n')[:3]
                            for line in lines:
                                if line.strip():
                                    print(f"  {DIM}  {line[:80]}{RESET}")
                            if len(response.split('\n')) > 3:
                                print(f"  {DIM}  ... (response logged){RESET}")
                    print()
            
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print(f"\n  {YELLOW}Daemon stopped{RESET}")
    finally:
        DAEMON_PID_FILE.unlink(missing_ok=True)


def main():
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
    elif args[0] == "--enqueue":
        if len(args) < 2:
            print(f"  {YELLOW}Usage: jarvis-cli --enqueue \"task description\"{RESET}")
            return
        task = " ".join(args[1:])
        enqueue_task(task)
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


if __name__ == "__main__":
    main()
