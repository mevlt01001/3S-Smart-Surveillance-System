"""
Runtime data locations and crash-safe JSON persistence helpers.

All mutable state (camera / rule / event databases, settings, the anomaly journal,
recorded clips, incident snapshots and change-detection references) lives under
DATA_DIR. It defaults to this package directory so existing installations keep
working unchanged; set AEGIS_DATA_DIR to relocate it (e.g. for isolated test runs).
"""

import json
import os
import threading
import time
from typing import Any

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.getenv("AEGIS_DATA_DIR") or BACKEND_DIR)
os.makedirs(DATA_DIR, exist_ok=True)


# Set when the server starts shutting down: every long-lived loop (video streams, event
# streams, worker threads) checks it so the process exits promptly instead of lingering.
SHUTTING_DOWN = threading.Event()

_instance_lock_handle = None


def acquire_instance_lock(wait_sec: float = 20.0) -> None:
    """
    Guarantees a single backend process per data directory.

    The databases are plain JSON files rewritten from memory. Two processes on the same
    directory (e.g. an old instance that has not finished shutting down yet) would silently
    overwrite each other's journal entries and settings. A restarting instance waits here
    until its predecessor is gone; a genuine second instance fails with a clear message.
    """
    global _instance_lock_handle
    if _instance_lock_handle is not None:
        return
    try:
        import fcntl
    except ImportError:  # non-POSIX platform: no locking available
        return
    try:
        wait_sec = float(os.getenv("AEGIS_LOCK_WAIT_SEC", wait_sec))
    except ValueError:
        pass
    handle = open(os.path.join(DATA_DIR, ".aegis.lock"), "a+")
    deadline = time.time() + wait_sec
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= deadline:
                handle.close()
                raise RuntimeError(
                    f"Bu veri dizinini ({DATA_DIR}) kullanan başka bir AegisVision sunucusu çalışıyor. "
                    "Önce onu durdurun veya AEGIS_DATA_DIR ile farklı bir veri dizini verin."
                )
            time.sleep(0.25)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _instance_lock_handle = handle


def data_path(*parts: str) -> str:
    """Returns an absolute path inside the runtime data directory."""
    return os.path.join(DATA_DIR, *parts)


def atomic_write_json(path: str, obj: Any, indent: int = 2) -> None:
    """
    Writes JSON via a temp file + atomic rename so a crash or a concurrent reader
    never observes a truncated / half-written database file.
    """
    tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=indent, ensure_ascii=False)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
