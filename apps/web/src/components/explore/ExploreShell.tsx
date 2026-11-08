"use client";

import type { Geometry } from "geojson";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { api, type AreaDetail, type CellReport as Report, type Category, type MapResponse, type TopPick } from "@/lib/api";
import { has, t } from "@/lib/i18n";
import { AreaMap } from "@/components/map/AreaMap";
import { CellReport } from "@/components/report/CellReport";
import { TopBar } from "@/components/TopBar";
import { CategorySwitcher } from "./CategorySwitcher";
import { Legend } from "./Legend";
import { CellList, RankedList } from "./Lists";
import { Sheet, type Snap } from "./Sheet";

export function ExploreShell({ area }: { area: string }) {
  const params = useParams<{ h3?: string }>();
  const pathname = usePathname();
  const search = useSearchParams();
  const router = useRouter();
  const selected = params.h3 ?? null;
  const [snapState, setSnap] = useState<{ snap: Snap; for: string | null }>({
    snap: selected ? "half" : "peek",
    for: selected,
  });
  // Opening a cell lifts the sheet from peek to half (derived, not an effect).
  const snap: Snap =
    snapState.for !== selected && selected && snapState.snap === "peek" ? "half" : snapState.snap;
  const onSnap = useCallback((s: Snap) => setSnap({ snap: s, for: selected }), [selected]);
  const [listView, setListView] = useState(false);

  const areaQ = useQuery({ queryKey: ["area", area], queryFn: () => api<AreaDetail>(`/areas/${area}`, { auth: false }) });
  const catsQ = useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories", { auth: false }) });
  const cats = useMemo(() => catsQ.data ?? [], [catsQ.data]);
  const category = search.get("c") ?? cats[0]?.slug ?? "pharmacy";
  const catObj = cats.find((c) => c.slug === category);

  const mapQ = useQuery({
    queryKey: ["map", area, category],
    queryFn: () => api<MapResponse>(`/areas/${area}/map?category=${category}`, { auth: false }),
    enabled: !!catObj,
  });
  const topAllQ = useQuery({
    queryKey: ["top", area, "all"],
    queryFn: () => api<TopPick[]>(`/areas/${area}/top?limit=5`, { auth: false }),
  });
  const topCatQ = useQuery({
    queryKey: ["top", area, category],
    queryFn: () => api<TopPick[]>(`/areas/${area}/top?category=${category}&limit=3`, { auth: false }),
    enabled: !!catObj,
  });
  const reportQ = useQuery({
    queryKey: ["report", selected, category],
    queryFn: () => api<Report>(`/cells/${selected}/report?category=${category}`, { auth: false }),
    enabled: !!selected && !!catObj,
  });

  const qs = `?c=${category}`;
  const hrefFor = useCallback((h3: string) => `/explore/${area}/cell/${h3}${qs}`, [area, qs]);
  const areaHref = `/explore/${area}${qs}`;
  const setCategory = (slug: string) => router.replace(`${pathname}?c=${slug}`, { scroll: false });
  const onSelect = useCallback((h3: string) => router.push(hrefFor(h3), { scroll: false }), [router, hrefFor]);

  const areaName = areaQ.data?.name ?? "";
  const plural = has(`category_plural.${category}`) ? t(`category_plural.${category}`) : (catObj?.name ?? "");
  const circled = useMemo(() => (topCatQ.data ?? []).map((p) => p.h3), [topCatQ.data]);

  if (areaQ.isError) {
    return (
      <>
        <TopBar />
        <main id="main" className="mx-auto max-w-xl p-6">
          <h1 className="text-2xl">{t("explore.error_title", { area })}</h1>
          <p className="mt-2 text-ink-soft">{(areaQ.error as Error).message}</p>
          <button type="button" className="btn btn-secondary mt-4" onClick={() => areaQ.refetch()}>
            {t("common.retry")}
          </button>
        </main>
      </>
    );
  }

  const switcher = cats.length > 0 && <CategorySwitcher categories={cats} value={category} onChange={setCategory} />;

  return (
    <div className="flex h-dvh flex-col">
      <TopBar areaName={areaName}>{switcher}</TopBar>
      <div className="border-b border-rule bg-sheet px-4 py-2 lg:hidden">{switcher}</div>
      <main id="main" className="relative flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {listView ? (
            <div className="h-full overflow-y-auto bg-mist px-4 pb-[20dvh] pt-4 lg:px-8">
              <button type="button" className="btn btn-secondary" onClick={() => setListView(false)}>
                {t("common.map_view")}
              </button>
              <CellList cells={mapQ.data?.cells ?? []} hrefFor={hrefFor} />
            </div>
          ) : (
            <AreaMap
              label={t("explore.map_label", { area: areaName, category: plural })}
              boundary={(areaQ.data?.boundary as Geometry | undefined) ?? null}
              bbox={areaQ.data?.bbox ?? null}
              cells={mapQ.data?.cells ?? []}
              circled={circled}
              selected={selected}
              onSelect={onSelect}
            />
          )}
          {!listView && (
            <div className="absolute bottom-4 left-4 hidden flex-col items-start gap-2 lg:flex">
              <Legend />
              <button type="button" className="btn btn-secondary" onClick={() => setListView(true)}>
                {t("explore.open_list")}
              </button>
            </div>
          )}
          {!listView && (
            <button
              type="button"
              className="btn btn-secondary absolute right-3 top-3 lg:hidden"
              onClick={() => setListView(true)}
            >
              {t("common.list_view")}
            </button>
          )}
        </div>

        <Sheet label={selected ? t("report.how_we_know") : t("explore.title")} snap={snap} onSnap={onSnap}>
          {selected ? (
            reportQ.isPending ? (
              <p className="pt-2 text-ink-soft" aria-live="polite">{t("report.loading")}</p>
            ) : reportQ.isError ? (
              <div className="pt-2">
                <p className="font-bold">{(reportQ.error as Error).message}</p>
                <Link href={areaHref}>{t("report.back_to_area", { area: areaName })}</Link>
              </div>
            ) : (
              <CellReport report={reportQ.data} areaHref={areaHref} />
            )
          ) : (
            <div>
              <h1 className="text-3xl font-extrabold">{areaName || t("common.loading_area", { area })}</h1>
              <p className="mt-1 font-display text-lg font-bold text-ink-soft">{t("explore.title")}</p>
              {topAllQ.data && (
                <RankedList
                  picks={topAllQ.data}
                  hrefFor={(h3) => {
                    const p = topAllQ.data.find((x) => x.h3 === h3);
                    return `/explore/${area}/cell/${h3}?c=${p?.category ?? category}`;
                  }}
                  areaName={areaName}
                  categoryName={plural}
                />
              )}
              {topAllQ.data?.length === 0 && mapQ.data?.cells.length === 0 && (
                <p className="mt-3 text-ink-soft">{t("explore.no_run", { area: areaName })}</p>
              )}
              <p className="mt-4 text-sm text-ink-soft">{t("explore.pick_cell")}</p>
              {areaQ.data?.survey_slug && (
                <p className="mt-6 border-t border-rule pt-4">
                  <Link href={`/survey/${areaQ.data.survey_slug}`} className="font-bold">
                    {t("explore.survey_prompt")}
                  </Link>
                </p>
              )}
              <div className="mt-6 lg:hidden">
                <Legend />
              </div>
            </div>
          )}
        </Sheet>
      </main>
    </div>
  );
}
