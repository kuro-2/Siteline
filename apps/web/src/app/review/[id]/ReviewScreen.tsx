"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { Geometry } from "geojson";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, type AreaDetail, type CellReport } from "@/lib/api";
import { formatDate, formatDistance, type Confidence } from "@/lib/format";
import { shortId } from "@/lib/hex";
import { t } from "@/lib/i18n";
import { AreaMap } from "@/components/map/AreaMap";
import { ConfidenceDots } from "@/components/ui/ConfidenceDots";

type Decision = "approve" | "approve_with_edits" | "adjust" | "reject" | "needs_data";

interface Detail {
  id: string;
  h3: string;
  area: string;
  category: string;
  category_name: string;
  status: string;
  engine_score: number;
  final_score: number | null;
  score_low: number | null;
  score_high: number | null;
  confidence: Confidence;
  components: { name: string; effect: number; why: string }[];
  features: Record<string, { value: unknown; source: string; as_of: string | null; n: number | null }>;
  explanation_draft: string | null;
  explanation_final: string | null;
  history: { decision: string; score_delta: number | null; reason: string | null; created_at: string; analyst: string | null }[];
  evidence: CellReport["evidence"] | null;
  limits: string[];
}

export function ReviewScreen({ id }: { id: string }) {
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["review", id], queryFn: () => api<Detail>(`/review/${id}`) });
  const area = useQuery({
    queryKey: ["area", d.data?.area],
    queryFn: () => api<AreaDetail>(`/areas/${d.data?.area}`, { auth: false }),
    enabled: !!d.data,
  });
  const [text, setText] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [delta, setDelta] = useState(0);
  const [result, setResult] = useState<{ status: string; warnings: string[] } | null>(null);

  const regen = useMutation({
    mutationFn: () => api<{ explanation_draft: string }>(`/review/${id}/regenerate-explanation`, { method: "POST" }),
    onSuccess: (r) => {
      setText(r.explanation_draft);
      qc.invalidateQueries({ queryKey: ["review", id] });
    },
  });
  const decide = useMutation({
    mutationFn: (decision: Decision) =>
      api<{ status: string; warnings: string[] }>(`/review/${id}`, {
        method: "POST",
        body: {
          decision,
          score_delta: decision === "adjust" ? delta : null,
          explanation_final: text ?? undefined,
          reason: reason || undefined,
        },
      }),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["review-queue"] });
    },
  });

  if (d.isPending) return <p className="p-6">{t("common.loading")}</p>;
  if (d.isError) return <p className="p-6 text-gamosa">{(d.error as Error).message}</p>;
  const r = d.data;
  const explanation = text ?? r.explanation_final ?? r.explanation_draft ?? "";
  const edited = text !== null && text !== (r.explanation_draft ?? "");
  const decided = r.status === "published" || r.status === "rejected" || result !== null;

  return (
    <main id="main" className="grid gap-6 px-4 py-6 lg:grid-cols-[1.1fr_1fr_1.1fr] lg:px-6">
      {/* column 1: map + evidence */}
      <section>
        <p className="text-sm">
          <Link href="/review">{t("common.back")}</Link>
        </p>
        <h1 className="mt-2 text-2xl font-extrabold">
          {r.category_name}, {t("report.block", { short: shortId(r.h3) })}
        </h1>
        <p className="mt-1">
          <span className="font-bold num">{t("report.score", { score: r.final_score ?? r.engine_score })}</span>{" "}
          <span className="text-ink-soft num">({t("report.range", { low: r.score_low ?? "–", high: r.score_high ?? "–" })})</span>
        </p>
        <ConfidenceDots value={r.confidence} />
        <div className="relative mt-4 h-72 overflow-hidden rounded-input border border-rule">
          <AreaMap
            label={t("explore.map_label", { area: r.area, category: r.category_name })}
            boundary={(area.data?.boundary as Geometry | undefined) ?? null}
            bbox={area.data?.bbox ?? null}
            cells={[[r.h3, r.engine_score, r.confidence, false]]}
            circled={[]}
            selected={r.h3}
            showControls={false}
          />
        </div>
        <h2 className="mt-6 text-lg">{t("review.evidence")}</h2>
        <table className="ruled mt-2 text-sm">
          <tbody>
            {Object.entries(r.features).map(([k, f]) => (
              <tr key={k}>
                <th scope="row" className="text-ink">{k}</th>
                <td className="r num">{f.value === null ? "–" : String(f.value)}</td>
                <td className="text-ink-soft">
                  {f.source}
                  {f.as_of ? `, ${f.as_of}` : ""}
                  {f.n !== null ? ` (n=${f.n})` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {r.evidence && r.evidence.competitors.length > 0 && (
          <>
            <h3 className="mt-4 font-bold">{t("report.nearby")}</h3>
            <ul className="text-sm">
              {r.evidence.competitors.slice(0, 8).map((c, i) => (
                <li key={i} className="border-b border-rule py-1">
                  {c.name} <span className="text-ink-soft">{formatDistance(c.distance_m)}, {c.source_label}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {/* column 2: engine components */}
      <section>
        <h2 className="text-lg">{t("review.components")}</h2>
        <table className="ruled mt-2">
          <tbody>
            {r.components.map((c) => (
              <tr key={c.name}>
                <td>{c.why}</td>
                <td className="r num font-bold">
                  {c.effect > 0 ? "+" : ""}
                  {c.effect}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <h2 className="mt-6 text-lg">{t("report.cant_see")}</h2>
        <ul className="mt-2 list-disc pl-5 text-sm">
          {r.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        {r.history.length > 0 && (
          <>
            <h2 className="mt-6 text-lg">{t("review.history")}</h2>
            <ul className="mt-2 text-sm">
              {r.history.map((h, i) => (
                <li key={i} className="border-b border-rule py-1">
                  {formatDate(h.created_at)}: {h.analyst ?? "–"}, {h.decision}
                  {h.score_delta ? ` (${h.score_delta > 0 ? "+" : ""}${h.score_delta})` : ""}
                  {h.reason ? `: ${h.reason}` : ""}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {/* column 3: explanation editor + decision */}
      <section className="flex flex-col">
        <label htmlFor="explanation" className="font-display text-lg font-bold">
          {t("review.explanation")}
        </label>
        <p className="hint">{t("review.draft_label")}</p>
        <textarea
          id="explanation"
          className="field mt-2 min-h-48 flex-none"
          value={explanation}
          onChange={(e) => setText(e.target.value)}
          disabled={decided}
        />
        <button type="button" className="btn btn-quiet mt-1 self-start" onClick={() => regen.mutate()} disabled={decided || regen.isPending}>
          {t("review.regenerate")}
        </button>

        <fieldset className="mt-6 border-t border-rule pt-4" disabled={decided}>
          <legend className="font-display text-lg font-bold">{t("review.decision")}</legend>
          <label htmlFor="delta" className="label mt-2">
            {t("review.delta")}
          </label>
          <input
            id="delta"
            type="number"
            min={-15}
            max={15}
            step={1}
            className="field max-w-[8rem] num"
            value={delta}
            onChange={(e) => setDelta(Math.max(-15, Math.min(15, Number(e.target.value) || 0)))}
          />
          <label htmlFor="reason" className="label mt-4">
            {t("review.reason")}
          </label>
          <textarea id="reason" className="field min-h-24" value={reason} onChange={(e) => setReason(e.target.value)} />
          <p className="hint num" aria-live="polite">
            {t("review.reason_count", { n: reason.trim().length })}
          </p>
          {decide.error && <p className="mt-2 text-gamosa" role="alert">{(decide.error as Error).message}</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="btn btn-primary" onClick={() => decide.mutate(edited ? "approve_with_edits" : "approve")}>
              {edited ? t("review.publish_edits") : t("review.publish")}
            </button>
            <button type="button" className="btn btn-secondary" disabled={delta === 0} onClick={() => decide.mutate("adjust")}>
              {t("review.adjust")}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => decide.mutate("needs_data")}>
              {t("review.needs_data")}
            </button>
            <button type="button" className="btn btn-danger" onClick={() => decide.mutate("reject")}>
              {t("review.reject")}
            </button>
          </div>
        </fieldset>
        {result && (
          <div className="mt-4" role="status">
            <p className="font-bold">
              {result.status === "published" ? t("review.published") : result.status === "rejected" ? t("review.rejected") : t("review.sent_back")}
            </p>
            {result.warnings.map((w) => (
              <p key={w} className="mt-1 border-l-[3px] border-muga pl-3 text-sm">
                {t("review.warning")}: {w}
              </p>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
