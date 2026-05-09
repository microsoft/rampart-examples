import type { ChatMessage, ToolCall } from "@/lib/conversations";
import { consumeSSE } from "@/lib/sse";

export interface TicketSummary {
  id: string;
  subject: string;
  from: string;
  preview: string;
  mtime_ns: number;
}

export interface TicketDetail {
  id: string;
  subject: string;
  from: string;
  body: string;
  mtime_ns: number;
  rendered: string;
}

export interface TicketCreate {
  subject: string;
  from: string;
  body: string;
}

export interface HealthResponse {
  agent_configured: boolean;
  provider: "openai" | "azure-openai-key" | "azure-openai-entra" | "fake" | null;
  model: string | null;
  versions: Record<string, string>;
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, string>;
}

export function getHealth(): Promise<HealthResponse> {
  return fetch("/api/health").then((r) => asJson<HealthResponse>(r));
}

export function getTools(): Promise<ToolInfo[]> {
  return fetch("/api/tools").then((r) => asJson<ToolInfo[]>(r));
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = (await res.json()) as { detail?: string };
      if (data?.detail) detail = data.detail;
    } catch {
      /* body wasn't JSON */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export function listTickets(): Promise<TicketSummary[]> {
  return fetch("/api/tickets").then((r) => asJson<TicketSummary[]>(r));
}

export function getTicket(id: string): Promise<TicketDetail> {
  return fetch(`/api/tickets/${encodeURIComponent(id)}`).then((r) => asJson<TicketDetail>(r));
}

export function createTicket(payload: TicketCreate): Promise<TicketDetail> {
  return fetch("/api/tickets", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  }).then((r) => asJson<TicketDetail>(r));
}

export async function deleteTicket(id: string): Promise<void> {
  const r = await fetch(`/api/tickets/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(`${r.status}`);
}

export async function sampleTicket(): Promise<TicketDetail | null> {
  const r = await fetch("/api/tickets/sample");
  if (r.status === 404) return null;
  return asJson<TicketDetail>(r);
}

// --- Streaming chat -----------------------------------------------------

export interface ChatHandlers {
  onDelta: (text: string) => void;
  onToolCall: (callId: string, name: string) => void;
  /** ``arguments`` and ``result`` arrive together. */
  onToolResult: (
    callId: string,
    name: string,
    args: Record<string, unknown>,
    result: string | null,
  ) => void;
  onFinal: (reply: string, toolCalls: ToolCall[]) => void;
  onError: (detail: string) => void;
}

export interface StreamHandle {
  abort(): void;
}

interface WireToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result: string | null;
}

export function streamChat(messages: readonly ChatMessage[], handlers: ChatHandlers): StreamHandle {
  const controller = new AbortController();
  void run(messages, handlers, controller.signal);
  return { abort: () => controller.abort() };
}

async function run(
  messages: readonly ChatMessage[],
  handlers: ChatHandlers,
  signal: AbortSignal,
): Promise<void> {
  // The wire format only carries (role, content, optional tool_calls).
  // The local "error" role is UI-only; never sent to the server.
  const wire = messages
    .filter((m) => m.role !== "error")
    .map((m) => ({
      role: m.role,
      content: m.content,
      tool_calls: m.toolCalls ?? null,
    }));
  let res: Response;
  try {
    res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "text/event-stream",
      },
      body: JSON.stringify({ messages: wire }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    handlers.onError((err as Error).message || "network error");
    return;
  }
  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: string };
      if (data?.detail) detail = data.detail;
    } catch {
      /* not json */
    }
    handlers.onError(detail);
    return;
  }
  try {
    await consumeSSE(
      res.body,
      (event, data) => {
        const obj = (data ?? {}) as Record<string, unknown>;
        switch (event) {
          case "delta":
            handlers.onDelta(String(obj.text ?? ""));
            break;
          case "tool_call":
            handlers.onToolCall(String(obj.call_id ?? ""), String(obj.name ?? ""));
            break;
          case "tool_result":
            handlers.onToolResult(
              String(obj.call_id ?? ""),
              String(obj.name ?? ""),
              (obj.arguments as Record<string, unknown> | undefined) ?? {},
              (obj.result as string | null) ?? null,
            );
            break;
          case "final": {
            const tc = (obj.tool_calls as WireToolCall[] | undefined) ?? [];
            handlers.onFinal(
              String(obj.reply ?? ""),
              tc.map((t) => ({
                name: t.name,
                arguments: t.arguments ?? {},
                result: t.result ?? null,
              })),
            );
            break;
          }
          case "error":
            handlers.onError(String(obj.detail ?? "stream error"));
            break;
        }
      },
      signal,
    );
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    handlers.onError((err as Error).message || "stream failed");
  }
}
