// Serve MapLibre's worker (and the chunk it imports) from /maplibre so bundlers don't break it.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

const require = createRequire(import.meta.url);
const dist = dirname(require.resolve("maplibre-gl/package.json")) + "/dist";
const out = resolve(import.meta.dirname, "../public/maplibre");
mkdirSync(out, { recursive: true });
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) copyFileSync(`${dist}/${f}`, `${out}/${f}`);
console.log("maplibre worker copied to public/maplibre");
