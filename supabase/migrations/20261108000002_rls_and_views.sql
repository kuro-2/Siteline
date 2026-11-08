-- Row Level Security, helper functions and public views. See docs/03-database.md.
-- The FastAPI service and the engine connect with the service role / postgres user and
-- bypass RLS; these policies protect direct browser access through supabase-js.

-- ---------------------------------------------------------------- helpers
-- security definer + empty search_path: reading profiles here must not re-enter the
-- profiles RLS policies (which themselves call auth_role()).
create or replace function public.auth_role() returns public.user_role
language sql stable security definer set search_path = '' as
$$ select coalesce((select role from public.profiles where id = auth.uid()), 'public'::public.user_role) $$;

create or replace function public.is_staff() returns boolean
language sql stable security definer set search_path = '' as
$$ select public.auth_role() in ('analyst'::public.user_role, 'admin'::public.user_role) $$;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = '' as
$$ select public.auth_role() = 'admin'::public.user_role $$;

revoke all on function public.auth_role() from public;
revoke all on function public.is_staff() from public;
revoke all on function public.is_admin() from public;
grant execute on function public.auth_role(), public.is_staff(), public.is_admin() to anon, authenticated, service_role;

-- New auth user → profile row (role 'public').
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as
$$
begin
  insert into public.profiles (id) values (new.id) on conflict (id) do nothing;
  return new;
end
$$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Belt and braces: even if a grant is widened by mistake, only admins (or the service role)
-- may change role / verification / consent fields.
-- Runs as the caller (not security definer) so current_user is the real role.
create or replace function public.protect_profile_fields() returns trigger
language plpgsql set search_path = '' as
$$
begin
  if current_user in ('postgres', 'service_role', 'supabase_admin') or public.is_admin() then
    return new;
  end if;
  if new.role is distinct from old.role
     or new.verified_at is distinct from old.verified_at
     or new.consent_version is distinct from old.consent_version
     or new.consent_at is distinct from old.consent_at
     or new.home_h3 is distinct from old.home_h3 then
    raise exception 'Only the Siteline service can change role, verification, consent or home cell'
      using errcode = '42501';
  end if;
  return new;
end
$$;
create trigger profiles_protect before update on public.profiles
  for each row execute function public.protect_profile_fields();

-- ---------------------------------------------------------------- enable RLS everywhere
alter table public.areas enable row level security;
alter table public.categories enable row level security;
alter table public.h3_cells enable row level security;
alter table public.places enable row level security;
alter table public.place_snapshots enable row level security;
alter table public.place_review_themes enable row level security;
alter table public.surveyors enable row level security;
alter table public.ground_counts enable row level security;
alter table public.rent_observations enable row level security;
alter table public.profiles enable row level security;
alter table public.saved_areas enable row level security;
alter table public.surveys enable row level security;
alter table public.survey_responses enable row level security;
alter table public.model_runs enable row level security;
alter table public.cell_features enable row level security;
alter table public.scores enable row level security;
alter table public.backtests enable row level security;
alter table public.recommendations enable row level security;
alter table public.analyst_reviews enable row level security;
alter table public.data_tasks enable row level security;
alter table public.outcomes enable row level security;
alter table public.job_runs enable row level security;
alter table public.api_usage enable row level security;
alter table public.audit_log enable row level security;
alter table public.llm_cache enable row level security;

-- Admin can do everything on every table.
do $$
declare t text;
begin
  foreach t in array array[
    'areas','categories','h3_cells','places','place_snapshots','place_review_themes',
    'surveyors','ground_counts','rent_observations','profiles','saved_areas','surveys',
    'survey_responses','model_runs','cell_features','scores','backtests','recommendations',
    'analyst_reviews','data_tasks','outcomes','job_runs','api_usage','audit_log'
  ] loop
    execute format(
      'create policy admin_all on public.%I for all to authenticated using (public.is_admin()) with check (public.is_admin())', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- reference data
create policy read_published on public.areas for select to anon, authenticated
  using (is_published or public.auth_role() <> 'public');

create policy read_active on public.categories for select to anon, authenticated
  using (active or public.is_staff());

create policy read_published_area on public.h3_cells for select to anon, authenticated
  using (
    public.auth_role() <> 'public'
    or exists (select 1 from public.areas a where a.id = area_id and a.is_published)
  );

-- ---------------------------------------------------------------- raw data
create policy staff_read on public.places for select to authenticated using (public.is_staff());
create policy staff_read on public.place_snapshots for select to authenticated using (public.is_staff());
create policy staff_read on public.place_review_themes for select to authenticated using (public.is_staff());
create policy staff_read on public.surveyors for select to authenticated using (public.is_staff());

create policy surveyor_insert_own on public.ground_counts for insert to authenticated
  with check (public.auth_role() = 'surveyor' and surveyor_id = auth.uid());
create policy surveyor_read_own on public.ground_counts for select to authenticated
  using (surveyor_id = auth.uid() or public.is_staff());

create policy surveyor_insert_own on public.rent_observations for insert to authenticated
  with check (public.auth_role() in ('surveyor','analyst') and entered_by = auth.uid());
create policy read_own_or_staff on public.rent_observations for select to authenticated
  using (entered_by = auth.uid() or public.is_staff());

-- ---------------------------------------------------------------- users
create policy read_own on public.profiles for select to authenticated using (id = auth.uid());
create policy update_own on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());
-- Column privileges: clients may only edit their display name. Role etc. go through the API.
revoke update on public.profiles from anon, authenticated;
grant update (display_name) on public.profiles to authenticated;
revoke insert, delete on public.profiles from anon, authenticated;

create policy own_rows on public.saved_areas for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy read_active on public.surveys for select to anon, authenticated
  using (is_active or public.auth_role() in ('surveyor','analyst','admin'));

-- Responses are inserted by the API (fraud checks run there). Users can read their own.
create policy read_own on public.survey_responses for select to authenticated
  using (respondent_id = auth.uid());
revoke insert, update, delete on public.survey_responses from anon, authenticated;

-- ---------------------------------------------------------------- derived + review
create policy staff_read on public.model_runs for select to authenticated using (public.is_staff());
create policy staff_read on public.cell_features for select to authenticated using (public.is_staff());
create policy staff_read on public.scores for select to authenticated using (public.is_staff());
create policy staff_read on public.recommendations for select to authenticated using (public.is_staff());
create policy staff_read on public.backtests for select to authenticated using (public.is_staff());
create policy staff_read on public.outcomes for select to authenticated using (public.is_staff());

create policy analyst_read on public.analyst_reviews for select to authenticated using (public.is_staff());
create policy analyst_insert_own on public.analyst_reviews for insert to authenticated
  with check (public.is_staff() and analyst_id = auth.uid());

create policy staff_or_surveyor_read on public.data_tasks for select to authenticated
  using (public.auth_role() in ('surveyor','analyst','admin'));
create policy analyst_insert on public.data_tasks for insert to authenticated
  with check (public.is_staff() and created_by = auth.uid());

-- job_runs, api_usage, audit_log: admin only (covered by admin_all). llm_cache: no client access.
revoke all on public.llm_cache from anon, authenticated;

-- ---------------------------------------------------------------- public views
-- These views intentionally run with the owner's rights (security_invoker = false) so the
-- public can read exactly these columns and nothing else from the protected tables.
create view public.public_recommendations as
select r.id, r.area_id, r.category_id, r.h3,
       coalesce(r.final_score, r.engine_score) as score,
       r.confidence, r.explanation_final, r.published_at,
       p.display_name as reviewed_by_name
from public.recommendations r
left join public.profiles p on p.id = r.reviewed_by
where r.status = 'published';

-- OSM and ground rows only: Google content is never exposed directly to browsers.
create view public.public_places as
select pl.id, pl.source, pl.category_id, pl.h3, pl.geom,
       pl.name,
       pl.business_status, pl.last_seen_at
from public.places pl
where pl.merged_into is null and pl.source <> 'google';

revoke all on public.public_recommendations, public.public_places from anon, authenticated;
grant select on public.public_recommendations, public.public_places to anon, authenticated;
