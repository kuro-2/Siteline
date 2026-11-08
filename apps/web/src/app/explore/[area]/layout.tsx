import "maplibre-gl/dist/maplibre-gl.css";
import { Suspense } from "react";
import { ExploreShell } from "@/components/explore/ExploreShell";
import { t } from "@/lib/i18n";

export default async function ExploreLayout({
  params,
  children,
}: {
  params: Promise<{ area: string }>;
  children: React.ReactNode;
}) {
  const { area } = await params;
  return (
    <Suspense fallback={<p className="p-6 text-ink-soft">{t("common.loading_area", { area })}</p>}>
      <ExploreShell area={area} />
      {children}
    </Suspense>
  );
}
