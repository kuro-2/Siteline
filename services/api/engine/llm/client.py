"""Provider-agnostic LLM client. Text in, text out. Never used to compute numbers.

Providers: template (default, no network), ollama (local), gemini, groq.
Outputs are cached in `llm_cache` by a hash of (provider, model, system, prompt, schema).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

import httpx

from engine.settings import Settings, get_settings


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    provider: str
    model: str

    def complete(
        self, system: str, prompt: str, json_schema: dict[str, Any] | None = None
    ) -> str: ...


class TemplateClient:
    """No model at all. Callers fall back to their deterministic templates."""

    provider = "template"
    model = "none"

    def complete(self, system: str, prompt: str, json_schema: dict[str, Any] | None = None) -> str:
        raise LLMError("template provider: use the deterministic fallback")


class OllamaClient:
    provider = "ollama"

    def __init__(self, base_url: str, model: str, http: httpx.Client | None = None) -> None:
        if not model:
            raise LLMError("OLLAMA_MODEL is not set (e.g. run `ollama pull qwen3:4b` and set it).")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.http = http or httpx.Client(timeout=120)

    def complete(self, system: str, prompt: str, json_schema: dict[str, Any] | None = None) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        if json_schema:
            body["format"] = json_schema
        r = self.http.post(f"{self.base_url}/api/chat", json=body)
        r.raise_for_status()
        return str(r.json()["message"]["content"])


class GeminiClient:
    provider = "gemini"

    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None) -> None:
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set.")
        self.api_key = api_key
        self.model = model
        self.http = http or httpx.Client(timeout=60)

    def complete(self, system: str, prompt: str, json_schema: dict[str, Any] | None = None) -> str:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        if json_schema:
            body["generationConfig"]["responseMimeType"] = "application/json"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )
        r = self.http.post(url, json=body, headers={"x-goog-api-key": self.api_key})
        r.raise_for_status()
        data = r.json()
        try:
            return str(data["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected Gemini response: {str(data)[:200]}") from e


class GroqClient:
    provider = "groq"

    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None) -> None:
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set.")
        self.api_key = api_key
        self.model = model
        self.http = http or httpx.Client(timeout=60)

    def complete(self, system: str, prompt: str, json_schema: dict[str, Any] | None = None) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if json_schema:
            body["response_format"] = {"type": "json_object"}
        r = self.http.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        r.raise_for_status()
        return str(r.json()["choices"][0]["message"]["content"])


def make_client(settings: Settings | None = None) -> LLMClient:
    s = settings or get_settings()
    p = s.llm_provider.lower().strip()
    if p in ("", "template", "none"):
        return TemplateClient()
    if p == "ollama":
        return OllamaClient(s.ollama_base_url, s.ollama_model)
    if p == "gemini":
        return GeminiClient(s.gemini_api_key, s.gemini_model)
    if p == "groq":
        return GroqClient(s.groq_api_key, s.groq_model)
    raise LLMError(
        f"Unknown LLM_PROVIDER '{s.llm_provider}'. Use template, ollama, gemini or groq."
    )


def cache_key(client: LLMClient, system: str, prompt: str, schema: dict[str, Any] | None) -> str:
    raw = json.dumps([client.provider, client.model, system, prompt, schema], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


class CachedClient:
    """Wraps a client with a cache (dict for tests, DB in production)."""

    def __init__(self, inner: LLMClient, cache: dict[str, str] | None = None, use_db: bool = False):
        self.inner = inner
        self.provider = inner.provider
        self.model = inner.model
        self.cache = cache if cache is not None else {}
        self.use_db = use_db

    def complete(self, system: str, prompt: str, json_schema: dict[str, Any] | None = None) -> str:
        key = cache_key(self.inner, system, prompt, json_schema)
        if key in self.cache:
            return self.cache[key]
        if self.use_db:
            from engine.db import connect

            with connect() as conn:
                row = conn.execute(
                    "select output from llm_cache where input_hash=%s", (key,)
                ).fetchone()
            if row:
                self.cache[key] = row["output"]
                return str(row["output"])
        out = self.inner.complete(system, prompt, json_schema)
        self.cache[key] = out
        if self.use_db:
            from engine.db import connect

            with connect() as conn:
                conn.execute(
                    """insert into llm_cache (input_hash, provider, model, output) values (%s,%s,%s,%s)
                       on conflict (input_hash) do nothing""",
                    (key, self.provider, self.model, out),
                )
        return out
