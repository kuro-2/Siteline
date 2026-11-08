"use client";

import * as Collapsible from "@radix-ui/react-collapsible";
import { CaretRight, ShareNetwork, BookmarkSimple } from "@phosphor-icons/react/dist/ssr";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { CellReport as Report } from "@/lib/api";
import { api } from "@/lib/api";
import { formatDate, formatDistance, formatInt, percent } from "@/lib/format";
import { shortId } from "@/lib/hex";
import { has, t } from "@/lib/i18n";
import { useAuth } from "@/components/providers";
import { ConfidenceDots } from "@/components/ui/ConfidenceDots";
import { HandUnderline } from "@/components/marks/HandUnderline";

const FEEDBACK_EMAIL = process.env.NEXT_PUBLIC_FEEDBACK_EMAIL || "";

/** Split a headline into [before, key phrase, after] for the gold hand-underline. */
export function keyPhrase(headline: string): [string, string, string] {
  const comma = headline.indexOf(", ");
  if (comma > 0) {
    const rest = headline.slice(comma + 2);
    const stop = rest.search(/ within | for |\.$/);
    const phrase = stop > 0 ? rest.slice(0, stop) : rest.replace(/\.$/, "");
    const before = headline.slice(0, comma + 2);
    return [before, phrase, headline.slice(before.length + phrase.length)];
  }
  const colon = headline.indexOf(":");
  if (colon > 0) return ["", headline.slice(0, colon), headline.slice(colon)];
  const words = headline.split(" ");
  const k = Math.min(3, words.length);
  return ["", words.slice(0, k).join(" "), headline.slice(words.slice(0, k).join(" ").length)];
}

function confidenceReason(r: Report): string {
  const date = formatDate(r.evidence.places_as_of ?? r.data_snapshot_at);
  if (r.confidence === "confident") return t("report.confidence_reason.confident", { n: r.evidence.survey?.n ?? 0 });
  if (r.confidence === "fairly_sure") {
    let extra = "";
    if (r.evidence.ground_count) extra += t("report.extra_ground", { date: formatDate(r.evidence.ground_count.counted_on) });
    if (r.evidence.survey && r.evidence.survey.n >= 20) extra += t("report.extra_survey", { n: r.evidence.survey.n });
    return t("report.confidence_reason.fairly_sure", { date, extra });
  }
  return t(`report.confidence_reason.${r.confidence}`, { date });
}

export function CellReport({ report: r, areaHref }: { report: Report; areaHref: string }) {
  const { session } = useAuth();
  const router = useRouter();
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [before, phrase, after] = keyPhrase(r.headline);
  const minutes = r.evidence.population.walk_minutes;

  async function save() {
    if (!session) {
      router.push(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
      return;
    }
    await api("/saved-areas", { method: "POST", body: { area: r.area.slug, category: r.category.slug, h3: r.h3 } });
    setSaved(true);
  }

  async function share() {
    const url = window.location.href;
    if (navigator.share) {
      try {
        await navigator.share({ title: r.headline, url });
        return;
      } catch {
        /* user cancelled: fall through to copy */
      }
    }
    await navigator.clipboard?.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <article aria-labelledby="report-headline" className="pb-6">
      <p className="text-sm">
        <Link href={areaHref}>{t("report.back_to_area", { area: r.area.name })}</Link>
      </p>
      <p className="mt-3 text-sm text-ink-soft">{t("report.eyebrow", { area: r.area.name, short: shortId(r.h3) })}</p>
      <h1 id="report-headline" className="mt-1 text-2xl font-extrabold">
        {before}
        <HandUnderline id={`${r.h3}-${r.category.slug}`}>{phrase}</HandUnderline>
        {after}
      </h1>

      <div className="mt-5">
        {r.score !== null ? (
          <p className="text-lg">
            <span className="font-bold num">{t("report.score", { score: r.score })}</span>{" "}
            {r.score_low !== null && r.score_high !== null && (
              <span className="text-ink-soft num">({t("report.range", { low: r.score_low, high: r.score_high })})</span>
            )}
          </p>
        ) : (
          <p className="text-lg">{t("report.no_score")}</p>
        )}
        <p className="mt-1">
          <ConfidenceDots value={r.confidence} />
        </p>
        <p className="mt-1 text-ink-soft">{confidenceReason(r)}</p>
      </div>

      {r.status === "engine_only" && (
        <p className="mt-4 border-l-[3px] border-rule pl-3 text-sm">{t("report.engine_only")}</p>
      )}

      {r.components.length > 0 && (
        <section className="mt-6">
          <h2 className="text-lg">{t("report.why")}</h2>
          {r.status === "published" && r.explanation ? (
            <p className="mt-2 measure">{r.explanation}</p>
          ) : (
            <ul className="mt-2 list-disc space-y-1 pl-5 measure">
              {r.components.map((c) => (
                <li key={c.name}>{c.why}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="mt-6">
        <h2 className="text-lg">{t("report.nearby")}</h2>
        {r.evidence.competitors.length === 0 ? (
          <p className="mt-2 text-ink-soft">{t("report.nearby_empty", { minutes })}</p>
        ) : (
          <>
            <table className="ruled mt-2 text-sm">
              <thead>
                <tr>
                  <th scope="col">{t("report.col_name")}</th>
                  <th scope="col" className="r">{t("report.col_distance")}</th>
                  <th scope="col" className="r">{t("report.col_rating")}</th>
                </tr>
              </thead>
              <tbody>
                {r.evidence.competitors.slice(0, 12).map((c, i) => (
                  <tr key={`${c.name}-${i}`}>
                    <td>
                      {c.name}
                      <span className="block text-xs text-ink-soft">{c.source_label}</span>
                    </td>
                    <td className="r num">{formatDistance(c.distance_m)}</td>
                    <td className="r num">
                      {c.rating !== null ? t("report.rating_n", { rating: c.rating, n: c.rating_count ?? 0 }) : "–"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {r.evidence.competitors.some((c) => c.source.includes("google")) && (
              <p className="mt-1 text-xs text-ink-soft">{t("report.google_attribution")}</p>
            )}
          </>
        )}
      </section>

      <section className="mt-6">
        <h2 className="text-lg">{t("report.cant_see")}</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 measure">
          {r.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </section>

      <Collapsible.Root className="mt-6">
        <Collapsible.Trigger className="group flex min-h-[44px] items-center gap-2 font-display text-lg font-bold text-ink">
          {t("report.how_we_know")}
          <CaretRight size={20} className="transition-transform group-data-[state=open]:rotate-90" aria-hidden="true" />
        </Collapsible.Trigger>
        <Collapsible.Content>
          <dl className="notebook mt-2 grid grid-cols-[1fr_auto] gap-x-4 text-sm leading-[28px]">
            <Evidence
              label={t("report.evidence_population", { minutes })}
              value={r.evidence.population.value !== null ? formatInt(r.evidence.population.value) : t("report.evidence_none")}
              source={t("common.source_date", { source: "WorldPop", date: r.evidence.population.as_of ?? "–" })}
            />
            <Evidence
              label={t("report.evidence_competitors")}
              value={String(r.evidence.competitors.length)}
              source={t("common.source_date", { source: "OpenStreetMap", date: formatDate(r.evidence.places_as_of) })}
            />
            <Evidence
              label={t("report.evidence_ground")}
              value={
                r.evidence.ground_count
                  ? t("report.evidence_ground_value", { count: r.evidence.ground_count.value, informal: r.evidence.ground_count.informal })
                  : t("report.evidence_none")
              }
              source={r.evidence.ground_count ? t("common.source_date", { source: r.evidence.ground_count.by, date: formatDate(r.evidence.ground_count.counted_on) }) : ""}
            />
            <Evidence
              label={t("report.evidence_survey")}
              value={
                r.evidence.survey
                  ? t("report.evidence_survey_value", { n: r.evidence.survey.n, share: percent(r.evidence.survey.share_travel_far), minutes: r.evidence.survey.travel_minutes })
                  : t("report.evidence_none")
              }
              source={r.evidence.survey ? formatDate(r.evidence.survey.as_of) : ""}
            />
            <Evidence
              label={t("report.evidence_rent")}
              value={
                r.evidence.rent_band?.median_inr_per_sqft
                  ? t("report.evidence_rent_value", { rent: formatInt(r.evidence.rent_band.median_inr_per_sqft), n: r.evidence.rent_band.n })
                  : t("report.evidence_none")
              }
              source=""
            />
          </dl>
          <p className="mt-2 text-sm">
            <Link href="/method#sources">{t("explore.see_method")}</Link>
          </p>
        </Collapsible.Content>
      </Collapsible.Root>

      {r.reviewed_by && (
        <p className="mt-6 font-bold">{t("report.reviewed_by", { name: r.reviewed_by.name, date: formatDate(r.reviewed_by.on) })}</p>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-2">
        <button type="button" className="btn btn-primary" onClick={save} disabled={saved}>
          <BookmarkSimple size={20} aria-hidden="true" />
          {saved ? t("report.saved") : t("report.save")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={share}>
          <ShareNetwork size={20} aria-hidden="true" />
          {copied ? t("report.copied") : t("report.share")}
        </button>
        {FEEDBACK_EMAIL && (
          <a
            className="btn btn-quiet"
            href={`mailto:${FEEDBACK_EMAIL}?subject=${encodeURIComponent(`${r.area.name} ${shortId(r.h3)} ${r.category.name}`)}`}
          >
            {t("report.feedback")}
          </a>
        )}
      </div>

      {r.neighbours.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg">{t("report.neighbours")}</h2>
          <ul className="mt-2">
            {r.neighbours.map((n) => (
              <li key={n.h3} className="border-b border-rule py-2 text-sm">
                <Link href={`/explore/${r.area.slug}/cell/${n.h3}?c=${r.category.slug}`}>
                  {t("report.neighbour_row", {
                    distance: formatDistance(n.distance_m),
                    direction: has(`directions.${n.direction}`) ? t(`directions.${n.direction}`) : n.direction,
                    score: n.score,
                  })}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

function Evidence({ label, value, source }: { label: string; value: string; source: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className="text-right num">
        {value}
        {source && <span className="block text-xs leading-4 text-ink-soft">{source}</span>}
      </dd>
    </>
  );
}
