/** Survey drafts saved on the phone so a flaky connection never loses answers. */
export interface SurveyDraft {
  answers: Record<string, string | string[]>;
  step: number;
  startedAt: number;
  idempotencyKey: string;
  pending: boolean; // answers are final and waiting to be sent
}

const key = (slug: string) => `siteline.survey.${slug}`;

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function loadDraft(slug: string, store: Storage = localStorage): SurveyDraft {
  try {
    const raw = store.getItem(key(slug));
    if (raw) return JSON.parse(raw) as SurveyDraft;
  } catch {
    /* corrupted or unavailable storage: start fresh */
  }
  return { answers: {}, step: 0, startedAt: Date.now(), idempotencyKey: uuid(), pending: false };
}

export function saveDraft(slug: string, draft: SurveyDraft, store: Storage = localStorage): void {
  try {
    store.setItem(key(slug), JSON.stringify(draft));
  } catch {
    /* storage full or blocked: answers stay in memory */
  }
}

export function clearDraft(slug: string, store: Storage = localStorage): void {
  try {
    store.removeItem(key(slug));
  } catch {
    /* ignore */
  }
}

export function deviceId(store: Storage = localStorage): string {
  const k = "siteline.device";
  try {
    const v = store.getItem(k);
    if (v) return v;
    const id = uuid();
    store.setItem(k, id);
    return id;
  } catch {
    return uuid();
  }
}

export interface Question {
  id: string;
  type: "single" | "multi";
  text_key: string;
  options: string[];
  max?: number;
  maps_to_category?: string;
  show_if?: { question: string; not: string };
}

/** Questions visible given current answers (show_if rules). */
export function visibleQuestions(questions: Question[], answers: Record<string, unknown>): Question[] {
  return questions.filter((q) => !q.show_if || answers[q.show_if.question] !== q.show_if.not);
}
