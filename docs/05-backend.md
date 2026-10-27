# 05 — Server modules

Directory: `WebInterface/backend/`. Run with: `uvicorn WebInterface.backend.server:app`.

```
backend/
├── __init__.py              OpenCV environment options
├── server.py                Application: start-up, shutdown, middleware, attaching the routers
├── paths.py                 Data directory, safe writes, single-instance lock, shutdown flag
├── api/                     HTTP layer (no business logic)
│   ├── schemas.py           Request bodies
│   ├── system.py            /api/health, /api/system/stats, /api/onvif/scan
│   ├── cameras.py           /api/cameras/…  (registry, snapshot, MJPEG, WebSocket)
│   ├── live.py              /api/live/state, /api/change-detection/…
│   ├── rules.py             /api/rules/…
│   ├── events.py            /api/anomaly/…  (log, evidence files, SSE)
│   ├── reports.py           /api/reports
│   ├── settings.py          /api/settings
│   └── frontend.py          Serving the interface files
├── camera_service.py        Camera records and the live frame source
├── onvif_core.py            ONVIF discovery and device queries
├── onvif_auth.py            WS-Security authentication header
├── anomaly_service.py       Anomaly loop; score → event
├── live_detection_service.py  Rule loop; detection → violation
├── change_detector.py       Obstruction / change zones (SSIM)
├── rule_compilation.py      Background compilation of rule descriptions
├── rules_service.py         Rule records
├── settings_service.py      Settings: defaults, limits, persistence
├── event_journal.py         Event log
├── evidence_store.py        Event videos and snapshots
├── event_stream.py          Live notification (SSE) publisher
├── reports.py               Report figures from the event log
└── system_stats.py          Analysis server and graphics card status
```

Dependencies point one way: `api/` → services → `paths`. Services import nothing from `api/`.

---

## `server.py`

Builds the application; contains no endpoints.

- `acquire_instance_lock()` is called before the service imports (the order matters).
- `QuietPollingFilter`: removes the successful requests the interface makes often from the access log.
- `lifespan`: wraps the `SIGINT`/`SIGTERM` handlers (`SHUTTING_DOWN` first), stops the service loops
  and closes the camera workers on shutdown.
- Middleware: GZip (≥ 1 KB), CORS (open to every origin).

## `paths.py`

| Name | Function |
| :--- | :--- |
| `DATA_DIR`, `data_path(*parts)` | Data directory (`AEGIS_DATA_DIR`, by default this package's directory). |
| `atomic_write_json(path, obj)` | Write through a temporary file + rename. |
| `acquire_instance_lock(wait_sec=20)` | `flock` on `.aegis.lock`; the wait is changed with `AEGIS_LOCK_WAIT_SEC`. Raises `RuntimeError` if the lock cannot be taken. |
| `SHUTTING_DOWN` | `threading.Event`; checked by every long-lived loop. |

## `camera_service.py`

Two classes and the singleton `camera_service`.

### `CameraLiveWorker`

The thread that decodes one camera's stream.

| Constant | Value | Meaning |
| :--- | :--- | :--- |
| `STREAM_STALE_SEC` | 3.0 | If no frame arrives for this long, the stream counts as "stalled". |
| `WORKER_IDLE_SEC` | 120.0 | Without consumers, the connection is released after this time. |
| `MAX_OUTPUT_FPS` | 30.0 | Highest frame rate processed per camera. |

States: `connecting` → `live` ⇄ `stalled`, `idle` when unused. Important behaviour:

- `is_live()` requires at least two frames in the session; the first frame is often an old one from the
  decoder's buffer.
- If a read stalls for more than 4 seconds, the session is dropped; stale frames that the decoder flushes
  later are never served as "live".
- An address that works is remembered; if the stored IP cannot be reached, the same path is tried through
  `localhost` (for streams on the same machine as the server).
- `add_listener` / `remove_listener`: functions to call on each new frame (WebSocket distribution uses this).
- `get_frame_info`, `get_frame_at(ts)`, `get_clip_frames(seconds)`, `get_clip_frames_range(start, end)`,
  `get_ai_frames(count)`, `get_bgr_frame()`.

### `CameraService`

| Method | Function |
| :--- | :--- |
| `get_all()`, `get_by_id(id)` | Camera records (including the password; used only inside the server). |
| `public_view(camera)` | A copy without the password and with the stream state added; the API returns this. |
| `probe_and_register(ip, port, …)` | Connects over ONVIF, reads device and stream details, stores the record, starts the worker. The record is created even if the device cannot be reached (`status`: `offline` / `auth_error`). |
| `update_camera`, `delete_camera` | Update name / description; delete (stops the worker). |
| `get_stream_health(id)` | `stream_live`, `stream_connecting`, `stream_standby`, `stream_state`, `stream_fps`, `last_frame_age`. |
| `get_camera_snapshot(id)` | The current JPEG or a status card ("BAĞLANIYOR", "SİNYAL YOK"). |
| `iter_frames(id, max_fps)` | Async generator: yields a JPEG on every new frame; a status card once per second without signal. |
| `mjpeg_stream_generator(id)` | The same frames as `multipart/x-mixed-replace`. |
| `set_clip_window(sec)` | Length of the frame buffer (set by the anomaly service from the settings). |
| `sync_stream_status()` | Watchdog: marks a camera `offline` after 8 seconds without frames; allows 20 s on first connection. Does not overwrite `auth_error`. |
| `shutdown()` | Stops all workers. |

The camera id has the form `cam_<ip, dots as underscores>_<onvif port>`; adding the same address again
updates the same record.

The status cards are drawn by the server as images and are in Turkish in both interface languages.

## `onvif_core.py`, `onvif_auth.py`

- `run_multi_nic_ws_discovery(timeout)`: sends a WS-Discovery probe to `239.255.255.250:3702` from every
  active network card and returns the devices that answer.
- `ONVIFClient`: device information, profiles, stream address (`GetStreamUri`), snapshot address.
  The camera's clock is read first with an unauthenticated `GetSystemDateAndTime`; the timestamp in the
  authentication header is produced from the camera's clock (so that a clock difference does not break
  authentication).
- `generate_ws_security_header(user, password, clock_offset)`: `PasswordDigest` header.

## `anomaly_service.py`

Singleton `anomaly_service`. Constants at the top of the file:

| Constant | Value | Meaning |
| :--- | :--- | :--- |
| `CYCLE_SEC` | 0.25 | Length of one round; each camera is scored ~4 times per second. |
| `MAX_BATCH_SIZE` | 8 | Most cameras in one request. |
| `SCORE_FRESH_SEC` | 10 | Scores older than this are not shown. |
| `RULE_CLIP_SEC` | 5 | Look-back video length for a rule violation. |
| `RULE_VIOLATION_SCORE` | 75 | Fixed score written to a rule violation record. |

| Method | Function |
| :--- | :--- |
| `_run()` | Loop: close quiet events → is analysis on → connect to the server → `_score`. |
| `_pending_clips(cameras)` | The last 16 frames of the cameras that have a new frame. |
| `_score(cameras)` | Sends the batches to the model; logit → sigmoid → 0–100 score. |
| `_apply_score` | Smooths the score (only below the threshold), classifies it, passes it to `_track_incident`. |
| `_track_incident`, `_close_incident` | Opens, continues and closes the event (see chapter 08). |
| `_process_evidence` | Starts the video encoding and summary threads. |
| `rule_violated(camera, rule, title, message, severity)` | Entry point the rule loop calls on every violating frame: opens the event or keeps it open; `_close_silent_incidents` closes it (see chapter 08, B.6). |
| `simulate_anomaly(camera, score)` | Records a test event (API: `/api/anomaly/simulate`). |
| `summarize_entry(id)`, `get_entry_frames(id)` | Writes the summary again; returns frames from the video. |
| `clear_events()` | Deletes every event with its evidence. |
| `get_fleet_summary()` | Status of each camera and counters. |
| `get_storage_stats()`, `delete_orphan_clips()` | Disk usage; deleting files that belong to no event. |
| `reload_settings()` | Called when the settings change; reconnects if the server address changed. |

`last_latency_ms` and `last_inference_ts` are read by `system_stats`.

## `event_journal.py`

Singleton `event_journal`. Keeps the event list in memory; writes every change to disk and announces it
through `event_stream`. The records it returns are copies.

| Method | Function | Notification published |
| :--- | :--- | :--- |
| `add(record, capacity)` | Adds at the front; drops the oldest records beyond the capacity together with their evidence. | `new_anomaly` |
| `update(id, **fields)` | Changes fields; `None` if the record does not exist. | `update_anomaly` |
| `set_label(id, label, note, operator)` | Operator verdict; `ValueError` for an invalid label. | `update_anomaly` |
| `expire_clips(names)` | Marks records whose video was deleted by the quota (`clip_expired`). | — |
| `clear()` | Deletes everything, returns what was deleted. | `journal_cleared` |
| `get(id)`, `list(…)`, `stats()`, `referenced_files()` | Reading. | — |

At start-up it repairs records left half-done: `is_ongoing` → closed and marked `interrupted`;
`ai_status: generating` → `interrupted`.

## `evidence_store.py`

Stateless functions. It does not know the log; the caller says which files are in use.

| Function | Purpose |
| :--- | :--- |
| `save_snapshot(id, jpeg, taken_at)` | `snap_<id>.jpg`; the returned address is stamped with `?v=<time>`. |
| `encode_clip(id, frames)` | Pipes the JPEGs into ffmpeg to produce `clip_<id>.mp4` (H.264 baseline, `+faststart`). The frame rate is computed from the capture times. |
| `footage_seconds(frames)` | The real time the frames cover. Below `MIN_CLIP_SECONDS` (1 s) no video is made. |
| `enforce_quota(max_count, max_mb)` | Deletes the oldest videos; returns the names of those deleted. |
| `usage(used_videos, used_snapshots)` | Disk usage and the number of orphan files. |
| `delete_unreferenced_clips`, `delete_unreferenced_snapshots` | Deletes orphan files; leaves those newer than 120 s alone. |
| `delete_files_of(record)` | Deletes the video and snapshot of one event. |

## `event_stream.py`

Singleton `event_stream`: `subscribe()` (from the event loop), `unsubscribe(queue)`, `publish(event)`
(from any thread). Each queue holds at most 256 messages; a stuck client loses its oldest message.

## `live_detection_service.py`

Singleton `live_detection_service`. The loop processes cameras that have an active rule and bring a new
frame.

- `_ensure_detector()`: connects `YOLODetector` to Triton; on failure retries at growing intervals.
- `_get_plan(rule, zone)`: validates the stored plan and caches it under `(rule, zone, updated_at)`. Plans
  that look only for "person" are routed to `coco_detector`.
- `_process_camera(camera)`: depending on the zone type, either `change_detector.check_frame` or detection
  + object tracking (`ObjectTracker`, one per camera and model) + `ConditionEvaluator.evaluate`. Within a
  frame, detection and tracking run once per model and class set. A rule counts as an alarm, and
  `rule_violated` is called, only when it has been violated without interruption for `RULE_CONFIRM_SEC`.
- `get_detections(camera_id=None)`: the latest state — `alarm`, `alarm_text`, `detections` (`track_id`,
  `class_name`, `confidence`, `bbox_normalized`, `in_zone`, `is_violation`), `change_results`.
- Constants: `MIN_CYCLE_SEC` 0.08, `IDLE_SLEEP_SEC` 0.5, `RULE_CONFIRM_SEC` 1.0, `TRACKER_IDLE_SEC` 60.

`alarm_text` is written in Turkish; the interface rewrites it in English mode (`alarmText()` in
`labels.js`).

## `change_detector.py`

Singleton `change_detector`. Stores the reference picture of each zone under `change_refs/`.

- `capture_reference(camera, zone, frame, points, …)`: masks the polygon, shrinks it to 160×120, stores it.
- `check_frame(…)`: brings the live frame to the same form and computes SSIM against the reference.
  SSIM < 0.72 → `alarm`; < 0.88 → `warning` (counted as an alarm if the changed area exceeds 10 %);
  otherwise `clear`.
- `get_zone_state`, `delete_reference`, `delete_camera_references`.

## `rule_compilation.py`

The bridge between `Rule_Generator_LLM.compiler.RuleCompiler` and the HTTP layer.

| Function | Purpose |
| :--- | :--- |
| `is_available()` | Whether the compiler could be set up (key and dependencies present). |
| `start(rule_id)` | Compiles the zones without a plan in the background. If the rule changed meanwhile, the result is discarded. |
| `recompile(zones)` | Compiles every zone again (blocking call). |
| `keep_unchanged_plans(old, new)` | Keeps the plan of a zone whose description did not change. |
| `apply_manual_plans(zones)` | Builds the plan of zones defined from lists (`manual`) immediately; `ValueError` for an invalid choice. |
| `compiled_changes(rule, zones, plans)` | What to store after compilation: the zones and (if the user gave no hours in the form) the working hours read from the sentence. |
| `status_of(rule)` | `compiling`, `error`, `unsupported`, `not_required`, `compiled`, `fallback`, `pending`, `unavailable`. |
| `rule_view(rule, slim, lang)` | API view (including `schedule_text`, `active_now`); `slim` puts a short `plan_summary` in place of the plan. `lang` (`"tr"` / `"en"`) is the language of the plan sentences and the working-hours text. |

## `reports.py`

`build_report(events, days, now, capacity)`: a pure function that computes the report figures from the
event log (no state, files or service imports, so it can be tested without a running system). Its
endpoint is `api/reports.py`. The fields are in chapter 06.

## `rules_service.py`, `settings_service.py`

- `rules_service`: `get_all(camera_id)`, `get_by_id`, `create_rule`, `update_rule`, `delete_rule`,
  `delete_rules_for_camera`. Reloads if the file is changed from outside (`mtime`).
- `settings_service`: `get_all()`, `get_section(name)`, `update(changes)`, `reset_defaults()`.
  `_sanitize()` pulls every value into its allowed range; the ranges are in chapter 09.

## `system_stats.py`

`get_system_telemetry()`: whether Triton is ready and which models are ready, analysis times **measured**
in the last 15 seconds (`null` otherwise), and graphics card name, memory, load and temperature from
`nvidia-smi`. The result is cached for 2 seconds.

## The `api/` layer

Each module defines an `APIRouter`; `api/__init__.py` collects them in the `routers` list. Rules:

- A router validates, calls the service and shapes the response; it contains no business logic.
- A missing resource is `404`, invalid input `422`, a conflict `409`, an unreachable service `503`.
  Error messages are in Turkish (the `detail` field); the interface shows them as they are, or through
  its catalogue in English mode.
- The rule endpoints read the `Accept-Language` header (`_language()`: `en…` → English, otherwise
  Turkish) and pass it to `rule_view`.
- Blocking calls are made through `asyncio.to_thread`.
