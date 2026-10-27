# 06 — API reference

Base address: `http://<server>:8500`. All bodies are JSON. The interactive documentation (Swagger) is at
`/docs` while the server is running.

**There is no authentication.** Anyone who can reach the API can do anything.

## General rules

- Successful responses usually contain `"success": true`.
- Error response: `{"detail": "<explanation in Turkish>"}`. The interface shows this text as it is (in
  English mode, through its catalogue).
- Language: the rule endpoints read the `Accept-Language` header. `en…` returns the plan sentences
  (`plan_summary.text`) and the working-hours text (`schedule_text`) in English; anything else returns
  Turkish. All other fields, and stored texts such as summaries and rule notes, do not depend on it.
  The interface sends the header on every request.

| Code | Meaning |
| :--- | :--- |
| 404 | Camera, rule, event or file not found. |
| 409 | The rule was changed while it was being prepared. |
| 422 | Invalid input (IP, port, label, empty title, no live picture…). |
| 400 | The summary could not be started (service off or no event). |
| 503 | The rule preparation service cannot be reached. |

The example values below are real server output, so their texts are in Turkish.

---

## System

### `GET /api/health`
Liveness check. `{"ok": true, "time": 1791525513.68}`

### `GET /api/system/stats`
Analysis server and graphics card status. Cached for 2 seconds.

```json
{
  "triton": {
    "status": "READY",
    "url": "http://localhost:8000",
    "models_ready": ["safety_detector", "coco_detector", "yoloe_detector", "anomaly_detector"],
    "avg_gpu_latency_ms": 43.8,
    "object_detection_latency_ms": null,
    "anomaly_detection_latency_ms": 43.8
  },
  "gpu": {"available": true, "name": "NVIDIA GeForce GTX 1650 Ti", "vram_used_mb": 2728,
          "vram_total_mb": 4096, "utilization_gpu_pct": 10, "temperature_c": 55}
}
```

Times are numbers if they were **measured** in the last 15 seconds, `null` otherwise (that model is not
running at the moment). While not ready, `status` takes a value such as `"OFFLINE"`; the interface only
checks whether it is `"READY"`.

### `POST /api/onvif/scan?timeout=3.0`
Searches the network for ONVIF devices (WS-Discovery).

```json
{"success": true, "count": 2, "devices": [
  {"ip": "192.168.1.100", "port": 8891, "name": "Hikvision", "hardware": "DS-2CD2043G2-I"}
]}
```

---

## Cameras

### `GET /api/cameras`
```json
{"success": true, "count": 1, "cameras": [{
  "id": "cam_192_168_1_100_8891",
  "ip": "192.168.1.100", "port": 8891, "rtsp_port": 554, "username": "admin",
  "name": "Depo girişi", "description": "",
  "manufacturer": "Hikvision", "model": "DS-2CD2043G2-I",
  "firmware_version": "V5.7.1 build 220510", "serial_number": "…",
  "status": "online", "status_message": "Bağlantı Aktif",
  "resolution": "1920x1080", "encoding": "H.264", "framerate": 30,
  "stream_uri": "rtsp://admin:…@192.168.1.100:8554/video7_1",
  "stream_live": true, "stream_connecting": false, "stream_standby": false,
  "stream_state": "live", "stream_fps": 25.0, "last_frame_age": 0.0
}]}
```

- `status`: `online` | `offline` | `auth_error` — the result of the last contact with the device.
- `stream_state`: `live` | `connecting` | `stalled` | `idle` — the current state of the stream.
- The password is **not** in the response; `stream_uri`, however, contains the credentials (the interface
  masks them when it shows the address).

### `POST /api/cameras/add`
```json
{"ip": "192.168.1.150", "port": 80, "username": "admin", "password": "…", "name": "", "rtsp_port": 554}
```
Only `ip` is required. The record is created even if the camera cannot be reached; `camera.status` gives
the result. Sending the same `ip:port` again updates the existing record. Response:
`{"success": true, "camera": {…}}`. May take up to 45 seconds. Errors: `422` (invalid IP or port).

### `PUT /api/cameras/{id}`
`{"name": "New name", "description": "This camera …"}` — the fields given are changed.

### `DELETE /api/cameras/{id}`
Deletes the camera, its rules and its reference pictures. `{"success": true, "removed_rules": 2}`

### `POST /api/cameras/{id}/reconnect`
Probes the camera again with the stored details. The response is the same as for `add`.

### `GET /api/cameras/{id}/snapshot`
The current frame (JPEG). Without a signal a status card is returned; **always 200**. Not cached. `HEAD`
is supported.

### `GET /api/cameras/{id}/stream`
MJPEG (`multipart/x-mixed-replace; boundary=frame`). For clients that cannot use WebSocket.

### `WS /api/cameras/{id}/ws?fps=0`
Binary messages; each message is one JPEG frame, sent as soon as a new frame is decoded. If `fps` > 0 the
rate is limited to that value (at most 60). If the camera does not exist, the connection is closed with
code `1008`. While the signal is lost, a status card is sent once per second.

---

## Live state

### `GET /api/live/state`
The single request behind the live wall.

```json
{
  "success": true,
  "detector_ready": true,
  "fleet": {
    "total_cameras": 9, "critical_count": 0, "warning_count": 1, "normal_count": 8,
    "offline_count": 0, "connecting_count": 0, "standby_count": 0,
    "triton_model_ready": true, "analysis_enabled": true,
    "thresholds": {"normal": 25.0, "warning": 50.0},
    "cameras": [{
      "camera_id": "cam_192_168_1_100_8891", "name": "Depo girişi", "ip": "192.168.1.100",
      "score": 31.4, "tier": "warning", "label": "Şüpheli / Dikkat", "analyzed": true,
      "stream_live": true, "stream_connecting": false, "stream_standby": false, "stream_fps": 25.0
    }]
  },
  "detections": {
    "cam_192_168_1_100_8891": {
      "camera_id": "cam_192_168_1_100_8891", "timestamp": 1791525786.93,
      "has_rules": true, "stream_live": true, "detector_ready": true,
      "alarm": true, "alarm_text": "Depo girişi: baretsiz kişi",
      "detections_count": 1,
      "detections": [{"class_name": "NO-Hardhat", "confidence": 0.81,
                      "bbox_normalized": [0.41, 0.22, 0.52, 0.61],
                      "in_zone": true, "is_violation": true, "zone_name": "Depo girişi",
                      "rule_title": "Baret kontrolü"}],
      "change_results": [{"zone_id": "zone_cd", "zone_name": "Acil çıkış", "has_reference": true,
                          "ssim": 0.9949, "alarm": false, "alarm_level": "clear", "change_pct": 0.0}]
    }
  }
}
```

- `fleet.cameras[].tier`: `normal` | `warning` | `critical` | `offline`. The list starts with the most
  urgent.
- `analyzed`: whether the camera has a score fresher than 10 seconds.
- `thresholds.normal` is the warning level, `thresholds.warning` the critical level.
- `bbox_normalized`: `[x1, y1, x2, y2]`, between 0 and 1.
- `track_id`: the object's id on this camera; the same object keeps the same number across frames.
- `alarm`: a rule has been violated without interruption for at least 1 second.
- `alarm_text` is in Turkish; the interface rewrites it in English mode.

### `GET /api/anomaly/status`
Only the `fleet` section.

### `GET /api/cameras/{id}/live-detections`
Only that camera's `detections` record: `{"success": true, "data": {…}}`

### `GET /api/change-detection/{camera}/{zone}`
State of the zone: `has_reference`, `reference_ts`, `last_ssim`, `alarm`, `alarm_level`, `alarm_since`,
`last_check_ts`. `404` if there is no reference.

### `POST /api/change-detection/{camera}/{zone}/capture-reference`
Stores the current live frame as the zone's "empty" reference. Errors: `404` (no camera or zone), `422`
(no live picture, zone too small).

### `DELETE /api/change-detection/{camera}/{zone}/reference`
Deletes the reference; the zone is not evaluated until a new one is taken.

---

## Rules

### `GET /api/rules?camera_id=&full=false`
```json
{"success": true, "count": 1, "compiler_available": true, "rules": [{
  "id": "rule_e1d406dd91", "title": "Baret kontrolü",
  "scope": "camera", "camera_id": "cam_192_168_1_100_8897", "camera_name": "Depo",
  "severity": "warning", "description": "Depo girişi: Baret takmayan biri girerse haber ver.",
  "enabled": true, "created_at": 1791524774.12, "updated_at": 1791524965.31,
  "compile_status": "compiled", "camera_missing": false,
  "zones": [{
    "id": "zone_1791524742354_ow88", "name": "Depo girişi",
    "description": "Baret takmayan biri girerse haber ver.",
    "zone_type": "detection",
    "points": [{"x": 0.2067, "y": 0.1519}, {"x": 0.61, "y": 0.15}, {"x": 0.6, "y": 0.8}],
    "color_idx": 0,
    "compile_meta": {"latency_ms": 1376.8, "status": "success", "model": "qwen3-vl-30b",
                     "compiled_at": "2026-10-09T05:46:15+00:00"},
    "plan_summary": {"model": "safety_detector", "classes": ["NO-Hardhat"],
                     "conditions": ["zone_presence"], "status": "success"}
  }]
}]}
```

- `scope`: `camera` (single camera) | `system` (all cameras; `camera_id` is `null`).
- `zone_type`: `detection` (person / object rule) | `change_detection` (obstruction / change).
- `compile_status`: `compiling` | `compiled` | `fallback` | `pending` | `unavailable` | `error` |
  `unsupported` | `not_required`.
- `compile_note`: only with `unsupported`; why the request could not be turned into a rule (a sentence
  written for the operator).
- `plan_summary.note`: if the rule is only the closest thing to what was asked, what could not be done and
  what the rule does instead; otherwise `null`.
- `camera_missing`: the rule's camera has been deleted.
- `full=true` returns the whole plan (`detection_plan`, `compile_logs`, `raw_llm_response`) instead of
  `plan_summary`.

### `POST /api/rules`
```json
{"title": "Baret kontrolü", "scope": "camera", "camera_id": "cam_…", "camera_name": "Depo",
 "zones": [{"id": "zone_1", "name": "Depo girişi", "description": "Baret takmayan biri girerse haber ver.",
            "zone_type": "detection", "points": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}]}]}
```
Stores the rule and starts compiling the zone descriptions **in the background**; the response returns
at once with `compile_status` `compiling`. Request the list again to see the result. Errors: `422` (empty
title, no camera, a missing or invalid choice in a zone defined from lists).

Optional fields:

- `"manual": {"subject": "person", "condition": "waiting", "value": 20}` on a zone: the zone is defined
  by choices instead of a sentence; the server builds the plan immediately (no language model) and writes
  the `description` itself. `subject`: `person`, `vehicle`, `no_hardhat`, `no_vest`, `forklift`, `bag`.
  `condition`: `presence`, `waiting` (seconds), `absence` (seconds), `more_than` (count), `fewer_than`
  (count).
- `"schedule": {"start": "22:00", "end": "06:00", "days": [0, 1, 2, 3, 4]}` on the rule: working hours
  (`days`: 0 Monday … 6 Sunday; if the end is before the start, the window runs past midnight). If not
  given, the hours are read from the zone sentences; if they have none either, the rule always runs.

The returned rule also carries `schedule_text` ("22:00–06:00 · Weekdays", empty without hours),
`active_now` (on **and** within its working hours) and, for each zone, `plan_summary.text` (what the plan
does, in one sentence). These two texts follow `Accept-Language`.

### `GET /api/rules/{id}`
One rule, with its plans.

### `PUT /api/rules/{id}`
Changes the fields given: `title`, `enabled`, `scope`, `camera_id`, `camera_name`, `zones`, `description`.
If `zones` is sent, zones whose description did not change keep their plan; only new or changed zones are
compiled.

### `DELETE /api/rules/{id}`
Deletes the rule and the references of its obstruction zones.

### `POST /api/rules/{id}/compile`
Compiles every zone again and **waits until done** (a few seconds). `{"success": true, "plans_count": 1}`.
Errors: `503`, `409`.

### `GET /api/rules/{id}/plan`
Diagnostics: each zone's compiled plan, the compile log and the model's raw response.
`{"compile_status", "compile_error", "plans": [{"zone_id", "zone_name", "detection_plan", "compile_logs", "compile_meta", "raw_llm_response"}]}`

---

## Reports

### `GET /api/reports/summary?days=7`
Summary of the last `days` calendar days (1–90; 1 = since midnight today). Test events (`sim_…`) are not
counted.

```json
{"success": true, "report": {
  "days": 7, "from_text": "03.10.2026", "to_text": "09.10.2026 21:30",
  "totals": {"events": 51, "rule": 32, "movement": 19, "correct": 30, "false_positive": 4,
             "unreviewed": 17, "false_alarm_pct": 11.8},
  "buckets": [{"label": "03.10", "rule": 9, "movement": 5}, "…"],
  "by_rule": [{"name": "Gece girişi", "events": 14, "total_sec": 9004.0, "ongoing": 0,
               "correct": 6, "false_positive": 2, "unreviewed": 6}],
  "by_camera": [{"name": "Depo", "events": 20, "rule": 12, "correct": 9, "false_positive": 1, "unreviewed": 10}],
  "summary_verdict": {"compared": 34, "agreed": 27},
  "incomplete": false}}
```

- `buckets`: one row per hour (24 rows) if `days` is 1, otherwise one per day.
- `false_alarm_pct`: `false_positive / (correct + false_positive)`; `null` if no event has been reviewed.
- `total_sec`: total duration of the violations (an ongoing violation counts up to now).
- `summary_verdict`: among events that have an operator verdict and whose summary says `confirmed` /
  `normal`, how many times the two agree.
- `incomplete`: the event log is full and its oldest event lies inside the period, so older ones may have
  been deleted.

---

## Events

For historical reasons the endpoints live under `/api/anomaly/`; they cover rule violations too.

### `GET /api/anomaly/journal?camera_id=&tier=&operator_label=&limit=250`
Events from newest to oldest, with counters. `limit` is at most 2000.

```json
{"success": true, "count": 1,
 "stats": {"total_events": 1, "critical_count": 1, "warning_count": 0, "normal_count": 0,
           "rule_violation_count": 0, "total_warnings": 1,
           "correct_count": 0, "false_positive_count": 0, "unlabeled_count": 1},
 "journal": [{
   "id": "anom_58361cda",
   "timestamp": 1791525040.45, "timestamp_str": "08:50:40", "date_str": "09.10.2026",
   "camera_id": "cam_192_168_1_100_8892", "camera_name": "Depo",
   "score": 99.3, "tier": "critical", "label": "Kritik Anomali",
   "anomaly_type": "Olağandışı hareket",
   "start_time_str": "08:50:39", "peak_time_str": "08:50:43", "end_time_str": "08:50:46",
   "duration_sec": 6.8, "is_ongoing": false,
   "snapshot_url": "/api/anomaly/snapshots/snap_anom_58361cda.jpg?v=1791525043",
   "clip_url": "/api/anomaly/clips/clip_anom_58361cda.mp4",
   "ai_status": "completed",
   "ai_headline": "Bir kişi, palet arabasıyla bir nesneyi düşürdü.",
   "ai_verdict": "confirmed",
   "ai_summary": "**Özet Başlık:** Bir kişi, palet arabasıyla bir nesneyi düşürdü.\n- …\n**Öneri:** …",
   "message": "Depo: Bir kişi, palet arabasıyla bir nesneyi düşürdü."
 }]}
```

When the operator gives a verdict, `operator_label` (`correct` / `false_positive`) is added to the
record; without it, the event has not been reviewed. The full description of the fields is in
[09 — Data and configuration](09-data-and-configuration.md).

### `GET /api/anomaly/stats`
Counters only: `{"success": true, "stats": {…}}`

### `GET /api/anomaly/events-stream`
Server-Sent Events. `{"type": "connected"}` on connection, then:

| `type` | When | Body |
| :--- | :--- | :--- |
| `new_anomaly` | An event opened | `entry`: the whole event |
| `update_anomaly` | An event closed, its summary arrived, it was marked, its video could not be written | `entry`: its current state |
| `journal_cleared` | All events were deleted | — |

After 15 seconds of silence a `: keep-alive` comment is sent.

### `POST /api/anomaly/{id}/label`
`{"label": "correct"}` — `correct` | `false_positive` | `unlabeled`. Optional `notes`, `operator_name`.
Response: `{"success": true, "entry": {…}}`. Errors: `422` (invalid label), `404`.

### `POST /api/anomaly/{id}/summarize`
Writes the summary again. Returns at once (`{"success": true, "status": "generating"}`); the result
arrives with an `update_anomaly` notification. Error: `400`.

### `GET /api/anomaly/{id}/frames`
Up to 8 evenly spaced frames from the event video.
`{"success": true, "duration_sec": 6.8, "timestamps": [0.0, 0.85, …], "frames": ["<base64 JPEG>", …]}`

### `POST /api/anomaly/clear`
Deletes every event with its videos and snapshots. Cannot be undone.

### `POST /api/anomaly/simulate`
`{"camera_id": "cam_…", "score": 55}` — records a test event with that score (for demonstrations and
tests).

### `GET /api/anomaly/clips/{file}` · `GET /api/anomaly/snapshots/{file}`
Event video (MP4, range requests supported) and event snapshot (JPEG, cacheable for 7 days). If the video
is still being encoded, the server waits up to 3 seconds. `404` if missing.

### `GET /api/anomaly/storage`
```json
{"clip_count": 1, "clip_mb": 0.4, "orphan_clip_count": 0, "orphan_clip_mb": 0.0,
 "snapshot_count": 1, "snapshot_mb": 0.01, "orphan_snapshot_count": 0,
 "journal_entries": 1, "max_storage_mb": 1000, "max_stored_clips": 500}
```
`orphan_*`: files no event points to.

### `POST /api/anomaly/storage/cleanup-orphans`
Deletes orphan videos and snapshots (except those newer than 120 seconds).
`{"success": true, "deleted_count": 3, "deleted_snapshots": 1, "freed_mb": 12.4}`

---

## Settings

### `GET /api/settings`
`{"success": true, "settings": {"anomaly": {…}, "recording": {…}, "live_wall": {…}}}` — the fields are in
chapter 09.

### `POST /api/settings`
Body: all of the settings or a section of them. Values are pulled into their allowed range, stored and
applied to the running services **immediately**. The response is the full set of applied settings.

### `POST /api/settings/reset`
Returns to the defaults.

---

## Interface files

| Path | Content |
| :--- | :--- |
| `/` | `index.html` |
| `/ui/css/*`, `/ui/js/*` | Interface files (`Cache-Control: no-cache`) |
| `/static/js/*.js` | One-time reload script for cached pages left from an old version |
| `/docs`, `/openapi.json` | API documentation generated by FastAPI |
