"use client";

import { useState } from "react";
import { ConfidenceDots } from "@/components/ui/ConfidenceDots";
import { HandUnderline } from "@/components/marks/HandUnderline";
import { t } from "@/lib/i18n";

const COLORS = ["mist", "sheet", "ink", "ink-soft", "rule", "tea", "river", "muga", "gamosa"];
const STEPS: [string, number][] = [
  ["13", 13], ["15", 15], ["17 (base)", 17], ["21", 21], ["26", 26], ["33", 33], ["42", 42],
];

/** Visual review of every token from docs/06, in light and dark. */
export default function TokensPage() {
  const [theme, setTheme] = useState<"system" | "light" | "dark">("system");
  function apply(next: "system" | "light" | "dark") {
    setTheme(next);
    if (next === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", next);
  }
  return (
    <main id="main" className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-3xl font-extrabold">{t("dev.tokens_title")}</h1>
      <fieldset className="mt-4 flex gap-2">
        <legend className="label">{t("dev.theme")}</legend>
        {(["system", "light", "dark"] as const).map((m) => (
          <button key={m} type="button" className={`btn ${theme === m ? "btn-primary" : "btn-secondary"}`} onClick={() => apply(m)}>
            {m}
          </button>
        ))}
      </fieldset>

      <h2 className="mt-10 text-xl">Colour</h2>
      <ul className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {COLORS.map((c) => (
          <li key={c} className="border border-rule bg-sheet p-2">
            <span className="block h-14 border border-rule" style={{ background: `var(--${c})` }} />
            <span className="mt-1 block text-sm font-bold">--{c}</span>
          </li>
        ))}
      </ul>

      <h2 className="mt-10 text-xl">Opportunity scale</h2>
      <div className="mt-3 flex">
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className="h-12 flex-1 border-y border-r border-rule first:border-l" style={{ background: `var(--opp-${i})` }} />
        ))}
      </div>
      <div className="mt-2 flex">
        {[1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            className="h-12 flex-1"
            style={{
              background: `repeating-linear-gradient(135deg, var(--opp-${i}) 0 3px, transparent 3px 7px)`,
              opacity: 0.6,
            }}
          />
        ))}
      </div>
      <p className="hint mt-1">Second row: low confidence (hatched, 60% opacity).</p>

      <h2 className="mt-10 text-xl">Type</h2>
      <div className="mt-3 space-y-2">
        {STEPS.map(([label, px]) => (
          <p key={label} style={{ fontSize: px }} className={px >= 26 ? "font-display font-bold" : ""}>
            <span className="text-ink-soft">{label}px</span> Plenty of people, few pharmacies
          </p>
        ))}
        <p className="font-display text-3xl font-extrabold">
          Zoo Road: <HandUnderline id="tokens-demo">few pharmacies</HandUnderline>
        </p>
        <p className="num">Tabular: 1,23,456 · 7,100 · 3,900</p>
      </div>

      <h2 className="mt-10 text-xl">Components</h2>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="button" className="btn btn-primary">Publish</button>
        <button type="button" className="btn btn-secondary">Save this area</button>
        <button type="button" className="btn btn-quiet">Not right? Tell us</button>
        <button type="button" className="btn btn-danger">Delete my data</button>
      </div>
      <div className="mt-4 flex flex-wrap gap-6">
        {(["not_enough_data", "early_signal", "fairly_sure", "confident"] as const).map((c) => (
          <ConfidenceDots key={c} value={c} />
        ))}
      </div>
      <div className="mt-6 max-w-md rounded-t-sheet bg-sheet p-4 shadow-float">
        <p className="font-bold">Field-report sheet</p>
        <p className="text-sm text-ink-soft">16px top corners only, one shadow for things over the map.</p>
        <div className="notebook mt-3 h-28" />
      </div>
      <div className="mt-6 flex gap-2">
        <span className="map-control" aria-hidden="true">+</span>
        <input className="field max-w-xs" placeholder="Input, 6px radius" aria-label="Example input" />
      </div>
    </main>
  );
}
