import { useEffect, useRef, useState } from "react";
import * as api from "@/api";
import {
  type ChatMessage,
  conversations,
  extractTicketIds,
  type ToolCall,
  useConversations,
} from "@/lib/conversations";
import { ChatEmptyState } from "./ChatEmptyState";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";

interface Props {
  activeId: string | null;
  onActiveIdChange: (id: string | null) => void;
  prefill: string;
  onPrefillConsumed: () => void;
  /** Empty-state prompt picked. Parent typically pushes this into
   *  ``prefill`` so the user can review/tweak before sending. */
  onPickPrompt: (text: string) => void;
}

export function ChatPanel({
  activeId,
  onActiveIdChange,
  prefill,
  onPrefillConsumed,
  onPickPrompt,
}: Props) {
  const [streaming, setStreaming] = useState(false);
  const { conversations: list, refresh } = useConversations();
  const conversation = activeId ? (list.find((c) => c.id === activeId) ?? null) : null;
  const streamRef = useRef<api.StreamHandle | null>(null);

  useEffect(() => {
    const onPageHide = () => streamRef.current?.abort();
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      streamRef.current?.abort();
    };
  }, []);

  const stop = () => {
    streamRef.current?.abort();
    streamRef.current = null;
    setStreaming(false);
  };

  const retry = (errorIndex: number) => {
    if (streaming || !activeId) return;
    const msgs = conversation?.messages ?? [];
    // Walk back to the nearest user message; that's the turn we resend.
    let userMsg: ChatMessage | undefined;
    let userIdx = -1;
    for (let i = errorIndex - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m && m.role === "user") {
        userMsg = m;
        userIdx = i;
        break;
      }
    }
    if (!userMsg || userIdx < 0) return;
    conversations.truncateFrom(activeId, userIdx);
    refresh();
    void submit(userMsg.content);
  };

  const submit = async (text: string) => {
    if (streaming) return;
    streamRef.current?.abort();

    let id = activeId;
    if (!id) {
      const c = conversations.create();
      id = c.id;
      onActiveIdChange(id);
    }
    const cid = id;

    conversations.appendMessage(cid, { role: "user", content: text });
    // Snapshot the model at send time so older bubbles keep their
    // original badge if the user later switches providers.
    const snapshotModel = await api
      .getHealth()
      .then((h) => h.model ?? h.provider ?? undefined)
      .catch(() => undefined);
    conversations.appendMessage(cid, {
      role: "assistant",
      content: "",
      toolCalls: [],
      model: snapshotModel,
    });
    for (const ref of extractTicketIds(text)) {
      conversations.recordTicketReference(cid, ref);
    }
    refresh();

    // The history we send to the server is everything up to (and
    // including) the new user prompt; not the empty assistant
    // placeholder we just appended.
    const snapshot = conversations.get(cid);
    const wireMessages: ChatMessage[] = (snapshot?.messages ?? []).slice(0, -1);

    setStreaming(true);
    streamRef.current = api.streamChat(wireMessages, {
      onDelta: (chunk) => {
        conversations.mutateLastMessage(cid, (draft) => {
          draft.content += chunk;
        });
        refresh();
      },
      onToolCall: (callId, name) => {
        conversations.mutateLastMessage(cid, (draft) => {
          const calls = draft.toolCalls ?? [];
          calls.push({ callId, name, arguments: {}, result: null });
          draft.toolCalls = calls;
        });
        refresh();
      },
      onToolResult: (callId, _name, args, result) => {
        conversations.mutateLastMessage(cid, (draft) => {
          const calls = draft.toolCalls;
          if (!calls) return;
          const idx = calls.findIndex((c) => c.callId === callId);
          const target = calls[idx];
          if (!target) return;
          calls[idx] = { ...target, arguments: args, result };
        });
        refresh();
      },
      onFinal: (reply, toolCalls) => {
        conversations.mutateLastMessage(cid, (draft) => {
          draft.content = reply || draft.content;
          draft.toolCalls = toolCalls as ToolCall[];
        });
        setStreaming(false);
        refresh();
      },
      onError: (detail) => {
        conversations.mutateLastMessage(cid, (draft) => {
          draft.role = "error";
          draft.content = detail;
          draft.toolCalls = undefined;
        });
        setStreaming(false);
        refresh();
      },
    });
  };

  const messages = conversation?.messages ?? [];
  const isEmpty = messages.length === 0;

  return (
    <section className="flex h-full flex-col">
      <header className="border-b border-border bg-surface/60 px-6 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-fg-muted">
          {conversation ? conversation.title : "Chat"}
        </h2>
      </header>
      {isEmpty ? (
        <div className="flex-1 overflow-y-auto">
          <ChatEmptyState onPick={onPickPrompt} />
        </div>
      ) : (
        <MessageList messages={messages} streaming={streaming} onRetry={retry} />
      )}
      <Composer
        prefill={prefill}
        onPrefillConsumed={onPrefillConsumed}
        onSubmit={submit}
        streaming={streaming}
        onStop={stop}
        focusKey={activeId ?? "empty"}
      />
    </section>
  );
}
