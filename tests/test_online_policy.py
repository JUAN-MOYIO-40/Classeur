from pathlib import Path

from mdjr_classeur.application.online_policy import OnlineAssistPolicy, OnlineMode


def test_online_assistance_is_local_only_by_default(tmp_path: Path):
    document = tmp_path / "secret.txt"
    document.write_text("contenu privé", encoding="utf-8")
    policy = OnlineAssistPolicy()
    assert not policy.enabled
    assert policy.prepare_excerpt(document, "contenu privé") is None


def test_excerpt_requires_consent(tmp_path: Path):
    document = tmp_path / "document.txt"
    document.write_text("contenu", encoding="utf-8")
    policy = OnlineAssistPolicy(mode=OnlineMode.EXCERPT_ONLY, consent_given=False)
    assert not policy.can_send(document, "contenu")


def test_excerpt_is_bounded_and_contains_no_file_bytes(tmp_path: Path):
    document = tmp_path / "document.txt"
    document.write_text("contenu", encoding="utf-8")
    policy = OnlineAssistPolicy(mode=OnlineMode.EXCERPT_ONLY, consent_given=True, max_excerpt_chars=5)
    payload = policy.prepare_excerpt(document, "  texte très long  ")
    assert payload == {"filename": "document.txt", "extension": ".txt", "excerpt": "texte"}
