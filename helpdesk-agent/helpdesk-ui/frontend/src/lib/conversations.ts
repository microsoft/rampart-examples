import { useCallback, useEffect, useState } from "react";

export interface ToolCall {
  callId?: string;
  name: string;
  arguments: Record<string, unknown>;
  result: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  toolCalls?: ToolCall[];
  model?: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  messages: ChatMessage[];
  referencedTickets?: string[];
}

const KEY_CONVERSATIONS = "helpdesk-ui:conversations:v1";
const CHANNEL_NAME = "helpdesk-ui:conversations";

const TITLE_MAX = 40;

function readAll(): Conversation[] {
  try {
    const raw = sessionStorage.getItem(KEY_CONVERSATIONS);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as Conversation[]) : [];
  } catch {
    return [];
  }
}

function writeAll(list: Conversation[]): void {
  try {
    sessionStorage.setItem(KEY_CONVERSATIONS, JSON.stringify(list));
  } catch {
    /* quota or disabled storage; mutations are best-effort */
  }
  postChange();
}

let channel: BroadcastChannel | null = null;
function getChannel(): BroadcastChannel | null {
  if (channel) return channel;
  if (typeof BroadcastChannel === "undefined") return null;
  channel = new BroadcastChannel(CHANNEL_NAME);
  return channel;
}

function postChange(): void {
  getChannel()?.postMessage({ type: "change" });
}

export const conversations = {
  list(): Conversation[] {
    const all = readAll();
    return [...all].sort((a, b) => b.createdAt - a.createdAt);
  },
  get(id: string): Conversation | null {
    return readAll().find((c) => c.id === id) ?? null;
  },
  create(): Conversation {
    const conversation: Conversation = {
      id: crypto.randomUUID(),
      title: "New chat",
      createdAt: Date.now(),
      messages: [],
    };
    writeAll([...readAll(), conversation]);
    return conversation;
  },
  appendMessage(id: string, msg: Omit<ChatMessage, "id"> & { id?: string }): void {
    const all = readAll();
    const idx = all.findIndex((c) => c.id === id);
    const conv = all[idx];
    if (!conv) return;
    const stamped: ChatMessage = { ...msg, id: msg.id ?? crypto.randomUUID() };
    conv.messages = [...conv.messages, stamped];
    if (conv.title === "New chat" && msg.role === "user" && msg.content.trim().length > 0) {
      const trimmed = msg.content.trim().slice(0, TITLE_MAX);
      conv.title = trimmed.length === msg.content.trim().length ? trimmed : `${trimmed}…`;
    }
    all[idx] = conv;
    writeAll(all);
  },
  mutateLastMessage(id: string, fn: (draft: ChatMessage) => void): void {
    const all = readAll();
    const idx = all.findIndex((c) => c.id === id);
    const conv = all[idx];
    if (!conv || conv.messages.length === 0) return;
    const tail = conv.messages[conv.messages.length - 1];
    if (!tail) return;
    const last = { ...tail };
    fn(last);
    conv.messages = [...conv.messages.slice(0, -1), last];
    all[idx] = conv;
    writeAll(all);
  },
  remove(id: string): void {
    writeAll(readAll().filter((c) => c.id !== id));
  },
  truncateFrom(id: string, fromIndex: number): void {
    const all = readAll();
    const idx = all.findIndex((c) => c.id === id);
    const conv = all[idx];
    if (!conv) return;
    if (fromIndex < 0 || fromIndex >= conv.messages.length) return;
    all[idx] = { ...conv, messages: conv.messages.slice(0, fromIndex) };
    writeAll(all);
  },
  recordTicketReference(id: string, ticketId: string): void {
    const all = readAll();
    const idx = all.findIndex((c) => c.id === id);
    const conv = all[idx];
    if (!conv) return;
    const refs = new Set(conv.referencedTickets ?? []);
    if (refs.has(ticketId)) return;
    refs.add(ticketId);
    all[idx] = { ...conv, referencedTickets: [...refs] };
    writeAll(all);
  },
};

const TICKET_ID_RE = /\bT-\d{3,}\b/g;

export function extractTicketIds(text: string): string[] {
  return [...new Set(text.match(TICKET_ID_RE) ?? [])];
}

export function allReferencedTicketIds(): Set<string> {
  const out = new Set<string>();
  for (const c of readAll()) {
    for (const id of c.referencedTickets ?? []) out.add(id);
  }
  return out;
}

export function useConversations(): {
  conversations: Conversation[];
  refresh: () => void;
} {
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    const ch = getChannel();
    if (!ch) return;
    const onMessage = () => refresh();
    ch.addEventListener("message", onMessage);
    return () => ch.removeEventListener("message", onMessage);
  }, [refresh]);
  void tick; // dependency for re-reading the snapshot
  return { conversations: conversations.list(), refresh };
}
