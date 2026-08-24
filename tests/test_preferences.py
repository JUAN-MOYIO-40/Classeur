from pathlib import Path

from mdjr_classeur.i18n import set_language, tr
from mdjr_classeur.preferences import load_preferences, save_preferences


def test_preferences_are_validated_and_persisted(tmp_path: Path):
    path = tmp_path / "preferences.json"
    save_preferences(path, {"language": "en", "theme": "dark", "accent": "#336699", "background": "", "confirm_actions": False})
    values = load_preferences(path)
    assert values["language"] == "en"
    assert values["theme"] == "dark"
    assert values["accent"] == "#336699"
    assert values["confirm_actions"] is False


def test_invalid_preferences_fall_back_to_safe_defaults(tmp_path: Path):
    path = tmp_path / "preferences.json"
    path.write_text('{"language": "xx", "theme": "neon", "accent": "red", "background": "/missing.png"}', encoding="utf-8")
    values = load_preferences(path)
    assert values["language"] == "fr"
    assert values["theme"] == "system"
    assert values["accent"] == "#1c8c70"
    assert values["background"] == ""


def test_translation_switches_without_changing_internal_key():
    set_language("en")
    assert tr("Préférences") == "Preferences"
    set_language("fr")
    assert tr("Préférences") == "Préférences"
