from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from shapely.geometry import box

from engine.geo import grid as g
from engine.quota import (
    MemoryUsageStore,
    QuotaExceeded,
    QuotaGuard,
    effective_cap,
    estimate_cost_usd,
    month_start,
)
from engine.sources import google_places as gp
from engine.sources.categories import (
    CategoryDef,
    is_business,
    match_google,
    match_osm,
    raw_category,
)
from engine.sources.dedupe import PlaceRef, find_merges, name_similarity, normalise_name
from engine.sources.kobo import parse_geopoint, parse_submission
from engine.sources.ohsome import parse_features
from engine.sources.osm import OverpassClient, build_query, parse_elements

CATS = [
    CategoryDef(
        "1",
        "pharmacy",
        "Pharmacy",
        [{"amenity": "pharmacy"}, {"shop": "chemist"}],
        ["pharmacy", "drugstore"],
        3,
        sort_order=10,
    ),
    CategoryDef("2", "cafe", "Café", [{"amenity": "cafe"}], ["cafe"], 2, sort_order=20),
    CategoryDef(
        "5",
        "coaching",
        "Coaching",
        [{"amenity": "prep_school"}],
        [],
        6,
        google_text_query="coaching centre",
        sort_order=40,
    ),
]

PILOT = box(91.78, 26.17, 91.80, 26.19)  # ~2 × 2.2 km in Guwahati


# ------------------------------------------------------------------ grid
def test_boundary_and_grid(tmp_path: Path) -> None:
    p = tmp_path / "b.geojson"
    p.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": json.loads(
                            json.dumps(
                                {"type": "Polygon", "coordinates": [list(PILOT.exterior.coords)]}
                            )
                        ),
                    }
                ],
            }
        )
    )
    mp = g.load_boundary(p)
    assert 3 < g.area_km2(mp) < 6
    cells = g.build_grid(mp, 9, 2)
    inside = [c for c in cells if c.in_area]
    assert 25 < len(inside) < 60
    assert all(mp.contains(c.centroid) for c in inside)
    assert len(cells) > len(inside)


def test_boundary_errors() -> None:
    with pytest.raises(ValueError):
        g.boundary_from_geojson({"type": "Point", "coordinates": [91.7, 26.1]})
    tiny = box(91.78, 26.17, 91.7801, 26.1701)
    with pytest.raises(ValueError):
        g.build_grid(
            g.boundary_from_geojson(
                json.loads(
                    json.dumps({"type": "Polygon", "coordinates": [list(tiny.exterior.coords)]})
                )
            ),
            9,
            1,
        )


def test_distance_and_direction() -> None:
    import h3

    c = h3.latlng_to_cell(26.18, 91.79, 9)
    ring = h3.grid_ring(c, 1)
    d = g.cell_distance_m(c, ring[0])
    assert 250 < d < 400
    assert g.direction(c, h3.latlng_to_cell(26.19, 91.79, 9)) == "north"
    assert g.direction(c, h3.latlng_to_cell(26.18, 91.80, 9)) == "east"
    assert len(g.catchment(c, 2)) == 19
    assert g.haversine_m(0, 0, 0, 1) == pytest.approx(111_195, rel=1e-3)


# ------------------------------------------------------------------ categories
def test_category_mapping() -> None:
    assert match_osm({"amenity": "pharmacy"}, CATS).slug == "pharmacy"  # type: ignore[union-attr]
    assert match_osm({"shop": "chemist", "name": "X"}, CATS).slug == "pharmacy"  # type: ignore[union-attr]
    assert match_osm({"shop": "bakery"}, CATS) is None
    assert match_google(["cafe", "food"], CATS).slug == "cafe"  # type: ignore[union-attr]
    assert match_google(["bank"], CATS) is None
    assert is_business({"shop": "bakery"})
    assert is_business({"amenity": "cafe"})
    assert not is_business({"amenity": "bench"})
    assert raw_category({"shop": "bakery"}) == "shop=bakery"
    assert raw_category({"highway": "bus_stop"}) is None


# ------------------------------------------------------------------ dedupe
def test_name_normalisation() -> None:
    assert normalise_name("Das Medicos & Sons") == "das"
    assert normalise_name("Pharmacy") == "pharmacy"  # don't drop everything
    assert normalise_name(None) == ""
    assert name_similarity("Das Medical Hall", "DAS MEDICOS") == 1.0
    assert name_similarity("Apollo Pharmacy", "Wellness Forever") < 0.8
    assert name_similarity(None, "x") == 0.0


def test_find_merges() -> None:
    places = [
        PlaceRef("o1", "osm", "Das Medicos", "1", 26.18, 91.79),
        PlaceRef("g1", "google", "Das Medical Hall", "1", 26.18010, 91.79010),  # ~15 m
        PlaceRef("g2", "google", "Something Else", "1", 26.1900, 91.7900),  # far away
        PlaceRef("o2", "osm", None, "2", 26.17, 91.78),
        PlaceRef("g3", "google", "Tea Point", "2", 26.17005, 91.78005),  # same cat, alone
        PlaceRef("o3", "osm", "A", "1", 26.16, 91.77),
        PlaceRef("o4", "osm", "B", "1", 26.16001, 91.77001),  # same source: no
    ]
    merges = find_merges(places)
    assert merges == {"g1": "o1", "g3": "o2"}


# ------------------------------------------------------------------ quota
def test_quota_guard_caps_and_costs() -> None:
    store = MemoryUsageStore()
    guard = QuotaGuard(store, cap=3)
    day = date(2026, 11, 8)
    for _ in range(3):
        guard.spend("nearby_search_pro", day)
    assert guard.calls == 3 and guard.spent_usd == 0.0  # inside free allowance
    with pytest.raises(QuotaExceeded):
        guard.spend("nearby_search_pro", day)
    with pytest.raises(QuotaExceeded):
        guard.check("nearby_search_pro", 1, day)
    assert guard.remaining("nearby_search_pro", date(2026, 12, 1)) == 3  # new month


def test_cost_estimates() -> None:
    assert estimate_cost_usd("nearby_search_pro", 0, 5000) == 0.0
    assert estimate_cost_usd("nearby_search_pro", 4900, 200) == pytest.approx(3.2)
    assert estimate_cost_usd("nearby_search_enterprise", 1000, 1000) == pytest.approx(35.0)
    assert effective_cap("nearby_search_enterprise", 4500) == 900
    assert effective_cap("nearby_search_pro", 4500) == 4500
    assert month_start(date(2026, 11, 30)) == date(2026, 11, 1)


# ------------------------------------------------------------------ google
def test_google_plan_and_mask() -> None:
    circles = gp.plan_circles(PILOT, 300)
    assert 15 < len(circles) < 80
    subs = gp.split_circle(circles[0])
    assert len(subs) == 4 and all(s.radius_m == 225 for s in subs)
    assert "places.rating" not in gp.field_mask(False)
    assert "places.rating" in gp.field_mask(True)
    assert gp.field_mask(False, text_search=True).endswith("nextPageToken")
    assert gp.sku_for("nearby", False) == "nearby_search_pro"
    assert gp.sku_for("text", True) == "text_search_enterprise"


@respx.mock
def test_google_client_splits_full_circles_and_guards() -> None:
    def place(i: int) -> dict[str, object]:
        return {
            "id": f"p{i}",
            "displayName": {"text": f"Shop {i}"},
            "types": ["pharmacy"],
            "location": {"latitude": 26.18, "longitude": 91.79},
            "businessStatus": "OPERATIONAL",
        }

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers["X-Goog-FieldMask"] == gp.field_mask(False)
        n = 20 if calls["n"] == 1 else 2
        return httpx.Response(200, json={"places": [place(calls["n"] * 100 + i) for i in range(n)]})

    respx.post(gp.NEARBY_URL).mock(side_effect=handler)
    guard = QuotaGuard(MemoryUsageStore(), cap=100)
    client = gp.GooglePlacesClient("k", guard, ratings=False, http=httpx.Client())
    found = client.nearby_recursive(gp.Circle(26.18, 91.79, 300), ["pharmacy"])
    assert calls["n"] == 5 and guard.calls == 5
    assert len(gp.dedupe_by_id(found + found)) == 28
    with pytest.raises(ValueError):
        gp.GooglePlacesClient("", guard, ratings=False)


@respx.mock
def test_google_text_search_paginates() -> None:
    pages = [
        {
            "places": [{"id": "a", "location": {"latitude": 1, "longitude": 2}}],
            "nextPageToken": "t",
        },
        {"places": [{"id": "b", "location": {"latitude": 1, "longitude": 2}}]},
    ]
    respx.post(gp.TEXT_URL).mock(side_effect=[httpx.Response(200, json=p) for p in pages])
    guard = QuotaGuard(MemoryUsageStore(), cap=10)
    client = gp.GooglePlacesClient("k", guard, ratings=True, http=httpx.Client())
    out = client.text("coaching centre", gp.Circle(26.18, 91.79, 1500))
    assert [p.place_id for p in out] == ["a", "b"] and guard.calls == 2


@respx.mock
def test_quota_blocks_before_the_call() -> None:
    route = respx.post(gp.NEARBY_URL).mock(return_value=httpx.Response(200, json={}))
    guard = QuotaGuard(MemoryUsageStore(), cap=0)
    client = gp.GooglePlacesClient("k", guard, ratings=False, http=httpx.Client())
    with pytest.raises(QuotaExceeded):
        client.nearby(gp.Circle(26.18, 91.79, 300), ["pharmacy"])
    assert not route.called


# ------------------------------------------------------------------ osm
def test_overpass_query_and_parse() -> None:
    q = build_query(PILOT)
    assert q.startswith("[out:json]") and 'nwr["shop"](26.17000,91.78000,26.19000,91.80000);' in q
    assert "out center tags;" in q
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 26.18,
                "lon": 91.79,
                "tags": {"amenity": "pharmacy", "name": "A"},
            },
            {
                "type": "way",
                "id": 2,
                "center": {"lat": 26.181, "lon": 91.791},
                "tags": {"shop": "hardware"},
            },
            {"type": "way", "id": 3, "tags": {"shop": "x"}},  # no centre → skipped
        ]
    }
    places = parse_elements(payload)
    assert [p.source_id for p in places] == ["node/1", "way/2"]
    assert places[0].name == "A"


@respx.mock
def test_overpass_caches_and_backs_off(tmp_path: Path) -> None:
    route = respx.post("https://overpass.test/api").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={"elements": []})]
    )
    waits: list[float] = []
    client = OverpassClient(
        "https://overpass.test/api", "test", tmp_path, http=httpx.Client(), sleep=waits.append
    )
    data, cached = client.fetch("q")
    assert data == {"elements": []} and not cached and waits == [15.0]
    data2, cached2 = client.fetch("q")
    assert cached2 and route.call_count == 2


# ------------------------------------------------------------------ ohsome / kobo
def test_ohsome_parse() -> None:
    payload = {
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [91.79, 26.18]},
                "properties": {
                    "@osmId": "node/9",
                    "@snapshotTimestamp": "x",
                    "amenity": "pharmacy",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": []},
                "properties": {},
            },
        ]
    }
    out = parse_features(payload)
    assert len(out) == 1 and out[0].source_id == "node/9" and out[0].tags == {"amenity": "pharmacy"}


def test_kobo_parse() -> None:
    assert parse_geopoint("26.18 91.79 50 5") == (26.18, 91.79)
    assert parse_geopoint([26.1, 91.7]) == (26.1, 91.7)
    assert parse_geopoint(None) is None
    sub = {
        "_uuid": "u1",
        "_submitted_by": "rupjyoti",
        "group/category": "pharmacy",
        "group/shop_count": "3",
        "group/informal_count": "1",
        "location": "26.18 91.79 0 0",
        "counted_on": "2026-10-12",
        "_attachments": [
            {"filename": "a.jpg", "mimetype": "image/jpeg", "download_url": "https://k/a"}
        ],
    }
    k = parse_submission(sub)
    assert k is not None
    assert (k.category_slug, k.count, k.informal_count) == ("pharmacy", 3, 1)
    assert k.counted_at.date() == date(2026, 10, 12) and k.photos[0]["url"] == "https://k/a"
    assert parse_submission({"_uuid": "x"}) is None
