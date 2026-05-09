# helpdesk-ui

A small FastAPI + React web app on top of [helpdesk-agent](../README.md):
ticket inbox, chat against the agent, inline tool-call rendering, and
the visual surface a customer would ship for an internal helpdesk
console.

The Python webapp lives at `helpdesk_ui/` (this directory's
`pyproject.toml`). The React frontend lives next to it at `frontend/`
and builds into `frontend/dist/`. Both share the workspace venv;
nothing ships in a wheel.

## Quickstart

From the repo root:

```bash
uv sync                                                     # workspace venv
( cd helpdesk-agent/helpdesk-ui/frontend && npm ci && npm run build )
uv run helpdesk-ui                                          # http://127.0.0.1:8000
```

The chat panel surfaces "no provider configured" inline as a red error
bubble; the header pill goes amber. Set one of:

```bash
# OpenAI direct
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4o            # optional; defaults to gpt-4o

# Azure OpenAI with API key
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_MODEL=gpt-4o

# Azure OpenAI with Entra ID  (also: uv sync --extra azure)
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
export AZURE_OPENAI_USE_AZURE_CREDENTIAL=true
export AZURE_OPENAI_MODEL=gpt-4o
```

`.env` (alongside `helpdesk-agent/.env`) is loaded automatically by
`uv run helpdesk-ui`.

## What's in the UI

* **3-pane resizable layout** — conversations sidebar, chat pane,
  ticket inbox. Drag the column dividers to resize.
* **Header bar** — wordmark, subtitle, provider pill (model name when
  configured, "no provider" when not), light/dark theme toggle
  (default dark; persists per tab).
* **Chat empty-state** with three pre-built prompts that name a
  ticket id; clicking populates the composer for review/tweak before
  sending. The named ticket auto-gets a "discussed in chat" badge in
  the inbox after submission.
* **Streaming agent reply** with a blinking cursor. Tool calls render
  inline under the bubble: a shimmering placeholder while the call is
  in flight, then the parsed args + result land atomically.
* **Stop button** while streaming aborts the open SSE connection. A
  `pagehide` listener also aborts on tab close so the server doesn't
  drain into a closed socket.
* **Retry on error** — the most recent failed turn shows a `[Retry]`
  button. Click rolls history back to the prior user message and
  resends.
* **Per-bubble model badge** — assistant bubbles snapshot the
  provider model at send time so older turns keep their original
  badge if the user switches provider.
* **Markdown** in both user and assistant bubbles (sanitised by
  DOMPurify, allowlist locked down to safe tags).
* **Ticket form** — manual creation, plus a "Load sample ticket"
  button that pre-fills with the seeded `T-1003`.

## Development (hot reload)

Two terminals:

```bash
# Terminal 1: API on :8000, auto-reload
uv run uvicorn helpdesk_ui.app:create_app --factory --reload --port 8000

# Terminal 2: Vite on :5173 with /api proxied to :8000
cd helpdesk-agent/helpdesk-ui/frontend && npm run dev
```

Open <http://127.0.0.1:5173>.

## Lint, typecheck, build

Frontend (Biome + tsc):

```bash
cd helpdesk-agent/helpdesk-ui/frontend
npm run lint        # biome check .
npm run typecheck   # tsc -b --noEmit
npm run check       # both
npm run format      # biome --write
npm run build       # tsc + vite build → frontend/dist/
```

Backend (from the repo root):

```bash
uv run ruff check
uv run ty check
uv run pytest helpdesk-agent/helpdesk-ui/tests
```

## API

| Method   | Path                          | Purpose                                                |
| -------- | ----------------------------- | ------------------------------------------------------ |
| `GET`    | `/api/tickets`                | List inbox (newest first by `mtime_ns`).               |
| `GET`    | `/api/tickets/sample`         | Seeded sample ticket (T-1003); 404 if absent.          |
| `GET`    | `/api/tickets/{id}`           | Full envelope as the agent ingests it.                 |
| `POST`   | `/api/tickets`                | File a new ticket; allocates next `T-####`.            |
| `DELETE` | `/api/tickets/{id}`           | Remove a ticket.                                       |
| `POST`   | `/api/chat/stream`            | One agent turn, streamed as Server-Sent Events.        |
| `GET`    | `/api/health`                 | Provider readout (model, kind) + package versions.     |
| `GET`    | `/api/tools`                  | Manifest tools `[{name, description, parameters}]`.    |

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

Server is stateless per turn. The browser sends the full conversation
each time; the server reconstructs an `AgentSession`, seeds it into
the `InMemoryHistoryProvider` source key, and runs one turn against a
fresh agent. Conversations live in the browser's `sessionStorage`,
scoped per tab.

SSE event vocabulary, in order of arrival:

* `delta` — `{text}`. Append to the open assistant bubble.
* `tool_call` — `{call_id, name}`. UI shows a pending placeholder.
* `tool_result` — `{call_id, name, arguments, result}`. Parsed args
  and result arrive together; UI hydrates the placeholder atomically.
* `final` — `{reply, tool_calls}`. Authoritative. UI replaces the
  bubble's accumulated text with `reply` and snapshots the canonical
  tool-call list.
* `error` — `{detail}`. Terminal failure surfaced as an inline red
  bubble.

Schemas in [`helpdesk_ui/agent_runner.py`](helpdesk_ui/agent_runner.py).

## Layout

```
helpdesk-agent/helpdesk-ui/
├── pyproject.toml            # name = "helpdesk-ui"; depends on helpdesk-agent
├── helpdesk_ui/              # Python package
│   ├── app.py                # FastAPI factory + `helpdesk-ui` entrypoint
│   ├── schemas.py            # ChatMessage / Ticket models
│   ├── agent_runner.py       # run_turn + TurnEvent union + SSE serialisation
│   └── routes/
│       ├── chat.py           # POST /api/chat/stream + get_agent_factory dep
│       ├── meta.py           # /api/health + /api/tools
│       └── tickets.py        # ticket CRUD
├── frontend/
│   ├── biome.json            # lint + format config
│   ├── package.json          # vite, react, biome, marked, dompurify, …
│   ├── vite.config.ts        # outDir: ./dist (Vite default)
│   ├── dist/                 # built bundle (gitignored)
│   └── src/
│       ├── main.tsx          # <StrictMode><ErrorBoundary><App/>…
│       ├── App.tsx           # 3-pane resizable layout
│       ├── api.ts            # typed fetch + streamChat
│       ├── styles.css        # Tailwind v4 @theme tokens (dark + light)
│       ├── lib/
│       │   ├── conversations.ts  # useSyncExternalStore over sessionStorage
│       │   ├── markdown.ts       # marked + DOMPurify wrapper
│       │   ├── sse.ts            # AbortSignal-aware SSE parser
│       │   ├── time.ts           # Intl.RelativeTimeFormat
│       │   ├── tools.ts          # /api/tools fetch-once cache
│       │   └── useTheme.ts       # data-theme on <html>
│       └── components/       # AppHeader, ChatPanel, MessageList, ToolCallCard, …
└── tests/                    # LLM-free unit tests
```

## Environment

| Variable                                | Effect                                                                              |
| --------------------------------------- | ----------------------------------------------------------------------------------- |
| `HELPDESK_TICKET_DIR`                   | Backing dir for the live ticket store. Default: `helpdesk-agent/data/tickets/`.     |
| `HELPDESK_UI_STATIC_DIR`                | Override for the React bundle location. Default: `frontend/dist/`.                  |
| `HELPDESK_WEB_HOST`                     | Bind host. Default `127.0.0.1`.                                                     |
| `HELPDESK_WEB_PORT`                     | Bind port. Default `8000`.                                                          |
| `OPENAI_API_KEY`                        | Plain OpenAI provider.                                                              |
| `OPENAI_MODEL`                          | Plain OpenAI model. Default `gpt-4o`.                                               |
| `AZURE_OPENAI_ENDPOINT`                 | Azure OpenAI endpoint URL.                                                          |
| `AZURE_OPENAI_API_KEY`                  | Azure OpenAI API-key auth.                                                          |
| `AZURE_OPENAI_USE_AZURE_CREDENTIAL`     | When truthy, use `DefaultAzureCredential` (Entra ID) instead of an API key.         |
| `AZURE_OPENAI_MODEL`                    | Deployment / model id for Azure OpenAI.                                             |
| `AZURE_OPENAI_API_VERSION`              | Optional Azure API version override.                                                |

## Tooling

* **Biome** for the frontend (lint, format, organise imports). One
  config in `biome.json`; CSS picks up Tailwind directives.
* **Tailwind CSS v4** (no `tailwind.config.js`) — semantic tokens in
  `styles.css` `@theme {}` block; light theme overrides under
  `[data-theme="light"]`. `tailwind-scrollbar` plugin for the four
  scrollers.
* **uv workspace** — both `helpdesk-agent` and `helpdesk-ui` are
  members; one `uv sync` from the repo root pulls everything.
* **Dependabot** updates for `uv`, `npm`, `github-actions`, and
  `pre-commit`. CI runs Python `{3.11, 3.12, 3.13}` plus the frontend
  `lint → typecheck → build` job.

## Security posture

* **CSP**: `default-src 'self'; script-src 'self'; style-src 'self';
  frame-ancestors 'none'`. No CDN scripts.
* **Markdown sanitised** by DOMPurify with an explicit allowlist;
  `script`, `style`, and event-handler attributes blocked.
* **Body size limit** of 256 KB on every API request to bound runaway
  message histories.
* **Provider env vars** never logged; the agent factory reads them via
  `helpdesk_agent.providers.detect_provider()` which never raises if
  any individual var is missing — it returns `None` and the route
  surfaces the configuration error to the UI in-band.
