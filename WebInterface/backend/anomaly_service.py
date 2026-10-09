"""
Anomaly service: scores every live camera for unusual movement and turns what it sees
into events.

A background thread feeds the last frames of each camera to the anomaly model on the
analysis server (Triton), a few times per second and several cameras per request. A score
above the warning threshold opens an incident; when the camera has been calm for a while
the incident is closed, its video clip is cut from the camera's frame buffer and a short
written summary is requested. Rule violations found by the live detection service are
recorded through the same path.

Storage of events lives in `event_journal`, their files in `evidence_store`.
"""

import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Zero-copy Triton client: a 4-camera batch is 38 MB per request and the generic
# tritonclient spends ~75 ms of GIL-holding CPU per call just copying it.
from Object_Detection.triton_fast_client import TritonFastClient

from . import evidence_store
from .camera_service import camera_service
from .event_journal import event_journal
from .paths import SHUTTING_DOWN
from .settings_service import settings_service

try:
    from Rule_Generator_LLM import vlm_summarizer
except Exception:  # the summarizer's dependencies are optional
    vlm_summarizer = None

logger = logging.getLogger("aegis.anomaly")

MODEL_INPUT_SIZE = 224          # the model takes [3, clip_len, 224, 224] clips
MAX_BATCH_SIZE = 8
CYCLE_SEC = 0.25                # every camera is scored about four times per second
SCORE_FRESH_SEC = 10.0          # an older score is not shown: the engine stopped refreshing it
RULE_CLIP_SEC = 5.0             # footage kept before a rule violation
RULE_VIOLATION_SCORE = 75.0
RULE_QUIET_SEC = 10.0           # a rule violation is over when the rule was not violated for this long
CLIP_WAIT_SEC = 4.0             # a manual summary waits this long for a clip that is still encoding

Incident = Dict[str, Any]


def _clock(timestamp: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(timestamp))


# Title of a movement alarm. The detector only knows that the movement is unusual, not what
# it is: the interface shows the headline of the summary instead as soon as there is one.
UNUSUAL_MOVEMENT = "Olağandışı hareket"


class AnomalyService:
    def __init__(self):
        self.client: Optional[TritonFastClient] = None
        self.model_ready = False
        self.summarizer = vlm_summarizer.VLMSummarizer() if vlm_summarizer else None
        if self.summarizer and not self.summarizer.available:
            self.summarizer = None  # no credentials: events are simply recorded without a summary

        # Measured inference time per camera; None until the first forward pass ran
        self.last_latency_ms: Optional[float] = None
        self.last_inference_ts = 0.0

        self._load_settings()
        self.camera_scores: Dict[str, Dict[str, Any]] = {}   # camera id -> latest score
        self._incidents: Dict[str, Incident] = {}            # camera id -> incident in progress
        # (camera id, rule id) -> rule violation in progress; written by the rule engine's thread
        self._rule_incidents: Dict[Tuple[str, str], Incident] = {}
        self._rule_lock = threading.Lock()
        self._scored_frame: Dict[str, int] = {}              # camera id -> last frame number scored
        self._batch: Optional[np.ndarray] = None

        self.running = True
        threading.Thread(target=self._run, daemon=True, name="AnomalyWorker").start()

    # ---------------------------------------------------------------- settings
    def _load_settings(self) -> None:
        settings = settings_service.get_all()
        anomaly, recording = settings.get("anomaly", {}), settings.get("recording", {})

        self.triton_url = anomaly.get("triton_url", "localhost:8000")
        self.model_name = anomaly.get("model_name", "anomaly_detector")
        self.clip_len = int(anomaly.get("clip_len", 16))
        self.threshold_normal = float(anomaly.get("threshold_normal", 25.0))
        self.threshold_warning = float(anomaly.get("threshold_warning", 50.0))
        self.batch_size = max(1, min(MAX_BATCH_SIZE, int(anomaly.get("batch_size", 4))))
        self.analysis_enabled = bool(anomaly.get("continuous_pipeline", True))

        self.auto_record_clips = bool(recording.get("auto_record_clips", True))
        self.tolerance_sec = float(recording.get("tolerance_sec", 2.0))
        self.padding_sec = float(recording.get("padding_sec", 1.5))
        self.max_clip_duration_sec = float(recording.get("max_clip_duration_sec", 60.0))
        self.max_stored_clips = int(recording.get("max_stored_clips", 500))
        self.max_storage_mb = float(recording.get("max_storage_mb", 1000))

        # Frames kept in memory per camera: the longest clip that can be cut (maximum
        # duration, both paddings, merge tolerance) plus a safety margin.
        camera_service.set_clip_window(self.max_clip_duration_sec + 2.0 * self.padding_sec + self.tolerance_sec + 8.0)

    def reload_settings(self, _settings: Optional[Dict[str, Any]] = None) -> None:
        """Applies changed settings to the running engine."""
        endpoint = (self.triton_url, self.model_name)
        self._load_settings()
        if (self.triton_url, self.model_name) != endpoint:
            self.client = None
            self.model_ready = False
        if not self.analysis_enabled:
            self.camera_scores.clear()
            self._scored_frame.clear()

    def classify(self, score: float) -> Tuple[str, str]:
        """(tier, label) of a score under the configured thresholds."""
        if score >= self.threshold_warning:
            return "critical", "Kritik Anomali"
        if score >= self.threshold_normal:
            return "warning", "Şüpheli / Dikkat"
        return "normal", "Normal / Güvenli"

    # ---------------------------------------------------------- inference loop
    def _connect(self) -> bool:
        try:
            self.client = self.client or TritonFastClient(self.triton_url, timeout=6.0, connect_timeout=2.0)
            self.model_ready = self.client.is_server_live() and self.client.is_model_ready(self.model_name)
        except Exception:
            self.client = None
            self.model_ready = False
        return self.model_ready

    def _run(self) -> None:
        time.sleep(1.5)  # let the camera workers connect
        while self.running and not SHUTTING_DOWN.is_set():
            started = time.perf_counter()
            try:
                # First, so that it also happens while analysis is paused or the server is down
                self._close_silent_incidents()
                if not self.analysis_enabled:
                    time.sleep(0.5)
                    continue
                cameras = camera_service.get_all()
                if not cameras:
                    time.sleep(0.5)
                    continue
                if not self.model_ready and not self._connect():
                    time.sleep(2.0)
                    continue
                self._score(cameras)
                time.sleep(max(0.0, CYCLE_SEC - (time.perf_counter() - started)))
            except Exception as exc:
                logger.error("Anomaly loop error: %s", exc)
                time.sleep(1.0)

    def _pending_clips(self, cameras: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], List[np.ndarray], int]]:
        """(camera, its last `clip_len` model-sized frames, frame number) for every camera with a new frame."""
        known = {camera.get("id") for camera in cameras}
        for removed in [camera_id for camera_id in self.camera_scores if camera_id not in known]:
            self._forget(removed)

        pending = []
        for camera in cameras:
            camera_id = camera.get("id")
            worker = camera_service.get_worker(camera_id)
            if worker is None:
                camera_service.get_camera_ai_frames(camera_id, count=1)  # starts the worker on first use
                continue
            _, frame_number, _ = worker.get_frame_info(touch=True)
            if not worker.is_live():
                self._forget(camera_id)  # scoring a frozen frame would report a fake "normal"
                continue
            if self._scored_frame.get(camera_id) == frame_number:
                continue
            frames = worker.get_ai_frames(count=self.clip_len, touch=False)
            if frames:
                # A stream that just connected has fewer frames: repeat the oldest one
                frames = [frames[0]] * (self.clip_len - len(frames)) + frames
                pending.append((camera, frames[-self.clip_len:], frame_number))
        return pending

    def _forget(self, camera_id: str) -> None:
        self.camera_scores.pop(camera_id, None)
        self._scored_frame.pop(camera_id, None)

    def _score(self, cameras: List[Dict[str, Any]]) -> None:
        shape = (self.batch_size, 3, self.clip_len, MODEL_INPUT_SIZE, MODEL_INPUT_SIZE)
        if self._batch is None or self._batch.shape != shape:
            self._batch = np.empty(shape, dtype=np.float32)

        pending = self._pending_clips(cameras)
        for start in range(0, len(pending), self.batch_size):
            if not self.running:
                return
            chunk = pending[start:start + self.batch_size]
            batch = self._batch[:len(chunk)]
            for index, (_, frames, _) in enumerate(chunk):
                # [T, H, W, 3] uint8 -> [3, T, H, W] float32 in [0, 1], written straight into
                # the reusable batch buffer (single pass, no temporaries)
                np.divide(np.stack(frames).transpose(3, 0, 1, 2), np.float32(255.0), out=batch[index], dtype=np.float32)

            try:
                request_started = time.perf_counter()
                logits = self.client.infer(self.model_name, {"video_segment": batch}, ["logits"])["logits"]
                latency_ms = (time.perf_counter() - request_started) * 1000.0 / len(chunk)
            except Exception as exc:
                logger.error("Anomaly inference failed: %s", exc)
                self.model_ready = False
                if self.client:
                    self.client.close()
                return

            now = time.time()
            self.last_inference_ts = now
            previous = self.last_latency_ms
            self.last_latency_ms = round(latency_ms if previous is None else 0.25 * latency_ms + 0.75 * previous, 1)
            probabilities = 1.0 / (1.0 + np.exp(-logits[:, 0]))
            for (camera, _, frame_number), probability in zip(chunk, probabilities):
                self._scored_frame[camera["id"]] = frame_number
                self._apply_score(camera, round(float(probability) * 100.0, 1), now)
            time.sleep(0.005)  # let the video threads run between batches

    def _apply_score(self, camera: Dict[str, Any], raw_score: float, now: float) -> None:
        camera_id = camera["id"]
        previous = self.camera_scores.get(camera_id, {}).get("score", raw_score)
        # An alarm shows at once; a calm scene is smoothed slightly so the score does not flicker
        score = raw_score if raw_score >= self.threshold_normal else round(0.15 * previous + 0.85 * raw_score, 1)
        tier, label = self.classify(score)
        self.camera_scores[camera_id] = {"score": score, "tier": tier, "label": label, "timestamp": now}
        self._track_incident(camera_id, camera.get("name") or camera.get("ip") or camera_id, score, tier, label, now)

    # --------------------------------------------------------------- incidents
    def _track_incident(self, camera_id: str, camera_name: str, score: float, tier: str, label: str, now: float) -> None:
        """
        An incident starts when the score reaches the warning threshold, survives pauses
        shorter than the merge tolerance, and is split once it exceeds the maximum clip length.
        """
        incident = self._incidents.get(camera_id)
        if score < self.threshold_normal:
            if incident and now - incident["last_active_ts"] > self.tolerance_sec:
                self._close_incident(camera_id)
            return

        if incident is None:
            entry = self._new_entry("anom", camera_id, camera_name, now, score, tier, label, UNUSUAL_MOVEMENT, is_ongoing=True, end_time_str="")
            event_journal.add(entry, self.max_stored_clips)
            self._incidents[camera_id] = {
                "id": entry["id"], "camera_name": camera_name, "start_ts": now, "last_active_ts": now,
                "peak_ts": now, "peak_score": score, "peak_tier": tier, "label": label,
            }
            return

        incident["last_active_ts"] = now
        if score > incident["peak_score"]:
            incident.update(peak_ts=now, peak_score=score, peak_tier=tier, label=label)
        if now - incident["start_ts"] >= self.max_clip_duration_sec:
            self._close_incident(camera_id)

    def _close_silent_incidents(self) -> None:
        now = time.time()
        for camera_id, incident in list(self._incidents.items()):
            if now - incident["last_active_ts"] > self.tolerance_sec + 0.5:
                self._close_incident(camera_id)
        with self._rule_lock:
            finished = [key for key, incident in self._rule_incidents.items()
                        if now - incident["last_active_ts"] > RULE_QUIET_SEC]
            closed = [self._rule_incidents.pop(key) for key in finished]
        for incident in closed:
            event_journal.update(
                incident["id"],
                is_ongoing=False,
                end_time_str=_clock(incident["last_active_ts"]),
                incident_sec=round(incident["last_active_ts"] - incident["start_ts"], 1),
            )

    def _close_incident(self, camera_id: str) -> None:
        """Completes the event of a finished incident: final times, peak snapshot, clip and summary."""
        incident = self._incidents.pop(camera_id)
        entry_id = incident["id"]
        clip_start = max(0.0, incident["start_ts"] - self.padding_sec)
        clip_end = incident["last_active_ts"] + self.padding_sec
        duration_sec = max(1.0, round(clip_end - clip_start, 1))
        frames = (camera_service.get_camera_clip_frames_range(camera_id, start_ts=clip_start, end_ts=clip_end)
                  or camera_service.get_camera_clip_frames(camera_id, duration_sec=duration_sec))
        has_clip = self._worth_a_clip(frames)

        changes = {
            "score": round(incident["peak_score"], 1),
            "tier": incident["peak_tier"],
            "label": incident["label"],
            "start_time_str": _clock(clip_start),
            "peak_time_str": _clock(incident["peak_ts"]),
            "end_time_str": _clock(clip_end),
            "duration_sec": duration_sec,
            "clip_url": evidence_store.clip_url(entry_id) if has_clip else None,
            "is_ongoing": False,
            "ai_status": "generating" if (self.summarizer and frames) else "none",
        }
        # The snapshot taken at the start is replaced by the frame of the peak moment
        peak_snapshot = evidence_store.save_snapshot(
            entry_id, camera_service.get_camera_jpeg_at(camera_id, incident["peak_ts"]), taken_at=incident["peak_ts"]
        )
        if peak_snapshot:
            changes["snapshot_url"] = peak_snapshot
        if event_journal.update(entry_id, **changes) is None:
            # The journal was cleared while the incident was running: nothing to attach evidence to
            evidence_store.delete_files_of({"snapshot_url": peak_snapshot})
            return
        self._process_evidence(entry_id, frames, has_clip)

    def _worth_a_clip(self, frames: List[evidence_store.JpegFrame]) -> bool:
        return self.auto_record_clips and evidence_store.footage_seconds(frames) >= evidence_store.MIN_CLIP_SECONDS

    def _new_entry(self, kind: str, camera_id: str, camera_name: str, now: float, score: float,
                   tier: str, label: str, anomaly_type: str, **fields: Any) -> Dict[str, Any]:
        """A journal entry with the fields every event has; `fields` add to or replace them."""
        entry_id = f"{kind}_{uuid.uuid4().hex[:8]}"
        entry = {
            "id": entry_id,
            "timestamp": now,
            "timestamp_str": _clock(now),
            "date_str": time.strftime("%d.%m.%Y", time.localtime(now)),
            "camera_id": camera_id,
            "camera_name": camera_name,
            "score": round(score, 1),
            "tier": tier,
            "label": label,
            "anomaly_type": anomaly_type,
            "start_time_str": _clock(now),
            "peak_time_str": _clock(now),
            "end_time_str": _clock(now),
            "duration_sec": 0.0,
            "snapshot_url": evidence_store.save_snapshot(entry_id, camera_service.get_camera_jpeg_at(camera_id)),
            "clip_url": None,
            "is_ongoing": False,
            "ai_status": "none",
            "ai_summary": None,
            "message": f"{camera_name}: {anomaly_type}",
        }
        entry.update(fields)
        return entry

    # ---------------------------------------------------------------- evidence
    def _process_evidence(self, entry_id: str, frames: List[evidence_store.JpegFrame], has_clip: bool) -> None:
        """Encodes the clip and requests the summary, each in its own thread (both take seconds)."""
        if has_clip:
            threading.Thread(target=self._write_clip, args=(entry_id, frames), daemon=True, name=f"Clip-{entry_id}").start()
        if self.summarizer and frames:
            threading.Thread(target=self._summarize, args=(entry_id, frames), daemon=True, name=f"Summary-{entry_id}").start()

    def _write_clip(self, entry_id: str, frames: List[evidence_store.JpegFrame]) -> None:
        if not evidence_store.encode_clip(entry_id, frames):
            event_journal.update(entry_id, clip_url=None)
            return
        if event_journal.get(entry_id) is None:
            # The event was deleted while ffmpeg was encoding: do not leave its clip behind
            evidence_store.delete_files_of({"clip_url": evidence_store.clip_url(entry_id)})
            return
        event_journal.expire_clips(evidence_store.enforce_quota(self.max_stored_clips, self.max_storage_mb))

    def _summarize(self, entry_id: str, frames: Optional[List[evidence_store.JpegFrame]] = None) -> None:
        """Writes the summary of an event from the given frames, or from its clip file when there are none."""
        entry = event_journal.get(entry_id)
        if entry is None:
            return
        video_path = None
        if not frames:
            video_path = evidence_store.clip_path(entry_id)
            deadline = time.time() + CLIP_WAIT_SEC
            while not os.path.exists(video_path) and time.time() < deadline:
                time.sleep(0.3)
        rule_context = ": ".join(part for part in (entry.get("rule_title"), entry.get("rule_description")) if part)
        try:
            result = self.summarizer.summarize(
                camera_name=entry.get("camera_name", "Kamera"),
                anomaly_type=entry.get("anomaly_type", ""),
                duration_sec=entry.get("duration_sec") or RULE_CLIP_SEC,
                video_path=video_path,
                raw_frames=frames,
                rule_context=rule_context or None,
            )
        except Exception as exc:
            logger.error("Summary of %s failed: %s", entry_id, exc)
            event_journal.update(entry_id, ai_status="error")
            return
        changes = {"ai_summary": result["summary"], "ai_headline": result["headline"],
                   "ai_verdict": result["verdict"], "ai_status": result["status"]}
        if result["status"] == "completed":
            changes["message"] = f"{entry.get('camera_name', '')}: {result['headline']}"
        event_journal.update(entry_id, **changes)

    # ------------------------------------------------------- recording events
    def rule_violated(self, camera_id: str, rule_id: str, rule_title: str, message: str, severity: str = "warning") -> None:
        """
        Called by the rule engine for every frame on which a rule is violated. The first call
        opens an event; the following ones only keep it running, so a violation that lasts an
        hour is one event with a start and an end, not one event every few seconds. The event
        is closed by `_close_silent_incidents` once the rule stayed quiet for RULE_QUIET_SEC.
        """
        now = time.time()
        with self._rule_lock:
            incident = self._rule_incidents.get((camera_id, rule_id))
            if incident:
                incident["last_active_ts"] = now
                return
            # Reserved before the slow part below, so that the next frame does not open a second event
            incident = self._rule_incidents[(camera_id, rule_id)] = {"id": None, "start_ts": now, "last_active_ts": now}
        try:
            incident["id"] = self._open_rule_event(camera_id, rule_title, message, severity)["id"]
        except Exception:
            with self._rule_lock:
                self._rule_incidents.pop((camera_id, rule_id), None)
            raise

    def _open_rule_event(self, camera_id: str, rule_title: str, message: str, severity: str) -> Dict[str, Any]:
        """Records the start of a rule violation with the last seconds of footage before it as evidence."""
        now = time.time()
        camera = camera_service.get_by_id(camera_id)
        camera_name = (camera or {}).get("name") or camera_id
        frames = camera_service.get_camera_clip_frames(camera_id, duration_sec=RULE_CLIP_SEC)
        has_clip = self._worth_a_clip(frames)
        critical = severity == "critical"

        entry = self._new_entry(
            "rule", camera_id, camera_name, now, RULE_VIOLATION_SCORE,
            "critical" if critical else "warning",
            "Kritik Kural İhlali" if critical else "Kural İhlali",
            f"Kural İhlali: {rule_title}",
            rule_title=rule_title,
            rule_description=message,
            is_ongoing=True,
            end_time_str="",
            ai_status="generating" if (self.summarizer and frames) else "none",
            message=f"{camera_name}: {rule_title} - {message}",
        )
        if has_clip:
            # Report the footage that really exists: the buffer is shorter right after a camera connected
            entry.update(
                start_time_str=_clock(frames[0][0]),
                duration_sec=round(evidence_store.footage_seconds(frames), 1),
                clip_url=evidence_store.clip_url(entry["id"]),
            )
        event_journal.add(entry, self.max_stored_clips)
        self._process_evidence(entry["id"], frames, has_clip)
        return entry

    def simulate_anomaly(self, camera_id: str, score: float) -> Dict[str, Any]:
        """Records an event with the given score, as if the model had produced it (demonstrations, tests)."""
        now = time.time()
        tier, label = self.classify(score)
        camera = camera_service.get_by_id(camera_id)
        camera_name = (camera or {}).get("name") or camera_id
        self.camera_scores[camera_id] = {"score": round(score, 1), "tier": tier, "label": label, "timestamp": now}
        entry = self._new_entry("sim", camera_id, camera_name, now, score, tier, label, f"Deneme alarmı ({label})")
        event_journal.add(entry, self.max_stored_clips)
        return entry

    def summarize_entry(self, entry_id: str) -> Dict[str, Any]:
        """Starts writing the summary of an event again. Returns {"success", "error"?}."""
        if not self.summarizer:
            return {"success": False, "error": "Özet servisi şu anda kullanılamıyor."}
        if event_journal.update(entry_id, ai_status="generating") is None:
            return {"success": False, "error": "Olay kaydı bulunamadı."}
        threading.Thread(target=self._summarize, args=(entry_id,), daemon=True, name=f"Summary-{entry_id}").start()
        return {"success": True, "status": "generating"}

    def get_entry_frames(self, entry_id: str) -> Dict[str, Any]:
        """Frames sampled evenly from the clip of an event, as base64 JPEGs."""
        entry = event_journal.get(entry_id)
        if entry is None:
            return {"success": False, "error": "Olay kaydı bulunamadı."}
        if vlm_summarizer is None:
            return {"success": False, "error": "Bu videodan kare alınamıyor."}
        path = evidence_store.clip_path(entry_id)
        frames = vlm_summarizer.sample_frames_from_video(path) if os.path.exists(path) else []
        duration_sec = entry.get("duration_sec") or RULE_CLIP_SEC
        return {
            "success": True,
            "entry_id": entry_id,
            "camera_name": entry.get("camera_name"),
            "duration_sec": duration_sec,
            "timestamps": vlm_summarizer.frame_times(duration_sec, len(frames)),
            "frames": [vlm_summarizer.frame_to_base64(frame) for frame in frames],
        }

    def clear_events(self) -> None:
        """Deletes every event together with its clip and snapshot."""
        removed = event_journal.clear()
        self._incidents.clear()  # running incidents would update events that no longer exist
        with self._rule_lock:
            self._rule_incidents.clear()
        for entry in removed:
            evidence_store.delete_files_of(entry)
        # With an empty journal no snapshot is referenced any more. Clips that never belonged
        # to an event are left alone here; Settings offers their clean-up explicitly.
        evidence_store.delete_unreferenced_snapshots(set(), min_age_sec=0.0)

    # ----------------------------------------------------------------- storage
    def get_storage_stats(self) -> Dict[str, Any]:
        stats = evidence_store.usage(*event_journal.referenced_files())
        stats.update(
            journal_entries=len(event_journal),
            max_storage_mb=int(self.max_storage_mb),
            max_stored_clips=int(self.max_stored_clips),
        )
        return stats

    def delete_orphan_clips(self) -> Dict[str, Any]:
        """Deletes evidence files that no event refers to (for example left behind by older versions)."""
        clips, snapshots = event_journal.referenced_files()
        deleted, freed_mb = evidence_store.delete_unreferenced_clips(clips)
        return {
            "deleted_count": deleted,
            "deleted_snapshots": evidence_store.delete_unreferenced_snapshots(snapshots),
            "freed_mb": freed_mb,
        }

    # ------------------------------------------------------------ live summary
    def _camera_state(self, camera: Dict[str, Any]) -> Dict[str, Any]:
        camera_id = camera.get("id")
        health = camera_service.get_stream_health(camera_id)
        reachable = camera.get("status") == "online"
        standby = bool(health.get("stream_standby"))
        connecting = bool(health.get("stream_connecting")) and reachable
        score = self.camera_scores.get(camera_id)
        if score and time.time() - score["timestamp"] > SCORE_FRESH_SEC:
            score = None  # after an outage the last value must not linger as if it were current

        if not health["stream_live"]:
            # A camera without video is neither "normal" nor "safe"
            tier, value = "offline", 0.0
            label = "Beklemede" if standby else "Bağlanıyor" if connecting else "Sinyal Yok"
        elif score:
            tier, value, label = score["tier"], score["score"], score["label"]
        else:
            tier, value = "normal", 0.0
            label = ("Analiz Duraklatıldı" if not self.analysis_enabled
                     else "İzleme Başlatılıyor" if self.model_ready else "AI Sunucu Bekleniyor")
        return {
            "camera_id": camera_id,
            "name": camera.get("name") or camera.get("ip") or camera_id,
            "ip": camera.get("ip"),
            "score": value,
            "tier": tier,
            "label": label,
            "analyzed": bool(score) and health["stream_live"],
            "stream_live": health["stream_live"],
            "stream_connecting": connecting,
            "stream_standby": standby,
            "stream_fps": health["stream_fps"],
        }

    def get_fleet_summary(self) -> Dict[str, Any]:
        """State of every camera (most urgent first) with the counters of each state."""
        urgency = {"critical": 0, "warning": 1, "offline": 2, "normal": 3}
        states = sorted((self._camera_state(camera) for camera in camera_service.get_all()),
                        key=lambda state: (urgency[state["tier"]], -state["score"]))
        without_video = [state for state in states if state["tier"] == "offline"]
        count = lambda tier: sum(1 for state in states if state["tier"] == tier)  # noqa: E731
        return {
            "total_cameras": len(states),
            "critical_count": count("critical"),
            "warning_count": count("warning"),
            "normal_count": count("normal"),
            # "Still connecting" and "standby" are not a signal loss
            "standby_count": sum(1 for state in without_video if state["stream_standby"]),
            "connecting_count": sum(1 for s in without_video if s["stream_connecting"] and not s["stream_standby"]),
            "offline_count": sum(1 for s in without_video if not (s["stream_standby"] or s["stream_connecting"])),
            "triton_model_ready": self.model_ready,
            "analysis_enabled": self.analysis_enabled,
            "thresholds": {"normal": self.threshold_normal, "warning": self.threshold_warning},
            "cameras": states,
        }


anomaly_service = AnomalyService()
