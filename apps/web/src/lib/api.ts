import type { components } from "./api-types";
import { API_BASE_URL } from "./config";
import { t } from "./i18n";

export type CellReport = components["schemas"]["CellReport"];
export type AreaDetail = components["schemas"]["AreaDetail"];
export type AreaSummary = components["schemas"]["AreaSummary"];
export type Category = components["schemas"]["Category"];
export type MapResponse = components["schemas"]["MapResponse"];
export type TopPick = components["schemas"]["TopPick"];
export type CheckResponse = components["schemas"]["CheckResponse"];
export type GeocodeResult = components["schemas"]["GeocodeResult"];
export type MapCell = MapResponse["cells"][number];

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public hint: string | null = null,
  ) {
    super(message);
  }
}

type TokenGetter = () => Promise<string | null>;
let getToken: TokenGetter = async () => null;

/** Called once by the auth provider so requests carry the user's access token. */
export function setTokenGetter(fn: TokenGetter): void {
  getToken = fn;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  auth?: boolean;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.auth !== false) {
    const token = await getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/v1${path}`, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "offline", t("errors.offline"), t("errors.offline_hint"));
  }
  const text = await res.text();
  const data: unknown = text ? safeJson(text) : null;
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string; hint?: string | null } })?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "error",
      err?.message ?? t("errors.generic"),
      err?.hint ?? null,
    );
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
