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


def detect_capabilities() -> SystemCapabilities:
    total, available = _ram_info()
    llama_path = shutil.which("llama-cli") or ""
    return SystemCapabilities(
        total_ram_mb=total,
        available_ram_mb=available,
        cpu_name=_cpu_name(),
        cpu_count=os.cpu_count() or 1,
        os_name=f"{platform.system()} {platform.release()}",
        has_llama_cli=bool(llama_path),
        llama_cli_path=llama_path,
    )


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
    if info is None or not capabilities.has_llama_cli:
        return "heuristic_only"
    estimated_ram = info["estimated_ram_mb"]
    if capabilities.total_ram_mb < 6000:
        return "heuristic_recommended"
    if capabilities.available_ram_mb < estimated_ram + 1500:
        return "heuristic_recommended"
    return "llm_local"
