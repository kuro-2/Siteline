-- Nukkad schema. Source of truth: docs/03-database.md (keep both in sync).

create extension if not exists postgis with schema extensions;
create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------- enums
create type public.user_role as enum ('public','resident','surveyor','analyst','admin');
create type public.place_source as enum ('osm','google','ground');
create type public.rec_status as enum ('draft','in_review','published','rejected','needs_data');
create type public.review_decision as enum ('approve','approve_with_edits','adjust','reject','needs_data');
create type public.confidence_band as enum ('not_enough_data','early_signal','fairly_sure','confident');
create type public.job_status as enum ('running','succeeded','failed','dry_run');

-- ---------------------------------------------------------------- reference
create table public.areas (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null check (slug ~ '^[a-z0-9-]+$'),
  name text not null,
  city text not null default 'Guwahati',
  boundary extensions.geometry(MultiPolygon,4326) not null,
  is_published boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.categories (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null check (slug ~ '^[a-z0-9-]+$'),
  name text not null,
  description text,
  osm_tags jsonb not null,
  google_types text[] not null,
  google_text_query text,                 -- used when Google has no matching place type
  catchment_k int not null check (catchment_k between 1 and 10),
  people_per_outlet_benchmark int,
  sort_order int not null default 100,
  active boolean not null default true
);

create table public.h3_cells (
  h3 text primary key,
  area_id uuid not null references public.areas(id) on delete cascade,
  geom extensions.geometry(Polygon,4326) not null,
  centroid extensions.geometry(Point,4326) not null,
  in_area boolean not null default true,  -- false = buffer ring outside the boundary
  population numeric,
  population_source_year int
);
create index on public.h3_cells using gist (geom);
create index on public.h3_cells (area_id);

-- ---------------------------------------------------------------- raw data
create table public.places (
  id uuid primary key default gen_random_uuid(),
  source public.place_source not null,
  source_id text not null,
  name text,
  category_id uuid references public.categories(id),
  raw_category text,
  geom extensions.geometry(Point,4326) not null,
  h3 text references public.h3_cells(h3) on delete set null,
  business_status text,
  rating numeric(2,1),
  rating_count int,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  fetched_at timestamptz not null default now(),
  content_expired boolean not null default false,  -- Google fields cleared per caching terms
  merged_into uuid references public.places(id) on delete set null,
  unique (source, source_id)
);
create index on public.places using gist (geom);
create index on public.places (category_id, h3);
create index on public.places (source, fetched_at);

-- Weekly copy of what each source said, so outcome scans can compare dates.
create table public.place_snapshots (
  snapshot_on date not null,
  place_id uuid not null references public.places(id) on delete cascade,
  category_id uuid references public.categories(id),
  h3 text,
  business_status text,
  primary key (snapshot_on, place_id)
);

create table public.place_review_themes (
  place_id uuid primary key references public.places(id) on delete cascade,
  themes jsonb not null,
  model text not null,
  summarized_at timestamptz not null default now()
);

create table public.surveyors (            -- links a KoboToolbox username to a Nukkad user
  kobo_username text primary key,
  user_id uuid references auth.users(id) on delete set null,
  display_name text not null,
  active boolean not null default true
);

create table public.ground_counts (
  id uuid primary key default gen_random_uuid(),
  kobo_submission_id text unique,
  surveyor_id uuid references auth.users(id) on delete set null,
  surveyor_name text,
  h3 text not null references public.h3_cells(h3),
  category_id uuid not null references public.categories(id),
  count int not null check (count >= 0),
  informal_count int not null default 0 check (informal_count >= 0),
  photo_paths text[],
  counted_at timestamptz not null,
  notes text
);
create index on public.ground_counts (h3, category_id, counted_at desc);

create table public.rent_observations (
  id uuid primary key default gen_random_uuid(),
  h3 text references public.h3_cells(h3),
  geom extensions.geometry(Point,4326),
  monthly_rent_inr int not null check (monthly_rent_inr > 0),
  area_sqft int check (area_sqft > 0),
  source text not null check (source in ('field','owner-entered','broker')),
  observed_on date not null,
  entered_by uuid references auth.users(id) on delete set null
);
create index on public.rent_observations (h3);

-- ---------------------------------------------------------------- users, surveys
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  role public.user_role not null default 'public',
  home_h3 text references public.h3_cells(h3) on delete set null,
  verified_at timestamptz,
  consent_version text,
  consent_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.saved_areas (
  user_id uuid not null references auth.users(id) on delete cascade,
  area_id uuid not null references public.areas(id) on delete cascade,
  category_id uuid references public.categories(id) on delete set null,
  h3 text references public.h3_cells(h3) on delete set null,
  created_at timestamptz not null default now(),
  primary key (user_id, area_id)
);

create table public.surveys (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  area_id uuid not null references public.areas(id),
  title text not null,
  questions jsonb not null,
  version int not null default 1,
  opens_at timestamptz, closes_at timestamptz,
  is_active boolean not null default true
);

create table public.survey_responses (
  id uuid primary key default gen_random_uuid(),
  survey_id uuid not null references public.surveys(id),
  survey_version int not null,
  respondent_id uuid not null references auth.users(id) on delete cascade,
  h3 text not null references public.h3_cells(h3),
  answers jsonb not null,
  device_hash text,
  ip_hash text,
  duration_seconds int,
  idempotency_key text unique,
  submitted_at timestamptz not null default now(),
  location_check_passed boolean,
  fraud_flags text[] not null default '{}',
  weight numeric not null default 1.0,
  excluded boolean not null default false,
  cleared_by uuid references auth.users(id) on delete set null,
  unique (survey_id, respondent_id)
);
create index on public.survey_responses (survey_id, h3);

-- ---------------------------------------------------------------- derived
create table public.model_runs (
  id uuid primary key default gen_random_uuid(),
  engine_version text not null,
  params jsonb not null,
  area_id uuid references public.areas(id),
  data_snapshot_at timestamptz not null,
  kind text not null default 'live' check (kind in ('live','backtest')),
  created_at timestamptz not null default now()
);

create table public.cell_features (
  run_id uuid references public.model_runs(id) on delete cascade,
  h3 text references public.h3_cells(h3) on delete cascade,
  category_id uuid references public.categories(id),
  features jsonb not null,
  primary key (run_id, h3, category_id)
);

create table public.scores (
  run_id uuid references public.model_runs(id) on delete cascade,
  h3 text references public.h3_cells(h3) on delete cascade,
  category_id uuid references public.categories(id),
  score numeric not null check (score between 0 and 100),
  score_low numeric, score_high numeric,
  confidence public.confidence_band not null,
  components jsonb not null,
  primary key (run_id, h3, category_id)
);

create table public.backtests (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references public.model_runs(id) on delete set null,
  area_id uuid references public.areas(id),
  as_of date not null,
  evaluated_on date not null,
  metrics jsonb not null,
  report_md text,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- human in the loop
create table public.recommendations (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.model_runs(id),
  area_id uuid not null references public.areas(id),
  category_id uuid not null references public.categories(id),
  h3 text not null references public.h3_cells(h3),
  engine_score numeric not null,
  final_score numeric check (final_score between 0 and 100),
  confidence public.confidence_band not null,
  explanation_draft text,
  explanation_final text,
  status public.rec_status not null default 'draft',
  reviewed_by uuid references auth.users(id) on delete set null,
  published_at timestamptz,
  created_at timestamptz not null default now()
);
create index on public.recommendations (status, area_id, category_id);

create table public.analyst_reviews (
  id uuid primary key default gen_random_uuid(),
  recommendation_id uuid not null references public.recommendations(id) on delete cascade,
  analyst_id uuid not null references auth.users(id),
  decision public.review_decision not null,
  score_delta numeric check (score_delta between -15 and 15),
  reason text,
  created_at timestamptz not null default now(),
  constraint reason_required check (
    decision in ('approve','approve_with_edits') or length(coalesce(reason,'')) >= 10
  ),
  constraint delta_only_on_adjust check (decision = 'adjust' or score_delta is null)
);

create table public.data_tasks (           -- "send back for more data"
  id uuid primary key default gen_random_uuid(),
  recommendation_id uuid references public.recommendations(id) on delete cascade,
  kind text not null check (kind in ('ground_count','survey_boost')),
  h3 text not null references public.h3_cells(h3),
  category_id uuid references public.categories(id),
  status text not null default 'open' check (status in ('open','done','cancelled')),
  notes text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.outcomes (
  id uuid primary key default gen_random_uuid(),
  place_id uuid references public.places(id) on delete set null,
  recommendation_id uuid references public.recommendations(id) on delete set null,
  event text not null check (event in ('opened','closed','still_open')),
  observed_on date not null,
  source text not null,
  followed_our_report boolean,
  notes text
);

-- ---------------------------------------------------------------- operations
create table public.job_runs (
  id uuid primary key default gen_random_uuid(),
  job text not null, args jsonb,
  status public.job_status not null,
  started_at timestamptz not null default now(), finished_at timestamptz,
  counts jsonb, error text, est_cost_usd numeric default 0
);
create index on public.job_runs (job, started_at desc);

create table public.api_usage (
  provider text not null, sku text not null, month date not null,
  calls int not null default 0, est_cost_usd numeric not null default 0,
  primary key (provider, sku, month)
);

create table public.audit_log (
  id bigserial primary key,
  actor uuid, action text not null, entity text, entity_id text,
  diff jsonb, at timestamptz not null default now()
);

create table public.llm_cache (
  input_hash text primary key,
  provider text not null,
  model text not null,
  output text not null,
  created_at timestamptz not null default now()
);
