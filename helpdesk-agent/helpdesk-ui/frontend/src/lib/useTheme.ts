import { useEffect, useState } from "react";

export type Theme = "dark" | "light";

const KEY = "helpdesk-ui:theme:v1";

function readStored(): Theme {
  try {
    const v = sessionStorage.getItem(KEY);
    return v === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function apply(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function useTheme(): {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
} {
  const [theme, setThemeState] = useState<Theme>(readStored);

  useEffect(() => {
    apply(theme);
    try {
      sessionStorage.setItem(KEY, theme);
    } catch {}
  }, [theme]);

  return {
    theme,
    setTheme: setThemeState,
    toggle: () => setThemeState((t) => (t === "dark" ? "light" : "dark")),
  };
}
