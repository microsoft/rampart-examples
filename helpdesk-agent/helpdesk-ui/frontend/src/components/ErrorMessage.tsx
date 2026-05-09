interface Props {
  detail: string;
  onRetry?: () => void;
}

export function ErrorMessage({ detail, onRetry }: Props) {
  return (
    <div className="flex justify-start">
      <div
        className="w-full rounded border border-red-700/50 bg-red-700/10 px-4 py-3 font-mono text-xs text-red-200"
        data-testid="error-message"
      >
        <div>{detail}</div>
        {onRetry && (
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={onRetry}
              className="rounded border border-red-700/50 px-3 py-1 text-[11px] uppercase tracking-wider text-red-200 transition hover:bg-red-700/20"
              data-testid="error-retry"
            >
              Retry
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
