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
from pathlib import Path

# Agent code lives in the nodes-bio-clean repo
AGENT_BACKEND = Path.home() / "repos" / "nodes-bio-clean" / "app" / "backend"

API_URL = os.environ.get("JARVIS_CLI_API", "http://localhost:8000/api/jarvis-cli")
TASK_FILE = Path("/tmp/jarvis-cli-task.txt")
LOOP_STATE = Path.home() / ".jarvis_cli_state.json"

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


def main():
    args = sys.argv[1:]

    if not args:
        interactive()
    elif args[0] in ("-h", "--help"):
        show_help()
    elif args[0] == "--prioritize":
        prioritize()
    elif args[0] == "--build":
        build()
    elif args[0] == "--loop":
        loop()
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
