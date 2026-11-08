"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { TopBar } from "@/components/TopBar";
import { t } from "@/lib/i18n";
import { supabase } from "@/lib/supabase";

function LoginForm() {
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);
  const sb = supabase();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!sb) return;
    setState("sending");
    setError(null);
    const redirect = `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;
    const { error: err } = await sb.auth.signInWithOtp({ email, options: { emailRedirectTo: redirect } });
    if (err) {
      setError(err.message);
      setState("idle");
    } else {
      setState("sent");
    }
  }

  if (!sb) return <p className="mt-4">{t("auth.not_configured")}</p>;
  if (state === "sent") return <p className="mt-4 text-lg" role="status">{t("auth.sent")}</p>;
  return (
    <form onSubmit={submit} className="mt-6 max-w-sm">
      <label htmlFor="email" className="label">
        {t("auth.email")}
      </label>
      <input
        id="email"
        type="email"
        required
        autoComplete="email"
        inputMode="email"
        className="field"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      {error && (
        <p className="mt-2 text-sm text-gamosa" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="btn btn-primary mt-4" disabled={state === "sending"}>
        {t("auth.send")}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <>
      <TopBar />
      <main id="main" className="mx-auto max-w-xl px-4 py-10">
        <h1 className="text-3xl font-extrabold">{t("auth.title")}</h1>
        <p className="mt-2">{t("auth.intro")}</p>
        <Suspense>
          <LoginForm />
        </Suspense>
      </main>
    </>
  );
}
