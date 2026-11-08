"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { shortId } from "@/lib/hex";
import { t } from "@/lib/i18n";
import { useAuth } from "@/components/providers";
import { TopBar } from "@/components/TopBar";

interface Saved {
  area: string;
  area_name: string;
  category: string | null;
  h3: string | null;
  created_at: string;
}

export default function AccountPage() {
  const { me, session, ready, signOut } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState("");
  const [deleted, setDeleted] = useState(false);
  const saved = useQuery({ queryKey: ["saved"], queryFn: () => api<Saved[]>("/saved-areas"), enabled: !!session });
  const remove = useMutation({
    mutationFn: (area: string) => api(`/saved-areas/${area}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved"] }),
  });
  const del = useMutation({
    mutationFn: () => api("/me", { method: "DELETE" }),
    onSuccess: async () => {
      setDeleted(true);
      await signOut();
    },
  });

  return (
    <>
      <TopBar />
      <main id="main" className="mx-auto max-w-2xl px-4 py-10">
        <h1 className="text-3xl font-extrabold">{t("account.title")}</h1>
        {deleted ? (
          <p className="mt-4 text-lg" role="status">
            {t("account.deleted")}
          </p>
        ) : !ready ? (
          <p className="mt-4">{t("common.loading")}</p>
        ) : !session ? (
          <p className="mt-4">
            {t("auth.required")} <Link href="/login?next=/account">{t("nav.login")}</Link>
          </p>
        ) : (
          <>
            <dl className="mt-6 grid grid-cols-[10rem_1fr] gap-y-2">
              <dt className="text-ink-soft">{t("account.email")}</dt>
              <dd>{me?.email ?? session.user.email}</dd>
              <dt className="text-ink-soft">{t("account.home")}</dt>
              <dd>
                {me?.home_h3 ? `${me.home_area?.name ?? ""}, ${t("report.block", { short: shortId(me.home_h3) })}` : t("account.home_none")}
              </dd>
              <dt className="text-ink-soft">{t("account.role")}</dt>
              <dd>{me?.role}</dd>
            </dl>
            <button type="button" className="btn btn-secondary mt-4" onClick={() => signOut().then(() => router.push("/"))}>
              {t("auth.logout")}
            </button>

            <section className="mt-10">
              <h2 className="text-xl">{t("account.saved")}</h2>
              {saved.data?.length === 0 && <p className="mt-2 text-ink-soft">{t("account.saved_empty")}</p>}
              <ul className="mt-2">
                {saved.data?.map((s) => (
                  <li key={s.area} className="flex items-center justify-between border-b border-rule py-2">
                    <Link href={s.h3 ? `/explore/${s.area}/cell/${s.h3}?c=${s.category ?? ""}` : `/explore/${s.area}`}>
                      {s.area_name}
                      {s.h3 ? `, ${t("report.block", { short: shortId(s.h3) })}` : ""}
                    </Link>
                    <span className="flex items-center gap-3 text-sm text-ink-soft">
                      {formatDate(s.created_at)}
                      <button type="button" className="btn btn-quiet" onClick={() => remove.mutate(s.area)}>
                        {t("account.remove")}
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <section className="mt-12 border-t border-rule pt-6">
              <h2 className="text-xl">{t("account.delete_title")}</h2>
              <p className="mt-2 measure">{t("account.delete_body")}</p>
              <label htmlFor="confirm-delete" className="label mt-4">
                {t("account.delete_confirm_label")}
              </label>
              <input
                id="confirm-delete"
                className="field max-w-xs"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="off"
              />
              {del.error && <p className="mt-2 text-gamosa" role="alert">{(del.error as Error).message}</p>}
              <button
                type="button"
                className="btn btn-danger mt-3"
                disabled={confirm !== "DELETE" || del.isPending}
                onClick={() => del.mutate()}
              >
                {t("account.delete")}
              </button>
            </section>
          </>
        )}
      </main>
    </>
  );
}
