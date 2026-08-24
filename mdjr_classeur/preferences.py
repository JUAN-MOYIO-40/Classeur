from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

DEFAULT_PREFERENCES = {
    "language": "fr",
    "theme": "system",
    "accent": "#1c8c70",
    "background": "",
    "confirm_actions": True,
}
VALID_LANGUAGES = {"fr", "en"}
VALID_THEMES = {"system", "light", "dark"}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _safe_color(value: object) -> str:
    candidate = str(value or "")
    return candidate if HEX_COLOR.fullmatch(candidate) else DEFAULT_PREFERENCES["accent"]


def load_preferences(path: Path) -> dict[str, object]:
    values = dict(DEFAULT_PREFERENCES)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if isinstance(raw, dict):
            language = raw.get("language")
            theme = raw.get("theme")
            background = raw.get("background")
            if language in VALID_LANGUAGES:
                values["language"] = language
            if theme in VALID_THEMES:
                values["theme"] = theme
            values["accent"] = _safe_color(raw.get("accent"))
            if isinstance(background, str):
                values["background"] = background
            if isinstance(raw.get("confirm_actions"), bool):
                values["confirm_actions"] = raw["confirm_actions"]
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    background = str(values["background"] or "")
    if background and not Path(background).expanduser().is_file():
        values["background"] = ""
    return values


def save_preferences(path: Path, values: dict[str, object]) -> None:
    payload = dict(DEFAULT_PREFERENCES)
    payload["language"] = values.get("language") if values.get("language") in VALID_LANGUAGES else "fr"
    payload["theme"] = values.get("theme") if values.get("theme") in VALID_THEMES else "system"
    payload["accent"] = _safe_color(values.get("accent"))
    background = str(values.get("background") or "")
    payload["background"] = background if not background or Path(background).expanduser().is_file() else ""
    payload["confirm_actions"] = bool(values.get("confirm_actions", True))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
