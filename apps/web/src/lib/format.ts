import { TIME_ZONE } from "./config";
import { t } from "./i18n";

export type Confidence = "not_enough_data" | "early_signal" | "fairly_sure" | "confident";

export const CONFIDENCE_LEVEL: Record<Confidence, number> = {
  not_enough_data: 0,
  early_signal: 1,
  fairly_sure: 2,
  confident: 3,
};

export function confidenceWords(c: Confidence): string {
  return t(`confidence.${c}`);
}

/** Indian digit grouping: 1,23,456. */
export function formatInt(n: number): string {
  return Math.round(n).toLocaleString("en-IN");
}

/** ₹ with lakh/crore words for big sums: ₹4.5 lakh, ₹1.2 crore. */
export function formatRupees(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${trim(n / 1e7)} crore`;
  if (abs >= 1e5) return `₹${trim(n / 1e5)} lakh`;
  return `₹${formatInt(n)}`;
}

function trim(x: number): string {
  return x.toFixed(1).replace(/\.0$/, "");
}

/** "4 Nov" or "4 Nov 2025" when not this year, in Asia/Kolkata. */
export function formatDate(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return t("common.unknown_date");
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00+05:30` : iso);
  if (Number.isNaN(d.getTime())) return t("common.unknown_date");
  const sameYear =
    new Intl.DateTimeFormat("en-IN", { year: "numeric", timeZone: TIME_ZONE }).format(d) ===
    new Intl.DateTimeFormat("en-IN", { year: "numeric", timeZone: TIME_ZONE }).format(now);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
    timeZone: TIME_ZONE,
  }).format(d);
}

export function formatDistance(m: number): string {
  if (m < 1000) return `${Math.round(m / 10) * 10} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

/** Map a score (0–100) to one of the 5 opportunity steps (1–5). */
export function opportunityStep(score: number | null): number {
  if (score === null) return 0;
  if (score >= 80) return 5;
  if (score >= 65) return 4;
  if (score >= 50) return 3;
  if (score >= 35) return 2;
  return 1;
}

export function percent(x: number | null | undefined): string {
  if (x === null || x === undefined) return "–";
  return `${Math.round(x * 100)}%`;
}
