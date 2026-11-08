"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { t } from "@/lib/i18n";
import { useAuth } from "./providers";

/** Renders children only for analysts/admins (the API enforces this too). */
export function StaffGate({ role = "analyst", children }: { role?: "analyst" | "admin"; children: ReactNode }) {
  const { ready, session, me } = useAuth();
  if (!ready || (session && !me)) return <p className="p-6">{t("common.loading")}</p>;
  if (!session)
    return (
      <p className="p-6">
        {t("auth.required")} <Link href="/login">{t("nav.login")}</Link>
      </p>
    );
  const ok = role === "admin" ? me?.role === "admin" : me?.role === "analyst" || me?.role === "admin";
  if (!ok) return <p className="p-6">{t("errors.forbidden")}</p>;
  return <>{children}</>;
}
