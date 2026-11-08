import Link from "next/link";
import { LandingHero } from "@/components/landing/LandingHero";
import { TopBar } from "@/components/TopBar";
import { t } from "@/lib/i18n";

export default function Home() {
  return (
    <>
      <TopBar />
      <main id="main">
        <LandingHero />
        {/* Below the fold: one short section, told as a real process with real people. */}
        <section className="border-t border-rule bg-sheet px-4 py-12 lg:px-12 lg:py-18">
          <div className="mx-auto max-w-[68ch]">
            <h2 className="text-2xl">{t("landing.how_title")}</h2>
            <ol className="mt-6 space-y-5 text-lg">
              {(["how_1", "how_2", "how_3", "how_4"] as const).map((k, i) => (
                <li key={k} className="grid grid-cols-[2rem_1fr] gap-2">
                  <span className="font-display font-bold text-ink-soft num">{i + 1}.</span>
                  <span>{t(`landing.${k}`)}</span>
                </li>
              ))}
            </ol>
            <p className="mt-8">
              <Link href="/method" className="font-bold">
                {t("landing.method_link")}
              </Link>
            </p>
          </div>
        </section>
      </main>
    </>
  );
}
