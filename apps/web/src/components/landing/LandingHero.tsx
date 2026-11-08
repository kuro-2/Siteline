"use client";

import type { Geometry } from "geojson";

import "maplibre-gl/dist/maplibre-gl.css";
import { MagnifyingGlass } from "@phosphor-icons/react/dist/ssr";
import { useQuery } from "@tanstack/react-query";
import { latLngToCell } from "h3-js";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError, type AreaDetail, type GeocodeResult, type MapResponse, type TopPick } from "@/lib/api";
import { DEFAULT_AREA } from "@/lib/config";
import { t } from "@/lib/i18n";
import { AreaMap } from "@/components/map/AreaMap";

export function LandingHero() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<GeocodeResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const area = useQuery({
    queryKey: ["area", DEFAULT_AREA],
    queryFn: () => api<AreaDetail>(`/areas/${DEFAULT_AREA}`, { auth: false }),
  });
  const top = useQuery({
    queryKey: ["top", DEFAULT_AREA, "all"],
    queryFn: () => api<TopPick[]>(`/areas/${DEFAULT_AREA}/top?limit=5`, { auth: false }),
  });
  const firstCat = top.data?.[0]?.category ?? "pharmacy";
  const cells = useQuery({
    queryKey: ["map", DEFAULT_AREA, firstCat],
    queryFn: () => api<MapResponse>(`/areas/${DEFAULT_AREA}/map?category=${firstCat}`, { auth: false }),
  });
  const name = area.data?.name ?? "";
  // Keep the area clear of the question card: card on the left (desktop) or bottom (mobile).
  const [heroPadding] = useState(() =>
    typeof window !== "undefined" && window.innerWidth >= 1024
      ? { top: 60, right: 60, bottom: 60, left: 660 }
      : { top: 40, right: 24, bottom: 360, left: 24 },
  );

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<GeocodeResult[]>(`/areas/${DEFAULT_AREA}/geocode?q=${encodeURIComponent(q)}`, { auth: false });
      if (r.length === 1 && r[0]) go(r[0]);
      else setResults(r);
      if (r.length === 0) setError(t("check.no_results", { area: name }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.generic"));
    } finally {
      setBusy(false);
    }
  }

  function go(r: GeocodeResult) {
    const h3 = latLngToCell(r.lat, r.lng, 9);
    router.push(`/explore/${DEFAULT_AREA}/cell/${h3}?c=${firstCat}`);
  }

  return (
    <section className="relative h-[100svh] min-h-[560px]">
      <div className="absolute inset-0">
        <AreaMap
          label={t("explore.map_label", { area: name, category: firstCat })}
          boundary={(area.data?.boundary as Geometry | undefined) ?? null}
          bbox={area.data?.bbox ?? null}
          cells={cells.data?.cells ?? []}
          circled={(top.data ?? []).filter((p) => p.category === firstCat).map((p) => p.h3)}
          showControls={false}
          interactive={false}
          padding={heroPadding}
        />
      </div>
      <div className="absolute inset-x-4 bottom-6 mx-auto max-w-[560px] rounded-sheet bg-sheet p-5 shadow-float lg:inset-x-auto lg:bottom-auto lg:left-12 lg:top-28 lg:p-7">
        <h1 className="text-[clamp(33px,6vw,42px)] font-extrabold">{t("landing.question")}</h1>
        <p className="mt-2 text-lg">{t("landing.sub")}</p>
        <form onSubmit={search} className="mt-5 flex gap-2" role="search">
          <label htmlFor="area-search" className="sr-only">
            {t("landing.search_label")}
          </label>
          <input
            id="area-search"
            className="field"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("landing.search_placeholder")}
            autoComplete="off"
          />
          <button type="submit" className="btn btn-secondary shrink-0" aria-label={t("check.search_button")} disabled={busy}>
            <MagnifyingGlass size={20} aria-hidden="true" />
          </button>
        </form>
        {error && (
          <p className="mt-2 text-sm text-gamosa" role="alert">
            {error}
          </p>
        )}
        {results && results.length > 1 && (
          <ul className="mt-2 border-t border-rule">
            {results.map((r) => (
              <li key={`${r.lat},${r.lng}`} className="border-b border-rule">
                <button type="button" className="min-h-[44px] w-full text-left" onClick={() => go(r)}>
                  {r.name}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Link href={`/explore/${DEFAULT_AREA}`} className="btn btn-primary">
            {name ? t("landing.explore_area", { area: name }) : t("nav.explore")}
          </Link>
          <Link href="/check">{t("landing.idea_link")}</Link>
        </div>
      </div>
    </section>
  );
}
