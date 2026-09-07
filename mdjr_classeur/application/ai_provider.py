from __future__ import annotations

import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..classifier import Classification, fold
from ..semantic import NativeSemanticEngine


@dataclass(frozen=True)
class AIResponse:
    text: str
    confidence: float
    provider: str
    suggestions: dict[str, str] = field(default_factory=dict)


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


class LlamaCppProvider(BaseAIProvider):
    """Provider pour modèle GGUF local via llama.cpp / llama-cli.

    Nécessite :
    - llama-cli ou llama-server installé et accessible dans le PATH
    - Un fichier modèle .gguf téléchargé localement
    - Au moins 8 Go de RAM libres pour un modèle Q4_K_M de 3-7B paramètres

    Ce provider est optionnel. L'application fonctionne parfaitement sans lui.
    """

    def __init__(self, model_path: Path | None = None, cli_name: str = "llama-cli"):
        self._model_path = model_path
        self._cli_name = cli_name
        self._max_tokens = 256
        self._timeout = 60

    @property
    def name(self) -> str:
        return "llama-cpp-local"

    @property
    def available(self) -> bool:
        if not shutil.which(self._cli_name):
            return False
        if self._model_path is None or not self._model_path.exists():
            return False
        return True

    def _run_prompt(self, prompt: str) -> str:
        if not self.available:
            return ""
        try:
            result = subprocess.run(
                [self._cli_name, "-m", str(self._model_path), "-p", prompt,
                 "-n", str(self._max_tokens), "--temp", "0.3", "--no-display-prompt"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self._timeout,
            )
            return (result.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    def summarize(self, text: str, max_words: int = 50) -> AIResponse:
        prompt = f"Résume ce texte en {max_words} mots maximum :\n\n{text[:3000]}\n\nRésumé :"
        output = self._run_prompt(prompt)
        return AIResponse(output, 0.7 if output else 0.0, self.name)

    def suggest_classification(self, text: str, filename: str, subjects: dict[str, list[str]], categories: dict[str, list[str]]) -> AIResponse:
        subject_list = ", ".join(subjects.keys())
        category_list = ", ".join(categories.keys())
        prompt = (
            f"Fichier : {filename}\nContenu : {text[:2000]}\n\n"
            f"Matières possibles : {subject_list}\n"
            f"Catégories possibles : {category_list}\n\n"
            f"Réponds uniquement avec le format :\nMatière: ...\nCatégorie: ...\nRaison: ..."
        )
        output = self._run_prompt(prompt)
        suggestions = {}
        for line in output.splitlines():
            if line.lower().startswith("matière:") or line.lower().startswith("matiere:"):
                val = line.split(":", 1)[1].strip()
                if val in subjects:
                    suggestions["subject"] = val
            elif line.lower().startswith("catégorie:") or line.lower().startswith("categorie:"):
                val = line.split(":", 1)[1].strip()
                if val in categories:
                    suggestions["category"] = val
        return AIResponse(output, 0.75 if suggestions else 0.3, self.name, suggestions)

    def suggest_filename(self, text: str, current_name: str, classification: Classification) -> AIResponse:
        prompt = (
            f"Fichier actuel : {current_name}\n"
            f"Matière : {classification.subject}\n"
            f"Catégorie : {classification.category}\n"
            f"Contenu : {text[:2000]}\n\n"
            f"Propose un nom de fichier descriptif (sans extension). Réponds uniquement avec le nom :"
        )
        output = self._run_prompt(prompt)
        output = re.sub(r'[<>:"/\\|?*]', '', output).strip()[:120]
        return AIResponse(output or current_name, 0.65 if output else 0.0, self.name, {"suggested_name": output} if output else {})

    def answer_question(self, question: str, context: str) -> AIResponse:
        prompt = f"Contexte :\n{context[:3000]}\n\nQuestion : {question}\n\nRéponse :"
        output = self._run_prompt(prompt)
        return AIResponse(output, 0.7 if output else 0.0, self.name)


class AIProviderRegistry:
    """Registre des providers AI disponibles, avec cascade automatique."""

    def __init__(self):
        self._providers: list[BaseAIProvider] = []
        self._fallback = LocalHeuristicProvider()
        self._providers.append(self._fallback)

    def register(self, provider: BaseAIProvider):
        self._providers.insert(0, provider)

    @property
    def active_provider(self) -> BaseAIProvider:
        for provider in self._providers:
            if provider.available:
                return provider
        return self._fallback

    @property
    def available_providers(self) -> list[str]:
        return [p.name for p in self._providers if p.available]

    def summarize(self, text: str, max_words: int = 50) -> AIResponse:
        return self.active_provider.summarize(text, max_words)

    def suggest_classification(self, text: str, filename: str, subjects: dict[str, list[str]], categories: dict[str, list[str]]) -> AIResponse:
        return self.active_provider.suggest_classification(text, filename, subjects, categories)

    def suggest_filename(self, text: str, current_name: str, classification: Classification) -> AIResponse:
        return self.active_provider.suggest_filename(text, current_name, classification)

    def answer_question(self, question: str, context: str) -> AIResponse:
        return self.active_provider.answer_question(question, context)
