"""Task B: turn computed score components into 3–5 plain sentences.

The LLM may only reword. A post-check extracts every number from its text and rejects the
draft if any number is not present in the components JSON. One retry, then the
deterministic template is used.
"""

from __future__ import annotations

import json
import re
from typing import Any

from engine.llm.client import LLMClient, LLMError

SYSTEM = (
    "You rewrite a small-business location analysis into plain English for people in "
    "Guwahati, India. Write like a well-informed neighbour who did the homework: plain, "
    "specific, warm, honest about doubt. Use 'we' for the team and 'you' for the reader. "
    "Indian English spelling (neighbour, centre). Sentence case. 3 to 5 short sentences. "
    "Use ONLY numbers that appear in the JSON you are given, written the same way. Never add "
    "a percentage chance of success. Never say AI, smart, insights, unlock, leverage, "
    "seamless, empower or magic. No lists, no headings, no emoji."
)

_NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
CONFIDENCE_WORDS = {
    "not_enough_data": "We don't have enough data here yet",
    "early_signal": "This is an early signal from map data only",
    "fairly_sure": "We're fairly sure",
    "confident": "We're confident",
}


def numbers_in(text: str) -> set[float]:
    out: set[float] = set()
    for m in _NUM.findall(text):
        try:
            out.add(round(float(m.replace(",", "")), 2))
        except ValueError:  # pragma: no cover
            continue
    return out


def allowed_numbers(payload: Any) -> set[float]:
    """All numbers in the JSON, including numbers written inside its strings."""
    out: set[float] = set()

    def walk(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, int | float):
            out.add(round(float(v), 2))
            out.add(round(float(v)))
            out.add(round(abs(float(v)), 2))
        elif isinstance(v, str):
            out.update(numbers_in(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(payload)
    return out


def check_numbers(text: str, payload: Any) -> list[float]:
    """Numbers in `text` that are not in `payload`. Empty list = passes."""
    allowed = allowed_numbers(payload)
    return sorted(n for n in numbers_in(text) if n not in allowed)


def template_explanation(payload: dict[str, Any]) -> str:
    """Deterministic fallback built only from the components' own sentences."""
    parts: list[str] = []
    items = payload.get("components", [])
    for c in sorted(items, key=lambda c: -abs(float(c.get("effect", 0)))):
        why = str(c.get("why", "")).strip()
        if why:
            parts.append(why if why.endswith(".") else why + ".")
        if len(parts) == 4:
            break
    band = payload.get("confidence")
    if band in CONFIDENCE_WORDS:
        parts.append(CONFIDENCE_WORDS[band] + ".")
    return " ".join(parts)


def build_prompt(payload: dict[str, Any]) -> str:
    return (
        "Rewrite this analysis of one street block as 3 to 5 plain sentences for someone "
        "thinking of opening a shop there. Lead with the main reason. Mention how sure we "
        "are using the confidence field. JSON:\n" + json.dumps(payload, ensure_ascii=False)
    )


def draft_explanation(client: LLMClient, payload: dict[str, Any]) -> tuple[str, str]:
    """Return (text, method) where method is 'llm', 'llm_retry' or 'template'."""
    prompt = build_prompt(payload)
    for attempt, method in enumerate(("llm", "llm_retry")):
        try:
            p = (
                prompt
                if attempt == 0
                else prompt
                + ("\nYour last answer used numbers not in the JSON. Use only the JSON's numbers.")
            )
            text = client.complete(SYSTEM, p).strip()
        except (LLMError, OSError, ValueError, KeyError):
            break
        except Exception:  # network/HTTP errors from any provider
            break
        if text and not check_numbers(text, payload) and len(text) < 1200:
            return text, method
    return template_explanation(payload), "template"
