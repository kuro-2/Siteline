"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { DEFAULT_AREA } from "@/lib/config";
import { formatDate, formatRupees } from "@/lib/format";
import { t } from "@/lib/i18n";
import { StaffGate } from "@/components/StaffGate";
import { TopBar } from "@/components/TopBar";

interface Fresh { source: string; job: string; last_success: string | null; age_days: number | null; last_failure: { at: string; error: string } | null }
interface Costs { rows: { provider: string; sku: string; month: string; calls: number; est_cost_usd: number; est_cost_inr: number }[] }
interface Job { id: string; job: string; status: string; started_at: string; counts: Record<string, unknown> | null; error: string | null }
interface Backtest { id: string; as_of: string; evaluated_on: string; metrics: { categories_beating_baselines: number; good_enough_to_publish: boolean }; created_at: string }
interface Calib { bands: { band: string; published: number; opened: number; closed: number }[] }
interface User { id: string; email: string; display_name: string | null; role: string }

const JOBS = ["ingest-osm", "ingest-worldpop", "dedupe", "score", "explain", "ingest-google", "ingest-kobo", "google-expire", "outcomes", "backtest"];
const ROLES = ["public", "resident", "surveyor", "analyst", "admin"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-xl">{title}</h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function Admin() {
  const qc = useQueryClient();
  const fresh = useQuery({ queryKey: ["admin", "fresh"], queryFn: () => api<Fresh[]>("/admin/freshness") });
  const costs = useQuery({ queryKey: ["admin", "costs"], queryFn: () => api<Costs>("/admin/costs") });
  const jobs = useQuery({ queryKey: ["admin", "jobs"], queryFn: () => api<Job[]>("/admin/jobs?limit=20") });
  const backtests = useQuery({ queryKey: ["admin", "bt"], queryFn: () => api<Backtest[]>("/admin/backtests") });
  const calib = useQuery({ queryKey: ["admin", "calib"], queryFn: () => api<Calib>("/admin/calibration") });
  const [q, setQ] = useState("");
  const users = useQuery({ queryKey: ["admin", "users", q], queryFn: () => api<User[]>(`/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`) });
  const [dry, setDry] = useState(true);
  const [job, setJob] = useState(JOBS[0] ?? "ingest-osm");
  const [note, setNote] = useState<string | null>(null);
  const [report, setReport] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: () => api(`/admin/jobs/${job}`, { method: "POST", body: { dry_run: dry, area: DEFAULT_AREA } }),
    onSuccess: () => {
      setNote(t("admin.started"));
      setTimeout(() => qc.invalidateQueries({ queryKey: ["admin"] }), 3000);
    },
    onError: (e) => setNote((e as Error).message),
  });
  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => api(`/admin/users/${id}/role`, { method: "POST", body: { role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });

  return (
    <main id="main" className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-3xl font-extrabold">{t("admin.title")}</h1>

      <Section title={t("admin.freshness")}>
        <table className="ruled">
          <thead><tr><th scope="col">{t("admin.col_source")}</th><th scope="col">{t("admin.col_last")}</th><th scope="col" /></tr></thead>
          <tbody>
            {fresh.data?.map((f) => (
              <tr key={f.job}>
                <td className="font-bold">{f.source}</td>
                <td>{f.last_success ? `${formatDate(f.last_success)} (${t("admin.age", { n: Math.round(f.age_days ?? 0) })})` : t("admin.never")}</td>
                <td className="text-sm text-gamosa">{f.last_failure && (!f.last_success || f.last_failure.at > f.last_success) ? f.last_failure.error?.slice(0, 120) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title={t("admin.costs")}>
        {costs.data?.rows.length === 0 ? (
          <p className="text-ink-soft">{t("admin.costs_empty")}</p>
        ) : (
          <table className="ruled">
            <thead><tr><th scope="col">{t("admin.col_month")}</th><th scope="col">{t("admin.col_sku")}</th><th scope="col" className="r">{t("admin.col_calls")}</th><th scope="col" className="r">{t("admin.col_cost")}</th></tr></thead>
            <tbody>
              {costs.data?.rows.map((r) => (
                <tr key={`${r.month}-${r.sku}`}>
                  <td>{r.month.slice(0, 7)}</td><td>{r.sku}</td>
                  <td className="r num">{r.calls}</td><td className="r num">{formatRupees(r.est_cost_inr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={t("admin.jobs")}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="label">{t("admin.col_job")}</span>
            <select className="field" value={job} onChange={(e) => setJob(e.target.value)}>
              {JOBS.map((j) => <option key={j} value={j}>{j}</option>)}
            </select>
          </label>
          <label className="flex min-h-[44px] items-center gap-2">
            <input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} className="h-5 w-5 accent-[var(--tea)]" />
            {t("admin.dry_run")}
          </label>
          <button type="button" className="btn btn-primary" onClick={() => run.mutate()}>{t("admin.run")}</button>
        </div>
        {note && <p className="mt-2" role="status">{note}</p>}
        <table className="ruled mt-4 text-sm">
          <thead><tr><th scope="col">{t("admin.col_job")}</th><th scope="col">{t("admin.col_status")}</th><th scope="col">{t("admin.col_started")}</th><th scope="col" /></tr></thead>
          <tbody>
            {jobs.data?.map((j) => (
              <tr key={j.id}>
                <td>{j.job}</td>
                <td className={j.status === "failed" ? "text-gamosa" : ""}>{j.status}</td>
                <td className="num">{formatDate(j.started_at)} {new Date(j.started_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" })}</td>
                <td className="max-w-md truncate text-ink-soft">{j.error ?? (j.counts ? JSON.stringify(j.counts).slice(0, 140) : "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title={t("admin.backtests")}>
        {backtests.data?.length === 0 && <p className="text-ink-soft">{t("admin.backtests_empty")}</p>}
        <ul>
          {backtests.data?.map((b) => (
            <li key={b.id} className="flex items-center justify-between border-b border-rule py-2">
              <span>
                {b.as_of} → {b.evaluated_on}: {b.metrics.categories_beating_baselines}/5
              </span>
              <button type="button" className="btn btn-quiet" onClick={async () => setReport((await api<{ report_md: string }>(`/admin/backtests/${b.id}`)).report_md)}>
                {t("admin.view_report")}
              </button>
            </li>
          ))}
        </ul>
        {report && <pre className="mt-3 max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-input border border-rule bg-sheet p-3 text-sm">{report}</pre>}
      </Section>

      <Section title={t("admin.calibration")}>
        {calib.data?.bands.length === 0 ? (
          <p className="text-ink-soft">{t("admin.calibration_empty")}</p>
        ) : (
          <table className="ruled">
            <tbody>
              {calib.data?.bands.map((b) => (
                <tr key={b.band}>
                  <th scope="row" className="text-ink">{t(`confidence.${b.band}`)}</th>
                  <td className="r num">{b.published}</td><td className="r num">{b.opened}</td><td className="r num">{b.closed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={t("admin.users")}>
        <label htmlFor="user-q" className="label">{t("admin.search_users")}</label>
        <input id="user-q" className="field max-w-sm" value={q} onChange={(e) => setQ(e.target.value)} />
        <table className="ruled mt-3">
          <thead><tr><th scope="col">{t("admin.col_email")}</th><th scope="col">{t("admin.col_role")}</th></tr></thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id}>
                <td>{u.email}{u.display_name ? <span className="block text-sm text-ink-soft">{u.display_name}</span> : null}</td>
                <td>
                  <label className="sr-only" htmlFor={`role-${u.id}`}>{t("admin.set_role")}</label>
                  <select id={`role-${u.id}`} className="field" value={u.role} onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value })}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </main>
  );
}

export default function AdminPage() {
  return (
    <>
      <TopBar />
      <StaffGate role="admin">
        <Admin />
      </StaffGate>
    </>
  );
}
