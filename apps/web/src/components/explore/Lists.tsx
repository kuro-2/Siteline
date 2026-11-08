"use client";

import Link from "next/link";
import type { MapCell, TopPick } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { rankCells, shortId } from "@/lib/hex";
import { t } from "@/lib/i18n";
import { ConfidenceDots } from "@/components/ui/ConfidenceDots";

/** Analyst-reviewed picks, ranked. A list, not cards. */
export function RankedList({
  picks,
  hrefFor,
  areaName,
  categoryName,
}: {
  picks: TopPick[];
  hrefFor: (h3: string) => string;
  areaName: string;
  categoryName: string;
}) {
  if (picks.length === 0) {
    return <p className="mt-3 text-ink-soft">{t("explore.ranked_empty", { category: categoryName.toLowerCase(), area: areaName })}</p>;
  }
  const reviewer = picks[0];
  return (
    <>
      <ol className="mt-3">
        {picks.map((p, i) => (
          <li key={p.id} className="border-b border-rule">
            <Link href={hrefFor(p.h3)} className="flex items-start gap-3 py-3 text-ink no-underline hover:bg-mist/60">
              <span className="font-display text-xl font-bold leading-none text-ink-soft num">{i + 1}</span>
              <span className="flex-1">
                <span className="block font-bold">{p.category_name}</span>
                <span className="block text-sm text-ink-soft">{t("report.block", { short: shortId(p.h3) })}</span>
                <ConfidenceDots value={p.confidence} compact />
              </span>
              <span className="font-display text-xl font-bold num">{p.score}</span>
            </Link>
          </li>
        ))}
      </ol>
      {reviewer?.reviewed_by_name && reviewer.published_at && (
        <p className="mt-3 text-sm text-ink-soft">
          {t("explore.reviewed_by", { name: reviewer.reviewed_by_name, date: formatDate(reviewer.published_at) })}{" "}
          <Link href="/method">{t("explore.see_method")}</Link>
        </p>
      )}
    </>
  );
}

/** Every block in the area as a list: the map is never the only way in (docs/06 §8). */
export function CellList({ cells, hrefFor }: { cells: MapCell[]; hrefFor: (h3: string) => string }) {
  const ranked = rankCells(cells);
  return (
    <section className="mt-6">
      <h2 className="text-lg">{t("explore.cells_heading", { count: cells.length })}</h2>
      <table className="ruled mt-2">
        <thead>
          <tr>
            <th scope="col">{t("review.col_where")}</th>
            <th scope="col">{t("review.col_confidence")}</th>
            <th scope="col" className="r">
              {t("review.col_score")}
            </th>
          </tr>
        </thead>
        <tbody>
          {ranked.map(([h3, score, confidence, rec]) => (
            <tr key={h3}>
              <td>
                <Link href={hrefFor(h3)}>{shortId(h3)}</Link>
                {!rec && <span className="ml-2 text-xs text-ink-soft">{t("common.not_reviewed")}</span>}
              </td>
              <td>
                <ConfidenceDots value={confidence} compact />
              </td>
              <td className="r num">{score ?? <span className="text-ink-soft">{t("explore.no_score")}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
