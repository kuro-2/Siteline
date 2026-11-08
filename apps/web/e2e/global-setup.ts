import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

/** Fresh drafts to review and two test users with passwords (local Supabase only). */
export default async function globalSetup() {
  const api = resolve(__dirname, "../../../services/api");
  const run = (args: string[]) =>
    execFileSync("uv", ["run", ...args], { cwd: api, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
  run(["engine", "score", "run"]);
  run(["engine", "explain", "draft"]);
  run(["engine", "survey", "create"]);
  const users = run(["python", resolve(__dirname, "setup_users.py")]);
  writeFileSync(resolve(__dirname, ".users.json"), users.trim().split("\n").pop() ?? "{}");
}
