"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { Geometry } from "geojson";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, type AreaDetail } from "@/lib/api";
import { clearDraft, deviceId, loadDraft, saveDraft, visibleQuestions, type Question, type SurveyDraft } from "@/lib/draft";
import { has, t } from "@/lib/i18n";
import { percent } from "@/lib/format";
import { AreaMap } from "@/components/map/AreaMap";
import { useAuth } from "@/components/providers";

interface Survey {
  slug: string;
  title: string;
  version: number;
  questions: Question[];
  area: { slug: string; name: string };
  already_answered: boolean;
}
interface Summary {
  n: number;
  min_n: number;
  shown: boolean;
  categories: { slug: string; name: string; n: number; share_travel_far: number }[];
}

function optionLabel(q: Question, opt: string): string {
  if (has(`survey.opt.${opt}`)) return t(`survey.opt.${opt}`);
  if (has(`category_short.${opt}`)) return t(`category_short.${opt}`);
  return opt;
}

export function SurveyFlow({ slug }: { slug: string }) {
  const { session, ready, me, refreshMe, configured } = useAuth();
  const qc = useQueryClient();
  const survey = useQuery({
    queryKey: ["survey", slug],
    queryFn: () => api<Survey>(`/surveys/${slug}`),
    enabled: !!session,
  });
  const [draft, setDraft] = useState<SurveyDraft | null>(null);
  const [geo, setGeo] = useState<{ lat: number; lng: number } | null>(null);
  const [confirmedOnMap, setConfirmedOnMap] = useState(false);
  const [phase, setPhase] = useState<"questions" | "sending" | "done" | "offline">("questions");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Load the saved draft once on the client (localStorage is not available on the server).
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time hydration from storage
    setDraft(loadDraft(slug));
  }, [slug]);

  const update = useCallback(
    (fn: (d: SurveyDraft) => SurveyDraft) =>
      setDraft((d) => {
        if (!d) return d;
        const next = fn(d);
        saveDraft(slug, next);
        return next;
      }),
    [slug],
  );

  const send = useCallback(async () => {
    if (!draft || !survey.data) return;
    setPhase("sending");
    setError(null);
    update((d) => ({ ...d, pending: true }));
    try {
      await api(`/surveys/${slug}/responses`, {
        method: "POST",
        headers: { "Idempotency-Key": draft.idempotencyKey },
        body: {
          answers: draft.answers,
          survey_version: survey.data.version,
          duration_seconds: Math.round((Date.now() - draft.startedAt) / 1000),
          device_id: deviceId(),
          geo,
          confirmed_on_map: confirmedOnMap,
        },
      });
      clearDraft(slug);
      setPhase("done");
      qc.invalidateQueries({ queryKey: ["survey", slug] });
    } catch (e) {
      if (e instanceof ApiError && e.code === "offline") {
        setPhase("offline");
      } else if (e instanceof ApiError && e.code === "already_answered") {
        clearDraft(slug);
        setPhase("done");
      } else {
        setError(e instanceof Error ? e.message : t("errors.generic"));
        setPhase("questions");
      }
    }
  }, [draft, survey.data, slug, geo, confirmedOnMap, update, qc]);

  // Retry automatically when the phone comes back online.
  useEffect(() => {
    if (phase !== "offline") return;
    const retry = () => void send();
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [phase, send]);

  if (!configured) return <p>{t("auth.not_configured")}</p>;
  if (!ready) return <p aria-live="polite">{t("common.loading")}</p>;
  if (!session)
    return (
      <Intro>
        <Link className="btn btn-primary mt-6" href={`/login?next=/survey/${slug}`}>
          {t("nav.login")}
        </Link>
      </Intro>
    );
  if (!me || survey.isPending || !draft) return <p aria-live="polite">{t("common.loading")}</p>;
  if (survey.isError) return <p role="alert">{(survey.error as Error).message}</p>;
  const s = survey.data;

  if (phase === "done") return <Thanks slug={slug} areaName={s.area.name} />;
  if (s.already_answered) return <p className="text-lg">{t("survey.already")}</p>;
  if (me.needs_consent) return <Consent version={me.current_consent_version} onDone={refreshMe} />;
  if (!me.home_h3)
    return (
      <HomePicker
        area={s.area.slug}
        onGeo={setGeo}
        onDone={() => {
          setConfirmedOnMap(true);
          refreshMe();
        }}
      />
    );

  return (
    <Questions
      questions={s.questions}
      draft={draft}
      update={update}
      onSend={send}
      sending={phase === "sending"}
      offline={phase === "offline"}
      error={error}
    />
  );
}

function Intro({ children }: { children?: React.ReactNode }) {
  return (
    <div>
      <h1 className="text-3xl font-extrabold">{t("survey.start_title")}</h1>
      <p className="mt-3 text-lg measure">{t("survey.start_intro")}</p>
      {children}
    </div>
  );
}

function Consent({ version, onDone }: { version: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div>
      <h1 className="text-3xl font-extrabold">{t("survey.consent_title")}</h1>
      <p className="mt-3 measure">{t("survey.consent_body")}</p>
      <p className="hint mt-2">
        {t("survey.consent_version", { version })}. <Link href="/method#s8">{t("nav.method")}</Link>
      </p>
      {err && <p className="mt-2 text-gamosa" role="alert">{err}</p>}
      <button
        type="button"
        className="btn btn-primary mt-6"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await api("/me/consent", { method: "POST", body: { version } });
            onDone();
          } catch (e) {
            setErr((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {t("survey.consent_agree")}
      </button>
    </div>
  );
}

function HomePicker({
  area,
  onGeo,
  onDone,
}: {
  area: string;
  onGeo: (g: { lat: number; lng: number }) => void;
  onDone: () => void;
}) {
  const a = useQuery({ queryKey: ["area", area], queryFn: () => api<AreaDetail>(`/areas/${area}`, { auth: false }) });
  const [pin, setPin] = useState<[number, number] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div>
      <h1 className="text-3xl font-extrabold">{t("survey.home_title")}</h1>
      <p className="mt-2">{t("survey.home_intro")}</p>
      <div className="relative mt-4 h-[50dvh] overflow-hidden rounded-input border border-rule">
        <AreaMap
          label={t("survey.home_pick")}
          boundary={(a.data?.boundary as Geometry | undefined) ?? null}
          bbox={a.data?.bbox ?? null}
          cells={[]}
          circled={[]}
          pin={pin}
          onMapClick={setPin}
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() =>
            navigator.geolocation?.getCurrentPosition((p) => {
              const g = { lat: p.coords.latitude, lng: p.coords.longitude };
              onGeo(g);
              setPin([g.lng, g.lat]);
            })
          }
        >
          {t("survey.home_use_location")}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!pin}
          onClick={async () => {
            if (!pin) return;
            setErr(null);
            try {
              await api("/me/home-cell", { method: "POST", body: { lat: pin[1], lng: pin[0] } });
              onDone();
            } catch (e) {
              setErr((e as Error).message);
            }
          }}
        >
          {t("survey.home_confirm")}
        </button>
      </div>
      {!pin && <p className="hint mt-2">{t("survey.home_pick")}</p>}
      {err && <p className="mt-2 text-gamosa" role="alert">{err}</p>}
    </div>
  );
}

function Questions({
  questions,
  draft,
  update,
  onSend,
  sending,
  offline,
  error,
}: {
  questions: Question[];
  draft: SurveyDraft;
  update: (fn: (d: SurveyDraft) => SurveyDraft) => void;
  onSend: () => void;
  sending: boolean;
  offline: boolean;
  error: string | null;
}) {
  const visible = useMemo(() => visibleQuestions(questions, draft.answers), [questions, draft.answers]);
  const step = Math.min(draft.step, visible.length - 1);
  const q = visible[step];
  if (!q) return null;
  const value = draft.answers[q.id];
  const last = step === visible.length - 1;
  const answered = q.type === "single" ? typeof value === "string" : Array.isArray(value);

  function choose(opt: string) {
    if (!q) return;
    update((d) => {
      const answers = { ...d.answers };
      if (q.type === "single") answers[q.id] = opt;
      else {
        const cur = Array.isArray(answers[q.id]) ? (answers[q.id] as string[]) : [];
        const has_ = cur.includes(opt);
        if (has_) answers[q.id] = cur.filter((x) => x !== opt);
        else if (!q.max || cur.length < q.max) answers[q.id] = [...cur, opt];
      }
      // drop answers to questions that are now hidden
      const vis = new Set(visibleQuestions(questions, answers).map((x) => x.id));
      for (const k of Object.keys(answers)) if (!vis.has(k)) delete answers[k];
      return { ...d, answers };
    });
  }

  return (
    <div>
      <p className="text-sm text-ink-soft num" aria-live="polite">
        {t("survey.progress", { n: step + 1, total: visible.length })}
      </p>
      <fieldset className="mt-2">
        <legend className="font-display text-2xl font-bold">{t(q.text_key)}</legend>
        {q.type === "multi" && q.max && <p className="hint mt-1">{t("survey.pick_up_to", { max: q.max })}</p>}
        <div className="mt-4 grid gap-2">
          {q.options.map((opt) => {
            const checked = q.type === "single" ? value === opt : Array.isArray(value) && value.includes(opt);
            return (
              <label
                key={opt}
                className={`flex min-h-[52px] cursor-pointer items-center gap-3 rounded-input border px-4 text-lg ${
                  checked ? "border-tea bg-mist" : "border-rule bg-sheet"
                }`}
              >
                <input
                  type={q.type === "single" ? "radio" : "checkbox"}
                  name={q.id}
                  checked={checked}
                  onChange={() => choose(opt)}
                  className="h-5 w-5 accent-[var(--tea)]"
                />
                {optionLabel(q, opt)}
              </label>
            );
          })}
        </div>
      </fieldset>
      <p className="hint mt-3">{t("survey.saved_draft")}</p>
      {offline && <p className="mt-3 font-bold" role="status">{t("survey.offline")}</p>}
      {error && <p className="mt-3 text-gamosa" role="alert">{error}</p>}
      <div className="mt-6 flex gap-2">
        {step > 0 && (
          <button type="button" className="btn btn-secondary" onClick={() => update((d) => ({ ...d, step: step - 1 }))}>
            {t("survey.back")}
          </button>
        )}
        {last ? (
          <button type="button" className="btn btn-primary" onClick={onSend} disabled={sending || offline}>
            {sending ? t("survey.sending") : t("survey.send")}
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary"
            disabled={!answered && q.type === "single"}
            onClick={() => update((d) => ({ ...d, step: step + 1 }))}
          >
            {t("survey.next")}
          </button>
        )}
      </div>
    </div>
  );
}

function Thanks({ slug, areaName }: { slug: string; areaName: string }) {
  const summary = useQuery({ queryKey: ["summary", slug], queryFn: () => api<Summary>(`/surveys/${slug}/summary`) });
  return (
    <div>
      <h1 className="text-3xl font-extrabold">{t("survey.thanks_title")}</h1>
      <p className="mt-2 text-lg">{t("survey.thanks_body", { area: areaName })}</p>
      <h2 className="mt-8 text-xl">{t("survey.summary_title")}</h2>
      {summary.data && !summary.data.shown && (
        <p className="mt-2 text-ink-soft">{t("survey.summary_hidden", { n: summary.data.n })}</p>
      )}
      {summary.data?.shown && (
        <ul className="mt-2">
          {summary.data.categories.map((c) => (
            <li key={c.slug} className="border-b border-rule py-2">
              {t("survey.summary_row", {
                share: percent(c.share_travel_far),
                category: has(`category_plural.${c.slug}`) ? t(`category_plural.${c.slug}`) : c.name,
              })}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
