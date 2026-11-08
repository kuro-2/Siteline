from __future__ import annotations

from datetime import date
from typing import Any

import h3
import httpx
import pytest
import respx

from engine.backtest.metrics import (
    calibration_by_decile,
    precision_recall_at_k,
    random_precision,
    rank,
    roc_auc,
)
from engine.backtest.run import evaluate_category, report_markdown, results_json, run_backtest_pure
from engine.features.build import CellRow
from engine.llm import client as llm
from engine.llm.explain import (
    allowed_numbers,
    check_numbers,
    draft_explanation,
    numbers_in,
    template_explanation,
)
from engine.llm.themes import summarise_reviews
from engine.scoring.config import ScoringConfig
from engine.settings import Settings
from engine.sources.categories import CategoryDef
from engine.sources.osm import OsmPlace
from engine.survey import default_questions, need_indicator, validate_answers

PAYLOAD: dict[str, Any] = {
    "category": "Pharmacy",
    "score": 72,
    "likely_between": [61, 80],
    "confidence": "fairly_sure",
    "components": [
        {
            "name": "gap",
            "effect": 31.0,
            "why": "1 pharmacy for every 7,100 people here, vs 1 for every 3,900 across the area.",
        },
        {
            "name": "survey_need",
            "effect": 4.2,
            "why": "41% of 64 neighbours who answered travel more than 10 minutes.",
        },
    ],
}


class FakeLLM:
    provider = "fake"
    model = "fake-1"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0

    def complete(self, system: str, prompt: str, json_schema: dict[str, Any] | None = None) -> str:
        self.calls += 1
        return self.replies.pop(0)


# ------------------------------------------------------------------ number check
def test_numbers_extraction() -> None:
    assert numbers_in("1 for every 7,100 people, 41% and 3.5 km") == {1.0, 7100.0, 41.0, 3.5}
    allowed = allowed_numbers(PAYLOAD)
    assert {72.0, 61.0, 80.0, 7100.0, 3900.0, 41.0, 64.0, 10.0} <= allowed


def test_check_numbers() -> None:
    assert check_numbers("About 41% of neighbours travel far; score 72.", PAYLOAD) == []
    assert check_numbers("There's a 90% chance this works.", PAYLOAD) == [90.0]


def test_draft_uses_llm_when_numbers_check_out() -> None:
    good = "Plenty of people, few pharmacies: 1 for every 7,100 people. We're fairly sure."
    text, method = draft_explanation(FakeLLM([good]), PAYLOAD)
    assert (text, method) == (good, "llm")


def test_draft_retries_then_falls_back() -> None:
    fake = FakeLLM(["Score 99, a 90% chance.", "Still 12 wrong numbers."])
    text, method = draft_explanation(fake, PAYLOAD)
    assert method == "template" and fake.calls == 2
    assert "7,100" in text and "fairly sure" in text
    fake2 = FakeLLM(["Wrong 99.", "1 for every 7,100 people."])
    assert draft_explanation(fake2, PAYLOAD)[1] == "llm_retry"


def test_template_provider_falls_back_without_network() -> None:
    text, method = draft_explanation(llm.TemplateClient(), PAYLOAD)
    assert method == "template"
    assert text == template_explanation(PAYLOAD)
    assert template_explanation({"components": []}) == ""


def test_make_client_and_errors() -> None:
    assert isinstance(llm.make_client(Settings(llm_provider="template")), llm.TemplateClient)
    with pytest.raises(llm.LLMError):
        llm.make_client(Settings(llm_provider="ollama", ollama_model=""))
    with pytest.raises(llm.LLMError):
        llm.make_client(Settings(llm_provider="gemini", gemini_api_key=""))
    with pytest.raises(llm.LLMError):
        llm.make_client(Settings(llm_provider="groq", groq_api_key=""))
    with pytest.raises(llm.LLMError):
        llm.make_client(Settings(llm_provider="gpt"))
    with pytest.raises(llm.LLMError):
        llm.TemplateClient().complete("s", "p")


@respx.mock
def test_providers_http_shapes() -> None:
    respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"content": "hi"}})
    )
    assert llm.OllamaClient("http://ollama.test", "m", httpx.Client()).complete("s", "p") == "hi"
    respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "g"}]}}]}
        )
    )
    assert (
        llm.GeminiClient("k", "gemini-x", httpx.Client()).complete("s", "p", {"type": "object"})
        == "g"
    )
    respx.post("https://api.groq.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "q"}}]})
    )
    assert llm.GroqClient("k", "m", httpx.Client()).complete("s", "p", {"type": "object"}) == "q"


def test_cached_client() -> None:
    fake = FakeLLM(["one"])
    c = llm.CachedClient(fake, cache={})
    assert c.complete("s", "p") == "one"
    assert c.complete("s", "p") == "one"
    assert fake.calls == 1


def test_review_themes_validation() -> None:
    ok = '{"themes": [{"theme": "long waits", "sentiment": -0.6, "mentions": 3}]}'
    themes = summarise_reviews(FakeLLM([ok]), ["slow", "slow again", "waited"])
    assert themes is not None and themes[0].theme == "long waits"
    assert summarise_reviews(FakeLLM(["not json"]), ["x"]) is None
    assert (
        summarise_reviews(
            FakeLLM(['{"themes": [{"theme": "x", "sentiment": 5, "mentions": 1}]}']), ["x"]
        )
        is None
    )
    assert summarise_reviews(FakeLLM([]), []) is None
    # mentions above the number of snippets are dropped (can't be true)
    many = '{"themes": [{"theme": "rude staff", "sentiment": -0.9, "mentions": 50}]}'
    assert summarise_reviews(FakeLLM([many]), ["a"]) == []


# ------------------------------------------------------------------ survey
def test_survey_questions_and_need() -> None:
    qs = default_questions(["pharmacy", "cafe", "salon", "coaching", "hardware"])
    assert 8 <= len(qs) <= 12
    assert qs[-1]["id"] == "wish_closer" and qs[-1]["weight"] == 0.5
    assert need_indicator({"where_pharmacy": "outside"}, "pharmacy", 10) == 1.0
    assert (
        need_indicator({"where_pharmacy": "in_area", "time_pharmacy": "10_20"}, "pharmacy", 10)
        == 1.0
    )
    assert (
        need_indicator({"where_pharmacy": "in_area", "time_pharmacy": "5_10"}, "pharmacy", 10)
        == 0.0
    )
    assert need_indicator({"wish_closer": ["pharmacy"]}, "pharmacy", 10) == 0.5
    assert need_indicator({"outside_last_month": ["pharmacy"]}, "pharmacy", 10) == 1.0
    assert need_indicator({"where_pharmacy": "dont_use"}, "pharmacy", 10) is None
    assert need_indicator({}, "pharmacy", 10) is None


def test_validate_answers() -> None:
    qs = default_questions(["pharmacy", "cafe"])
    assert validate_answers(qs, {"where_pharmacy": "outside", "wish_closer": ["cafe"]}) == []
    problems = validate_answers(
        qs,
        {
            "where_pharmacy": "mars",
            "nope": 1,
            "wish_closer": ["cafe", "pharmacy", "x"],
            "outside_last_month": "pharmacy",
        },
    )
    assert len(problems) == 4
    assert validate_answers(qs, {"wish_closer": ["cafe", "pharmacy"]}) == []


# ------------------------------------------------------------------ backtest
def test_metrics() -> None:
    scores = {"a": 90, "b": 80, "c": 70, "d": 10}
    pos = {"a", "c"}
    assert rank(scores) == ["a", "b", "c", "d"]
    assert precision_recall_at_k(rank(scores), pos, 2) == (0.5, 0.5)
    with pytest.raises(ValueError):
        precision_recall_at_k([], pos, 0)
    assert roc_auc(scores, pos) == pytest.approx(0.75)
    assert roc_auc(scores, set()) is None
    assert roc_auc({"a": 1, "b": 1}, {"a"}) == 0.5
    assert random_precision(10, 2) == 0.2 and random_precision(0, 0) == 0.0
    cal = calibration_by_decile({"a": 95, "b": 100, "c": 15}, {"a"})
    assert cal[-1] == {"from": 90, "to": 100, "cells": 2, "positives": 1, "rate": 0.5}


def test_evaluate_category_beats_baselines() -> None:
    scores = {f"c{i}": float(100 - i) for i in range(20)}
    pops = {f"c{i}": float(i) for i in range(20)}  # population ranks the opposite way
    m, beats = evaluate_category(scores, pops, {"c0", "c1", "c2"})
    assert beats and m["precision@5"] == 0.6 and m["population_only_precision@5"] == 0.0


def test_backtest_pure_end_to_end(cfg: ScoringConfig) -> None:
    centre = h3.latlng_to_cell(26.18, 91.79, 9)
    cells = {
        c: CellRow(c, h3.grid_distance(centre, c) <= 4, 2000.0) for c in h3.grid_disk(centre, 9)
    }
    cats = [CategoryDef("1", "pharmacy", "Pharmacy", [{"amenity": "pharmacy"}], [], 3)]
    lat, lng = h3.cell_to_latlng(centre)
    far = next(c for c, r in cells.items() if r.in_area and h3.grid_distance(centre, c) == 4)
    flat, flng = h3.cell_to_latlng(far)
    past = [OsmPlace("node/1", "Old", {"amenity": "pharmacy"}, flat, flng)]
    future = [*past, OsmPlace("node/2", "New", {"amenity": "pharmacy"}, lat, lng)]
    results = run_backtest_pure(
        cells=cells,
        cats=cats,
        past=past,
        future=future,
        as_of=date(2023, 6, 1),
        cfg=cfg,
        population_year=2020,
    )
    assert len(results) == 1 and results[0].positives == 1
    md = report_markdown("Test area", date(2023, 6, 1), date(2025, 6, 1), results, "abc")
    assert "What this test can't tell us" in md and "| Pharmacy |" in md
    assert results_json(results)["categories"]["pharmacy"]["positives"] == 1
