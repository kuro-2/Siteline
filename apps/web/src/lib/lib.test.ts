import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../../messages/en.json";
import { api, ApiError, setTokenGetter } from "./api";
import { clearDraft, deviceId, loadDraft, saveDraft, visibleQuestions, type Question } from "./draft";
import { formatDate, formatDistance, formatInt, formatRupees, opportunityStep, percent } from "./format";
import { cellsToGeoJSON, rankCells, seedFrom, shortId } from "./hex";
import { has, t, tn } from "./i18n";
import { mix } from "./mapstyle";

describe("format", () => {
  it("groups digits the Indian way", () => {
    expect(formatInt(123456)).toBe("1,23,456");
    expect(formatInt(7100.4)).toBe("7,100");
  });
  it("uses lakh and crore for money", () => {
    expect(formatRupees(450000)).toBe("₹4.5 lakh");
    expect(formatRupees(12000000)).toBe("₹1.2 crore");
    expect(formatRupees(48)).toBe("₹48");
    expect(formatRupees(100000)).toBe("₹1 lakh");
  });
  it("formats dates in Asia/Kolkata, adding the year only when different", () => {
    const now = new Date("2026-11-08T10:00:00Z");
    expect(formatDate("2026-11-04", now)).toBe("4 Nov");
    expect(formatDate("2025-10-12", now)).toBe("12 Oct 2025");
    // 20:00 UTC on 3 Nov is already 4 Nov in India
    expect(formatDate("2026-11-03T20:00:00Z", now)).toBe("4 Nov");
    expect(formatDate(null, now)).toBe(t("common.unknown_date"));
    expect(formatDate("not a date", now)).toBe(t("common.unknown_date"));
  });
  it("formats distances and percentages", () => {
    expect(formatDistance(423)).toBe("420 m");
    expect(formatDistance(1530)).toBe("1.5 km");
    expect(percent(0.414)).toBe("41%");
    expect(percent(null)).toBe("–");
  });
  it("maps scores to 5 opportunity steps", () => {
    expect([null, 10, 40, 55, 70, 90].map(opportunityStep)).toEqual([0, 1, 2, 3, 4, 5]);
  });
});

describe("i18n", () => {
  it("interpolates and pluralises", () => {
    expect(t("report.score", { score: 72 })).toBe("Score 72");
    expect(t("missing.key")).toBe("missing.key");
    expect(has("report.score")).toBe(true);
    expect(has("report")).toBe(false);
    expect(t("report.range", { low: 61 })).toBe("likely between 61 and {high}");
    expect(tn("nope", 1)).toBe("nope.one");
  });

  it("every literal t() key used in the code exists in en.json", () => {
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const f of readdirSync(dir)) {
        const p = join(dir, f);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.tsx?$/.test(f) && !f.endsWith(".test.ts")) files.push(p);
      }
    };
    walk(join(__dirname, ".."));
    const missing: string[] = [];
    for (const f of files) {
      const src = readFileSync(f, "utf8");
      for (const m of src.matchAll(/\bt\("([a-z_]+(?:\.[a-z0-9_-]+)+)"/g)) {
        if (m[1] && !has(m[1])) missing.push(`${f}: ${m[1]}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("copy avoids the design doc's 'never write' words", () => {
    const text = JSON.stringify(en).toLowerCase();
    for (const banned of ["ai-powered", "unlock", "leverage", "seamless", "revolutionis", "empower", "magic", "✨", "get started today", "welcome to", "discover the power"]) {
      expect(text, banned).not.toContain(banned);
    }
    expect(text).not.toMatch(/\bsmart\b/);
    expect(text).not.toMatch(/\bai\b/);
  });
});

describe("hex", () => {
  const cells = [
    ["8928308280fffff", 72, "fairly_sure", true],
    ["8928308280bffff", null, "not_enough_data", false],
    ["89283082807ffff", 55, "early_signal", false],
  ] as const;
  it("builds GeoJSON with steps and confidence flags", () => {
    const fc = cellsToGeoJSON(cells.map((c) => [...c]) as never);
    expect(fc.features).toHaveLength(3);
    const [a, b, c] = fc.features;
    expect(a?.properties).toMatchObject({ step: 4, lowConfidence: false, recommended: true });
    expect(b?.properties).toMatchObject({ step: 0, lowConfidence: true });
    expect(c?.properties.lowConfidence).toBe(true);
    const ring = a?.geometry.coordinates[0] ?? [];
    expect(ring[0]).toEqual(ring[ring.length - 1]);
  });
  it("ranks scored cells first and gives short ids and stable seeds", () => {
    expect(rankCells(cells.map((c) => [...c]) as never).map((c) => c[0])).toEqual([
      "8928308280fffff",
      "89283082807ffff",
      "8928308280bffff",
    ]);
    expect(shortId("893ce156327ffff")).toBe("56327");
    expect(seedFrom("abc")).toBe(seedFrom("abc"));
    expect(seedFrom("abc")).not.toBe(seedFrom("abd"));
  });
});

describe("drafts", () => {
  afterEach(() => localStorage.clear());
  it("round-trips a survey draft and keeps one device id", () => {
    const d = loadDraft("s1");
    expect(d.step).toBe(0);
    saveDraft("s1", { ...d, step: 3, answers: { where_pharmacy: "outside" } });
    expect(loadDraft("s1").step).toBe(3);
    expect(loadDraft("s1").idempotencyKey).toBe(d.idempotencyKey);
    clearDraft("s1");
    expect(loadDraft("s1").step).toBe(0);
    expect(deviceId()).toBe(deviceId());
  });
  it("survives corrupted storage", () => {
    localStorage.setItem("nukkad.survey.s2", "{not json");
    expect(loadDraft("s2").answers).toEqual({});
  });
  it("hides questions by show_if rules", () => {
    const qs: Question[] = [
      { id: "where_pharmacy", type: "single", text_key: "x", options: ["in_area", "dont_use"] },
      { id: "time_pharmacy", type: "single", text_key: "y", options: ["lt5"], show_if: { question: "where_pharmacy", not: "dont_use" } },
    ];
    expect(visibleQuestions(qs, {})).toHaveLength(2);
    expect(visibleQuestions(qs, { where_pharmacy: "dont_use" })).toHaveLength(1);
  });
});

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("sends the bearer token and parses JSON", async () => {
    setTokenGetter(async () => "tok");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api("/x")).resolves.toEqual({ ok: 1 });
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });
  it("turns the error shape into ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "outside_area", message: "That pin is outside Zoo Road.", hint: null } }), { status: 422 })));
    await expect(api("/check", { method: "POST", body: {} })).rejects.toMatchObject({ code: "outside_area", status: 422 });
  });
  it("reports offline clearly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = await api("/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("offline");
  });
});

describe("map colours", () => {
  it("mixes hex colours", () => {
    expect(mix("#000000", "#ffffff", 0.5)).toBe("#808080");
    expect(mix("#3b6a84", "#eef2ef", 1)).toBe("#3b6a84");
    expect(mix("var(--x)", "#ffffff", 0.5)).toBe("var(--x)");
  });
});
