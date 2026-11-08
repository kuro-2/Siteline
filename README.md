# Nukkad

*Know the street before you open the shutter.*

Nukkad studies one Guwahati locality and shows which kinds of small shop it's missing, how sure we are, and the evidence behind every claim. An analyst reviews every published result.

- `apps/web`: Next.js site (map, cell reports, survey, review, admin)
- `services/api`: FastAPI service (`app/`) and the data engine CLI (`engine/`)
- `supabase/`: Postgres + PostGIS schema, row-level security and seed data
- `docs/`: product, architecture, schema, scoring, API, design system, build plan, decisions, backtests, deploy runbook

## Run it locally (about 10 minutes)

Needs Node 22+, pnpm, Python 3.13 with uv, Docker and the Supabase CLI.

```bash
pnpm install
supabase start -x storage-api,imgproxy        # local Postgres + Auth in Docker
cp .env.example .env                          # then fill it from `supabase status -o env`
cd services/api && uv sync

# data for the pilot (free sources)
uv run engine area load                       # uses PILOT_BOUNDARY_PATH and PILOT_AREA_NAME
uv run engine geo build-grid
uv run engine ingest osm                      # needs CONTACT_EMAIL
uv run engine ingest worldpop                 # needs WORLDPOP_RASTER_PATH
uv run engine ingest dedupe
uv run engine score run
uv run engine explain draft
uv run engine survey create
uv run engine ingest google --dry-run         # prints calls and cost; calls nothing

# servers
uv run uvicorn app.main:app --reload --port 8000     # API on :8000 (docs at /docs)
cd ../../apps/web && pnpm dev                        # web on :3000
```

## Tests

```bash
cd services/api && uv run pytest                 # engine + RLS + API (DB tests need supabase start)
cd apps/web && pnpm test                         # Vitest
cd apps/web && pnpm build && pnpm start &        # then:
pnpm exec playwright test                        # e2e: explore, survey (offline), review
node scripts/screens.mjs                         # design self-review screenshots
```

## Where to read more

- How the score works and its limits: `docs/04-data-and-scoring.md`, and the public page `/method`
- Every non-obvious choice: `docs/decisions.md`
- Backtest results (honest, including bad ones): `docs/backtests/`
- Deploying and running it: `docs/deploy.md`
