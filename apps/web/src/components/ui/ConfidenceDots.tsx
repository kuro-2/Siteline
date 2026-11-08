import { CONFIDENCE_LEVEL, confidenceWords, type Confidence } from "@/lib/format";
import { t } from "@/lib/i18n";

/** Four small dots (filled = level) plus the words. Words are always shown; dots never alone. */
export function ConfidenceDots({ value, compact = false }: { value: Confidence; compact?: boolean }) {
  const level = CONFIDENCE_LEVEL[value];
  return (
    <span className="inline-flex items-center gap-2" title={t("confidence.label", { level: confidenceWords(value) })}>
      <span aria-hidden="true" className="inline-flex gap-[3px]">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className="inline-block h-[7px] w-[7px] rounded-full border border-tea"
            style={{ background: i <= level && level > 0 ? "var(--tea)" : "transparent" }}
          />
        ))}
      </span>
      <span className={compact ? "text-xs text-ink-soft" : "text-sm"}>{confidenceWords(value)}</span>
    </span>
  );
}
