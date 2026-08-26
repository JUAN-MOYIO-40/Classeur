from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..classifier import read_content


@dataclass(frozen=True)
class DocumentIdentity:
    path: Path
    size: int
    sha256: str
    normalized_text_sha256: str | None = None
    text_length: int = 0


class ContentIdentityService:
    """Calcule une identité forte du fichier et une signature textuelle non destructive."""

    TEXT_SIGNATURE_LIMIT = 250_000

    @staticmethod
    def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def normalize_text(text: str) -> str:
        lines = []
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if line:
                lines.append(line)
        return "\n".join(lines).casefold()

    def identify(self, path: Path, content: str | None = None) -> DocumentIdentity | None:
        try:
            stat = path.stat()
            digest = self.sha256_file(path)
            if content is None:
                content = read_content(path, self.TEXT_SIGNATURE_LIMIT)
            normalized = self.normalize_text(content) if content else ""
            # Ne pas appeler une signature partielle une identité sémantique complète.
            normalized_digest = None
            if normalized and len(content) < self.TEXT_SIGNATURE_LIMIT:
                normalized_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            return DocumentIdentity(path.resolve(), stat.st_size, digest, normalized_digest, len(content))
        except (OSError, ValueError):
            return None
