import { t } from "@/lib/i18n";

export function Legend() {
  return (
    <div className="rounded-input bg-sheet/95 p-3 text-xs shadow-float">
      <p className="font-bold">{t("explore.legend_title")}</p>
      <div className="mt-2 flex items-center gap-2">
        <span className="flex" aria-hidden="true">
          {[1, 2, 3, 4, 5].map((i) => (
            <span key={i} className="h-3 w-5" style={{ background: `var(--opp-${i})` }} />
          ))}
        </span>
        <span>{t("explore.legend_scale")}</span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span
          aria-hidden="true"
          className="h-3 w-5 border border-rule"
          style={{
            background:
              "repeating-linear-gradient(135deg, var(--opp-4) 0 2px, transparent 2px 5px)",
            opacity: 0.7,
          }}
        />
        <span>{t("explore.legend_hatched")}</span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <svg aria-hidden="true" width="20" height="12" viewBox="0 0 20 12">
          <ellipse cx="10" cy="6" rx="8.5" ry="4.8" fill="none" stroke="var(--muga)" strokeWidth="2" />
        </svg>
        <span>{t("explore.legend_circled")}</span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span aria-hidden="true" className="h-3 w-5 border border-rule" />
        <span>{t("explore.legend_empty")}</span>
      </div>
    </div>
  );
}
