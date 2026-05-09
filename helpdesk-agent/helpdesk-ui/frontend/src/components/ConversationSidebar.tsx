import { conversations, useConversations } from "@/lib/conversations";

interface Props {
  activeId: string | null;
  onSelect: (id: string | null) => void;
  onNew: () => void;
}

export function ConversationSidebar({ activeId, onSelect, onNew }: Props) {
  const { conversations: list, refresh } = useConversations();

  const remove = (id: string) => {
    if (!confirm("Delete this conversation?")) return;
    conversations.remove(id);
    if (id === activeId) {
      onSelect(null);
    }
    refresh();
  };

  return (
    <aside className="flex h-full flex-col border-r border-border bg-surface/40">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5">
        <div className="flex items-baseline gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-fg-muted">
            Conversations
          </h2>
          {list.length > 0 && (
            <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-muted">
              {list.length}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onNew}
          className="rounded bg-surface-2 px-2 py-1 text-xs hover:bg-surface-2"
          data-testid="new-chat"
        >
          + New
        </button>
      </div>
      <ul className="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-border-strong scrollbar-track-transparent">
        {list.length === 0 && (
          <li className="px-4 py-6 text-center text-xs text-fg-subtle">No conversations yet.</li>
        )}
        {list.map((c) => {
          const isActive = c.id === activeId;
          return (
            <li
              key={c.id}
              data-testid="conversation-row"
              className={`group flex items-center gap-2 border-b border-border/60 px-3 py-2 ${
                isActive ? "bg-surface" : ""
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                className="min-w-0 flex-1 truncate text-left text-base text-fg"
                title={c.title}
              >
                {c.title}
              </button>
              <button
                type="button"
                onClick={() => remove(c.id)}
                aria-label="Delete conversation"
                className="shrink-0 text-fg-subtle opacity-0 transition-opacity hover:text-red-400 focus-visible:opacity-100 group-hover:opacity-100"
              >
                ✕
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
