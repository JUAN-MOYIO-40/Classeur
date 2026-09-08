"""Tests d'intégration LLM — couvre les 20 scénarios de dégradation exigés.

Aucun modèle LLM réel n'est nécessaire pour exécuter ces tests.
Les tests vérifient que Classeur fonctionne parfaitement dans tous les cas :
sans LLM, avec LLM simulé, LLM absent, corrompu, timeout, etc.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mdjr_classeur.application.ai_provider import (
    AIProviderRegistry,
    AIResponse,
    BaseAIProvider,
    KoboldCppProvider,
    LlamaCppProvider,
    LocalHeuristicProvider,
    _extract_json,
)
from mdjr_classeur.infrastructure.system_info import (
    SystemCapabilities,
    detect_capabilities,
    model_file_info,
    recommend_mode,
    _find_koboldcpp,
    _find_llama_cli,
    _format_size,
)
from mdjr_classeur.preferences import (
    DEFAULT_PREFERENCES,
    VALID_AI_MODES,
    load_preferences,
    save_preferences,
)
from mdjr_classeur.classifier import LocalClassifier, Classification
from mdjr_classeur.application.services import ClassificationService
from mdjr_classeur.cache import ClassificationCache
from mdjr_classeur.search_index import SearchIndex


# =========================================================================
# 1. Machine sans LLM
# =========================================================================

class TestNoLLM:
    """Scénario : aucun LLM installé — Classeur fonctionne normalement."""

    def test_registry_defaults_to_heuristic(self):
        reg = AIProviderRegistry()
        assert reg.active_provider.name == "local-heuristic"
        assert reg.active_provider.available is True

    def test_classification_works_without_llm(self, tmp_path):
        classifier = LocalClassifier()
        cache = ClassificationCache(tmp_path / "c.db")
        cs = ClassificationService(classifier, cache)
        f = tmp_path / "facture_edf.txt"
        f.write_text("Facture EDF electricite consommation", encoding="utf-8")
        result = cs.classify(f)
        assert result.subject
        assert result.confidence > 0

    def test_search_works_without_llm(self, tmp_path):
        si = SearchIndex(tmp_path / "s.db")
        f = tmp_path / "doc.txt"
        f.write_text("test", encoding="utf-8")
        c = Classification("Test", "Doc", 80, "test")
        si.upsert(f, c)
        results = si.hybrid_search("test")
        assert len(results) >= 1

    def test_summarize_falls_back_to_heuristic(self):
        reg = AIProviderRegistry()
        response = reg.summarize("Ceci est un document très important. Il contient des informations essentielles.")
        assert response.text
        assert response.provider == "local-heuristic"

    def test_should_use_llm_false_without_provider(self):
        reg = AIProviderRegistry()
        assert not reg.should_use_llm(50)
        assert not reg.should_use_llm(20)


# =========================================================================
# 2. Machine avec LLM simulé
# =========================================================================

class TestWithMockLLM:
    """Scénario : LLM disponible et fonctionnel (simulé)."""

    def _make_registry_with_mock_llm(self):
        reg = AIProviderRegistry(llm_threshold=80, mode="auto")
        mock_provider = MagicMock(spec=LlamaCppProvider)
        mock_provider.name = "llama-cpp-local"
        mock_provider.available = True
        mock_provider.suggest_classification.return_value = AIResponse(
            "Assurance détectée", 0.85, "llama-cpp-local",
            {"subject": "Assurance", "category": "Contrat"},
        )
        mock_provider.summarize.return_value = AIResponse(
            "Résumé du document.", 0.80, "llama-cpp-local",
        )
        mock_provider.suggest_filename.return_value = AIResponse(
            "Contrat_Assurance_2026", 0.75, "llama-cpp-local",
            {"suggested_name": "Contrat_Assurance_2026"},
        )
        mock_provider.answer_question.return_value = AIResponse(
            "La prime est de 150 euros.", 0.78, "llama-cpp-local",
        )
        reg.register(mock_provider)
        return reg, mock_provider

    def test_active_provider_is_llm(self):
        reg, _ = self._make_registry_with_mock_llm()
        assert reg.active_provider.name == "llama-cpp-local"

    def test_should_use_llm_below_threshold(self):
        reg, _ = self._make_registry_with_mock_llm()
        assert reg.should_use_llm(50)
        assert reg.should_use_llm(79)

    def test_should_not_use_llm_above_threshold(self):
        reg, _ = self._make_registry_with_mock_llm()
        assert not reg.should_use_llm(80)
        assert not reg.should_use_llm(95)

    def test_classify_with_fallback_calls_llm(self):
        reg, mock = self._make_registry_with_mock_llm()
        result = reg.classify_with_fallback(
            "contrat assurance", "contrat.pdf",
            {"Assurance": ["assurance"]}, {"Contrat": ["contrat"]},
            heuristic_confidence=50,
        )
        assert result is not None
        assert result.provider == "llama-cpp-local"

    def test_classify_with_fallback_skips_high_confidence(self):
        reg, mock = self._make_registry_with_mock_llm()
        result = reg.classify_with_fallback(
            "contrat assurance", "contrat.pdf",
            {"Assurance": ["assurance"]}, {"Contrat": ["contrat"]},
            heuristic_confidence=95,
        )
        assert result is None
        mock.suggest_classification.assert_not_called()


# =========================================================================
# 3. Modèle absent
# =========================================================================

class TestModelAbsent:

    def test_llama_provider_not_available_without_model(self, tmp_path):
        provider = LlamaCppProvider(model_path=tmp_path / "nonexistent.gguf")
        assert provider.available is False

    def test_model_file_info_returns_none(self, tmp_path):
        info = model_file_info(tmp_path / "nonexistent.gguf")
        assert info is None

    def test_registry_falls_back_when_model_absent(self, tmp_path):
        reg = AIProviderRegistry()
        reg.register(LlamaCppProvider(model_path=tmp_path / "nonexistent.gguf"))
        assert reg.active_provider.name == "local-heuristic"


# =========================================================================
# 4. Runtime absent
# =========================================================================

class TestRuntimeAbsent:

    def test_llama_provider_not_available_without_cli(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        with patch("shutil.which", return_value=None):
            provider = LlamaCppProvider(model_path=model)
            provider.invalidate_cache()
            assert provider.available is False
            assert "introuvable" in provider.last_error

    def test_registry_falls_back_without_runtime(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        reg = AIProviderRegistry()
        with patch("shutil.which", return_value=None):
            provider = LlamaCppProvider(model_path=model)
            reg.register(provider)
            assert reg.active_provider.name == "local-heuristic"


# =========================================================================
# 5. Modèle corrompu
# =========================================================================

class TestModelCorrupt:

    def test_tiny_model_detected_as_corrupt(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"CORRUPT")
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider = LlamaCppProvider(model_path=model)
            provider.invalidate_cache()
            assert provider.available is False
            assert "corrompu" in provider.last_error

    def test_model_info_for_tiny_file(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"TINY")
        info = model_file_info(model)
        assert info is not None
        assert info["size_bytes"] == 4


# =========================================================================
# 6. Modèle incompatible (llama-cli error)
# =========================================================================

class TestModelIncompatible:

    def test_run_prompt_handles_nonzero_exit(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = LlamaCppProvider(model_path=model)
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider.invalidate_cache()
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1, stdout="", stderr="incompatible model format"
                )
                result = provider.summarize("test")
                assert result.text == ""
                assert result.confidence == 0.0


# =========================================================================
# 7. Timeout
# =========================================================================

class TestTimeout:

    def test_timeout_returns_empty_response(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = LlamaCppProvider(model_path=model, timeout=1)
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider.invalidate_cache()
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("llama-cli", 1)):
                result = provider.summarize("test text")
                assert result.text == ""
                assert "Timeout" in provider.last_error

    def test_timeout_does_not_crash(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = LlamaCppProvider(model_path=model, timeout=1)
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider.invalidate_cache()
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("llama-cli", 1)):
                result = provider.answer_question("question?", "contexte")
                assert isinstance(result, AIResponse)


# =========================================================================
# 8. Erreur de génération
# =========================================================================

class TestGenerationError:

    def test_os_error_returns_empty(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = LlamaCppProvider(model_path=model)
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider.invalidate_cache()
            with patch("subprocess.run", side_effect=OSError("disk error")):
                result = provider.summarize("test")
                assert result.text == ""
                assert "disk error" in provider.last_error


# =========================================================================
# 9. JSON invalide
# =========================================================================

class TestJSONParsing:

    def test_valid_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_json_in_markdown_fence(self):
        text = '```json\n{"category": "Facture"}\n```'
        assert _extract_json(text) == {"category": "Facture"}

    def test_json_surrounded_by_text(self):
        text = 'Voici le résultat : {"category": "Facture", "confidence": 0.9} fin.'
        result = _extract_json(text)
        assert result == {"category": "Facture", "confidence": 0.9}

    def test_partial_json_returns_none(self):
        assert _extract_json('{"a": 1') is None

    def test_empty_string(self):
        assert _extract_json("") is None
        assert _extract_json("   ") is None

    def test_no_json_at_all(self):
        assert _extract_json("Pas de JSON ici, juste du texte.") is None

    def test_nested_json(self):
        text = '{"outer": {"inner": "value"}}'
        result = _extract_json(text)
        assert result == {"outer": {"inner": "value"}}

    def test_classification_json(self):
        text = '{"category": "Facture", "subject": "Finance", "confidence": 0.93, "reason": "numéro de facture"}'
        result = _extract_json(text)
        assert result["category"] == "Facture"
        assert result["confidence"] == 0.93

    def test_llm_response_with_fallback_parsing(self, tmp_path):
        """LLM retourne du texte non-JSON, le provider parse les lignes."""
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = LlamaCppProvider(model_path=model)
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider.invalidate_cache()
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="Matière: Assurance\nCatégorie: Contrat\nRaison: mots-clés", stderr=""
                )
                result = provider.suggest_classification(
                    "contrat assurance", "doc.pdf",
                    {"Assurance": ["assurance"]}, {"Contrat": ["contrat"]}
                )
                assert result.suggestions.get("subject") == "Assurance"
                assert result.suggestions.get("category") == "Contrat"


# =========================================================================
# 10. Fallback automatique
# =========================================================================

class TestFallback:

    def test_classify_with_fallback_returns_none_on_error(self):
        reg = AIProviderRegistry(llm_threshold=80)
        mock_provider = MagicMock(spec=LlamaCppProvider)
        mock_provider.name = "llama-cpp-local"
        mock_provider.available = True
        mock_provider.suggest_classification.side_effect = RuntimeError("boom")
        reg.register(mock_provider)
        result = reg.classify_with_fallback(
            "text", "file.pdf",
            {"A": ["a"]}, {"B": ["b"]},
            heuristic_confidence=50,
        )
        assert result is None

    def test_classify_with_fallback_returns_none_for_empty_response(self):
        reg = AIProviderRegistry(llm_threshold=80)
        mock_provider = MagicMock(spec=LlamaCppProvider)
        mock_provider.name = "llama-cpp-local"
        mock_provider.available = True
        mock_provider.suggest_classification.return_value = AIResponse("", 0.0, "llama-cpp-local")
        reg.register(mock_provider)
        result = reg.classify_with_fallback(
            "text", "file.pdf",
            {"A": ["a"]}, {"B": ["b"]},
            heuristic_confidence=50,
        )
        assert result is None


# =========================================================================
# 11. Classification faible → LLM utilisé
# =========================================================================

class TestLowConfidenceTrigger:

    def test_low_confidence_triggers_llm(self):
        reg = AIProviderRegistry(llm_threshold=80)
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = True
        reg.register(mock)
        assert reg.should_use_llm(40)
        assert reg.should_use_llm(79)

    def test_threshold_is_configurable(self):
        reg = AIProviderRegistry(llm_threshold=60)
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = True
        reg.register(mock)
        assert reg.should_use_llm(59)
        assert not reg.should_use_llm(60)
        assert not reg.should_use_llm(80)


# =========================================================================
# 12. Classification forte → LLM non utilisé
# =========================================================================

class TestHighConfidenceSkips:

    def test_high_confidence_skips_llm(self):
        reg = AIProviderRegistry(llm_threshold=80)
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = True
        reg.register(mock)
        assert not reg.should_use_llm(80)
        assert not reg.should_use_llm(95)
        assert not reg.should_use_llm(100)


# =========================================================================
# 13. Fonctionnement totalement offline
# =========================================================================

class TestFullyOffline:

    def test_all_operations_offline(self, tmp_path):
        def block_connect(*args, **kwargs):
            raise OSError("Network blocked")

        with patch.object(socket.socket, "connect", block_connect):
            classifier = LocalClassifier()
            cache = ClassificationCache(tmp_path / "c.db")
            si = SearchIndex(tmp_path / "s.db")
            reg = AIProviderRegistry()

            f = tmp_path / "assurance.txt"
            f.write_text("Contrat assurance vie police beneficiaire", encoding="utf-8")

            cs = ClassificationService(classifier, cache)
            result = cs.classify(f)
            assert result.subject
            assert result.confidence > 0

            si.upsert(f, result)
            results = si.hybrid_search("assurance")
            assert len(results) >= 1

            resp = reg.summarize("Un texte important à résumer correctement.")
            assert resp.text
            assert resp.provider == "local-heuristic"


# =========================================================================
# 14. UI toujours réactive (vérifié par non-blocking)
# =========================================================================

class TestNonBlocking:

    def test_heuristic_provider_is_fast(self):
        provider = LocalHeuristicProvider()
        start = time.monotonic()
        for _ in range(100):
            provider.summarize("Un document contenant beaucoup de texte important.")
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"100 appels heuristiques en {elapsed:.2f}s, trop lent"

    def test_llm_timeout_is_bounded(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = LlamaCppProvider(model_path=model, timeout=2)
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider.invalidate_cache()
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 2)):
                start = time.monotonic()
                provider.summarize("test")
                elapsed = time.monotonic() - start
                assert elapsed < 3.0


# =========================================================================
# 15. Mémoire raisonnable (vérifications structurelles)
# =========================================================================

class TestMemory:

    def test_system_capabilities_reports_ram(self):
        caps = detect_capabilities()
        assert caps.total_ram_mb > 0
        assert caps.available_ram_mb >= 0
        assert caps.available_ram_mb <= caps.total_ram_mb

    def test_model_ram_estimate_is_reasonable(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * (2 * 1024 * 1024 * 1024 + 100))  # ~2 Go
        info = model_file_info(model)
        assert info is not None
        ram_mb = info["estimated_ram_mb"]
        assert 2500 < ram_mb < 5000, f"RAM estimée {ram_mb} Mo pour 2 Go model"

    def test_recommend_mode_respects_low_ram(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        caps = SystemCapabilities(
            total_ram_mb=3800, available_ram_mb=1500,
            cpu_name="test", cpu_count=2, os_name="test",
            has_llama_cli=True, llama_cli_path="/bin/llama-cli",
        )
        mode = recommend_mode(caps, model)
        assert mode == "heuristic_recommended"

    def test_recommend_mode_allows_llm_with_enough_ram(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        caps = SystemCapabilities(
            total_ram_mb=16000, available_ram_mb=10000,
            cpu_name="test", cpu_count=8, os_name="test",
            has_llama_cli=True, llama_cli_path="/bin/llama-cli",
        )
        mode = recommend_mode(caps, model)
        assert mode == "llm_local"


# =========================================================================
# 16. Plusieurs requêtes successives
# =========================================================================

class TestMultipleRequests:

    def test_consecutive_heuristic_calls(self):
        reg = AIProviderRegistry()
        for i in range(10):
            resp = reg.summarize(f"Document numéro {i} avec du contenu important et pertinent.")
            assert resp.provider == "local-heuristic"

    def test_consecutive_llm_calls_with_mock(self):
        reg = AIProviderRegistry()
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = True
        mock.summarize.return_value = AIResponse("Résumé", 0.8, "llama-cpp-local")
        reg.register(mock)
        for _ in range(10):
            resp = reg.summarize("texte")
            assert resp.provider == "llama-cpp-local"
        assert mock.summarize.call_count == 10


# =========================================================================
# 17. Chargement/déchargement du modèle
# =========================================================================

class TestModelLoadUnload:

    def test_provider_availability_cache_invalidation(self, tmp_path):
        model = tmp_path / "model.gguf"
        provider = LlamaCppProvider(model_path=model)
        assert provider.available is False
        model.write_bytes(b"\x00" * 200_000)
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider.invalidate_cache()
            assert provider.available is True
        model.unlink()
        provider.invalidate_cache()
        assert provider.available is False

    def test_model_appears_after_init(self, tmp_path):
        model = tmp_path / "model.gguf"
        reg = AIProviderRegistry()
        provider = LlamaCppProvider(model_path=model)
        reg.register(provider)
        assert reg.active_provider.name == "local-heuristic"
        model.write_bytes(b"\x00" * 200_000)
        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider.invalidate_cache()
            assert reg.active_provider.name == "llama-cpp-local"


# =========================================================================
# 18. Changement de modèle
# =========================================================================

class TestModelChange:

    def test_switch_model_path(self, tmp_path):
        model_a = tmp_path / "model_a.gguf"
        model_b = tmp_path / "model_b.gguf"
        model_a.write_bytes(b"\x00" * 200_000)
        model_b.write_bytes(b"\x00" * 300_000)

        with patch("shutil.which", return_value="/usr/bin/llama-cli"):
            provider_a = LlamaCppProvider(model_path=model_a)
            assert provider_a.available is True

            info_a = model_file_info(model_a)
            info_b = model_file_info(model_b)
            assert info_a["size_bytes"] != info_b["size_bytes"]


# =========================================================================
# 19. Désactivation du LLM
# =========================================================================

class TestLLMDisable:

    def test_heuristic_only_mode(self):
        reg = AIProviderRegistry(mode="heuristic_only")
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = True
        mock.summarize.return_value = AIResponse("LLM", 0.9, "llama-cpp-local")
        reg.register(mock)
        assert reg.active_provider.name == "local-heuristic"
        assert not reg.should_use_llm(30)
        resp = reg.summarize("texte")
        assert resp.provider == "local-heuristic"
        mock.summarize.assert_not_called()

    def test_mode_can_be_toggled(self):
        reg = AIProviderRegistry(mode="auto")
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = True
        reg.register(mock)
        assert reg.should_use_llm(50)
        reg.mode = "heuristic_only"
        assert not reg.should_use_llm(50)
        reg.mode = "auto"
        assert reg.should_use_llm(50)


# =========================================================================
# 20. Démarrage complet sans modèle
# =========================================================================

class TestStartupWithoutModel:

    def test_full_startup_without_model(self, tmp_path):
        classifier = LocalClassifier()
        cache = ClassificationCache(tmp_path / "c.db")
        si = SearchIndex(tmp_path / "s.db")
        reg = AIProviderRegistry(mode="auto")
        provider = LlamaCppProvider(model_path=tmp_path / "absent.gguf")
        reg.register(provider)

        assert reg.active_provider.name == "local-heuristic"
        assert reg.available_providers == ["local-heuristic"]

        f = tmp_path / "test.txt"
        f.write_text("Document de test pour vérifier le démarrage", encoding="utf-8")
        cs = ClassificationService(classifier, cache)
        result = cs.classify(f)
        assert result.subject
        si.upsert(f, result)
        assert si.stats()["total"] == 1


# =========================================================================
# Extras : SystemInfo, preferences, format_size
# =========================================================================

class TestSystemInfo:

    def test_detect_capabilities_fields(self):
        caps = detect_capabilities()
        assert isinstance(caps.total_ram_mb, int)
        assert isinstance(caps.cpu_name, str)
        assert isinstance(caps.cpu_count, int)
        assert isinstance(caps.os_name, str)
        assert isinstance(caps.has_llama_cli, bool)

    def test_format_size(self):
        assert _format_size(500) == "500 o"
        assert "Ko" in _format_size(50_000)
        assert "Mo" in _format_size(5_000_000)
        assert "Go" in _format_size(5_000_000_000)

    def test_find_llama_cli_in_runtime_dir(self, tmp_path):
        runtime = tmp_path / "runtime" / "llama-build"
        runtime.mkdir(parents=True)
        exe = runtime / ("llama-cli.exe" if os.name == "nt" else "llama-cli")
        exe.write_bytes(b"\x00" * 100)
        with patch("mdjr_classeur.infrastructure.system_info.shutil.which", return_value=None), \
             patch("mdjr_classeur.infrastructure.system_info.Path.home", return_value=tmp_path):
            # Create the expected directory structure
            config_dir = tmp_path / ".mdjr_classeur" / "runtime" / "llama-build"
            config_dir.mkdir(parents=True)
            cli = config_dir / ("llama-cli.exe" if os.name == "nt" else "llama-cli")
            cli.write_bytes(b"\x00" * 100)
            result = _find_llama_cli()
            assert result != ""
            assert "llama-cli" in result

    def test_model_file_info_existing(self, tmp_path):
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 2_000_000)
        info = model_file_info(model)
        assert info is not None
        assert info["size_bytes"] == 2_000_000
        assert info["name"] == "model"
        assert "Mo" in info["size_display"]
        assert info["estimated_ram_mb"] > 0


class TestPreferencesAI:

    def test_default_ai_preferences(self):
        assert DEFAULT_PREFERENCES["ai_mode"] == "auto"
        assert DEFAULT_PREFERENCES["llm_threshold"] == 80

    def test_save_and_load_ai_preferences(self, tmp_path):
        path = tmp_path / "prefs.json"
        values = dict(DEFAULT_PREFERENCES)
        values["ai_mode"] = "llm_local"
        values["llm_threshold"] = 65
        save_preferences(path, values)
        loaded = load_preferences(path)
        assert loaded["ai_mode"] == "llm_local"
        assert loaded["llm_threshold"] == 65

    def test_invalid_ai_mode_falls_back(self, tmp_path):
        path = tmp_path / "prefs.json"
        path.write_text(json.dumps({"ai_mode": "cloud_api", "llm_threshold": 200}), encoding="utf-8")
        loaded = load_preferences(path)
        assert loaded["ai_mode"] == "auto"
        assert loaded["llm_threshold"] == 80

    def test_valid_ai_modes(self):
        assert VALID_AI_MODES == {"auto", "heuristic_only", "llm_local"}


class TestRegistryModes:

    def test_auto_mode_selects_best(self):
        reg = AIProviderRegistry(mode="auto")
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = True
        reg.register(mock)
        assert reg.active_provider.name == "llama-cpp-local"

    def test_llm_local_mode_with_unavailable_llm(self):
        reg = AIProviderRegistry(mode="llm_local")
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = False
        reg.register(mock)
        assert reg.active_provider.name == "local-heuristic"

    def test_threshold_clamping(self):
        reg = AIProviderRegistry(llm_threshold=-10)
        assert reg.llm_threshold == 0
        reg = AIProviderRegistry(llm_threshold=150)
        assert reg.llm_threshold == 100
        reg.llm_threshold = 50
        assert reg.llm_threshold == 50

    def test_llm_provider_property(self):
        reg = AIProviderRegistry()
        assert reg.llm_provider is None
        mock = MagicMock(spec=LlamaCppProvider)
        mock.name = "llama-cpp-local"
        mock.available = True
        reg.register(mock)
        assert reg.llm_provider is mock


class TestKoboldCppProvider:

    def test_kobold_unavailable_no_exe(self, tmp_path):
        provider = KoboldCppProvider(tmp_path / "model.gguf", exe_path="/nonexistent/koboldcpp.exe")
        assert not provider.available
        assert "introuvable" in provider.last_error

    def test_kobold_unavailable_no_model(self, tmp_path):
        exe = tmp_path / "koboldcpp.exe"
        exe.write_bytes(b"\x00" * 100)
        provider = KoboldCppProvider(tmp_path / "missing.gguf", exe_path=str(exe))
        assert not provider.available
        assert "modèle" in provider.last_error.lower()

    def test_kobold_available_with_exe_and_model(self, tmp_path):
        exe = tmp_path / "koboldcpp.exe"
        exe.write_bytes(b"\x00" * 100)
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = KoboldCppProvider(model, exe_path=str(exe))
        assert provider.available

    def test_kobold_invalidate_cache(self, tmp_path):
        exe = tmp_path / "koboldcpp.exe"
        exe.write_bytes(b"\x00" * 100)
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = KoboldCppProvider(model, exe_path=str(exe))
        assert provider.available
        provider.invalidate_cache()
        assert provider.available

    def test_kobold_name(self, tmp_path):
        provider = KoboldCppProvider(tmp_path / "model.gguf")
        assert provider.name == "koboldcpp-local"

    def test_registry_recognizes_kobold_as_llm(self):
        reg = AIProviderRegistry(mode="auto")
        mock = MagicMock(spec=KoboldCppProvider)
        mock.name = "koboldcpp-local"
        mock.available = True
        reg.register(mock)
        assert reg.llm_provider is mock
        assert reg.active_provider.name == "koboldcpp-local"

    def test_kobold_stop_server_safe(self, tmp_path):
        provider = KoboldCppProvider(tmp_path / "model.gguf")
        provider.stop_server()

    def test_kobold_chat_without_server(self, tmp_path):
        exe = tmp_path / "koboldcpp.exe"
        exe.write_bytes(b"\x00" * 100)
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 200_000)
        provider = KoboldCppProvider(model, exe_path=str(exe))
        result = provider.summarize("test text")
        assert result.confidence == 0.0


class TestKoboldDetection:

    def test_detect_koboldcpp_in_runtime(self, tmp_path):
        from mdjr_classeur.infrastructure.system_info import _find_koboldcpp
        runtime = tmp_path / ".mdjr_classeur" / "runtime"
        runtime.mkdir(parents=True)
        exe = runtime / ("koboldcpp.exe" if os.name == "nt" else "koboldcpp")
        exe.write_bytes(b"\x00" * 100)
        with patch("mdjr_classeur.infrastructure.system_info.Path.home", return_value=tmp_path), \
             patch("mdjr_classeur.infrastructure.system_info.shutil.which", return_value=None):
            result = _find_koboldcpp()
            assert result != ""
            assert "koboldcpp" in result

    def test_capabilities_include_kobold_fields(self):
        caps = detect_capabilities()
        assert isinstance(caps.has_koboldcpp, bool)
        assert isinstance(caps.koboldcpp_path, str)
