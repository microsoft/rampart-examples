import type { ToolCall } from "@/lib/conversations";
import { renderMarkdown } from "@/lib/markdown";
import { ToolCallCard } from "./ToolCallCard";

interface Props {
  content: string;
  toolCalls?: ToolCall[];
  model?: string;
  isStreamingTail: boolean;
}

export function AgentMessage({ content, toolCalls, model, isStreamingTail }: Props) {
  const html = content ? renderMarkdown(content) : "";
  return (
    <div className="flex flex-col gap-2" data-testid="agent-message">
      <div className="max-w-[90%] rounded-2xl rounded-tl-sm border border-border bg-bubble-agent px-4 py-3 text-base text-bubble-agent-fg shadow-sm">
        {html ? (
          <div
            className="markdown"
            // biome-ignore lint/security/noDangerouslySetInnerHtml: sanitized by DOMPurify in lib/markdown.ts
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          isStreamingTail && <span className="text-fg-subtle">…</span>
        )}
        {isStreamingTail && content && <span className="streaming-cursor">▋</span>}
      </div>
      {model && !isStreamingTail && (
        <span className="ml-2 inline-flex w-fit rounded-full border border-border bg-surface/40 px-2 py-0.5 font-mono text-[11px] text-fg-subtle">
          {model}
        </span>
      )}
      {toolCalls && toolCalls.length > 0 && (
        <details open className="ml-2 max-w-[90%] rounded border border-border bg-surface/30 p-2">
          <summary className="cursor-pointer text-xs uppercase tracking-wider text-fg-muted">
            Tool calls ({toolCalls.length})
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            {toolCalls.map((call, i) => (
              <ToolCallCard
                key={call.callId ?? `${call.name}-${i}`}
                call={call}
                index={i + 1}
                total={toolCalls.length}
              />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
