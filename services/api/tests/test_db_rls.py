"""Row Level Security, tested the way supabase-js reaches the database: as the
`anon` / `authenticated` roles with JWT claims set."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from tests.db_fixtures import Scenario, build_scenario, raw_conn, requires_db

pytestmark = [pytest.mark.db, requires_db]


@pytest.fixture(scope="module")
def scen() -> Iterator[Scenario]:
    yield from build_scenario()


def as_role(conn: psycopg.Connection[dict[str, Any]], role: str, uid: str | None = None) -> None:
    conn.execute(f"set local role {role}")
    claims = {"role": role}
    if uid:
        claims["sub"] = uid
    conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))


def query(role: str, sql: str, params: tuple[Any, ...] = (), uid: str | None = None) -> list[dict[str, Any]]:
    conn = raw_conn()
    try:
        with conn.transaction():
            as_role(conn, role, uid)
            return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_scenario_has_a_draft(scen: Scenario) -> None:
    assert scen.rec_id, "scoring should have produced at least one draft"


def test_anon_cannot_read_drafts_or_scores(scen: Scenario) -> None:
    assert query("anon", "select * from recommendations") == []
    assert query("anon", "select * from scores") == []
    assert query("anon", "select * from cell_features") == []
    assert query("anon", "select * from job_runs") == []
    assert query("anon", "select * from survey_responses") == []
    # but reference data of a published area is public
    assert query("anon", "select slug from areas where slug = 'ci-test'") == [{"slug": "ci-test"}]
    assert len(query("anon", "select h3 from h3_cells where area_id = %s", (scen.area_id,))) > 10
    assert len(query("anon", "select slug from categories")) >= 5


def test_public_views_only_show_published(scen: Scenario) -> None:
    assert query("anon", "select * from public_recommendations where area_id = %s", (scen.area_id,)) == []
    rows = query("anon", "select name from public_places where name like 'Test Medicos%%'")
    assert len(rows) == 6


def test_resident_cannot_change_role(scen: Scenario) -> None:
    u = scen.users["resident"]
    conn = raw_conn()
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            as_role(conn, "authenticated", u.id)
            conn.execute("update profiles set role = 'admin' where id = %s", (u.id,))
        # display name is allowed
        with conn.transaction():
            as_role(conn, "authenticated", u.id)
            n = conn.execute("update profiles set display_name = 'Mina' where id = %s", (u.id,)).rowcount
        assert n == 1
        # and nobody else's row is visible or editable
        with conn.transaction():
            as_role(conn, "authenticated", u.id)
            other = scen.users["other"].id
            assert conn.execute("select * from profiles where id = %s", (other,)).fetchall() == []
            assert conn.execute("update profiles set display_name='x' where id = %s", (other,)).rowcount == 0
    finally:
        conn.close()


def test_resident_cannot_insert_survey_response_directly(scen: Scenario) -> None:
    u = scen.users["resident"]
    conn = raw_conn()
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            as_role(conn, "authenticated", u.id)
            conn.execute(
                """insert into survey_responses (survey_id, survey_version, respondent_id, h3, answers)
                   values (gen_random_uuid(), 1, %s, %s, '{}')""",
                (u.id, scen.centre_cell),
            )
    finally:
        conn.close()


def test_analyst_can_read_and_review(scen: Scenario) -> None:
    a = scen.users["analyst"]
    rows = query("authenticated", "select id from recommendations where id = %s", (scen.rec_id,), a.id)
    assert len(rows) == 1
    assert len(query("authenticated", "select 1 from scores limit 1", (), a.id)) == 1
    conn = raw_conn()
    try:
        with conn.transaction():
            as_role(conn, "authenticated", a.id)
            conn.execute(
                """insert into analyst_reviews (recommendation_id, analyst_id, decision, reason)
                   values (%s, %s, 'needs_data', 'Need a ground count first.')""",
                (scen.rec_id, a.id),
            )
            # cannot write a review in someone else's name
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    """insert into analyst_reviews (recommendation_id, analyst_id, decision, reason)
                       values (%s, %s, 'approve', null)""",
                    (scen.rec_id, scen.users["admin"].id),
                )
    finally:
        conn.close()


def test_resident_cannot_read_reviews_or_recommendations(scen: Scenario) -> None:
    r = scen.users["resident"]
    assert query("authenticated", "select * from recommendations", (), r.id) == []
    assert query("authenticated", "select * from analyst_reviews", (), r.id) == []
    assert query("authenticated", "select * from places", (), r.id) == []


def test_admin_sees_operations(scen: Scenario) -> None:
    ad = scen.users["admin"]
    assert len(query("authenticated", "select 1 from job_runs limit 1", (), ad.id)) == 1


def test_surveyor_ground_counts_own_only(scen: Scenario) -> None:
    s = scen.users["surveyor"]
    conn = raw_conn()
    try:
        cat = conn.execute("select id from categories where slug='pharmacy'").fetchone()
        assert cat
        with conn.transaction():
            as_role(conn, "authenticated", s.id)
            conn.execute(
                """insert into ground_counts (surveyor_id, h3, category_id, count, counted_at)
                   values (%s, %s, %s, 2, now())""",
                (s.id, scen.centre_cell, cat["id"]),
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    """insert into ground_counts (surveyor_id, h3, category_id, count, counted_at)
                       values (%s, %s, %s, 2, now())""",
                    (scen.users["other"].id, scen.centre_cell, cat["id"]),
                )
    finally:
        conn.close()


def test_review_reason_rules_in_db(scen: Scenario) -> None:
    conn = raw_conn()
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                """insert into analyst_reviews (recommendation_id, analyst_id, decision, reason)
                   values (%s, %s, 'reject', 'short')""",
                (scen.rec_id, scen.users["analyst"].id),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                """insert into analyst_reviews (recommendation_id, analyst_id, decision, score_delta, reason)
                   values (%s, %s, 'adjust', 20, 'too big an adjustment')""",
                (scen.rec_id, scen.users["analyst"].id),
            )
    finally:
        conn.close()
