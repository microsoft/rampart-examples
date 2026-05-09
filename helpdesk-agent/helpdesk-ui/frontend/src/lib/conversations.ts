import { useSyncExternalStore } from "react";

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

const listeners = new Set<() => void>();

function loadInitial(): Conversation[] {
  try {
    const raw = sessionStorage.getItem(KEY_CONVERSATIONS);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as Conversation[]) : [];
  } catch {
    return [];
  }
}

let state: Conversation[] = loadInitial();

function setState(next: Conversation[]): void {
  state = next;
  try {
    sessionStorage.setItem(KEY_CONVERSATIONS, JSON.stringify(state));
  } catch {
    /* quota or disabled storage; in-memory state still authoritative */
  }
  for (const listener of listeners) listener();
  getChannel()?.postMessage({ type: "change" });
}

let channel: BroadcastChannel | null = null;
function getChannel(): BroadcastChannel | null {
  if (channel) return channel;
  if (typeof BroadcastChannel === "undefined") return null;
  channel = new BroadcastChannel(CHANNEL_NAME);
  // Cross-tab updates: re-read from storage and notify subscribers.
  channel.addEventListener("message", () => {
    state = loadInitial();
    for (const listener of listeners) listener();
  });
  return channel;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  getChannel();
  return () => {
    listeners.delete(listener);
  };
}

let cachedList: Conversation[] | null = null;
let cachedListSource: Conversation[] | null = null;

function getListSnapshot(): Conversation[] {
  if (cachedListSource !== state) {
    cachedList = [...state].sort((a, b) => b.createdAt - a.createdAt);
    cachedListSource = state;
  }
  return cachedList ?? [];
}

function replaceAt(idx: number, conv: Conversation): Conversation[] {
  return [...state.slice(0, idx), conv, ...state.slice(idx + 1)];
}

// --- Mutators -----------------------------------------------------------

export const conversations = {
  list(): Conversation[] {
    return getListSnapshot();
  },
  get(id: string): Conversation | null {
    return state.find((c) => c.id === id) ?? null;
  },
  create(): Conversation {
    const conversation: Conversation = {
      id: crypto.randomUUID(),
      title: "New chat",
      createdAt: Date.now(),
      messages: [],
    };
    setState([...state, conversation]);
    return conversation;
  },
  appendMessage(id: string, msg: Omit<ChatMessage, "id"> & { id?: string }): void {
    const idx = state.findIndex((c) => c.id === id);
    const conv = state[idx];
    if (!conv) return;
    const stamped: ChatMessage = { ...msg, id: msg.id ?? crypto.randomUUID() };
    const next = { ...conv, messages: [...conv.messages, stamped] };
    if (next.title === "New chat" && msg.role === "user" && msg.content.trim().length > 0) {
      const trimmed = msg.content.trim().slice(0, TITLE_MAX);
      next.title = trimmed.length === msg.content.trim().length ? trimmed : `${trimmed}…`;
    }
    setState(replaceAt(idx, next));
  },
  mutateLastMessage(id: string, fn: (draft: ChatMessage) => void): void {
    const idx = state.findIndex((c) => c.id === id);
    const conv = state[idx];
    if (!conv || conv.messages.length === 0) return;
    const tail = conv.messages[conv.messages.length - 1];
    if (!tail) return;
    const last = { ...tail };
    fn(last);
    setState(replaceAt(idx, { ...conv, messages: [...conv.messages.slice(0, -1), last] }));
  },
  remove(id: string): void {
    setState(state.filter((c) => c.id !== id));
  },
  truncateFrom(id: string, fromIndex: number): void {
    const idx = state.findIndex((c) => c.id === id);
    const conv = state[idx];
    if (!conv) return;
    if (fromIndex < 0 || fromIndex >= conv.messages.length) return;
    setState(replaceAt(idx, { ...conv, messages: conv.messages.slice(0, fromIndex) }));
  },
  recordTicketReference(id: string, ticketId: string): void {
    const idx = state.findIndex((c) => c.id === id);
    const conv = state[idx];
    if (!conv) return;
    const refs = new Set(conv.referencedTickets ?? []);
    if (refs.has(ticketId)) return;
    refs.add(ticketId);
    setState(replaceAt(idx, { ...conv, referencedTickets: [...refs] }));
  },
};

const TICKET_ID_RE = /\bT-\d{3,}\b/g;

export function extractTicketIds(text: string): string[] {
  return [...new Set(text.match(TICKET_ID_RE) ?? [])];
}

export function allReferencedTicketIds(): Set<string> {
  const out = new Set<string>();
  for (const c of state) {
    for (const id of c.referencedTickets ?? []) out.add(id);
  }
  return out;
}

export function useConversations(): {
  conversations: Conversation[];
  refresh: () => void;
} {
  const list = useSyncExternalStore(subscribe, getListSnapshot, getListSnapshot);
  return { conversations: list, refresh: noop };
}

function noop(): void {}
