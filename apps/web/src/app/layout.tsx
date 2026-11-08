import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible_Next, Bricolage_Grotesque } from "next/font/google";
import { Providers } from "@/components/providers";
import { APP_NAME } from "@/lib/config";
import { t } from "@/lib/i18n";
import "./globals.css";

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: "variable",
  axes: ["opsz"],
  variable: "--font-bricolage",
  display: "swap",
});

const atkinson = Atkinson_Hyperlegible_Next({
  subsets: ["latin"],
  weight: "variable",
  variable: "--font-atkinson",
  adjustFontFallback: false,
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: `${APP_NAME}: ${t("app.tagline")}`, template: `%s | ${APP_NAME}` },
  description: t("app.description"),
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfcfa" },
    { media: "(prefers-color-scheme: dark)", color: "#182327" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={`${bricolage.variable} ${atkinson.variable}`}>
      <body>
        <a
          href="#main"
          className="sr-only z-50 rounded-button bg-sheet p-3 focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        >
          {t("nav.skip")}
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
