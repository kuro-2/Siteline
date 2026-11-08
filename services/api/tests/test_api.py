"""API tests: happy path + main error for each endpoint (docs/07 Phase 4)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import h3
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.db_fixtures import TEST_AREA, Scenario, build_scenario, raw_conn, requires_db

pytestmark = [pytest.mark.db, requires_db]


@pytest.fixture(scope="module")
def scen() -> Iterator[Scenario]:
    yield from build_scenario()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def err(r: Any) -> str:
    body = r.json()
    assert set(body) == {"error"} and {"code", "message", "hint"} <= set(body["error"])
    return str(body["error"]["code"])


# ------------------------------------------------------------------ public
def test_health(client: TestClient) -> None:
    assert client.get("/v1/health").json() == {"status": "ok", "db": "ok"}


def test_areas(client: TestClient, scen: Scenario) -> None:
    slugs = [a["slug"] for a in client.get("/v1/areas").json()]
    assert TEST_AREA in slugs
    a = client.get(f"/v1/areas/{TEST_AREA}").json()
    assert a["name"] == "Test Bazaar" and a["boundary"]["type"] == "MultiPolygon"
    assert {f["source"] for f in a["freshness"]} >= {"OpenStreetMap", "Scores"}
    assert err(client.get("/v1/areas/nowhere")) == "not_found"


def test_categories(client: TestClient) -> None:
    cats = client.get("/v1/categories").json()
    assert [c["slug"] for c in cats][:2] == ["pharmacy", "cafe"]
    assert cats[0]["walk_minutes"] == 10


def test_map(client: TestClient, scen: Scenario) -> None:
    r = client.get(f"/v1/areas/{TEST_AREA}/map?category=pharmacy")
    assert r.status_code == 200 and "max-age" in r.headers["cache-control"]
    cells = r.json()["cells"]
    assert len(cells) == 26 and all(len(c) == 4 for c in cells)
    assert err(client.get(f"/v1/areas/{TEST_AREA}/map?category=bakery")) == "unknown_category"
    assert client.get(f"/v1/areas/{TEST_AREA}/map").status_code == 422


def test_cell_report_engine_only(client: TestClient, scen: Scenario) -> None:
    r = client.get(f"/v1/cells/{scen.centre_cell}/report?category=pharmacy")
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["status"] == "engine_only" and rep["reviewed_by"] is None
    assert rep["area"]["slug"] == TEST_AREA and rep["category"]["slug"] == "pharmacy"
    assert rep["headline"] and rep["limits"]
    assert any("can't measure" in lim for lim in rep["limits"])
    assert rep["evidence"]["population"]["source"] == "WorldPop"
    assert len(rep["neighbours"]) <= 6
    if rep["score"] is not None:
        assert rep["score_low"] <= rep["score"] <= rep["score_high"]
    assert err(client.get("/v1/cells/zzz/report?category=pharmacy")) == "bad_cell"
    far = h3.latlng_to_cell(10.0, 77.0, 9)
    assert err(client.get(f"/v1/cells/{far}/report?category=pharmacy")) == "not_found"


def test_check(client: TestClient, scen: Scenario) -> None:
    lat, lng = h3.cell_to_latlng(scen.centre_cell)
    r = client.post("/v1/check", json={"lat": lat, "lng": lng, "category": "pharmacy"})
    assert r.status_code == 200 and r.json()["report"]["h3"] == scen.centre_cell
    r2 = client.post("/v1/check", json={"lat": 10.0, "lng": 77.0, "category": "pharmacy"})
    assert err(r2) == "outside_area" and "Move it inside" in r2.json()["error"]["message"]


def test_top_is_empty_until_published(client: TestClient, scen: Scenario) -> None:
    assert client.get(f"/v1/areas/{TEST_AREA}/top?category=pharmacy").json() == []


# ------------------------------------------------------------------ me + surveys
def test_me_requires_login(client: TestClient) -> None:
    assert err(client.get("/v1/me")) == "login_required"
    assert err(client.get("/v1/me", headers={"Authorization": "Bearer nope"})) == "bad_token"


def test_resident_flow(client: TestClient, scen: Scenario) -> None:
    from engine.commands.analysis import create_survey

    s = create_survey(TEST_AREA, "ci-test-survey", "Test survey")
    u = scen.users["resident"]
    h = u.headers()
    me = client.get("/v1/me", headers=h).json()
    assert me["role"] == "public" and me["needs_consent"]
    lat, lng = h3.cell_to_latlng(scen.centre_cell)
    # home cell before consent → refused
    assert err(client.post("/v1/me/home-cell", json={"lat": lat, "lng": lng}, headers=h)) == "consent_required"
    assert err(client.post("/v1/me/consent", json={"version": "old"}, headers=h)) == "consent_outdated"
    v = me["current_consent_version"]
    assert client.post("/v1/me/consent", json={"version": v}, headers=h).status_code == 200
    assert err(client.post("/v1/me/home-cell", json={"lat": 10, "lng": 77}, headers=h)) == "outside_area"
    r = client.post("/v1/me/home-cell", json={"lat": lat, "lng": lng}, headers=h)
    assert r.json() == {"home_h3": scen.centre_cell, "area": "Test Bazaar", "role": "resident"}

    sv = client.get(f"/v1/surveys/{s['slug']}", headers=h).json()
    assert sv["already_answered"] is False and len(sv["questions"]) >= 8
    assert err(client.get("/v1/surveys/nope", headers=h)) == "not_found"
    body = {"answers": {"where_pharmacy": "outside", "wish_closer": ["pharmacy"]},
            "survey_version": sv["version"], "duration_seconds": 95, "device_id": "dev-1",
            "confirmed_on_map": True}
    url = f"/v1/surveys/{s['slug']}/responses"
    assert err(client.post(url, json=body, headers=h)) == "idempotency_key_required"
    key = str(uuid.uuid4())
    ok = client.post(url, json=body, headers={**h, "Idempotency-Key": key})
    assert ok.status_code == 201 and ok.json()["duplicate"] is False
    again = client.post(url, json=body, headers={**h, "Idempotency-Key": key})
    assert again.json()["duplicate"] is True
    dup = client.post(url, json=body, headers={**h, "Idempotency-Key": str(uuid.uuid4())})
    assert err(dup) == "already_answered"
    bad = {**body, "answers": {"where_pharmacy": "mars"}}
    other = scen.users["other"]
    assert err(client.post(url, json=bad, headers={**other.headers(), "Idempotency-Key": "x"})) == "forbidden"

    summary = client.get(f"/v1/surveys/{s['slug']}/summary", headers=h).json()
    assert summary["shown"] is False and summary["n"] == 1 and summary["min_n"] == 20

    assert client.post("/v1/saved-areas", json={"area": TEST_AREA, "category": "pharmacy"}, headers=h).json() == {"saved": True}
    assert client.get("/v1/saved-areas", headers=h).json()[0]["area"] == TEST_AREA
    assert err(client.post("/v1/saved-areas", json={"area": "nowhere"}, headers=h)) == "not_found"
    assert client.delete(f"/v1/saved-areas/{TEST_AREA}", headers=h).json() == {"deleted": True}


def test_fast_straightlined_response_is_flagged(client: TestClient, scen: Scenario) -> None:
    from engine.commands.analysis import create_survey

    s = create_survey(TEST_AREA, "ci-test-survey", "Test survey")
    conn = raw_conn()
    try:
        from tests.db_fixtures import make_user

        u = make_user(conn, "resident", "speedy")
        conn.execute("update profiles set home_h3 = %s, consent_version = %s where id = %s",
                     (scen.centre_cell, "2026-11-v1", u.id))
    finally:
        conn.close()
    sv = client.get(f"/v1/surveys/{s['slug']}", headers=u.headers()).json()
    answers = {q["id"]: q["options"][0] for q in sv["questions"] if q["type"] == "single"}
    r = client.post(f"/v1/surveys/{s['slug']}/responses",
                    json={"answers": answers, "survey_version": sv["version"], "duration_seconds": 8},
                    headers={**u.headers(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 201
    a = scen.users["analyst"]
    flagged = client.get("/v1/review/flagged-responses", headers=a.headers()).json()
    mine = [f for f in flagged if f["id"] == r.json()["id"]]
    assert mine and {"too_fast", "straight_lining"} <= set(mine[0]["fraud_flags"])
    assert "answers" not in mine[0]
    assert client.post(f"/v1/review/flagged-responses/{mine[0]['id']}", json={"action": "exclude"},
                       headers=a.headers()).json()["action"] == "exclude"


# ------------------------------------------------------------------ review
def test_review_flow(client: TestClient, scen: Scenario) -> None:
    assert scen.rec_id
    a = scen.users["analyst"].headers()
    assert err(client.get("/v1/review/queue", headers=scen.users["resident"].headers())) == "forbidden"
    q = client.get("/v1/review/queue", headers=a).json()
    assert any(i["id"] == scen.rec_id for i in q)
    d = client.get(f"/v1/review/{scen.rec_id}", headers=a).json()
    assert d["status"] == "in_review" and d["components"]
    assert err(client.get(f"/v1/review/{uuid.uuid4()}", headers=a)) == "not_found"

    regen = client.post(f"/v1/review/{scen.rec_id}/regenerate-explanation", headers=a).json()
    assert regen["method"] == "template" and regen["explanation_draft"]

    r = client.post(f"/v1/review/{scen.rec_id}", json={"decision": "reject", "reason": "short"}, headers=a)
    assert err(r) == "reason_required"
    r = client.post(f"/v1/review/{scen.rec_id}", json={"decision": "adjust", "reason": "rent is high here"}, headers=a)
    assert err(r) == "delta_required"
    r = client.post(f"/v1/review/{scen.rec_id}", json={"decision": "adjust", "score_delta": 30,
                                                       "reason": "rent is high here"}, headers=a)
    assert r.status_code == 422

    task = client.post(f"/v1/review/{scen.rec_id}/request-data", json={"kind": "ground_count"}, headers=a)
    assert task.json()["kind"] == "ground_count"

    pub = client.post(f"/v1/review/{scen.rec_id}",
                      json={"decision": "adjust", "score_delta": -5, "reason": "Rents on this stretch are high."},
                      headers=a).json()
    assert pub["status"] == "published" and pub["final_score"] is not None
    assert err(client.post(f"/v1/review/{scen.rec_id}", json={"decision": "approve"}, headers=a)) == "already_decided"

    top = client.get(f"/v1/areas/{TEST_AREA}/top").json()
    assert top and top[0]["reviewed_by_name"] == "Analyst"
    conn = raw_conn()
    try:
        cell = conn.execute("select h3, c.slug from recommendations r join categories c on c.id=r.category_id where r.id=%s",
                            (scen.rec_id,)).fetchone()
    finally:
        conn.close()
    assert cell
    rep = client.get(f"/v1/cells/{cell['h3']}/report?category={cell['slug']}").json()
    assert rep["status"] == "published" and rep["reviewed_by"]["name"] == "Analyst"
    m = client.get(f"/v1/areas/{TEST_AREA}/map?category={cell['slug']}").json()
    assert any(c[0] == cell["h3"] and c[3] for c in m["cells"])


# ------------------------------------------------------------------ admin
def test_admin(client: TestClient, scen: Scenario) -> None:
    ad = scen.users["admin"].headers()
    assert err(client.get("/v1/admin/freshness", headers=scen.users["analyst"].headers())) == "forbidden"
    fr = client.get("/v1/admin/freshness", headers=ad).json()
    assert any(f["job"] == "score.run" and f["last_success"] for f in fr)
    assert "rows" in client.get("/v1/admin/costs", headers=ad).json()
    assert client.get("/v1/admin/jobs?job=score.run", headers=ad).json()[0]["job"] == "score.run"
    assert err(client.post("/v1/admin/jobs/rm-rf", json={}, headers=ad)) == "unknown_job"
    assert client.get("/v1/admin/backtests", headers=ad).status_code == 200
    assert err(client.get(f"/v1/admin/backtests/{uuid.uuid4()}", headers=ad)) == "not_found"
    cats = client.get("/v1/admin/categories", headers=ad).json()
    assert len(cats) >= 5
    areas = client.get("/v1/admin/areas", headers=ad).json()
    assert any(a["slug"] == TEST_AREA for a in areas)
    assert err(client.patch("/v1/admin/areas/nowhere", json={"name": "x"}, headers=ad)) == "not_found"
    users = client.get("/v1/admin/users?q=surveyor", headers=ad).json()
    assert users and users[0]["role"] == "surveyor"
    target = scen.users["other"].id
    assert client.post(f"/v1/admin/users/{target}/role", json={"role": "surveyor"}, headers=ad).json()["role"] == "surveyor"
    me = scen.users["admin"].id
    assert err(client.post(f"/v1/admin/users/{me}/role", json={"role": "public"}, headers=ad)) == "self_demote"
    assert client.get("/v1/admin/calibration", headers=ad).status_code == 200
    assert isinstance(client.get("/v1/admin/data-tasks", headers=ad).json(), list)


def test_delete_my_data(client: TestClient, scen: Scenario) -> None:
    u = scen.users["other"]
    r = client.delete("/v1/me", headers=u.headers())
    assert r.json()["deleted"] is True
    conn = raw_conn()
    try:
        assert conn.execute("select 1 from auth.users where id = %s", (u.id,)).fetchone() is None
        assert conn.execute("select 1 from profiles where id = %s", (u.id,)).fetchone() is None
    finally:
        conn.close()


def test_openapi_renders(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/cells/{cell}/report" in spec["paths"]
    assert client.get("/docs").status_code == 200
