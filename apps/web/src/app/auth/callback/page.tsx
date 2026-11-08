"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { t } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

function Callback() {
  const router = useRouter();
  const params = useSearchParams();
  const [failed, setFailed] = useState(() => supabase() === null);

  useEffect(() => {
    const sb = supabase();
    const next = params.get("next") || "/";
    const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/";
    const code = params.get("code");
    if (!sb) return;
    (async () => {
      if (code) {
        const { error } = await sb.auth.exchangeCodeForSession(code);
        if (error) {
          // detectSessionInUrl may already have exchanged it
          const { data } = await sb.auth.getSession();
          if (!data.session) {
            setFailed(true);
            return;
          }
        }
      }
      router.replace(safeNext);
    })();
  }, [params, router]);

  if (failed)
    return (
      <p className="mt-4">
        {t("auth.callback_failed")} <Link href="/login">{t("auth.send")}</Link>
      </p>
    );
  return <p className="mt-4" aria-live="polite">{t("auth.callback")}</p>;
}

export default function CallbackPage() {
  return (
    <main id="main" className="mx-auto max-w-xl px-4 py-10">
      <Suspense>
        <Callback />
      </Suspense>
    </main>
  );
}
