"""Task A: summarise a competitor's review snippets into themes (only if enabled).

Raw review text is never stored; only the validated themes are.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from engine.llm.client import LLMClient, LLMError

SYSTEM = (
    "You summarise customer review snippets about one shop into themes. Return JSON only: "
    '{"themes": [{"theme": "short phrase", "sentiment": -1..1, "mentions": int}]}. '
    "At most 6 themes. Do not include names of people or any personal details."
)


class Theme(BaseModel):
    theme: str = Field(min_length=2, max_length=60)
    sentiment: float = Field(ge=-1, le=1)
    mentions: int = Field(ge=1, le=10_000)


class Themes(BaseModel):
    themes: list[Theme] = Field(max_length=6)


SCHEMA = Themes.model_json_schema()


def summarise_reviews(client: LLMClient, snippets: list[str]) -> list[Theme] | None:
    """Return validated themes or None (discard on any failure)."""
    if not snippets:
        return None
    prompt = "Review snippets:\n" + "\n".join(f"- {s[:400]}" for s in snippets[:30])
    try:
        raw = client.complete(SYSTEM, prompt, json_schema=SCHEMA)
        data = json.loads(raw)
        parsed = Themes.model_validate(data)
    except (LLMError, json.JSONDecodeError, ValidationError, OSError):
        return None
    total = len(snippets)
    return [t for t in parsed.themes if t.mentions <= total]
