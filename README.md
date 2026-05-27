# Jarvis CLI

Self-improving agentic development CLI powered by AI Synthesis.

## Install

```bash
pip install -e .
```

## Daemon Mode

Jarvis CLI supports daemon mode for background task processing:

### Commands

- `jarvis-cli --daemon` - Start daemon (polls `~/.jarvis_cli/queue.json`)
- `jarvis-cli --enqueue "task"` - Add task to queue
- `jarvis-cli --daemon-status` - Show status and queue info

### Usage Example

```bash
# Start the daemon in background
jarvis-cli --daemon &

# Queue some tasks
jarvis-cli --enqueue "list files in ~/repos"
jarvis-cli --enqueue "check git status in all repos"

# Check status
jarvis-cli --daemon-status
```

### Files

- `~/.jarvis_cli/queue.json` - Task queue
- `~/.jarvis_cli/completed.json` - Completed task log  
- `~/.jarvis_cli/daemon.pid` - Daemon process ID

## Architecture

- **This repo**: CLI entry point, UI, Stream Deck integration, self-improvement loop
- **nodes-bio-clean**: Agent brain (tools, executor, memory) at `app/backend/nodesbio/services/jarvis_next/`

## Usage

```bash
jarvis-cli              # Interactive mode
jarvis-cli --help       # Show tools + backlog
jarvis-cli --loop       # Self-improvement cycle
```

## Requirements

- `~/.jarvis_cli/api_key` — Anthropic API key
- `~/repos/nodes-bio-clean/` — Agent backend code
