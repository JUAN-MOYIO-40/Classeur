"""Détection des capacités matérielles et logicielles de la machine.

Ne fait aucun appel réseau. Tout est local.
"""
from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SystemCapabilities:
    total_ram_mb: int
    available_ram_mb: int
    cpu_name: str
    cpu_count: int
    os_name: str
    has_llama_cli: bool
    llama_cli_path: str
    has_koboldcpp: bool = False
    koboldcpp_path: str = ""


def _ram_info() -> tuple[int, int]:
    """Retourne (total_mb, available_mb). Fonctionne sous Windows, Linux et macOS."""
    try:
        import ctypes
        if platform.system() == "Windows":

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            return int(mem.ullTotalPhys / 1048576), int(mem.ullAvailPhys / 1048576)
    except Exception:
        pass
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        avail = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
        return int(total / 1048576), int(avail / 1048576)
    except Exception:
        pass
    return 0, 0


def _cpu_name() -> str:
    try:
        if platform.system() == "Windows":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            return str(name).strip()
    except Exception:
        pass
    return platform.processor() or "Unknown"


def _find_llama_cli() -> str:
    """Cherche llama-cli dans le PATH, puis dans le dossier runtime de l'application."""
    found = shutil.which("llama-cli")
    if found:
        return found
    config_dir = Path.home() / ".mdjr_classeur"
    runtime_dir = config_dir / "runtime"
    if runtime_dir.is_dir():
        for sub in sorted(runtime_dir.iterdir(), reverse=True):
            candidate = sub / "llama-cli.exe" if platform.system() == "Windows" else sub / "llama-cli"
            if candidate.is_file():
                return str(candidate)
    return ""


def _find_koboldcpp() -> str:
    """Cherche koboldcpp dans le dossier runtime de l'application."""
    config_dir = Path.home() / ".mdjr_classeur"
    runtime_dir = config_dir / "runtime"
    exe_name = "koboldcpp.exe" if platform.system() == "Windows" else "koboldcpp"
    candidate = runtime_dir / exe_name
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("koboldcpp")
    return found or ""


def detect_capabilities() -> SystemCapabilities:
    total, available = _ram_info()
    llama_path = _find_llama_cli()
    kobold_path = _find_koboldcpp()
    return SystemCapabilities(
        total_ram_mb=total,
        available_ram_mb=available,
        cpu_name=_cpu_name(),
        cpu_count=os.cpu_count() or 1,
        os_name=f"{platform.system()} {platform.release()}",
        has_llama_cli=bool(llama_path),
        llama_cli_path=llama_path,
        has_koboldcpp=bool(kobold_path),
        koboldcpp_path=kobold_path,
    )


def find_model_file(models_dir: Path) -> Path:
    """Retourne le modèle GGUF à utiliser dans un dossier.

    Un modèle téléchargé garde son nom d'origine, qui indique sa taille et sa
    quantification. Exiger un renommage en « model.gguf » n'apporte rien et
    revient à demander la même manipulation sur chaque poste : n'importe quel
    .gguf déposé dans le dossier est donc accepté. « model.gguf » reste
    prioritaire pour les installations existantes, et à défaut le plus gros
    fichier est retenu, un modèle partiellement téléchargé étant plus petit
    que celui qu'il est censé remplacer.

    Le chemin retourné quand aucun modèle n'est présent n'existe pas : les
    appelants testent son existence, et l'absence d'IA locale est un cas normal.
    """
    par_defaut = models_dir / "model.gguf"
    if par_defaut.is_file():
        return par_defaut
    try:
        candidats = [p for p in models_dir.glob("*.gguf") if p.is_file()]
    except OSError:
        return par_defaut
    if not candidats:
        return par_defaut
    return max(candidats, key=lambda p: p.stat().st_size)


def model_file_info(model_path: Path) -> dict[str, object] | None:
    """Retourne les informations sur un fichier modèle GGUF, ou None s'il n'existe pas."""
    if not model_path.exists() or not model_path.is_file():
        return None
    try:
        size = model_path.stat().st_size
    except OSError:
        return None
    return {
        "path": str(model_path),
        "name": model_path.stem,
        "size_bytes": size,
        "size_display": _format_size(size),
        "estimated_ram_mb": int(size / 1048576 * 1.6),
    }


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} o"
    if size_bytes < 1048576:
        return f"{size_bytes / 1024:.0f} Ko"
    if size_bytes < 1073741824:
        return f"{size_bytes / 1048576:.1f} Mo"
    return f"{size_bytes / 1073741824:.2f} Go"


def recommend_mode(capabilities: SystemCapabilities, model_path: Path) -> str:
    """Recommande le mode AI optimal pour cette machine.

    Retourne: 'llm_local', 'heuristic_only', ou 'heuristic_recommended'.
    """
    info = model_file_info(model_path)
    has_runtime = capabilities.has_llama_cli or capabilities.has_koboldcpp
    if info is None or not has_runtime:
        return "heuristic_only"
    estimated_ram = info["estimated_ram_mb"]
    if capabilities.total_ram_mb < 6000:
        return "heuristic_recommended"
    if capabilities.available_ram_mb < estimated_ram + 1500:
        return "heuristic_recommended"
    return "llm_local"
