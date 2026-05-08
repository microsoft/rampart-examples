import { useEffect, useState } from "react";
import type { ToolCall } from "@/lib/conversations";
import { getTool, loadTools } from "@/lib/tools";

interface Props {
  call: ToolCall;
  index: number;
  total: number;
}

export function ToolCallCard({ call, index, total }: Props) {
  const argEntries = Object.entries(call.arguments);
  const pending = call.result === null && argEntries.length === 0;

  const [, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    void loadTools().then(() => {
      if (!cancelled) setTick((t) => t + 1);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const tool = getTool(call.name);
  return (
    <div className="rounded border border-border bg-surface/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-sm text-fn" title={tool?.description}>
          {call.name}()
        </span>
        <span className="text-[10px] uppercase tracking-wider text-fg-subtle">
          step {index} / {total}
        </span>
      </div>
      {pending ? (
        <div className="mt-2 space-y-1.5">
          <div className="h-3 w-2/3 rounded bg-surface-2 shimmer" />
          <div className="h-3 w-1/2 rounded bg-surface-2 shimmer" />
        </div>
      ) : argEntries.length === 0 ? (
        <div className="mt-2 text-xs text-fg-subtle">(no arguments)</div>
      ) : (
        <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 font-mono text-xs">
          {argEntries.map(([k, v]) => (
            <FragmentRow key={k} k={k} v={v} />
          ))}
        </dl>
      )}
      {call.result !== null && call.result !== undefined && (
        <div className="mt-3">
          <div className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">Result</div>
          <pre className="whitespace-pre-wrap break-words rounded bg-code-bg p-2 font-mono text-xs text-fg-muted">
            {String(call.result)}
          </pre>
        </div>
      )}
    </div>
  );
}

function FragmentRow({ k, v }: { k: string; v: unknown }) {
  return (
    <>
      <dt className="text-fg-subtle">{k}</dt>
      <dd>{formatValue(v)}</dd>
    </>
  );
}

function formatValue(v: unknown): React.ReactNode {
  if (v === null || v === undefined) return <span className="text-fg-subtle">null</span>;
  if (typeof v === "string") return <span className="text-syntax-string">{JSON.stringify(v)}</span>;
  if (typeof v === "number") return <span className="text-syntax-number">{String(v)}</span>;
  if (typeof v === "boolean") return <span className="text-syntax-bool">{String(v)}</span>;
  return (
    <pre className="whitespace-pre-wrap break-words text-fg-muted">
      {JSON.stringify(v, null, 2)}
    </pre>
  );
}
