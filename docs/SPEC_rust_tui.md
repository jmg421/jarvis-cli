# SPEC: Jarvis CLI — Rust TUI Refactor

**Decision:** Option 3 — Rust TUI as streaming SSE client to existing FastAPI backend  
**Confidence:** 3/5 models unanimous (Claude, Gemini, +1)  
**Rationale:** The problem is "Python can't do terminal UX correctly." The solution is "Replace the terminal UX layer." Keep all 23 tools, agent loop, and Bedrock integration in Python.

---

## Architecture

```
┌─────────────────────┐         SSE stream          ┌──────────────────────────┐
│   Rust TUI Binary   │ ──────────────────────────▶  │  FastAPI Backend (:8000)  │
│                     │                              │                          │
│  • crossterm raw    │  POST /api/jarvis-cli/run    │  • run_agent_stream()    │
│  • bracket paste    │  Accept: text/event-stream   │  • 23 tools              │
│  • ratatui render   │                              │  • Bedrock/Anthropic     │
│  • Ctrl-C/Esc      │  ◀──────────────────────────  │  • Memory/sessions       │
│  • session mgmt    │         SSE events            │                          │
└─────────────────────┘                              └──────────────────────────┘
```

## Why Not the Others

- **Option 1 (subprocess):** Fragile IPC, still need Python installed, two processes to manage
- **Option 2 (reimplement in Rust):** 23 tools × months of work, duplicated logic, drift risk

## Crate Dependencies

```toml
[dependencies]
tokio = { version = "1", features = ["full"] }
crossterm = "0.28"
ratatui = "0.29"
reqwest = { version = "0.12", features = ["stream"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
dirs = "5"
clap = { version = "4", features = ["derive"] }
```

## SSE Event Protocol

The backend already emits these events from `run_agent_stream()`:

```json
{"type": "text_delta", "text": "..."}
{"type": "tool_call", "name": "file_write", "input": {...}}
{"type": "tool_result", "name": "file_write", "result": "..."}
{"type": "done", "session_id": "...", "iterations": N, "usage": {...}}
```

## Key UX Features

1. **Bracket paste mode** — detect `\e[200~`..`\e[201~`, show "N lines ▸ Press Tab to expand"
2. **Streaming text** — render markdown as it arrives (bold, headers, code blocks)
3. **Tool call display** — `⚡ tool_name args` with `→ result preview`
4. **Ctrl-C soft cancel** — send cancel signal, stop rendering, keep session
5. **Double Ctrl-C hard exit** — quit immediately
6. **Session persistence** — `--continue <id>`, `--sessions` list
7. **Daemon mode** — `--daemon`, `--enqueue`, `--daemon-status` (same as Python)

## Phased Implementation

### Phase 1: Minimal viable TUI (1-2 days)
- `cargo init jarvis-tui`
- Single-line input with crossterm raw mode
- POST to backend, stream SSE response
- Print text_delta events to terminal
- Ctrl-C to quit

### Phase 2: Full UX (2-3 days)
- Bracket paste detection + collapsed display
- Tool call rendering (⚡ icons, → results)
- Markdown rendering (bold, code blocks, headers)
- Session ID tracking, `--continue`
- History (save/load with dirs crate)

### Phase 3: Feature parity (2-3 days)
- `--daemon` mode (poll queue.json, process tasks)
- `--loop` (prioritize → build cycle)
- `--enqueue`, `--status`, `--log`, `--help`
- `--replay` (animated tool call replay)

### Phase 4: Polish
- Tab completion for /commands
- Syntax highlighting in code blocks
- Responsive layout (adapt to terminal width)
- Single binary distribution (cargo install)

## Migration Path

1. Build Rust TUI alongside Python CLI
2. Both use same backend, same sessions, same queue
3. Once Rust TUI has parity, deprecate Python CLI
4. Python code remains as the agent backend (FastAPI)

## File Structure

```
jarvis-tui/
├── Cargo.toml
├── src/
│   ├── main.rs          # CLI args, dispatch
│   ├── tui.rs           # Terminal setup, input loop
│   ├── sse.rs           # SSE client, event parsing
│   ├── render.rs        # Output formatting, markdown
│   ├── session.rs       # Session management
│   └── daemon.rs        # Background task processing
```
