import { useCallback, useEffect, useState } from "react";
import * as api from "@/api";
import { allReferencedTicketIds, useConversations } from "@/lib/conversations";
import { formatRelative } from "@/lib/time";
import { TicketDetail } from "./TicketDetail";
import { TicketForm } from "./TicketForm";

interface Props {
  onReference: (ticketId: string) => void;
}

const CHANNEL_NAME = "helpdesk-ui:tickets";

export function TicketInbox({ onReference }: Props) {
  const [tickets, setTickets] = useState<api.TicketSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  // Re-render the badges whenever the local conversation store changes.
  const { conversations: _convs } = useConversations();
  void _convs;
  const referenced = allReferencedTicketIds();

  const reload = useCallback(() => {
    api
      .listTickets()
      .then(setTickets)
      .catch(() => setTickets([]));
  }, []);

  useEffect(reload, [reload]);

  // Cross-tab refresh via BroadcastChannel; no SSE, no polling.
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const ch = new BroadcastChannel(CHANNEL_NAME);
    const onMessage = () => reload();
    ch.addEventListener("message", onMessage);
    return () => {
      ch.removeEventListener("message", onMessage);
      ch.close();
    };
  }, [reload]);

  const announce = () => {
    if (typeof BroadcastChannel === "undefined") return;
    const ch = new BroadcastChannel(CHANNEL_NAME);
    ch.postMessage({ type: "change" });
    ch.close();
  };

  return (
    <aside className="flex h-full flex-col border-l border-border bg-surface/40">
      <div className="flex items-center justify-between border-b border-border p-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-fg-muted">Tickets</h2>
        <button
          type="button"
          onClick={() => {
            setShowForm((v) => !v);
            setSelected(null);
          }}
          className="rounded bg-surface-2 px-2 py-1 text-xs hover:bg-surface-2"
        >
          {showForm ? "Cancel" : "+ New"}
        </button>
      </div>
      {showForm && (
        <div className="border-b border-border bg-surface/40 p-3">
          <TicketForm
            onCreated={(t: api.TicketDetail) => {
              setShowForm(false);
              setSelected(t.id);
              reload();
              announce();
            }}
          />
        </div>
      )}
      {selected ? (
        <div className="flex-1 overflow-y-auto">
          <div className="border-b border-border p-2">
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-xs text-fg-muted hover:text-fg"
            >
              ← Back to inbox
            </button>
          </div>
          <TicketDetail
            ticketId={selected}
            onReference={(id) => {
              onReference(id);
              setSelected(null);
            }}
            onDeleted={() => {
              setSelected(null);
              reload();
              announce();
            }}
          />
        </div>
      ) : (
        <ul className="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-border-strong scrollbar-track-transparent">
          {tickets.length === 0 && (
            <li className="px-4 py-6 text-center text-xs text-fg-subtle">No tickets.</li>
          )}
          {tickets.map((t) => {
            const wasReferenced = referenced.has(t.id);
            return (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => setSelected(t.id)}
                  className="block w-full border-b border-border/60 px-3 py-2 text-left transition hover:bg-surface"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-xs text-fg-subtle">{t.id}</span>
                    <span
                      className="text-xs text-fg-subtle"
                      title={new Date(t.mtime_ns / 1_000_000).toLocaleString()}
                    >
                      {formatRelative(t.mtime_ns / 1_000_000_000)}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-base font-medium text-fg">{t.subject}</div>
                  <div className="mt-0.5 line-clamp-2 text-xs text-fg-muted">{t.preview}</div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[10px] uppercase tracking-wider">
                    <span className="truncate text-fg-subtle">{t.from}</span>
                    {wasReferenced && (
                      <span className="rounded border border-brand/40 bg-brand/15 px-1.5 py-0.5 text-brand-2">
                        discussed in chat
                      </span>
                    )}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
