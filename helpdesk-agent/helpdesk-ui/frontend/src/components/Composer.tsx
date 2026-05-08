import { useEffect, useLayoutEffect, useRef, useState } from "react";

interface Props {
  prefill: string;
  onPrefillConsumed: () => void;
  onSubmit: (text: string) => void;
  streaming?: boolean;
  onStop?: () => void;
  focusKey?: unknown;
}

const MIN_ROWS_PX = 48; // ~2 rows
const MAX_ROWS_PX = 240; // ~10 rows; clamp before scroll

export function Composer({
  prefill,
  onPrefillConsumed,
  onSubmit,
  streaming = false,
  onStop,
  focusKey,
}: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (prefill) {
      setValue(prefill);
      onPrefillConsumed();
      requestAnimationFrame(() => ref.current?.focus());
    }
  }, [prefill, onPrefillConsumed]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: focusKey is the trigger
  useEffect(() => {
    ref.current?.focus();
  }, [focusKey]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: value drives DOM-measured height
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(Math.max(el.scrollHeight, MIN_ROWS_PX), MAX_ROWS_PX);
    el.style.height = `${next}px`;
  }, [value]);

  const submit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (streaming) {
      onStop?.();
      return;
    }
    const text = value.trim();
    if (!text) return;
    onSubmit(text);
    setValue("");
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="sticky bottom-0 border-t border-border bg-bg p-3">
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKey}
          placeholder="Send a message…  (Enter to send, Shift+Enter for newline)"
          rows={2}
          disabled={streaming}
          data-testid="composer-input"
          className="flex-1 resize-none rounded border border-border-strong bg-surface px-3 py-2 text-base text-fg placeholder:text-fg-subtle focus:border-border-strong focus:outline-none disabled:opacity-60"
          style={{ minHeight: MIN_ROWS_PX, maxHeight: MAX_ROWS_PX }}
        />
        {streaming ? (
          <button
            type="button"
            onClick={() => onStop?.()}
            data-testid="composer-stop"
            className="rounded bg-red-700 px-4 py-2 text-sm font-medium hover:bg-red-600"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!value.trim()}
            data-testid="composer-send"
            className="rounded bg-emerald-700 px-4 py-2 text-sm font-medium hover:bg-emerald-600 disabled:opacity-50"
          >
            Send
          </button>
        )}
      </div>
    </form>
  );
}
