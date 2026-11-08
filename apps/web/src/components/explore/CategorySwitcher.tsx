"use client";

import type { Category } from "@/lib/api";
import { has, t } from "@/lib/i18n";

/**
 * Segmented control on desktop, horizontally scrolling chips on mobile.
 * Selected = 3px tea underline, not a filled pill (docs/06 §4).
 */
export function CategorySwitcher({
  categories,
  value,
  onChange,
}: {
  categories: Category[];
  value: string;
  onChange: (slug: string) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={t("explore.categories")}
      className="flex gap-1 overflow-x-auto [scrollbar-width:none] lg:gap-0"
      onKeyDown={(e) => {
        const i = categories.findIndex((c) => c.slug === value);
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const next = categories[(i + (e.key === "ArrowRight" ? 1 : categories.length - 1)) % categories.length];
          if (next) {
            onChange(next.slug);
            requestAnimationFrame(() =>
              document.querySelector<HTMLButtonElement>(`[data-cat="${next.slug}"]`)?.focus(),
            );
          }
        }
      }}
    >
      {categories.map((c) => {
        const selected = c.slug === value;
        const label = has(`category_short.${c.slug}`) ? t(`category_short.${c.slug}`) : c.name;
        return (
          <button
            key={c.slug}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            data-cat={c.slug}
            onClick={() => onChange(c.slug)}
            className={[
              "relative min-h-[44px] shrink-0 whitespace-nowrap px-3 text-sm font-bold",
              "rounded-chip border border-rule bg-sheet lg:rounded-none lg:border-0 lg:bg-transparent",
              selected ? "text-ink" : "text-ink-soft hover:text-ink",
            ].join(" ")}
          >
            {label}
            <span
              aria-hidden="true"
              className="absolute inset-x-2 bottom-0 h-[3px] rounded-[2px]"
              style={{ background: selected ? "var(--tea)" : "transparent" }}
            />
          </button>
        );
      })}
    </div>
  );
}
