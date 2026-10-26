"""Memory Management & Hardware Resource Profiling Subsystem.

Provides dynamic RAM detection, low-memory embedded router profiling (512 MB target),
automatic SQLite PRAGMA scaling, and heap memory trimming via glibc malloc_trim.
"""
from __future__ import annotations

import gc
import logging
import os
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("nmb.common.memory")


def get_total_ram_mb() -> int:
    """Read total physical host RAM in megabytes."""
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) // 1024
    except Exception:
        pass

    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (pages * page_size) // (1024 * 1024)
    except Exception:
        pass

    return 1024  # Fallback default if completely undetectable


def get_available_ram_mb() -> int:
    """Read available (unallocated + reclaimable) RAM in megabytes."""
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) // 1024
    except Exception:
        pass
    return get_total_ram_mb() // 2


def is_low_memory_system() -> bool:
    """Return True if system has <= 768 MB RAM (e.g. 512MB / 256MB router or Pi Zero)."""
    # Allow manual override via environment variable
    env_override = os.environ.get("NMB_LOW_MEMORY")
    if env_override is not None:
        return env_override.strip() in ("1", "true", "yes", "on")
    return get_total_ram_mb() <= 768


def get_effective_memory_profile(configured_profile: str = "auto") -> str:
    """Determine active memory profile: 'low', 'standard', or 'performance'.
    
    Profiles:
      - 'low': For 512 MB (or 256 MB) embedded routers and low-resource devices.
               Reduces SQLite cache to 4MB, mmap to 16MB, caps socket buffers to 4MB,
               streams HTTP chunks, and bounds tmpfs DB size.
      - 'standard': For 1 GB - 2 GB devices (e.g. Raspberry Pi 3/4).
      - 'performance': For 4 GB+ high-throughput servers / workstations.
    """
    clean_prof = (configured_profile or "auto").lower().strip()
    if clean_prof in ("low", "embedded", "router"):
        return "low"
    if clean_prof in ("perf", "performance", "high"):
        return "performance"
    if clean_prof in ("std", "standard", "medium"):
        return "standard"

    # 'auto': calculate dynamically based on total host RAM
    total_ram = get_total_ram_mb()
    if total_ram <= 768:
        return "low"
    elif total_ram >= 3500:
        return "performance"
    else:
        return "standard"


def trim_process_memory() -> None:
    """Force Python garbage collection and release unused glibc heap arenas back to OS.
    
    Calls glibc malloc_trim(0) which instructs the allocator to release free top-of-heap
    memory and empty malloc arenas directly back to the Linux kernel via brk/madvise.
    Critical for embedded routers with 512MB RAM to prevent memory fragmentation bloat.
    """
    gc.collect()
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        if hasattr(libc, "malloc_trim"):
            libc.malloc_trim(0)
    except Exception:
        pass


def get_sqlite_pragmas(profile: str = "auto") -> List[str]:
    """Return tuned SQLite PRAGMAs tailored for the active memory profile."""
    eff = get_effective_memory_profile(profile)
    if eff == "low":
        # Tuned for 512 MB embedded routers
        return [
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA temp_store=FILE",            # Save RAM by using tmpfs files for temp sorts
            "PRAGMA cache_size=-4096",           # 4 MiB RAM page cache per connection (instead of 64MB)
            "PRAGMA mmap_size=16777216",         # 16 MiB zero-copy memory-mapped I/O (instead of 256MB)
            "PRAGMA wal_autocheckpoint=500",     # Checkpoint frequently to keep WAL file tiny
            "PRAGMA journal_size_limit=8388608", # 8 MiB WAL maximum file ceiling
            "PRAGMA busy_timeout=5000",
        ]
    elif eff == "performance":
        return [
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-65536",          # 64 MiB RAM page cache
            "PRAGMA mmap_size=268435456",        # 256 MiB zero-copy memory-mapped I/O
            "PRAGMA wal_autocheckpoint=2000",
            "PRAGMA journal_size_limit=33554432",# 32 MiB WAL maximum file ceiling
            "PRAGMA busy_timeout=5000",
        ]
    else:  # standard (1GB - 2GB RAM)
        return [
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-16384",          # 16 MiB RAM page cache
            "PRAGMA mmap_size=67108864",         # 64 MiB memory-mapped I/O
            "PRAGMA wal_autocheckpoint=1000",
            "PRAGMA journal_size_limit=16777216",# 16 MiB WAL file ceiling
            "PRAGMA busy_timeout=5000",
        ]


def get_db_live_size_cap(profile: str = "auto") -> int:
    """Return maximum live DB size cap in bytes for tmpfs protection."""
    eff = get_effective_memory_profile(profile)
    if eff == "low":
        return int(os.environ.get("NMB_DB_SIZE_CAP", 48 * 1024 * 1024))   # 48 MB cap for 512MB RAM
    elif eff == "performance":
        return int(os.environ.get("NMB_DB_SIZE_CAP", 192 * 1024 * 1024))  # 192 MB cap
    else:
        return int(os.environ.get("NMB_DB_SIZE_CAP", 96 * 1024 * 1024))   # 96 MB cap
