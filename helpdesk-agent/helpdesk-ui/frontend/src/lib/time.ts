// Tiny relative-time formatter using Intl.RelativeTimeFormat.
// No deps. Always picks the largest unit that yields ``|n| >= 1``.

const FORMATTER = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

const STEPS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 365 * 24 * 60 * 60],
  ["month", 30 * 24 * 60 * 60],
  ["day", 24 * 60 * 60],
  ["hour", 60 * 60],
  ["minute", 60],
  ["second", 1],
];

export function formatRelative(epochSeconds: number, now: number = Date.now() / 1000): string {
  const diff = epochSeconds - now;
  const abs = Math.abs(diff);
  for (const [unit, scale] of STEPS) {
    if (abs >= scale || unit === "second") {
      return FORMATTER.format(Math.round(diff / scale), unit);
    }
  }
  return FORMATTER.format(0, "second");
}
