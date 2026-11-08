"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Confidence } from "@/lib/format";
import { shortId } from "@/lib/hex";
import { t } from "@/lib/i18n";
import { ConfidenceDots } from "@/components/ui/ConfidenceDots";
import { StaffGate } from "@/components/StaffGate";
import { TopBar } from "@/components/TopBar";

interface QueueItem {
  id: string;
  h3: string;
  status: string;
  engine_score: number;
  confidence: Confidence;
  category: string;
  category_name: string;
  area_name: string;
  priority: number;
  data_age_days: number;
}
interface Flagged {
  id: string;
  h3: string;
  fraud_flags: string[];
  submitted_at: string;
  duration_seconds: number | null;
  survey: string;
}

function Queue() {
  const qc = useQueryClient();
  const queue = useQuery({ queryKey: ["review-queue"], queryFn: () => api<QueueItem[]>("/review/queue") });
  const flagged = useQuery({ queryKey: ["flagged"], queryFn: () => api<Flagged[]>("/review/flagged-responses") });
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "clear" | "exclude" }) =>
      api(`/review/flagged-responses/${id}`, { method: "POST", body: { action } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["flagged"] }),
  });

  return (
    <main id="main" className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-3xl font-extrabold">{t("review.title")}</h1>
      {queue.data?.length === 0 && <p className="mt-4 text-ink-soft">{t("review.empty")}</p>}
      {queue.error && <p className="mt-4 text-gamosa">{(queue.error as Error).message}</p>}
      {queue.data && queue.data.length > 0 && (
        <table className="ruled mt-6">
          <thead>
            <tr>
              <th scope="col">{t("review.col_where")}</th>
              <th scope="col">{t("review.col_category")}</th>
              <th scope="col" className="r">{t("review.col_score")}</th>
              <th scope="col">{t("review.col_confidence")}</th>
              <th scope="col">{t("review.col_status")}</th>
              <th scope="col" className="r">{t("review.col_age")}</th>
            </tr>
          </thead>
          <tbody>
            {queue.data.map((q) => (
              <tr key={q.id}>
                <td>
                  <Link href={`/review/${q.id}`} className="font-bold">
                    {q.area_name}, {shortId(q.h3)}
                  </Link>
                </td>
                <td>{q.category_name}</td>
                <td className="r num">{q.engine_score}</td>
                <td>
                  <ConfidenceDots value={q.confidence} compact />
                </td>
                <td>{t(`review.status.${q.status}`)}</td>
                <td className="r num">{t("review.age_days", { n: q.data_age_days })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className="mt-12">
        <h2 className="text-xl">{t("review.flagged")}</h2>
        {flagged.data?.length === 0 && <p className="mt-2 text-ink-soft">{t("review.flagged_empty")}</p>}
        <ul className="mt-2">
          {flagged.data?.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-3 border-b border-rule py-2 text-sm">
              <span className="font-bold">{shortId(f.h3)}</span>
              <span>{f.fraud_flags.join(", ")}</span>
              <span className="text-ink-soft num">{f.duration_seconds ?? "–"} s</span>
              <span className="ml-auto flex gap-2">
                <button type="button" className="btn btn-secondary" onClick={() => decide.mutate({ id: f.id, action: "clear" })}>
                  {t("review.clear")}
                </button>
                <button type="button" className="btn btn-danger" onClick={() => decide.mutate({ id: f.id, action: "exclude" })}>
                  {t("review.exclude")}
                </button>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

export default function ReviewPage() {
  return (
    <>
      <TopBar />
      <StaffGate>
        <Queue />
      </StaffGate>
    </>
  );
}
