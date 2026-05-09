import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/conversations";
import { AgentMessage } from "./AgentMessage";
import { ErrorMessage } from "./ErrorMessage";
import { UserMessage } from "./UserMessage";

interface Props {
  messages: ChatMessage[];
  streaming: boolean;
  onRetry?: (errorIndex: number) => void;
}

const NEAR_BOTTOM_PX = 100;

export function MessageList({ messages, streaming, onRetry }: Props) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Re-run on every message/streaming change so we keep the viewport
  // pinned to the bottom while a reply streams — but only when the
  // user was already near the bottom (otherwise they're reading
  // scrollback).
  // biome-ignore lint/correctness/useExhaustiveDependencies: deps are change triggers, not closure reads
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const distanceFromBottom = scroller.scrollHeight - (scroller.scrollTop + scroller.clientHeight);
    if (distanceFromBottom < NEAR_BOTTOM_PX) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }, [messages, streaming]);

  const lastIdx = messages.length - 1;
  const lastErrorIdx = (() => {
    for (let i = lastIdx; i >= 0; i--) {
      if (messages[i]?.role === "error") return i;
    }
    return -1;
  })();

  return (
    <div
      ref={scrollerRef}
      className="flex flex-1 flex-col gap-4 overflow-y-auto scrollbar-thin scrollbar-thumb-border-strong scrollbar-track-transparent px-6 py-4"
    >
      {messages.map((m, i) => {
        const isTail = i === lastIdx;
        switch (m.role) {
          case "user":
            return <UserMessage key={m.id} content={m.content} />;
          case "error":
            return (
              <ErrorMessage
                key={m.id}
                detail={m.content}
                onRetry={i === lastErrorIdx && !streaming && onRetry ? () => onRetry(i) : undefined}
              />
            );
          default:
            return (
              <AgentMessage
                key={m.id}
                content={m.content}
                toolCalls={m.toolCalls}
                model={m.model}
                isStreamingTail={isTail && streaming}
              />
            );
        }
      })}
      <div ref={sentinelRef} />
    </div>
  );
}
