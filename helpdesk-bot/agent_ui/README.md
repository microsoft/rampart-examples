# HelpdeskBot Agent UI

A small web console for chatting with the HelpdeskBot agent in a
browser and inspecting every tool it calls along the way. Useful
for demoing the agent end-to-end without touching `pytest`.

Each agent reply has a collapsible **Tool calls** panel that shows
the tool name, arguments, and returned text — bit-identical to what
the RAMPART tests assert on at the tool-call boundary.

---

## Install

From `rampart-examples/helpdesk-bot/`:

```bash
# uv (recommended)
uv venv --python 3.13
uv pip install -e '.[agent-ui]'

# or plain pip
python -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell
# source .venv/bin/activate           # macOS / Linux
pip install -e '.[agent-ui]'
```

Add `[azure]` if you'll authenticate to Azure OpenAI with Entra ID:

```bash
uv pip install -e '.[agent-ui,azure]'
```

---

## Configure a model provider

Copy the template and fill in **one** provider block:

```bash
cp .env.example .env        # macOS / Linux
Copy-Item .env.example .env # Windows PowerShell
```

| Provider | Required env vars |
|----------|-------------------|
| OpenAI direct | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| Azure OpenAI (key) | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_MODEL` |
| Azure OpenAI (Entra ID) | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_MODEL`, `AZURE_OPENAI_USE_AZURE_CREDENTIAL=true` (then `az login`) |

> ⚠️ For Azure OpenAI, `AZURE_OPENAI_ENDPOINT` must be the bare
> resource URL — `https://<resource>.openai.azure.com` — with no
> trailing path. `AZURE_OPENAI_MODEL` is the *deployment name* you
> created in the resource, not the underlying model id.

The server auto-loads `.env` on startup.

---

## Run it

```bash
python -m agent_ui
```

Then open <http://127.0.0.1:8000>. Press `Ctrl+C` to stop.

To bind on a different host or port:

```bash
# Windows PowerShell
$env:HELPDESK_AGENT_UI_HOST = "0.0.0.0"
$env:HELPDESK_AGENT_UI_PORT = "8080"
python -m agent_ui

# macOS / Linux
HELPDESK_AGENT_UI_HOST=0.0.0.0 HELPDESK_AGENT_UI_PORT=8080 python -m agent_ui
```

---

## Notes

- Conversation state is per-browser, in-memory only. Click **Reset
  conversation** to start fresh; restarting the server wipes
  everything.
- Tickets shown in the sidebar live at `data/tickets/` in the repo
  root. Drop a new JSON in there and hit **↻** to make it visible
  to the agent, or use the **New ticket** form in the sidebar.
- The **New ticket** form's *Load poisoned sample* button prefills
  an indirect-prompt-injection body so the before/after RAMPART
  demo is a two-click flow.
- Bind only to `127.0.0.1` for casual demos — there is no auth.

---

## HTTP API

| Method   | Path                  | Purpose                                                  |
|----------|-----------------------|----------------------------------------------------------|
| `GET`    | `/`                   | Single-page UI.                                          |
| `GET`    | `/api/tickets`        | List tickets in the store.                               |
| `GET`    | `/api/tickets/{id}`   | Fetch one ticket's full subject / from / body.           |
| `POST`   | `/api/tickets`        | File a new ticket; auto-allocates the next `T-####`.     |
| `DELETE` | `/api/tickets/{id}`   | Remove a ticket from the store.                          |
| `POST`   | `/api/chat`           | Send `{message}`; returns `{reply, tool_calls}`.         |
| `POST`   | `/api/reset`          | Clear the current browser's agent + session.             |
| `GET`    | `/api/history`        | Replay prior turns so the UI can rehydrate on reload.    |

`POST /api/tickets` body:

```json
{ "subject": "Forgot password", "sender": "alex@contoso.com", "body": "Hi…" }
```
