# helpdesk-ui

Small FastAPI + React app on top of [helpdesk-agent](../README.md). Lets a
viewer chat with the agent in their browser, file tickets through a form,
and watch the agent's tool calls render inline under each reply — the
visual surface a customer would ship for an internal helpdesk console.

The Python webapp lives at `helpdesk_ui` (this directory's
`pyproject.toml`). The React frontend lives next to it under
`frontend/` and builds into `frontend/dist/`. Both are part of the
workspace's single venv; nothing ships in a wheel.

## Quickstart

From the repo root:

```bash
uv sync                                                     # workspace venv
( cd helpdesk-agent/helpdesk-ui/frontend && npm ci && npm run build )
uv run helpdesk-ui                                          # http://127.0.0.1:8000
```

Forget the `npm run build` step? The server still boots and serves a
"frontend not built" page with the exact command to run, so you find
out before hitting record.

The chat panel surfaces "no provider configured" inline as a red error
message in the conversation. Set one of:

```bash
# OpenAI direct
export OPENAI_API_KEY=...

# Azure OpenAI with API key
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_MODEL=gpt-4o

# Azure OpenAI with Entra ID  (also: pip install -e '.[azure,ui]')
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
export AZURE_OPENAI_USE_AZURE_CREDENTIAL=true
export AZURE_OPENAI_MODEL=gpt-4o
```

`.env` (alongside `helpdesk-agent/.env`) is loaded automatically.

## Development (hot reload)

Two terminals:

```bash
# Terminal 1: API on :8000, auto-reload
uv run uvicorn helpdesk_ui.app:create_app --factory --reload --port 8000

# Terminal 2: Vite on :5173 with /api proxied to :8000
cd helpdesk-agent/helpdesk-ui/frontend && npm run dev
```

Open <http://127.0.0.1:5173>.

## API

| Method   | Path                          | Purpose                                       |
| -------- | ----------------------------- | --------------------------------------------- |
| `GET`    | `/api/tickets`                | List inbox (newest first by `mtime_ns`).      |
| `GET`    | `/api/tickets/sample`         | Seeded sample ticket (T-1003); 404 if absent. |
| `GET`    | `/api/tickets/{id}`           | Full envelope as the agent ingests it.        |
| `POST`   | `/api/tickets`                | File a new ticket; allocates next `T-####`.   |
| `DELETE` | `/api/tickets/{id}`           | Remove a ticket.                              |
| `POST`   | `/api/chat/stream`            | One agent turn, streamed as SSE.              |

`POST /api/chat/stream` body:

```json
{
  "messages": [
    { "role": "user", "content": "first prompt" },
    { "role": "assistant", "content": "...", "tool_calls": [] },
    { "role": "user", "content": "the new prompt" }
  ]
}
```

The server is stateless per turn: every request contains the full
conversation, replayed into a fresh `agent_framework.AgentSession`.
Conversations live in the browser's `sessionStorage`, scoped per tab.

SSE event vocabulary: `delta`, `tool_call`, `tool_result`, `final`,
`error`. Schemas in [`helpdesk_ui/agent_runner.py`](helpdesk_ui/agent_runner.py).

## Layout

```
helpdesk-agent/helpdesk-ui/
├── pyproject.toml            # name = "helpdesk-ui"; depends on helpdesk-agent
├── helpdesk_ui/              # Python package
│   ├── app.py                # FastAPI factory + `helpdesk-ui` entrypoint
│   ├── schemas.py
│   ├── agent_runner.py       # run_turn + TurnEvent + SSE serialisation
│   └── routes/{tickets,chat}.py
├── frontend/                 # NOT a Python package
│   ├── package.json
│   ├── vite.config.ts        # outDir: ./dist (Vite default)
│   ├── dist/                 # built bundle (gitignored)
│   └── src/
│       ├── App.tsx           # 3-pane grid: sidebar | chat | tickets
│       ├── api.ts
│       ├── lib/{conversations,sse,markdown}.ts
│       └── components/
└── tests/                    # unit tests; LLM-free
```

## Environment

| Variable                    | Effect                                                              |
| --------------------------- | ------------------------------------------------------------------- |
| `HELPDESK_TICKET_DIR`       | Backing dir for the live ticket store. Default: `helpdesk-agent/data/tickets/`. |
| `HELPDESK_UI_STATIC_DIR`    | Override for the React bundle location. Default: `frontend/dist/`.  |
| `HELPDESK_WEB_HOST`         | Bind host. Default `127.0.0.1`.                                      |
| `HELPDESK_WEB_PORT`         | Bind port. Default `8000`.                                          |
