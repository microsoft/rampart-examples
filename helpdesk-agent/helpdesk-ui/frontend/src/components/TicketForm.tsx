import { useEffect, useState } from "react";
import * as api from "@/api";

interface Props {
  onCreated: (t: api.TicketDetail) => void;
}

export function TicketForm({ onCreated }: Props) {
  const [subject, setSubject] = useState("");
  const [from, setFrom] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSample, setHasSample] = useState(false);

  // Show the sample button only if the backend has the seed; in test
  // envs without it, we just hide the affordance.
  useEffect(() => {
    api.sampleTicket().then((t) => setHasSample(t !== null));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const ticket = await api.createTicket({ subject, from, body });
      setSubject("");
      setFrom("");
      setBody("");
      onCreated(ticket);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const loadSample = async () => {
    setError(null);
    try {
      const fixture = await api.sampleTicket();
      if (!fixture) {
        setHasSample(false);
        return;
      }
      setSubject(fixture.subject);
      setFrom(fixture.from);
      setBody(fixture.body);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <input
        required
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
        placeholder="Subject"
        className="w-full rounded border border-border-strong bg-bg px-2 py-1 text-sm"
      />
      <input
        required
        type="email"
        value={from}
        onChange={(e) => setFrom(e.target.value)}
        placeholder="From (e.g. alice@contoso.com)"
        className="w-full rounded border border-border-strong bg-bg px-2 py-1 text-sm"
      />
      <textarea
        required
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Ticket body"
        rows={10}
        className="w-full rounded border border-border-strong bg-bg px-2 py-1 font-mono text-xs"
      />
      {error && <div className="text-xs text-red-400">{error}</div>}
      <div className="flex items-center justify-between gap-2">
        {hasSample ? (
          <button
            type="button"
            onClick={loadSample}
            className="rounded border border-border-strong px-2 py-1 text-xs text-fg-muted hover:border-border-strong"
          >
            Load sample ticket
          </button>
        ) : (
          <span />
        )}
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-emerald-700 px-3 py-1 text-xs font-medium hover:bg-emerald-600 disabled:opacity-50"
        >
          {busy ? "Filing…" : "File ticket"}
        </button>
      </div>
    </form>
  );
}
