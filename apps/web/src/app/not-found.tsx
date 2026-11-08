import Link from "next/link";
import { TopBar } from "@/components/TopBar";
import { DEFAULT_AREA } from "@/lib/config";
import { t } from "@/lib/i18n";

export default function NotFound() {
  return (
    <>
      <TopBar />
      <main id="main" className="mx-auto max-w-xl px-4 py-12">
        <h1 className="text-3xl font-extrabold">{t("errors.not_found_title")}</h1>
        <p className="mt-2">
          {t("errors.not_found_body")}{" "}
          <Link href={`/explore/${DEFAULT_AREA}`}>{t("nav.explore")}</Link>
        </p>
      </main>
    </>
  );
}
