# Jarvis CLI

Self-improving agentic development CLI — Rust TUI streaming to a FastAPI agent backend.

## Quick Start

```bash
# Build the Rust TUI
cargo build --release
cp target/release/jarvis-cli /usr/local/bin/jarvis

# Start the agent backend (auto-started by default)
jarvis                  # launches daemon + opens TUI
```

## Usage

```bash
jarvis                              # Interactive TUI (auto-starts daemon)
jarvis --continue <session_id>      # Resume a session
jarvis --sessions                   # List recent sessions
jarvis --prompt "task"              # Non-interactive: send one prompt, print, exit
echo "task" | jarvis                # Pipe stdin as a prompt (scripting mode)
cat spec.md | jarvis                # Feed a file as the prompt
jarvis --enqueue "task desc"        # Queue a background task
jarvis --status                     # Show daemon + queue status
jarvis --no-daemon                  # Skip auto-start (daemon already running)
```

## TUI Commands

| Command | Description |
|---------|-------------|
| `/new` | Start a fresh session |
| `/sessions` | List recent sessions |
| `/resume <id>` | Resume session by ID |
| `/session` | Show current session ID |
| `/delete [id]` | Delete session (default: current) |
| `/cost` | Show token usage & estimated cost |
| `/clear` | Clear the terminal screen |
| `/help` | Show command reference |
| `/quit` | Exit (also Ctrl-C twice) |

## Line Editing

Full readline-style editing in the input prompt:

| Key | Action |
|-----|--------|
| `←` / `→` | Move cursor left/right |
| `Ctrl-A` / `Home` | Jump to start of line |
| `Ctrl-E` / `End` | Jump to end of line |
| `Ctrl-W` | Delete word before cursor |
| `Ctrl-U` | Delete from cursor to start |
| `Ctrl-K` | Delete from cursor to end |
| `Ctrl-Left` / `Alt-Left` | Jump word left |
| `Ctrl-Right` / `Alt-Right` | Jump word right |
| `↑` / `↓` | Navigate history |
| `Backspace` | Delete char before cursor |
| `Delete` | Delete char at cursor |
| `Esc` | Cancel paste preview |

Multi-line paste is detected automatically — shows a preview with line count before sending.

## Token Cost Tracking

After each response, a compact footer shows:

```
session: abc123  ·  12.3k↑ 4.5k↓  ~$0.1087  14↺
```

The `↺` count is the number of tool-use iterations the agent made. Use `/cost` to see the cumulative total for the session.

Cost rates (Claude Sonnet 3.7):
- Input: $3/M tokens
- Output: $15/M tokens  
- Cache read: $0.30/M tokens
- Cache write: $3.75/M tokens

## Pipe / Non-interactive Mode

Any time stdin is not a TTY (piped data), or `--prompt` is passed, jarvis runs in single-shot mode:

```bash
# Ask a question and get the answer
jarvis --prompt "what's the git log for ~/repos/jarvis-cli?"

# Pipe a spec file and have the agent implement it
cat SPEC.md | jarvis

# Chain with other tools
git diff HEAD~1 | jarvis --prompt "summarize this diff"

# Use in scripts — exits with code 1 on error
jarvis --prompt "run the test suite" && echo "done"
```

Session ID and token stats are printed to stderr, response text goes to stdout — composable.

## Daemon & Queue

```bash
jarvis --enqueue "refactor auth module"   # add to queue
jarvis --status                           # show daemon PID + queue depth
```

Queue files: `~/.jarvis_cli/queue.json`, `~/.jarvis_cli/completed.json`

## Architecture

```
jarvis-cli (Rust TUI)
    │  SSE streaming
    ▼
jarvis-agent (FastAPI @ :8100)
    │  tool_use
    ▼
Claude Sonnet + tools (file ops, bash, git, search, QPU, etc.)
```

- **Agent backend**: `~/repos/jarvis-agent/` (standalone FastAPI service)
- **Tool definitions**: `~/repos/nodes-bio/app/backend/nodesbio/services/jarvis_next/`
- **History**: `~/.jarvis_cli/history` (last 500 entries)
- **API key**: `~/.jarvis_cli/api_key`
