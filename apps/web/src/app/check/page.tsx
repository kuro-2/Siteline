"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { Geometry } from "geojson";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError, type AreaDetail, type Category, type CheckResponse, type GeocodeResult } from "@/lib/api";
import { DEFAULT_AREA } from "@/lib/config";
import { t } from "@/lib/i18n";
import { AreaMap } from "@/components/map/AreaMap";
import { CellReport } from "@/components/report/CellReport";
import { TopBar } from "@/components/TopBar";

export default function CheckPage() {
  const [category, setCategory] = useState("pharmacy");
  const [pin, setPin] = useState<[number, number] | null>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<GeocodeResult[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const area = useQuery({ queryKey: ["area", DEFAULT_AREA], queryFn: () => api<AreaDetail>(`/areas/${DEFAULT_AREA}`, { auth: false }) });
  const cats = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories", { auth: false }) });
  const check = useMutation({
    mutationFn: (b: { lat: number; lng: number; category: string }) =>
      api<CheckResponse>("/check", { method: "POST", body: b, auth: false }),
  });
  const name = area.data?.name ?? "";

  async function search(e: React.FormEvent) {
    e.preventDefault();
    setSearchError(null);
    try {
      const r = await api<GeocodeResult[]>(`/areas/${DEFAULT_AREA}/geocode?q=${encodeURIComponent(q)}`, { auth: false });
      setResults(r);
      if (r.length === 0) setSearchError(t("check.no_results", { area: name }));
    } catch (err) {
      setSearchError(err instanceof ApiError ? err.message : t("errors.generic"));
    }
  }

  function submit() {
    if (!pin) return;
    check.mutate({ lat: pin[1], lng: pin[0], category });
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <TopBar areaName={name} />
      <main id="main" className="flex flex-1 flex-col lg:flex-row">
        <div className="relative h-[45dvh] lg:h-auto lg:flex-1">
          <AreaMap
            label={t("check.pin_hint")}
            boundary={(area.data?.boundary as Geometry | undefined) ?? null}
            bbox={area.data?.bbox ?? null}
            cells={[]}
            circled={[]}
            pin={pin}
            onMapClick={(ll) => {
              setPin(ll);
              check.reset();
            }}
          />
        </div>
        <section className="bg-sheet px-4 py-6 lg:w-[460px] lg:overflow-y-auto lg:border-l lg:border-rule lg:px-6">
          {check.data ? (
            <>
              <button type="button" className="btn btn-quiet -ml-2" onClick={() => check.reset()}>
                {t("common.back")}
              </button>
              {check.data.advice && <p className="mt-2 border-l-[3px] border-muga pl-3">{check.data.advice}</p>}
              <div className="mt-4">
                <CellReport report={check.data.report} areaHref={`/explore/${DEFAULT_AREA}?c=${category}`} />
              </div>
            </>
          ) : (
            <>
              <h1 className="text-3xl font-extrabold">{t("check.title")}</h1>
              <p className="mt-2">{t("check.intro")}</p>
              <fieldset className="mt-6">
                <legend className="label">{t("check.category")}</legend>
                <div className="mt-1 grid gap-2">
                  {(cats.data ?? []).map((c) => (
                    <label key={c.slug} className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-input border border-rule px-3">
                      <input
                        type="radio"
                        name="category"
                        value={c.slug}
                        checked={category === c.slug}
                        onChange={() => setCategory(c.slug)}
                        className="accent-[var(--tea)]"
                      />
                      {c.name}
                    </label>
                  ))}
                </div>
              </fieldset>
              <form onSubmit={search} className="mt-6" role="search">
                <label htmlFor="check-search" className="label">
                  {t("check.search")}
                </label>
                <div className="flex gap-2">
                  <input id="check-search" className="field" value={q} onChange={(e) => setQ(e.target.value)} />
                  <button type="submit" className="btn btn-secondary">
                    {t("check.search_button")}
                  </button>
                </div>
                {searchError && <p className="mt-2 text-sm text-gamosa" role="alert">{searchError}</p>}
                {results && results.length > 0 && (
                  <ul className="mt-2 border-t border-rule" aria-label={t("check.results")}>
                    {results.map((r) => (
                      <li key={`${r.lat},${r.lng}`} className="border-b border-rule">
                        <button
                          type="button"
                          className="min-h-[44px] w-full text-left"
                          onClick={() => {
                            setPin([r.lng, r.lat]);
                            setResults(null);
                          }}
                        >
                          {r.name}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="hint mt-2">{t("check.pin_hint")}</p>
              </form>
              {check.error && (
                <p className="mt-4 text-gamosa" role="alert">
                  {(check.error as Error).message}
                </p>
              )}
              <button type="button" className="btn btn-primary mt-6" onClick={submit} disabled={!pin || check.isPending}>
                {t("check.submit")}
              </button>
              {!pin && <p className="hint mt-2">{t("check.pin_needed")}</p>}
            </>
          )}
        </section>
      </main>
    </div>
  );
}
