"""
Evidence files of incidents: the MP4 clip and the JPEG snapshot of each event.

Knows the files and nothing about the journal; callers pass in which files are still
referenced when unreferenced ones are to be found.
"""

import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .paths import data_path

logger = logging.getLogger("aegis.evidence")

CLIPS_DIR = data_path("recordings", "clips")
SNAPSHOTS_DIR = data_path("recordings", "snapshots")
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

CLIP_URL_PREFIX = "/api/anomaly/clips/"
SNAPSHOT_URL_PREFIX = "/api/anomaly/snapshots/"

ENCODING_PREFIX = "tmp_"       # a clip carries this prefix until ffmpeg has finished it
MIN_CLIP_BYTES = 1024          # anything smaller is a failed encode
MIN_CLIP_SECONDS = 1.0         # a handful of frames (camera just connected) is not a video
ENCODE_TIMEOUT_SEC = 15.0
MEGABYTE = 1024.0 * 1024.0

JpegFrame = Tuple[float, bytes]  # (capture time, JPEG bytes)


def clip_name(entry_id: str) -> str:
    return f"clip_{entry_id}.mp4"


def clip_url(entry_id: str) -> str:
    return CLIP_URL_PREFIX + clip_name(entry_id)


def clip_path(entry_id: str) -> str:
    return os.path.join(CLIPS_DIR, clip_name(entry_id))


def file_name(url: Optional[str]) -> str:
    """File name inside an evidence URL ("" for none); a "?v=…" cache stamp is ignored."""
    return os.path.basename(str(url or "").split("?")[0])


def footage_seconds(frames: List[JpegFrame]) -> float:
    """Seconds of real footage covered by buffered frames (0 for fewer than two frames)."""
    return max(0.0, frames[-1][0] - frames[0][0]) if len(frames) >= 2 else 0.0


def _remove(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def save_snapshot(entry_id: str, jpeg: Optional[bytes], taken_at: Optional[float] = None) -> Optional[str]:
    """
    Stores the camera frame of an incident and returns its URL (None when there is no frame).
    A live snapshot URL would show what the camera sees now, not the incident.
    """
    if not jpeg:
        return None
    name = f"snap_{entry_id}.jpg"
    final_path = os.path.join(SNAPSHOTS_DIR, name)
    temp_path = f"{final_path}.{threading.get_ident()}.tmp"
    try:
        with open(temp_path, "wb") as file:
            file.write(jpeg)
        os.replace(temp_path, final_path)
    except OSError as exc:
        logger.error("Snapshot of %s could not be saved: %s", entry_id, exc)
        _remove(temp_path)
        return None
    # The stamp makes the browser fetch a replaced snapshot although the name is the same
    return f"{SNAPSHOT_URL_PREFIX}{name}?v={int(taken_at or time.time())}"


def encode_clip(entry_id: str, frames: List[JpegFrame]) -> bool:
    """
    Writes buffered JPEG frames as an H.264 MP4. The frames are piped to ffmpeg without being
    decoded here, and the file gets its final name only once it is complete, so a half-written
    clip is never served. The frame rate comes from the capture times: playback speed matches reality.
    """
    if footage_seconds(frames) <= 0:
        return False
    fps = max(1.0, min(60.0, (len(frames) - 1) / footage_seconds(frames)))
    final_path = clip_path(entry_id)
    temp_path = os.path.join(CLIPS_DIR, ENCODING_PREFIX + clip_name(entry_id))
    command = [
        "ffmpeg", "-y", "-f", "image2pipe", "-vcodec", "mjpeg", "-framerate", f"{fps:.2f}", "-i", "-",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "baseline",
        "-level", "3.1", "-pix_fmt", "yuv420p", "-movflags", "+faststart", temp_path,
    ]
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _, jpeg in frames:
                process.stdin.write(jpeg)
            process.stdin.close()
        except OSError:
            pass  # ffmpeg exited early; its return code tells the rest
        process.wait(timeout=ENCODE_TIMEOUT_SEC)
        if process.returncode == 0 and os.path.getsize(temp_path) >= MIN_CLIP_BYTES:
            os.replace(temp_path, final_path)
            return True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("Clip of %s could not be encoded: %s", entry_id, exc)
    _remove(temp_path)
    return False


def delete_files_of(entry: Dict[str, Any]) -> None:
    """Removes the clip and the snapshot an event points to."""
    if str(entry.get("clip_url") or "").startswith(CLIP_URL_PREFIX):
        _remove(os.path.join(CLIPS_DIR, file_name(entry["clip_url"])))
    if str(entry.get("snapshot_url") or "").startswith(SNAPSHOT_URL_PREFIX):
        _remove(os.path.join(SNAPSHOTS_DIR, file_name(entry["snapshot_url"])))


def _finished_clips() -> List[os.DirEntry]:
    return [item for item in os.scandir(CLIPS_DIR)
            if item.name.endswith(".mp4") and not item.name.startswith(ENCODING_PREFIX)]


def _snapshots() -> List[os.DirEntry]:
    return [item for item in os.scandir(SNAPSHOTS_DIR) if item.name.endswith(".jpg")]


def enforce_quota(max_clips: int, max_megabytes: float) -> List[str]:
    """Deletes the oldest clips until both limits hold. Returns the names of the deleted clips."""
    try:
        clips = sorted(((item.stat().st_mtime, item.stat().st_size, item) for item in _finished_clips()),
                       key=lambda clip: clip[0])
    except OSError as exc:
        logger.error("Clip directory could not be read: %s", exc)
        return []
    total_bytes = sum(size for _, size, _ in clips)
    deleted = []
    while clips and (len(clips) > max_clips or total_bytes > max_megabytes * MEGABYTE):
        _, size, oldest = clips.pop(0)
        total_bytes -= size
        if _remove(oldest.path):
            deleted.append(oldest.name)
    return deleted


def usage(referenced_clips: Set[str], referenced_snapshots: Set[str]) -> Dict[str, Any]:
    """Disk usage of the evidence, with the files that no event refers to counted separately."""
    stats = {"clip_count": 0, "clip_mb": 0.0, "orphan_clip_count": 0, "orphan_clip_mb": 0.0,
             "snapshot_count": 0, "snapshot_mb": 0.0, "orphan_snapshot_count": 0}
    try:
        for clip in _finished_clips():
            megabytes = clip.stat().st_size / MEGABYTE
            stats["clip_count"] += 1
            stats["clip_mb"] += megabytes
            if clip.name not in referenced_clips:
                stats["orphan_clip_count"] += 1
                stats["orphan_clip_mb"] += megabytes
        for snapshot in _snapshots():
            stats["snapshot_count"] += 1
            stats["snapshot_mb"] += snapshot.stat().st_size / MEGABYTE
            if snapshot.name not in referenced_snapshots:
                stats["orphan_snapshot_count"] += 1
    except OSError as exc:
        logger.error("Evidence directories could not be read: %s", exc)
    for key in ("clip_mb", "orphan_clip_mb"):
        stats[key] = round(stats[key], 1)
    stats["snapshot_mb"] = round(stats["snapshot_mb"], 2)
    return stats


def _delete_unreferenced(files: Iterable[os.DirEntry], referenced: Set[str], min_age_sec: float) -> Tuple[int, int]:
    """Returns (files deleted, bytes freed). Recent files are skipped: they may still be in the making."""
    now = time.time()
    count = freed = 0
    for item in files:
        if item.name in referenced:
            continue
        info = item.stat()
        if now - info.st_mtime >= min_age_sec and _remove(item.path):
            count += 1
            freed += info.st_size
    return count, freed


def delete_unreferenced_clips(referenced: Set[str], min_age_sec: float = 120.0) -> Tuple[int, float]:
    """Deletes clips that no event refers to. Returns (clips deleted, megabytes freed)."""
    try:
        count, freed = _delete_unreferenced(_finished_clips(), referenced, min_age_sec)
    except OSError as exc:
        logger.error("Unreferenced clips could not be cleaned up: %s", exc)
        return 0, 0.0
    return count, round(freed / MEGABYTE, 1)


def delete_unreferenced_snapshots(referenced: Set[str], min_age_sec: float = 120.0) -> int:
    """Deletes snapshots that no event refers to. Returns how many were deleted."""
    try:
        return _delete_unreferenced(_snapshots(), referenced, min_age_sec)[0]
    except OSError as exc:
        logger.error("Unreferenced snapshots could not be cleaned up: %s", exc)
        return 0
