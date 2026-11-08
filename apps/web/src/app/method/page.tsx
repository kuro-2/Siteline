import type { Metadata } from "next";
import { TopBar } from "@/components/TopBar";
import { t } from "@/lib/i18n";

export const metadata: Metadata = { title: t("method.title") };

const SECTIONS = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"] as const;

const SOURCES = ["osm", "worldpop", "google", "field", "survey", "rent"] as const;

export default function MethodPage() {
  return (
    <>
      <TopBar />
      <main id="main" className="px-4 py-10 lg:px-12">
        <article className="mx-auto max-w-[68ch]">
          <h1 className="text-3xl font-extrabold">{t("method.title")}</h1>
          <p className="mt-3 text-lg">{t("method.intro")}</p>
          {SECTIONS.map((s) => (
            <section key={s} id={s} className="mt-10">
              <h2 className="text-xl">{t(`method.${s}_title`)}</h2>
              <p className="mt-2">{t(`method.${s}`)}</p>
            </section>
          ))}
          <section id="sources" className="mt-10">
            <h2 className="text-xl">{t("method.sources_title")}</h2>
            <table className="ruled mt-3">
              <tbody>
                {SOURCES.map((k) => (
                  <tr key={k}>
                    <th scope="row" className="w-40 align-top text-sm text-ink">
                      {t(`method.source_rows.${k}_name`)}
                    </th>
                    <td>{t(`method.source_rows.${k}`)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </article>
      </main>
    </>
  );
}
