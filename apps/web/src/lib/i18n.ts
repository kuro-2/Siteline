/**
 * Tiny i18n layer. All user-facing copy lives in messages/<locale>.json.
 * `t("report.score", { score: 72 })` → "Score 72". Missing keys show the key (and fail tests).
 */
import en from "../../messages/en.json";

export type Locale = "en" | "as" | "hi";
type Messages = { [key: string]: string | Messages };

const catalogs: Record<Locale, Messages> = { en, as: en, hi: en };
let current: Locale = "en";

export function setLocale(locale: Locale): void {
  current = locale;
}

export function getLocale(): Locale {
  return current;
}

function lookup(messages: Messages, key: string): string | undefined {
  let node: string | Messages | undefined = messages;
  for (const part of key.split(".")) {
    if (node === undefined || typeof node === "string") return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

export function has(key: string, locale: Locale = current): boolean {
  return lookup(catalogs[locale], key) !== undefined;
}

export function t(key: string, vars?: Record<string, string | number>, locale: Locale = current): string {
  const raw = lookup(catalogs[locale], key) ?? lookup(catalogs.en, key) ?? key;
  if (!vars) return raw;
  return raw.replace(/\{(\w+)\}/g, (m, name: string) =>
    name in vars ? String(vars[name]) : m,
  );
}

/** Pick "key.one" or "key.other" by count. */
export function tn(key: string, count: number, vars?: Record<string, string | number>): string {
  return t(`${key}.${count === 1 ? "one" : "other"}`, { count, ...vars });
}
