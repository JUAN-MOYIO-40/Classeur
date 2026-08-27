from __future__ import annotations

import hashlib
import json
import os
import re
import time
from difflib import SequenceMatcher
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .semantic import NativeSemanticEngine
from .infrastructure.ocr import LocalPDFOCR
from xml.etree import ElementTree


_PDF_OCR = LocalPDFOCR()

DEFAULT_SUBJECTS = {
    "Mathématiques": ["math", "maths", "mathematique", "algebre", "analyse", "probabilite", "statistique", "geometrie", "integrale", "derivation"],
    "Physique": ["physique", "mecanique", "electromagnetisme", "electrostatique", "electricite", "magnetisme", "thermodynamique", "optique", "newton", "maxwell"],
    "Chimie": ["chimie", "molecule", "molecules", "atome", "reaction chimique", "organique", "inorganique", "ph", "solution"],
    "Biologie": ["biologie", "cellule", "genetique", "ecosysteme", "anatomie", "physiologie", "microbiologie"],
    "Informatique": ["info", "informatique", "python", "java", "sql", "programmation", "algorithmique", "reseau", "web", "base de donnees", "javascript"],
    "Droit": ["droit", "juridique", "constitution", "contrat", "civil", "penal", "jurisprudence", "loi", "code"],
    "Finance": ["finance", "budget", "epargne", "assurance", "impot", "impots", "fiscalite", "comptabilite", "investissement"],
    "Marketing": ["marketing", "marque", "campagne publicitaire", "publicite", "communication commerciale"],
    "Économie": ["eco", "economie", "microeconomie", "macroeconomie", "gestion", "marche", "entreprise"],
    "Langues": ["anglais", "english", "espagnol", "allemand", "langue", "grammaire", "vocabulaire", "translation", "traduction"],
    "Sciences": ["physique", "chimie", "biologie", "geologie", "science", "mecanique", "electricite", "thermodynamique"],
    "Gestion": ["management", "ressources humaines", "rh", "organisation", "entrepreneuriat", "communication"],
}

DEFAULT_DOMAINS = {
    "Sciences": ["physique", "chimie", "biologie", "mathematiques", "maths", "science", "mecanique", "electricite"],
    "Technologies": ["informatique", "programmation", "python", "web", "reseau", "logiciel", "technologie"],
    "Droit et société": ["droit", "juridique", "constitution", "sociologie", "politique"],
    "Économie et gestion": ["economie", "finance", "comptabilite", "gestion", "marketing", "entreprise"],
    "Langues et communication": ["anglais", "espagnol", "allemand", "langue", "communication", "grammaire"],
    "Administratif": ["administratif", "administration", "scolarite", "inscription", "attestation", "releve de notes"],
}

DEFAULT_TOPICS = {
    "Électromagnétisme": ["electromagnetisme", "electromagnetique", "champ electrique", "champ magnetique", "loi de gauss", "maxwell"],
    "Électrostatique": ["electrostatique", "coulomb", "potentiel electrique", "condensateur"],
    "Mécanique": ["mecanique", "cinematique", "dynamique", "newton", "mouvement"],
    "Analyse": ["analyse", "integrale", "integrales", "derivee", "derivation", "suite", "fonction", "limite"],
    "Algèbre": ["algebre", "matrice", "matrices", "vecteur", "espace vectoriel", "equation"],
    "Programmation": ["programmation", "python", "java", "javascript", "algorithmique", "code", "fonction"],
    "Scolarité": ["scolarite", "inscription", "universite", "formation", "etudiant"],
    "Relevé de notes": ["releve de notes", "releve", "resultats", "notes universitaires", "bulletin"],
}

DEFAULT_CATEGORIES = {
    "Administratif": ["administratif", "administration", "inscription", "certificat", "attestation", "bourse", "caf", "universite", "scolarite", "cv", "lettre de motivation", "facture", "identite"],
    "Cours": ["cours", "chapitre", "lecon", "syllabus", "support", "theorie", "lecture", "polycopie", "diaporama"],
    "TD": ["td", "travaux diriges", "exercice", "exercices", "feuille", "serie"],
    "TP": ["tp", "travaux pratiques", "laboratoire", "lab", "manipulation", "compte rendu"],
    "Examen": ["examen", "exam", "partiel", "controle", "concours", "annale", "rattrapage", "qcm", "epreuve", "sujet"],
    "Projet": ["projet", "memoire", "rapport", "presentation", "soutenance", "stage", "these", "proposition"],
    "Notes": ["note", "notes", "resume", "fiche", "revision", "synthese", "flashcard"],
    "Relevé de notes": ["releve de notes", "releve", "resultats universitaires", "bulletin de notes", "transcript"],
    "Lecture": ["article", "livre", "bibliographie", "recherche", "paper", "publication", "revue"],
}

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css", ".xml", ".yml", ".yaml", ".ini", ".log"}
ARCHIVE_TEXT_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".odt"}
KNOWN_CONTENT_EXTENSIONS = TEXT_EXTENSIONS | ARCHIVE_TEXT_EXTENSIONS | {".pdf"}


def fold(text: str) -> str:
    value = unicodedata.normalize("NFKD", text)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def clean_filename(value: str, fallback: str = "Document") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:120] or fallback


def suggest_title(path: Path, content: str) -> str:
    """Construit un titre de fichier lisible à partir du contenu disponible localement."""
    candidates = []
    for raw_line in content.splitlines():
        line = re.sub(r"^[#*•➜\-\s]+", "", raw_line).strip()
        line = re.sub(r"\s+", " ", line)
        if not line or len(line) < 5:
            continue
        if len(line) > 140:
            line = line[:140].rsplit(" ", 1)[0]
        normalized = fold(line)
        if normalized in {"table des matieres", "sommaire", "introduction", "document", "page"}:
            continue
        if sum(char.isalpha() for char in line) >= 5:
            candidates.append(line)
    if candidates:
        return clean_filename(candidates[0], path.stem)
    return clean_filename(path.stem, "Document")


def _read_pdf_with_status(path: Path, max_chars: int = 30000) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        chunks: list[str] = []
        total = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            if not text:
                continue
            remaining = max_chars - total
            if remaining <= 0:
                break
            chunks.append(text[:remaining])
            total += len(text)
        text = "\n".join(chunks)[:max_chars]
        if text.strip():
            return text, "contenu lu"
        ocr_result = _PDF_OCR.extract(path, max_chars)
        if ocr_result.text:
            return ocr_result.text, ocr_result.status
        return "", ocr_result.status
    except Exception:
        ocr_result = _PDF_OCR.extract(path, max_chars)
        if ocr_result.text:
            return ocr_result.text, ocr_result.status
        return "", "PDF illisible : OCR non concluant"


def _read_pdf(path: Path, max_chars: int = 30000) -> str:
    return _read_pdf_with_status(path, max_chars)[0]


def _read_zip_xml_text(path: Path, prefixes: tuple[str, ...], max_chars: int = 30000) -> str:
    """Extrait le texte visible de quelques formats XML compressés sans dépendance lourde."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.startswith(prefixes) and name.endswith(".xml")]
            chunks: list[str] = []
            total = 0
            for name in names:
                raw = archive.read(name)
                root = ElementTree.fromstring(raw)
                text = " ".join(node.text or "" for node in root.iter() if node.text)
                remaining = max_chars - total
                if remaining <= 0:
                    break
                chunks.append(text[:remaining])
                total += len(text)
            return " ".join(chunks)[:max_chars]
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return ""


def _read_docx(path: Path) -> str:
    return _read_zip_xml_text(path, ("word/",))


def _read_xlsx(path: Path) -> str:
    return _read_zip_xml_text(path, ("xl/worksheets/", "xl/sharedStrings.xml", "xl/workbook.xml"))


def _read_pptx(path: Path) -> str:
    return _read_zip_xml_text(path, ("ppt/slides/", "ppt/notesSlides/", "ppt/presentation.xml"))


def _read_odt(path: Path) -> str:
    return _read_zip_xml_text(path, ("content.xml", "meta.xml"))


def read_content_details(path: Path, max_chars: int = 30000) -> tuple[str, str]:
    extension = path.suffix.lower()
    if extension in TEXT_EXTENSIONS:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
            return text, "contenu lu" if text.strip() else "contenu vide"
        except OSError:
            return "", "contenu absent ou illisible"
    if extension == ".pdf":
        return _read_pdf_with_status(path, max_chars)
    readers = {".docx": _read_docx, ".xlsx": _read_xlsx, ".pptx": _read_pptx, ".odt": _read_odt}
    reader = readers.get(extension)
    if reader is not None:
        try:
            text = reader(path)[:max_chars]
            return text, "contenu lu" if text.strip() else "contenu absent ou illisible"
        except OSError:
            return "", "contenu absent ou illisible"
    return "", "format non pris en charge"


def read_content(path: Path, max_chars: int = 30000) -> str:
    return read_content_details(path, max_chars)[0]


@dataclass
class Classification:
    subject: str
    category: str
    confidence: int
    reason: str
    extracted_preview: str = ""
    title: str = ""
    year: str = ""
    domain: str = ""
    topic: str = ""
    hierarchy: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    needs_review: bool = False
    content_status: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class LocalClassifier:
    """Classificateur déterministe et privé : le contenu reste sur l'ordinateur."""

    def __init__(self, subjects: dict[str, list[str]] | None = None, categories: dict[str, list[str]] | None = None, domains: dict[str, list[str]] | None = None, topics: dict[str, list[str]] | None = None):
        self.subjects = subjects or DEFAULT_SUBJECTS
        self.categories = categories or DEFAULT_CATEGORIES
        self.domains = domains or DEFAULT_DOMAINS
        self.topics = topics or DEFAULT_TOPICS
        self.semantic = NativeSemanticEngine()

    @classmethod
    def from_json(cls, path: Path) -> "LocalClassifier":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(data.get("subjects") or DEFAULT_SUBJECTS, data.get("categories") or DEFAULT_CATEGORIES, data.get("domains") or DEFAULT_DOMAINS, data.get("topics") or DEFAULT_TOPICS)
        except (OSError, json.JSONDecodeError):
            return cls()

    def save_json(self, path: Path) -> None:
        payload = json.dumps({"subjects": self.subjects, "categories": self.categories, "domains": self.domains, "topics": self.topics}, ensure_ascii=False, indent=2)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @property
    def rules_version(self) -> str:
        payload = json.dumps({"subjects": self.subjects, "categories": self.categories, "domains": self.domains, "topics": self.topics}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def _score(self, text: str, rules: dict[str, list[str]]) -> tuple[str, int, list[str]]:
        normalized = fold(text)
        candidate_tokens = set(normalized.split()[:600])
        best_name, best_score, best_hits = "", 0, []
        for name, keywords in rules.items():
            hits = []
            score = 0
            for keyword in keywords:
                key = fold(keyword)
                if not key:
                    continue
                occurrences = len(re.findall(r"(?<!\w)" + re.escape(key) + r"(?!\w)", normalized))
                if occurrences:
                    hits.append(keyword)
                    score += min(occurrences, 4) * (4 if " " in key else 2)
                elif score == 0 and " " not in key and len(key) >= 5:
                    similarity = max((SequenceMatcher(None, key, token).ratio() for token in candidate_tokens), default=0.0)
                    if similarity >= 0.91:
                        hits.append(f"{keyword}~")
                        score += 1
            if score > best_score:
                best_name, best_score, best_hits = name, score, hits
        return best_name, best_score, best_hits

    @staticmethod
    def _year_from(text: str) -> str:
        # Les champs d’état civil et d’identité ne décrivent pas la période du document.
        safe_lines = []
        personal_markers = ("date de naissance", "lieu de naissance", "né le", "nee le", "date d expiration", "date d'expiration")
        for line in text.splitlines():
            if any(marker in fold(line) for marker in personal_markers):
                continue
            safe_lines.append(line)
        normalized = fold("\n".join(safe_lines))
        match = re.search(r"(?<!\d)(20\d{2})\s*[-_/ ]\s*(20\d{2})(?!\d)", normalized)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
        match = re.search(r"\b(?:annee|year)\s*([1-5])\b", normalized)
        if match:
            return f"Année {match.group(1)}"
        match = re.search(r"\b([1-5])(?:ere|e|er|eme|st|nd|rd|th)\s*(?:annee|year)\b", normalized)
        if match:
            return f"Année {match.group(1)}"
        match = re.search(r"\bl\s*([1-5])\b", normalized)
        if match:
            return f"Année {match.group(1)}"
        words = {"premiere": "1", "premier": "1", "deuxieme": "2", "seconde": "2", "troisieme": "3"}
        for word, number in words.items():
            if re.search(rf"\b{word}\s+annee\b", normalized):
                return f"Année {number}"
        match = re.search(r"(?<!\d)(20\d{2})(?!\d)", normalized)
        return match.group(1) if match else ""

    def _best_label(self, text: str, rules: dict[str, list[str]]) -> tuple[str, int, list[str]]:
        return self._score(text, rules)

    def classify(self, path: Path, content: str | None = None, extraction_status: str | None = None) -> Classification:
        # Le chemin est inclus : un fichier présent dans un dossier « Economie » bénéficie de ce contexte.
        context = " ".join([path.stem, *path.parts[-4:]])
        if content is None or extraction_status is None:
            content, extraction_status = read_content_details(path)
        context += " " + content
        subject, subject_score, subject_hits = self._score(context, self.subjects)
        category, category_score, category_hits = self._score(context, self.categories)
        domain, domain_score, domain_hits = self._best_label(context, self.domains)
        topic, topic_score, topic_hits = self._best_label(context, self.topics)
        year = self._year_from(context)
        if subject_score < 2:
            semantic_subject, semantic_score, semantic_hits = self.semantic.predict(context, self.subjects)
            if semantic_subject and semantic_score >= 0.18:
                subject, subject_score, subject_hits = semantic_subject, max(subject_score, round(semantic_score * 10)), semantic_hits or ["analyse sémantique locale"]
        if category_score < 2:
            semantic_category, semantic_score, semantic_hits = self.semantic.predict(context, self.categories)
            if semantic_category and semantic_score >= 0.18:
                category, category_score, category_hits = semantic_category, max(category_score, round(semantic_score * 10)), semantic_hits or ["analyse sémantique locale"]
        if subject_score < 2 and domain and domain_score >= 2:
            subject = subject or domain
        subject = subject or "À trier"
        category = category or "Autre"
        if category == "Administratif" and category_score >= 2 and subject_score <= 2:
            subject = "À trier"
            subject_score = 0
        confidence = min(99, 40 + subject_score * 7 + category_score * 7)
        alternatives: list[str] = []
        ranked_subjects = sorted(
            ((name, self._score(context, {name: keywords})[1]) for name, keywords in self.subjects.items()),
            key=lambda pair: pair[1],
            reverse=True,
        )
        for label, score in ranked_subjects[:3]:
            if label != subject and score >= max(1, subject_score - 1):
                alternatives.append(label)
        needs_review = bool(confidence < 62 or (alternatives and subject_score <= 2) or subject == "À trier")
        if subject == "À trier" and category == "Autre":
            confidence = 18
        if content:
            confidence = min(99, confidence + 5)
        reasons = []
        if subject_hits:
            reasons.append("matière : " + ", ".join(subject_hits[:4]))
        if category_hits:
            reasons.append("nature : " + ", ".join(category_hits[:4]))
        if domain_hits:
            reasons.append("domaine : " + ", ".join(domain_hits[:3]))
        if topic_hits:
            reasons.append("thème : " + ", ".join(topic_hits[:3]))
        if year:
            reasons.append("période : " + year)
        if not reasons:
            reasons.append("aucun mot-clé reconnu")
        if content:
            reasons.append(f"{extraction_status} : {path.suffix.lower() or 'fichier texte'}")
        else:
            reasons.append(extraction_status + " : analyse limitée au nom et au chemin")
        title = suggest_title(path, content)
        selected_topic = topic if topic_score >= 2 else ""
        hierarchy = tuple(part for part in (year, domain, subject, selected_topic, category) if part and part not in {"À trier", "Autre"})
        if needs_review:
            reasons.append("validation recommandée")
        content_status = extraction_status
        return Classification(subject, category, confidence, "; ".join(reasons), content[:500].replace("\n", " "), title, year, domain, selected_topic, hierarchy, tuple(alternatives), needs_review, content_status)

    def categories_for(self) -> Iterable[str]:
        return [*self.categories.keys(), "Autre"]

    def subjects_for(self) -> Iterable[str]:
        return [*self.subjects.keys(), "À trier"]


def write_default_rules(path: Path) -> None:
    LocalClassifier().save_json(path)


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("regles.json")
    write_default_rules(target)
    print(target)
