"""Thin wrapper around the Google GenAI SDK (Gemini).

* Disabled (returns ``None``) when there is no key or ``UTSAV_AI_ENABLED=false``.
* 20 s timeout per request.
* ``max_tokens`` is capped per task and oversized prompts are refused (cost guard).
* Responses are constrained with JSON-schema structured output, then parsed.
* A bounded in-memory LRU cache keyed by a hash of (model, task, prompts) avoids
  paying twice for the same request.
* Never raises for API problems: callers fall back to template output on ``None``.
  Logs carry the task name and outcome only, never user content.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from threading import Lock
from typing import Any

from google import genai
from google.genai import errors, types

from utsav.config import Settings

log = logging.getLogger("utsav.ai")

TIMEOUT_SECONDS = 20.0
MAX_PROMPT_CHARS = 12_000
MAX_TOKENS = {"ideas": 1200, "intake": 500, "explain": 900}
CACHE_SIZE = 256


class AIClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        enabled: bool = True,
        sdk: Any = None,  # injected in tests; defaults to genai.Client
        cache_size: int = CACHE_SIZE,
    ) -> None:
        self.model = model
        self.enabled = enabled and bool(api_key or sdk)
        self._api_key = api_key
        self._sdk: Any = sdk
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._cache_size = cache_size
        self._lock = Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> AIClient:
        return cls(
            api_key=settings.gemini_api_key, model=settings.model, enabled=settings.ai_enabled
        )

    def _client(self) -> Any:
        if self._sdk is None:
            self._sdk = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=TIMEOUT_SECONDS),
            )
        return self._sdk

    def complete_json(
        self, task: str, *, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Run one structured-output request. Returns parsed JSON or ``None`` on any failure."""
        if not self.enabled:
            return None
        if len(system) + len(user) > MAX_PROMPT_CHARS:
            log.warning("ai.%s refused: prompt too large", task)
            return None
        key = hashlib.sha256(
            json.dumps([self.model, task, system, user], ensure_ascii=False).encode()
        ).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                log.info("ai.%s cache hit", task)
                return self._cache[key]

        started = time.monotonic()
        try:
            config = types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=MAX_TOKENS.get(task, 500),
            )
            response = self._client().models.generate_content(
                model=self.model,
                contents=user,
                config=config,
            )
        except errors.APIError as exc:
            log.warning("ai.%s failed: %s", task, type(exc).__name__)
            return None
        except Exception as exc:
            log.warning("ai.%s unexpected error: %s", task, type(exc).__name__)
            return None

        elapsed = time.monotonic() - started
        candidates = getattr(response, "candidates", None)
        if candidates:
            finish_reason = getattr(candidates[0], "finish_reason", None)
            if finish_reason is not None:
                reason_str = str(finish_reason).upper()
                if "STOP" not in reason_str and finish_reason not in (None, "STOP"):
                    log.warning("ai.%s unusable finish_reason=%s", task, finish_reason)
                    return None

        text = getattr(response, "text", "") or ""
        if not text and candidates:
            parts = getattr(getattr(candidates[0], "content", None), "parts", [])
            text = "".join(getattr(p, "text", "") for p in parts if getattr(p, "text", None))

        try:
            data = json.loads(text)
        except ValueError:
            log.warning("ai.%s returned non-JSON", task)
            return None
        if not isinstance(data, dict):
            log.warning("ai.%s returned non-object JSON", task)
            return None

        log.info("ai.%s ok in %.2fs", task, elapsed)
        with self._lock:
            self._cache[key] = data
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return data
