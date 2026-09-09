from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..classifier import Classification, fold
from ..semantic import NativeSemanticEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIResponse:
    text: str
    confidence: float
    provider: str
    suggestions: dict[str, str] = field(default_factory=dict)
    duration_ms: int = 0


class BaseAIProvider(ABC):
    """Interface commune pour tout fournisseur d'intelligence documentaire.

    Le contrat : aucun appel réseau sans consentement explicite.
    Les implémentations locales n'ont besoin d'aucune connexion.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def summarize(self, text: str, max_words: int = 50) -> AIResponse: ...

    @abstractmethod
    def suggest_classification(self, text: str, filename: str, subjects: dict[str, list[str]], categories: dict[str, list[str]]) -> AIResponse: ...

    @abstractmethod
    def suggest_filename(self, text: str, current_name: str, classification: Classification) -> AIResponse: ...

    @abstractmethod
    def answer_question(self, question: str, context: str) -> AIResponse: ...


class LocalHeuristicProvider(BaseAIProvider):
    """Intelligence locale par heuristiques avancées et analyse sémantique n-gram.

    Fonctionne sur toute machine sans GPU, sans modèle, sans réseau.
    C'est le provider par défaut et le fallback permanent.
    """

    def __init__(self):
        self._semantic = NativeSemanticEngine()

    @property
    def name(self) -> str:
        return "local-heuristic"

    @property
    def available(self) -> bool:
        return True

    def summarize(self, text: str, max_words: int = 50) -> AIResponse:
        sentences = re.split(r"[.!?\n]+", text.strip())
        sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
        if not sentences:
            return AIResponse("", 0.0, self.name)
        summary_parts = []
        word_count = 0
        for sentence in sentences[:10]:
            words = sentence.split()
            if word_count + len(words) > max_words:
                break
            summary_parts.append(sentence)
            word_count += len(words)
        text_out = ". ".join(summary_parts)
        if text_out and not text_out.endswith("."):
            text_out += "."
        return AIResponse(text_out, 0.6, self.name)

    def suggest_classification(self, text: str, filename: str, subjects: dict[str, list[str]], categories: dict[str, list[str]]) -> AIResponse:
        context = f"{filename} {text}"
        sub_name, sub_score, sub_hits = self._semantic.predict(context, subjects)
        cat_name, cat_score, cat_hits = self._semantic.predict(context, categories)
        suggestions = {}
        if sub_name and sub_score >= 0.15:
            suggestions["subject"] = sub_name
        if cat_name and cat_score >= 0.15:
            suggestions["category"] = cat_name
        confidence = max(sub_score, cat_score)
        reason_parts = []
        if sub_hits:
            reason_parts.append(f"matière ({', '.join(sub_hits[:3])})")
        if cat_hits:
            reason_parts.append(f"catégorie ({', '.join(cat_hits[:3])})")
        reason = "Analyse sémantique locale : " + ", ".join(reason_parts) if reason_parts else "Aucun signal sémantique significatif."
        return AIResponse(reason, confidence, self.name, suggestions)

    def suggest_filename(self, text: str, current_name: str, classification: Classification) -> AIResponse:
        folded = fold(text[:5000])
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        candidate = ""
        for line in lines[:20]:
            cleaned = re.sub(r"\s+", " ", line).strip()
            if 10 <= len(cleaned) <= 120 and sum(c.isalpha() for c in cleaned) > len(cleaned) * 0.5:
                candidate = cleaned
                break
        if not candidate:
            return AIResponse(current_name, 0.2, self.name)
        parts = []
        if classification.year:
            parts.append(classification.year)
        if classification.subject and classification.subject != "À trier":
            parts.append(classification.subject)
        parts.append(candidate[:80])
        suggestion = " - ".join(parts)
        return AIResponse(suggestion, 0.55, self.name, {"suggested_name": suggestion})

    def answer_question(self, question: str, context: str) -> AIResponse:
        folded_q = fold(question)
        folded_c = fold(context[:10000])
        sentences = re.split(r"[.!?\n]+", context.strip())
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        q_tokens = set(folded_q.split())
        scored = []
        for sentence in sentences:
            s_tokens = set(fold(sentence).split())
            overlap = len(q_tokens & s_tokens)
            if overlap > 0:
                scored.append((overlap / max(len(q_tokens), 1), sentence))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if not scored:
            return AIResponse("Aucune information pertinente trouvée dans le contexte fourni.", 0.1, self.name)
        best = scored[:3]
        answer = " ".join(s for _, s in best)
        return AIResponse(answer, min(0.7, best[0][0]), self.name)


# ---------------------------------------------------------------------------
# JSON parsing robuste pour les réponses LLM
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict | None:
    """Tente d'extraire un objet JSON d'une réponse LLM potentiellement bruitée."""
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    # Retirer markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()
    # Tentative directe
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # Chercher le premier {...} dans le texte
    brace_start = cleaned.find("{")
    if brace_start == -1:
        return None
    depth = 0
    end = brace_start
    for i in range(brace_start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if depth != 0:
        return None
    try:
        obj = json.loads(cleaned[brace_start:end])
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# LlamaCppProvider — provider LLM local via llama.cpp
# ---------------------------------------------------------------------------

class LlamaCppProvider(BaseAIProvider):
    """Provider pour modèle GGUF local via llama-cli.

    Optimisé pour Ministral 3 3B Instruct Q4_K_M.
    Nécessite :
    - llama-cli accessible dans le PATH
    - Un fichier modèle .gguf
    - Au minimum 8 Go de RAM totale (recommandé)

    Ce provider est OPTIONNEL. L'application fonctionne parfaitement sans lui.
    """

    def __init__(self, model_path: Path | None = None, cli_name: str = "llama-cli",
                 max_tokens: int = 512, timeout: int = 120, threads: int | None = None):
        self._model_path = model_path
        self._cli_name = cli_name
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._threads = threads
        self._last_error: str = ""
        self._available_cache: bool | None = None

    @property
    def name(self) -> str:
        return "llama-cpp-local"

    @property
    def available(self) -> bool:
        if self._available_cache is not None:
            return self._available_cache
        result = self._check_available()
        self._available_cache = result
        return result

    def _check_available(self) -> bool:
        if not shutil.which(self._cli_name):
            self._last_error = "llama-cli introuvable dans le PATH"
            return False
        if self._model_path is None or not self._model_path.exists():
            self._last_error = "Fichier modèle introuvable"
            return False
        if self._model_path.stat().st_size < 100_000:
            self._last_error = "Fichier modèle trop petit (possiblement corrompu)"
            return False
        return True

    def invalidate_cache(self):
        """Force une re-vérification de la disponibilité."""
        self._available_cache = None

    @property
    def last_error(self) -> str:
        return self._last_error

    def _build_command(self, prompt: str, max_tokens: int | None = None) -> list[str]:
        tokens = max_tokens or self._max_tokens
        cmd = [
            self._cli_name, "-m", str(self._model_path),
            "-p", prompt,
            "-n", str(tokens),
            "--temp", "0.1",
            "--top-p", "0.9",
            "--repeat-penalty", "1.1",
            "--no-display-prompt",
        ]
        if self._threads:
            cmd.extend(["-t", str(self._threads)])
        return cmd

    def _run_prompt(self, prompt: str, max_tokens: int | None = None) -> tuple[str, int]:
        """Exécute un prompt et retourne (output, duration_ms)."""
        if not self.available:
            return "", 0
        start = time.monotonic()
        try:
            result = subprocess.run(
                self._build_command(prompt, max_tokens),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self._timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            duration = int((time.monotonic() - start) * 1000)
            output = (result.stdout or "").strip()
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                self._last_error = f"llama-cli exit {result.returncode}: {stderr[:200]}"
                logger.warning("LLM error: %s", self._last_error)
                if not output:
                    return "", duration
            return output, duration
        except subprocess.TimeoutExpired:
            duration = int((time.monotonic() - start) * 1000)
            self._last_error = f"Timeout après {self._timeout}s"
            logger.warning("LLM timeout after %ds", self._timeout)
            return "", duration
        except OSError as exc:
            duration = int((time.monotonic() - start) * 1000)
            self._last_error = str(exc)
            logger.warning("LLM OS error: %s", exc)
            return "", duration

    def summarize(self, text: str, max_words: int = 50) -> AIResponse:
        prompt = (
            f"<s>[INST] Résume ce texte en {max_words} mots maximum. "
            f"Réponds uniquement avec le résumé, sans introduction.\n\n"
            f"{text[:3000]}[/INST]"
        )
        output, duration = self._run_prompt(prompt, max_tokens=200)
        return AIResponse(output, 0.75 if output else 0.0, self.name, duration_ms=duration)

    def suggest_classification(self, text: str, filename: str, subjects: dict[str, list[str]], categories: dict[str, list[str]]) -> AIResponse:
        subject_list = ", ".join(subjects.keys())
        category_list = ", ".join(categories.keys())
        prompt = (
            f"<s>[INST] Tu es un assistant de classification documentaire. "
            f"Analyse ce document et réponds UNIQUEMENT avec un objet JSON valide.\n\n"
            f"Fichier : {filename}\n"
            f"Contenu : {text[:2500]}\n\n"
            f"Matières possibles : {subject_list}\n"
            f"Catégories possibles : {category_list}\n\n"
            f"Réponds avec ce format JSON exact :\n"
            f'{{"category": "...", "subject": "...", "confidence": 0.XX, '
            f'"reason": "explication courte"}}[/INST]'
        )
        output, duration = self._run_prompt(prompt, max_tokens=256)
        suggestions = {}
        parsed = _extract_json(output)
        if parsed:
            if parsed.get("subject") in subjects:
                suggestions["subject"] = parsed["subject"]
            if parsed.get("category") in categories:
                suggestions["category"] = parsed["category"]
            confidence = 0.80 if suggestions else 0.40
            reason = parsed.get("reason", output[:200])
        else:
            for line in output.splitlines():
                low = line.lower()
                if low.startswith(("matière:", "matiere:", "subject:")):
                    val = line.split(":", 1)[1].strip()
                    if val in subjects:
                        suggestions["subject"] = val
                elif low.startswith(("catégorie:", "categorie:", "category:")):
                    val = line.split(":", 1)[1].strip()
                    if val in categories:
                        suggestions["category"] = val
            confidence = 0.75 if suggestions else 0.30
            reason = output[:200]
        return AIResponse(reason, confidence, self.name, suggestions, duration_ms=duration)

    def suggest_filename(self, text: str, current_name: str, classification: Classification) -> AIResponse:
        prompt = (
            f"<s>[INST] Propose un nom de fichier descriptif pour ce document. "
            f"Réponds UNIQUEMENT avec le nom (sans extension, sans guillemets).\n\n"
            f"Fichier actuel : {current_name}\n"
            f"Matière : {classification.subject}\n"
            f"Catégorie : {classification.category}\n"
            f"Contenu : {text[:2000]}[/INST]"
        )
        output, duration = self._run_prompt(prompt, max_tokens=100)
        output = re.sub(r'[<>:"/\\|?*\n\r]', '', output).strip()[:120]
        output = output.strip('"\'` ')
        return AIResponse(
            output or current_name,
            0.70 if output else 0.0,
            self.name,
            {"suggested_name": output} if output else {},
            duration_ms=duration,
        )

    def answer_question(self, question: str, context: str) -> AIResponse:
        prompt = (
            f"<s>[INST] Réponds à la question en te basant uniquement sur le contexte fourni. "
            f"Si l'information n'est pas dans le contexte, dis-le clairement.\n\n"
            f"Contexte :\n{context[:3000]}\n\n"
            f"Question : {question}[/INST]"
        )
        output, duration = self._run_prompt(prompt)
        return AIResponse(output, 0.75 if output else 0.0, self.name, duration_ms=duration)


# ---------------------------------------------------------------------------
# KoboldCppProvider — provider LLM local via koboldcpp HTTP API
# ---------------------------------------------------------------------------

class ChatCompletionProvider(BaseAIProvider):
    """Base des providers qui dialoguent par messages système/utilisateur.

    Les quatre tâches documentaires ne diffèrent que par leur prompt : seule
    la façon d'envoyer les messages change d'un moteur à l'autre. Les
    sous-classes n'implémentent donc que `_chat`, et les prompts restent
    définis à un seul endroit.
    """

    @abstractmethod
    def _chat(self, messages: list[dict], max_tokens: int = 256) -> tuple[str, int]:
        """Retourne (réponse, durée en ms). Une réponse vide signale un échec."""

    def summarize(self, text: str, max_words: int = 50) -> AIResponse:
        messages = [
            {"role": "system", "content": f"Résume le texte en {max_words} mots maximum. Réponds uniquement avec le résumé."},
            {"role": "user", "content": text[:3000]},
        ]
        output, duration = self._chat(messages, max_tokens=200)
        return AIResponse(output, 0.75 if output else 0.0, self.name, duration_ms=duration)

    def suggest_classification(self, text: str, filename: str, subjects: dict[str, list[str]], categories: dict[str, list[str]]) -> AIResponse:
        subject_list = ", ".join(subjects.keys())
        category_list = ", ".join(categories.keys())
        messages = [
            {"role": "system", "content": "Tu es un assistant de classification documentaire. Réponds UNIQUEMENT avec un objet JSON valide."},
            {"role": "user", "content": (
                f"Analyse ce document et classifie-le.\n\n"
                f"Fichier : {filename}\nContenu : {text[:2500]}\n\n"
                f"Matières possibles : {subject_list}\n"
                f"Catégories possibles : {category_list}\n\n"
                f'Réponds avec ce JSON : {{"category": "...", "subject": "...", "confidence": 0.XX, "reason": "..."}}'
            )},
        ]
        output, duration = self._chat(messages, max_tokens=256)
        suggestions = {}
        parsed = _extract_json(output)
        if parsed:
            if parsed.get("subject") in subjects:
                suggestions["subject"] = parsed["subject"]
            if parsed.get("category") in categories:
                suggestions["category"] = parsed["category"]
            confidence = 0.80 if suggestions else 0.40
            reason = parsed.get("reason", output[:200])
        else:
            confidence = 0.30
            reason = output[:200]
        return AIResponse(reason, confidence, self.name, suggestions, duration_ms=duration)

    def suggest_filename(self, text: str, current_name: str, classification: Classification) -> AIResponse:
        messages = [
            {"role": "system", "content": "Propose un nom de fichier descriptif. Réponds UNIQUEMENT avec le nom, sans extension."},
            {"role": "user", "content": (
                f"Fichier actuel : {current_name}\n"
                f"Matière : {classification.subject}\n"
                f"Catégorie : {classification.category}\n"
                f"Contenu : {text[:2000]}"
            )},
        ]
        output, duration = self._chat(messages, max_tokens=100)
        output = re.sub(r'[<>:"/\\|?*\n\r]', '', output).strip()[:120]
        output = output.strip('"\'` ')
        return AIResponse(
            output or current_name,
            0.70 if output else 0.0,
            self.name,
            {"suggested_name": output} if output else {},
            duration_ms=duration,
        )

    def answer_question(self, question: str, context: str) -> AIResponse:
        messages = [
            {"role": "system", "content": "Réponds à la question en te basant uniquement sur le contexte fourni. Si l'information n'est pas dans le contexte, dis-le clairement."},
            {"role": "user", "content": f"Contexte :\n{context[:3000]}\n\nQuestion : {question}"},
        ]
        output, duration = self._chat(messages)
        return AIResponse(output, 0.75 if output else 0.0, self.name, duration_ms=duration)


class KoboldCppProvider(ChatCompletionProvider):
    """Provider pour modèle GGUF local via koboldcpp (API HTTP locale).

    Alternative à LlamaCppProvider quand llama-cli ne fonctionne pas.
    Koboldcpp lance un serveur HTTP local et expose une API OpenAI-compatible.
    """

    def __init__(self, model_path: Path | None = None,
                 exe_path: str = "koboldcpp.exe",
                 port: int = 5001, threads: int = 2,
                 context_size: int = 512, timeout: int = 180):
        self._model_path = model_path
        self._exe_path = exe_path
        self._port = port
        self._threads = threads
        self._context_size = context_size
        self._timeout = timeout
        self._last_error: str = ""
        self._available_cache: bool | None = None
        self._process: subprocess.Popen | None = None
        self._base_url = f"http://localhost:{port}"

    @property
    def name(self) -> str:
        return "koboldcpp-local"

    @property
    def available(self) -> bool:
        if self._available_cache is not None:
            return self._available_cache
        result = self._check_available()
        self._available_cache = result
        return result

    def _check_available(self) -> bool:
        if not Path(self._exe_path).is_file() and not shutil.which(self._exe_path):
            self._last_error = "koboldcpp introuvable"
            return False
        if self._model_path is None or not self._model_path.exists():
            self._last_error = "Fichier modèle introuvable"
            return False
        if self._model_path.stat().st_size < 100_000:
            self._last_error = "Fichier modèle trop petit (possiblement corrompu)"
            return False
        return True

    def invalidate_cache(self):
        self._available_cache = None

    @property
    def last_error(self) -> str:
        return self._last_error

    def _ensure_server(self) -> bool:
        """Démarre le serveur koboldcpp si pas déjà en cours."""
        if self._process is not None and self._process.poll() is None:
            try:
                req = urllib.request.Request(f"{self._base_url}/api/v1/model", method="GET")
                with urllib.request.urlopen(req, timeout=2):
                    return True
            except Exception:
                pass

        cmd = [
            self._exe_path, "--model", str(self._model_path),
            "--usecpu", "--threads", str(self._threads),
            "--contextsize", str(self._context_size),
            "--port", str(self._port), "--quiet", "--skiplauncher",
        ]
        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            self._last_error = f"Impossible de lancer koboldcpp: {exc}"
            return False

        for _ in range(60):
            if self._process.poll() is not None:
                self._last_error = f"koboldcpp s'est arrêté (code {self._process.returncode})"
                return False
            try:
                req = urllib.request.Request(f"{self._base_url}/api/v1/model", method="GET")
                with urllib.request.urlopen(req, timeout=2):
                    return True
            except Exception:
                time.sleep(2)
        self._last_error = "koboldcpp timeout au démarrage"
        return False

    def stop_server(self):
        """Arrête le serveur koboldcpp."""
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def _chat(self, messages: list[dict], max_tokens: int = 256) -> tuple[str, int]:
        """Envoie une requête chat completions et retourne (output, duration_ms)."""
        if not self._ensure_server():
            return "", 0
        payload = json.dumps({
            "model": "koboldcpp",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read())
                duration = int((time.monotonic() - start) * 1000)
                return data["choices"][0]["message"]["content"].strip(), duration
        except urllib.error.URLError as exc:
            duration = int((time.monotonic() - start) * 1000)
            self._last_error = f"Erreur API: {exc}"
            return "", duration
        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            self._last_error = str(exc)
            return "", duration


class Gpt4AllProvider(ChatCompletionProvider):
    """Provider pour modèle GGUF local via GPT4All, moteur embarqué dans l'exe.

    Contrairement à koboldcpp et llama-cli, GPT4All n'exige aucun binaire
    installé sur la machine : son moteur est une bibliothèque livrée avec
    l'application. Seul le fichier modèle reste à fournir, ce qui permet
    d'activer l'IA locale en déposant un .gguf, sans autre installation.
    """

    def __init__(self, model_path: Path | None = None, threads: int = 4,
                 context_size: int = 2048, timeout: int = 300):
        self._model_path = model_path
        self._threads = threads
        self._context_size = context_size
        self._timeout = timeout
        self._last_error: str = ""
        self._available_cache: bool | None = None
        self._model = None

    @property
    def name(self) -> str:
        return "gpt4all-local"

    @property
    def available(self) -> bool:
        if self._available_cache is None:
            self._available_cache = self._check_available()
        return self._available_cache

    def _check_available(self) -> bool:
        try:
            import gpt4all  # noqa: F401
        except ImportError:
            self._last_error = "Moteur GPT4All absent de cette installation"
            return False
        if self._model_path is None or not self._model_path.exists():
            self._last_error = "Fichier modèle introuvable"
            return False
        if self._model_path.stat().st_size < 100_000:
            self._last_error = "Fichier modèle trop petit (possiblement corrompu)"
            return False
        return True

    def invalidate_cache(self):
        self._available_cache = None
        self._model = None

    @property
    def last_error(self) -> str:
        return self._last_error

    def _ensure_model(self) -> bool:
        """Charge le modèle au premier usage : l'ouvrir coûte du temps et de la RAM."""
        if self._model is not None:
            return True
        if not self.available:
            return False
        try:
            from gpt4all import GPT4All
            self._model = GPT4All(
                self._model_path.name,
                model_path=str(self._model_path.parent),
                allow_download=False,
                device="cpu",
                n_ctx=self._context_size,
                n_threads=self._threads,
                verbose=False,
            )
        except Exception as exc:
            self._last_error = f"Chargement du modèle impossible : {exc}"
            self._model = None
            return False
        return True

    def unload(self):
        """Libère la mémoire occupée par le modèle."""
        self._model = None

    def _chat(self, messages: list[dict], max_tokens: int = 256) -> tuple[str, int]:
        if not self._ensure_model():
            return "", 0
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        prompt = "\n\n".join(m["content"] for m in messages if m.get("role") != "system")
        start = time.monotonic()
        try:
            with self._model.chat_session(system_prompt=system):
                output = self._model.generate(prompt, max_tokens=max_tokens, temp=0.1)
        except Exception as exc:
            self._last_error = str(exc)
            return "", int((time.monotonic() - start) * 1000)
        duration = int((time.monotonic() - start) * 1000)
        return (output or "").strip(), duration


# ---------------------------------------------------------------------------
# AIProviderRegistry — registre avec cascade et seuil configurable
# ---------------------------------------------------------------------------

_DEFAULT_LLM_THRESHOLD = 80


class AIProviderRegistry:
    """Registre des providers AI disponibles, avec cascade automatique.

    Le LLM n'est sollicité que pour les tâches où le moteur classique
    a une confiance inférieure au seuil configurable.
    """

    def __init__(self, llm_threshold: int = _DEFAULT_LLM_THRESHOLD, mode: str = "auto"):
        self._providers: list[BaseAIProvider] = []
        self._fallback = LocalHeuristicProvider()
        self._providers.append(self._fallback)
        self._llm_threshold = max(0, min(100, llm_threshold))
        self._mode = mode  # "auto", "heuristic_only", "llm_local"

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        if value in ("auto", "heuristic_only", "llm_local"):
            self._mode = value

    @property
    def llm_threshold(self) -> int:
        return self._llm_threshold

    @llm_threshold.setter
    def llm_threshold(self, value: int):
        self._llm_threshold = max(0, min(100, value))

    def register(self, provider: BaseAIProvider):
        self._providers.insert(0, provider)

    @property
    def llm_provider(self) -> BaseAIProvider | None:
        """Retourne le provider LLM s'il est enregistré et disponible."""
        for p in self._providers:
            if isinstance(p, (LlamaCppProvider, ChatCompletionProvider)) and p.available:
                return p
        return None

    @property
    def active_provider(self) -> BaseAIProvider:
        if self._mode == "heuristic_only":
            return self._fallback
        for provider in self._providers:
            if provider.available:
                return provider
        return self._fallback

    @property
    def available_providers(self) -> list[str]:
        return [p.name for p in self._providers if p.available]

    def should_use_llm(self, confidence: float, task: str = "classification") -> bool:
        """Détermine si le LLM doit être sollicité pour cette tâche.

        Le LLM n'est appelé que si :
        - Le mode n'est pas 'heuristic_only'
        - Un provider LLM est disponible
        - La confiance est sous le seuil
        """
        if self._mode == "heuristic_only":
            return False
        if self.llm_provider is None:
            return False
        return confidence < self._llm_threshold

    def summarize(self, text: str, max_words: int = 50) -> AIResponse:
        return self.active_provider.summarize(text, max_words)

    def suggest_classification(self, text: str, filename: str, subjects: dict[str, list[str]], categories: dict[str, list[str]]) -> AIResponse:
        return self.active_provider.suggest_classification(text, filename, subjects, categories)

    def suggest_filename(self, text: str, current_name: str, classification: Classification) -> AIResponse:
        return self.active_provider.suggest_filename(text, current_name, classification)

    def answer_question(self, question: str, context: str) -> AIResponse:
        return self.active_provider.answer_question(question, context)

    def classify_with_fallback(self, text: str, filename: str,
                               subjects: dict[str, list[str]], categories: dict[str, list[str]],
                               heuristic_confidence: float) -> AIResponse | None:
        """Appelle le LLM uniquement si la confiance heuristique est insuffisante.

        Retourne None si le LLM n'est pas nécessaire ou pas disponible.
        En cas d'erreur LLM, retourne None (fallback implicite vers le résultat heuristique).
        """
        if not self.should_use_llm(heuristic_confidence):
            return None
        llm = self.llm_provider
        if llm is None:
            return None
        try:
            response = llm.suggest_classification(text, filename, subjects, categories)
            if response.confidence > 0 and response.suggestions:
                return response
        except Exception as exc:
            logger.warning("LLM classification fallback error: %s", exc)
        return None
