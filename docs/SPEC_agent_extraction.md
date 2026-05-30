# SPEC: Extract Jarvis Agent into Standalone Service

**Status:** Draft  
**Goal:** Untangle the jarvis agent from nodes-bio into `~/repos/jarvis-agent/`

---

## 1. What Moves (the agent brain)

Everything in `nodes-bio/app/backend/nodesbio/services/jarvis_next/`:

| File | Purpose |
|------|---------|
| `agent.py` | Agentic loop (run_agent, run_agent_stream, _call_claude, _call_bedrock) |
| `executor.py` | 23 tool implementations + EXECUTORS registry |
| `tools.py` | Tool schemas (Anthropic tool_use format) |
| `memory.py` | Session persistence (~/.jarvis_next/sessions/) |
| `semantic_search.py` | Embedding-based codebase search |
| `tenant.py` | API key resolution (Secrets Manager) |

Plus a new thin FastAPI server to expose it as an HTTP service.

## 2. What Stays in nodes-bio

- `api/routers/jarvis_next.py` → becomes a **proxy** to the standalone service
- `api/routers/jarvis_gateway.py` → platform-specific jarvis features (synthesis UI, sharing)
- `api/routers/jarvis_generate.py` → MedMap generation (platform feature, not agent)
- `api/routers/jarvis_api_keys.py` → platform user key management
- `api/routers/jarvis_workflows.py` → platform workflows
- `api/routers/jarvis_export.py` → export features
- `api/routers/jarvis_upload.py` → file upload for platform

## 3. New Repo Structure

```
~/repos/jarvis-agent/
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── README.md
├── jarvis_agent/
│   ├── __init__.py
│   ├── server.py          # FastAPI app, SSE streaming endpoint
│   ├── agent.py           # from jarvis_next/agent.py
│   ├── executor.py        # from jarvis_next/executor.py
│   ├── tools.py           # from jarvis_next/tools.py
│   ├── memory.py          # from jarvis_next/memory.py
│   ├── semantic_search.py # from jarvis_next/semantic_search.py
│   └── keys.py            # from jarvis_next/tenant.py (renamed)
└── tests/
    ├── test_tools.py      # from nodes-bio tests
    └── test_agent.py
```

## 4. API Surface (server.py)

```python
# POST /run — non-streaming (daemon/loop use)
# POST /stream — SSE streaming (interactive use)
# GET /health
# GET /sessions — list sessions
# GET /sessions/{id} — get session
# DELETE /sessions/{id} — delete session
```

Both Rust TUI and nodes-bio connect via HTTP:

```
┌──────────────┐     HTTP/SSE      ┌─────────────────┐
│  Rust TUI    │ ────────────────▶ │  jarvis-agent   │
└──────────────┘                   │  :8100          │
                                   └─────────────────┘
┌──────────────┐     HTTP/SSE      ┌─────────────────┐
│  nodes-bio   │ ────────────────▶ │  jarvis-agent   │
│  :8000       │                   │  :8100          │
└──────────────┘                   └─────────────────┘

┌──────────────┐     direct import (legacy, temporary)
│  jarvis-cli  │ ────────────────▶ jarvis_agent.*
│  (Python)    │
└──────────────┘
```

## 5. Migration Steps (zero downtime)

### Phase 1: Copy + standalone server (1 hour)
1. `mkdir ~/repos/jarvis-agent && cd ~/repos/jarvis-agent && git init`
2. Copy `jarvis_next/*.py` → `jarvis_agent/`
3. Write `server.py` (FastAPI with /run and /stream endpoints)
4. Write `requirements.txt` (httpx, boto3, asyncpg, bcrypt, anthropic deps)
5. Write `Dockerfile`
6. Test: `uvicorn jarvis_agent.server:app --port 8100`

### Phase 2: Point clients at new service
1. Update `jarvis-cli` `JARVIS_CLI_API` env var → `http://localhost:8100`
2. Update `nodes-bio/api/routers/jarvis_next.py` → proxy to `:8100`
3. Verify both paths work

### Phase 3: Remove from nodes-bio
1. Delete `nodesbio/services/jarvis_next/` directory
2. Delete `tests/unit/test_jarvis_*` (moved to jarvis-agent)
3. Update imports in any remaining references
4. Keep proxy router as thin HTTP forwarder

### Phase 4: Deploy
1. jarvis-agent gets its own ECS service (or runs locally for dev)
2. nodes-bio staging/prod points at jarvis-agent service URL
3. Rust TUI points at same URL

## 6. Environment & Config

```env
# jarvis-agent/.env
PORT=8100
AWS_REGION=us-east-1
ANTHROPIC_API_KEY=sk-ant-...  # or use Secrets Manager
BEDROCK_MODEL_ID=us.anthropic.claude-opus-4-7
SESSIONS_DIR=~/.jarvis_next/sessions
```

## 7. What Changes in jarvis-cli (Python, temporary)

During migration, `jarvis-cli` can either:
- **Option A:** Import directly from `~/repos/jarvis-agent/jarvis_agent/` (change AGENT_BACKEND path)
- **Option B:** Call HTTP API at localhost:8100

Option A is fastest for migration. Option B is the final state.

## 8. Risks

- **Secrets Manager access:** jarvis-agent needs AWS creds for API keys. Currently inherited from nodes-bio's ECS task role.
- **Database access:** `db_query` tool connects to the platform DB. May need connection string passed as config.
- **Circular dependency:** nodes-bio calls jarvis-agent, jarvis-agent's `db_query` tool queries nodes-bio's DB. Acceptable for now.
