import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { createClient } from "@supabase/supabase-js";
import { loadEnvConfig } from "@next/env";

loadEnvConfig(resolve(__dirname, "../../.."));
const SB_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SB_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

/** Sign in with the test user's password and put the session where supabase-js looks for it. */
export async function loginAs(page: Page, role: "resident" | "analyst") {
  const users = JSON.parse(readFileSync(resolve(__dirname, ".users.json"), "utf8"));
  const sb = createClient(SB_URL, SB_KEY, { auth: { persistSession: false } });
  const { data, error } = await sb.auth.signInWithPassword(users[role]);
  if (error || !data.session) throw error ?? new Error("no session");
  const ref = new URL(SB_URL).hostname.split(".")[0];
  await page.goto("/method");
  await page.evaluate(
    ([k, v]) => localStorage.setItem(k, v),
    [`sb-${ref}-auth-token`, JSON.stringify(data.session)] as const,
  );
}
