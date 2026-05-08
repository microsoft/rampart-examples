interface Props {
  onPick: (prompt: string) => void;
}

// Each prompt names a specific ticket id so the agent has a concrete
// handle to retrieve. ChatPanel records mentioned ids on submit, so
// the corresponding inbox row gets its "discussed in chat" badge
// without any extra plumbing.
const EXAMPLE_PROMPTS = [
  "Triage ticket T-1003 and reset the password if appropriate.",
  "Summarise ticket T-1001 for the on-call engineer.",
  "Has ticket T-1002 been answered yet? If not, draft a reply.",
];

export function ChatEmptyState({ onPick }: Props) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-8 p-8 text-center">
      <div className="space-y-2">
        <div aria-hidden className="text-5xl text-brand">
          ⌂
        </div>
        <h2 className="text-2xl font-semibold text-fg">HelpdeskAgent</h2>
        <p className="text-base text-fg-muted">How can I help today?</p>
      </div>
      <ul className="flex w-full max-w-2xl flex-col gap-3">
        {EXAMPLE_PROMPTS.map((prompt) => (
          <li key={prompt}>
            <button
              type="button"
              onClick={() => onPick(prompt)}
              className="w-full rounded-lg border border-border bg-surface/40 px-4 py-4 text-left text-base text-fg-muted transition hover:border-border-strong hover:bg-surface hover:text-fg"
            >
              {prompt}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
