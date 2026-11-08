"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { APP_NAME } from "@/lib/config";
import { t } from "@/lib/i18n";
import { useAuth } from "./providers";

/** Thin bar on --sheet. The middle slot holds the area name and category switcher. */
export function TopBar({ children, areaName }: { children?: ReactNode; areaName?: string }) {
  const { me, session, configured } = useAuth();
  const staff = me && (me.role === "analyst" || me.role === "admin");
  return (
    <header className="relative z-20 flex min-h-[52px] items-center gap-3 border-b border-rule bg-sheet px-4 lg:gap-6 lg:px-6">
      <Link href="/" className="font-display text-lg font-extrabold tracking-[-0.01em] text-ink no-underline">
        {APP_NAME}
      </Link>
      {areaName && <span className="hidden text-sm text-ink-soft sm:inline">{t("nav.pilot", { area: areaName })}</span>}
      <div className="hidden min-w-0 flex-1 lg:block">{children}</div>
      <nav aria-label="Main" className="ml-auto flex items-center gap-1 text-sm lg:ml-0">
        <Link className="hidden px-2 py-3 md:inline" href="/check">
          {t("nav.check")}
        </Link>
        <Link className="hidden px-2 py-3 md:inline" href="/method">
          {t("nav.method")}
        </Link>
        {staff && (
          <Link className="px-2 py-3" href="/review">
            {t("nav.review")}
          </Link>
        )}
        {me?.role === "admin" && (
          <Link className="px-2 py-3" href="/admin">
            {t("nav.admin")}
          </Link>
        )}
        {configured &&
          (session ? (
            <Link className="px-2 py-3" href="/account">
              {t("nav.account")}
            </Link>
          ) : (
            <Link className="px-2 py-3 font-bold" href="/login">
              {t("nav.login")}
            </Link>
          ))}
      </nav>
    </header>
  );
}
