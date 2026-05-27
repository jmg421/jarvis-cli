# Jarvis CLI

Self-improving agentic development CLI powered by AI Synthesis.

## Install

```bash
pip install -e .
```

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
