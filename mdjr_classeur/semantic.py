from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter


def fold(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


class NativeSemanticEngine:
    """Moteur sémantique local compact : n-grammes, fréquence et similarité cosinus.

    Il ne télécharge aucun modèle et ne s'active que pour les classements incertains.
    """

    def __init__(self):
        self._ready = False

    def _ensure_ready(self):
        if not self._ready:
            self._ready = True

    @staticmethod
    def _features(text: str) -> Counter[str]:
        tokens = fold(text).split()
        features = Counter(tokens)
        features.update(f"{left}_{right}" for left, right in zip(tokens, tokens[1:]))
        return features

    @staticmethod
    def _cosine(left: Counter[str], right: Counter[str]) -> float:
        common = set(left) & set(right)
        numerator = sum(left[key] * right[key] for key in common)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)

    def predict(self, text: str, rules: dict[str, list[str]]) -> tuple[str, float, list[str]]:
        self._ensure_ready()
        document = self._features(text[:24000])
        best_name, best_score, best_hits = "", 0.0, []
        for name, keywords in rules.items():
            profile_text = " ".join(keywords)
            score = self._cosine(document, self._features(profile_text))
            if score > best_score:
                best_name = name
                best_score = score
                best_hits = [keyword for keyword in keywords if fold(keyword) in fold(text)]
        return best_name, best_score, best_hits[:4]
