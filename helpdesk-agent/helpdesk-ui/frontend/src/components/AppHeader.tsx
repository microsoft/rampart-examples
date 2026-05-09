import { useEffect, useState } from "react";
import * as api from "@/api";
import { useTheme } from "@/lib/useTheme";

export function AppHeader() {
  const { theme, toggle } = useTheme();
  const [health, setHealth] = useState<api.HealthResponse | null>(null);

  useEffect(() => {
    api
      .getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border bg-surface/60 px-5 py-3">
      <div className="flex items-baseline gap-3">
        <div className="flex items-center gap-2">
          <span aria-hidden className="text-2xl text-brand">
            ⌂
          </span>
          <h1 className="text-xl font-semibold tracking-tight text-fg">HelpdeskAgent</h1>
        </div>
        <span className="text-sm text-fg-subtle">Internal IT Helpdesk</span>
      </div>
      <div className="flex items-center gap-2">
        <ProviderPill health={health} />
        <button
          type="button"
          onClick={toggle}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          className="rounded border border-border-strong px-2 py-1 text-xs text-fg-muted transition hover:bg-surface-2 hover:text-fg"
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>
    </header>
  );
}

function ProviderPill({ health }: { health: api.HealthResponse | null }) {
  if (!health) return null;
  // ``fake`` is what /api/health reports under tests; don't surface it.
  if (health.provider === "fake") return null;
  if (!health.agent_configured) {
    return (
      <span
        className="flex items-center gap-1.5 rounded border border-amber-700/50 px-2 py-0.5 text-xs text-amber-300"
        title="No LLM provider configured. Set OPENAI_API_KEY or AZURE_OPENAI_*."
      >
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-amber-400" />
        no provider
      </span>
    );
  }
  return (
    <span
      className="flex items-center gap-1.5 rounded border border-border-strong px-2 py-0.5 text-xs text-fg-muted"
      title={`provider: ${health.provider}`}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand" />
      {health.model ?? health.provider}
    </span>
  );
}
