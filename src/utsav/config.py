"""Runtime settings read from the environment (and an optional ``.env`` file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from utsav.core.knowledge import DEFAULT_DATA_DIR

# Fast, inexpensive model by default; override with UTSAV_MODEL.
# Google Gemini model list: https://ai.google.dev/gemini-api/docs/models/gemini
DEFAULT_MODEL = "gemini-3.1-flash-lite"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _bool_env(names: list[str], default: bool) -> bool:
    for name in names:
        val = os.getenv(name)
        if val is not None:
            raw = val.strip().lower()
            if not raw:
                continue
            if raw in _TRUE:
                return True
            if raw in _FALSE:
                return False
            raise ValueError(f"{name} must be true or false, got {raw!r}")
    return default


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    model: str
    ai_enabled: bool
    db_path: Path
    data_dir: Path

    @property
    def ai_available(self) -> bool:
        return self.ai_enabled and bool(self.gemini_api_key)

    def __repr__(self) -> str:  # never print the key
        key = "set" if self.gemini_api_key else "unset"
        return f"Settings(model={self.model!r}, ai_enabled={self.ai_enabled}, key={key})"


def load_settings() -> Settings:
    load_dotenv(override=False)
    model = (os.getenv("UTSAV_MODEL") or os.getenv("UTSAV_AI_MODEL") or "").strip() or DEFAULT_MODEL
    if len(model) > 100 or not all(c.isalnum() or c in "-._:@" for c in model):
        raise ValueError("UTSAV_MODEL contains unexpected characters")
    gemini_key = (os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")).strip()
    default_db = "/tmp/utsav.db" if os.getenv("VERCEL") else "utsav.db"  # noqa: S108
    db_env = (
        os.getenv("UTSAV_DB_PATH") or os.getenv("UTSAV_AI_DB_PATH") or ""
    ).strip() or default_db
    data_env = (os.getenv("UTSAV_DATA_DIR") or os.getenv("UTSAV_AI_DATA_DIR") or "").strip() or str(
        DEFAULT_DATA_DIR
    )

    return Settings(
        gemini_api_key=gemini_key,
        model=model,
        ai_enabled=_bool_env(["UTSAV_AI_ENABLED", "UTSAV_ENABLED"], True),
        db_path=Path(db_env),
        data_dir=Path(data_env),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
