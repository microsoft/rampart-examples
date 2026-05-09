import { useEffect, useState } from "react";
import * as api from "@/api";

interface Props {
  ticketId: string;
  onReference: (id: string) => void;
  onDeleted: () => void;
}

const LOADING_DELAY_MS = 150;

export function TicketDetail({ ticketId, onReference, onDeleted }: Props) {
  const [ticket, setTicket] = useState<api.TicketDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showLoading, setShowLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    // Defer the loading flash so cached/local fetches don't blink.
    const timer = window.setTimeout(() => {
      if (!cancelled) setShowLoading(true);
    }, LOADING_DELAY_MS);
    api
      .getTicket(ticketId)
      .then((t) => {
        if (cancelled) return;
        setTicket(t);
        setShowLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError((e as Error).message);
        setShowLoading(false);
      })
      .finally(() => window.clearTimeout(timer));
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [ticketId]);

  const remove = async () => {
    if (!confirm("Delete this ticket?")) return;
    await api.deleteTicket(ticketId);
    onDeleted();
  };

  if (error) return <div className="p-4 text-xs text-red-400">{error}</div>;
  if (!ticket)
    return showLoading ? <div className="p-4 text-xs text-fg-subtle">Loading…</div> : null;

  return (
    <div className="space-y-3 p-4">
      <div className="space-y-1">
        <div className="font-mono text-xs uppercase tracking-wider text-fg-subtle">{ticket.id}</div>
        <h3 className="text-base font-semibold">{ticket.subject}</h3>
        <div className="text-xs text-fg-muted">From: {ticket.from}</div>
      </div>
      <pre className="whitespace-pre-wrap break-words rounded border border-border bg-surface/40 p-3 font-mono text-xs leading-relaxed text-fg">
        {ticket.body}
      </pre>
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => onReference(ticket.id)}
          className="rounded bg-surface-2 px-3 py-1 text-xs hover:bg-surface-2"
        >
          Reference in chat
        </button>
        <button
          type="button"
          onClick={remove}
          className="rounded border border-border-strong px-3 py-1 text-xs text-fg-muted hover:border-red-700/60 hover:text-red-300"
        >
          Delete
        </button>
      </div>
    </div>
  );
}
