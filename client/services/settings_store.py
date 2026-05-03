"""Single source of truth for loading and saving settings.json.

Both login.py and main_window.py import from here to avoid circular imports.
"""
import json
import structlog
from pathlib import Path

from shared.models import SettingsPayload

logger = structlog.get_logger()

_SETTINGS_DIR  = Path.home() / ".skype_reborn"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"


def load_settings() -> SettingsPayload:
    try:
        if _SETTINGS_FILE.exists():
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            return SettingsPayload(**data)
    except Exception as exc:
        logger.warning("Could not load settings, using defaults", error=str(exc))
    return SettingsPayload()


def save_settings(settings: SettingsPayload) -> None:
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        _SETTINGS_FILE.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not save settings", error=str(exc))
