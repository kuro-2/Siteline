"""Resident survey: default question schema and how answers become a need signal.

Questions ask about current behaviour (docs/04 §6). Text is i18n keys; the web app holds
the English strings in apps/web/messages/en.json under "survey.q.*".
"""

from __future__ import annotations

from typing import Any

TIME_BUCKETS = {"lt5": 0, "5_10": 5, "10_20": 10, "20p": 20}  # lower bound in minutes
WISH_WEIGHT = 0.5

# Categories asked about individually (where + how long). Others come through the
# "outside the area last month" and "wish closer" questions.
DETAILED = ["pharmacy", "cafe", "salon", "coaching", "hardware"]


def default_questions(category_slugs: list[str]) -> list[dict[str, Any]]:
    qs: list[dict[str, Any]] = []
    for slug in [s for s in DETAILED if s in category_slugs]:
        qs.append(
            {
                "id": f"where_{slug}",
                "type": "single",
                "text_key": f"survey.q.where.{slug}",
                "options": ["in_area", "outside", "dont_use"],
                "maps_to_category": slug,
            }
        )
        qs.append(
            {
                "id": f"time_{slug}",
                "type": "single",
                "text_key": f"survey.q.time.{slug}",
                "options": list(TIME_BUCKETS.keys()),
                "maps_to_category": slug,
                "show_if": {"question": f"where_{slug}", "not": "dont_use"},
            }
        )
    qs.append(
        {
            "id": "outside_last_month",
            "type": "multi",
            "text_key": "survey.q.outside_last_month",
            "options": category_slugs,
        }
    )
    qs.append(
        {
            "id": "wish_closer",
            "type": "multi",
            "max": 2,
            "text_key": "survey.q.wish_closer",
            "options": category_slugs,
            "weight": WISH_WEIGHT,
        }
    )
    return qs


def need_indicator(answers: dict[str, Any], slug: str, travel_minutes: int) -> float | None:
    """1 = this person goes far / leaves the area for this category; 0 = served nearby;
    0.5 = only says they wish it were closer; None = didn't tell us about this category."""
    where = answers.get(f"where_{slug}")
    time_ = answers.get(f"time_{slug}")
    outside = slug in (answers.get("outside_last_month") or [])
    wish = slug in (answers.get("wish_closer") or [])
    if where == "dont_use" and not outside and not wish:
        return None
    if where == "outside" or outside:
        return 1.0
    if isinstance(time_, str) and time_ in TIME_BUCKETS and TIME_BUCKETS[time_] >= travel_minutes:
        return 1.0
    if wish:
        return WISH_WEIGHT
    if where is None and time_ is None:
        return None
    return 0.0


def validate_answers(questions: list[dict[str, Any]], answers: dict[str, Any]) -> list[str]:
    """Return a list of problems (empty = valid). Unknown ids and bad options are rejected."""
    problems: list[str] = []
    by_id = {q["id"]: q for q in questions}
    for key, value in answers.items():
        q = by_id.get(key)
        if q is None:
            problems.append(f"unknown question '{key}'")
            continue
        opts = q.get("options") or []
        if q["type"] == "single":
            if not isinstance(value, str) or value not in opts:
                problems.append(f"'{key}' must be one of {opts}")
        elif q["type"] == "multi":
            if not isinstance(value, list) or any(v not in opts for v in value):
                problems.append(f"'{key}' must be a list drawn from {opts}")
            elif "max" in q and len(value) > int(q["max"]):
                problems.append(f"'{key}' allows at most {q['max']} choices")
    return problems
