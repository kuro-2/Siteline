// Generates src/lib/api-types.ts from FastAPI's OpenAPI schema. Never hand-edit that file.
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const apiDir = resolve(here, "../../../services/api");
const out = resolve(here, "../.openapi/openapi.json");
const json = execFileSync(
  "uv",
  ["run", "python", "-c", "import json; from app.main import app; print(json.dumps(app.openapi()))"],
  { cwd: apiDir, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
);
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, json);
execFileSync(
  process.platform === "win32" ? "pnpm.cmd" : "pnpm",
  ["exec", "openapi-typescript", out, "-o", "src/lib/api-types.ts"],
  { cwd: resolve(here, ".."), stdio: "inherit", shell: process.platform === "win32" },
);
