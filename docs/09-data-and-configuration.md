# 09 — Data and configuration

## Environment variables

Read from the `.env` file at the repository root or from the environment; a value set in the environment
overrides `.env`.

| Variable | Default | Effect |
| :--- | :--- | :--- |
| `EVREN_API_KEY` | empty | Key of the language model service. If empty, the service is not used. |
| `EVREN_BASE_URL` | `https://evren-llmapi.ssyz.org.tr/v1` | Address of the service (OpenAI-compatible API). |
| `EVREN_VLM_MODEL` | `qwen3-vl-30b` | Model name for rule compilation and summaries. |
| `AEGIS_DATA_DIR` | `WebInterface/backend` | Data directory. |
| `AEGIS_LOCK_WAIT_SEC` | `20` | How long to wait for the data directory lock at start-up. |

`.env` is read in two places: `WebInterface/run.sh` exports every variable in the file into the
environment; `Rule_Generator_LLM/llm_config.py` takes the `EVREN_*` values from it when the server is
started without `run.sh` (directly with `uvicorn` or from a script). On that second path the `AEGIS_*`
variables are not read from `.env`; they must be given on the command line.

## Data directory

```
<AEGIS_DATA_DIR>/
├── cameras_db.json          Cameras (passwords in plain text!)
├── rules_db.json            Rules, zones and compiled plans
├── settings.json            Settings
├── anomaly_journal.json     Event log
├── .aegis.lock              Single-instance lock (holds the process number)
├── change_refs/             Reference pictures of obstruction zones
└── recordings/
    ├── clips/               Event videos      clip_<event id>.mp4
    └── snapshots/           Event snapshots   snap_<event id>.jpg
```

- None of these files enters the repository (`.gitignore`). With an empty data directory the server
  starts from scratch.
- The files are dumps of the state in memory; do not edit them by hand while the server runs.
  (`cameras_db.json` and `rules_db.json` are reloaded if they change from outside; the others are not.)
- **Backup:** stop the server and copy the directory.
- **Reset:** stop the server and delete the file concerned.

Theme and interface language are not stored here; each browser keeps its own (see chapter 07, "Stored in
the browser").

### `cameras_db.json`

A dictionary from camera id to record.

| Field | Meaning |
| :--- | :--- |
| `id` | `cam_<ip>_<port>` |
| `ip`, `port`, `rtsp_port` | Address; `port` is the ONVIF service port. |
| `username`, `password` | ONVIF / RTSP account. **Plain text.** API responses do not contain `password`. |
| `name`, `description` | Display name; what the camera sees. |
| `manufacturer`, `model`, `firmware_version`, `serial_number` | Details read from the device. |
| `resolution`, `encoding`, `framerate`, `profiles_supported`, `profiles_detail` | Stream details. |
| `stream_uri`, `snapshot_uri` | RTSP and snapshot addresses reported by the device. |
| `status`, `status_message`, `last_seen` | Result of the last contact. |

### `rules_db.json`

A dictionary from rule id to record.

| Field | Meaning |
| :--- | :--- |
| `id`, `title`, `enabled` | `rule_…`; name; whether it is on. |
| `scope`, `camera_id`, `camera_name` | `camera` or `system`. |
| `description` | The zone descriptions joined (for information). |
| `severity` | `warning` / `critical`; sets the level of the violation record. The interface always sends `warning`. |
| `schedule` | Working hours: `{start, end, days, source}`. `source`: `user` (from the form) or `text` (read from the sentence). If the field is missing or holds no hours, the rule always runs; `{"source": "user"}` means "the user deliberately chose always" and takes precedence over hours in the sentence. |
| `zones[]` | The table below. |
| `created_at`, `updated_at` | Timestamps. `updated_at` is the key of the plan cache. |

Zone (`zones[]`):

| Field | Meaning |
| :--- | :--- |
| `id`, `name`, `color_idx` | Id, name, colour order in the interface. |
| `zone_type` | `detection` / `change_detection`. |
| `description` | Plain sentence (only `detection`). In a zone defined from lists, the sentence written by the server. |
| `manual` | Only in a zone defined from lists: `{subject, condition, value}`; the plan is built from it, without the language model. |
| `points[]` | `{x, y}`, corners between 0 and 1. |
| `detection_plan`, `compile_meta`, `compile_logs`, `raw_llm_response` | Compilation output (see chapter 08). |

The `assignee`, `escalation` and `actions` fields left from older versions are not read; they are harmless.

### `anomaly_journal.json`

The list of event records, newest first. Its capacity is `max_stored_clips`; the oldest record beyond it
is deleted with its evidence.

| Field | Meaning |
| :--- | :--- |
| `id` | The prefix gives the type: `anom_` unusual activity, `rule_` rule violation, `sim_` test. |
| `timestamp`, `timestamp_str`, `date_str` | Opening time. |
| `camera_id`, `camera_name` | The event's camera (the name is the name at the time of the event). |
| `score`, `tier`, `label` | Highest score; `warning` / `critical`; name of the level. |
| `anomaly_type` | `Kural İhlali: <rule name>` for a rule violation, always `Olağandışı hareket` for unusual activity. For the latter the interface shows the summary's headline. |
| `rule_title`, `rule_description` | Only for a rule violation: the rule's name and what was seen. |
| `start_time_str`, `peak_time_str`, `end_time_str`, `duration_sec` | The range the video covers. |
| `is_ongoing` | The event is ongoing. For a rule violation it stays `true` for as long as the rule is violated. |
| `incident_sec` | Only for a rule violation, once closed: total duration of the violation. `duration_sec` is the length of the video. |
| `snapshot_url`, `clip_url` | Evidence addresses; `clip_url` is `null` without a video. |
| `clip_expired` | The video was deleted because of the disk quota. |
| `ai_status` | `none`, `generating`, `completed`, `fallback`, `error`, `interrupted`. |
| `ai_summary`, `ai_headline` | Summary text and headline (Turkish). |
| `ai_verdict` | The summary's verdict on the footage: `confirmed`, `normal`, `unclear` or `null`. Information only. |
| `operator_label` | `correct`, `false_positive`, `unlabeled`; without the field, the event has not been reviewed. |
| `operator_notes`, `operator_name`, `operator_labeled_at` | Details of the verdict. |
| `interrupted` | The server restarted while the event was ongoing. |
| `message` | One-line text (used by search). |

The texts in these records are written once, in Turkish, and are not translated: the interface translates
the fixed ones it knows (`anomaly_type`, `label`) and the alarm sentences, and shows the rest as stored.

## Settings (`settings.json`)

Every value is pulled into the range below when saved (`settings_service._sanitize`). A change is applied
without restarting the server.

### `anomaly`

| Field | Default | Range | Effect | In the interface |
| :--- | :--- | :--- | :--- | :--- |
| `continuous_pipeline` | `true` | — | Unusual activity detection on / off. | Detection |
| `threshold_normal` | 25 | 1–95 | **Warning** threshold. | Warning level (5–45) |
| `threshold_warning` | 50 | 2–99, always > `threshold_normal` | **Critical** threshold. | Critical level (30–80) |
| `triton_url` | `localhost:8000` | — | Analysis server (`host:port`). | Advanced |
| `model_name` | `anomaly_detector` | — | Name of the anomaly model. | Advanced |
| `batch_size` | 4 | 1–8 | Cameras per request. | Advanced |
| `clip_len` | 16 | fixed | The model's input length; cannot be changed. | — |

### `recording`

| Field | Default | Range | Effect | In the interface |
| :--- | :--- | :--- | :--- | :--- |
| `auto_record_clips` | `true` | — | Event video recording. | Recording |
| `padding_sec` | 1.5 | 0–10 | Time added before and after the event. | Before and after the event (0.5–5) |
| `max_clip_duration_sec` | 60 | 5–300 | Longest duration of an event / video. | Longest video (15–180) |
| `max_storage_mb` | 1000 | 50–100000 | Disk quota for videos. | Storage for recordings (100–5000) |
| `tolerance_sec` | 2.0 | 0.5–10 | Pauses shorter than this do not split an event. | Advanced: Event merge time |
| `max_stored_clips` | 500 | 10–5000 | Most videos **and** event records. | Advanced: Maximum number of videos |

The sliders in the interface have a narrower range than the server accepts; if the file holds a wider
value, the slider widens enough to show it.

### `live_wall`

| Field | Default | Effect |
| :--- | :--- | :--- |
| `default_layout` | `grid-3x2` | Opening layout: `grid-1x1`, `grid-2x2`, `grid-3x2`, `grid-4x3`. |
| `alarm_borders` | `true` | Frame highlight on alarm. |
| `hud_badges` | `true` | Warning / alarm label. (The signal label is always visible.) |
| `click_to_focus` | `true` | Enlarge on click. |
| `zero_latency_mode` | `true` | When off, the stream is limited to 8 frames per second. |

## Memory and disk

- **Memory:** each camera keeps enough JPEG frames in memory to cut the longest event video:
  `max_clip_duration_sec + 2 × padding_sec + tolerance_sec + 8` seconds. With the defaults that is ~73
  seconds; at 1080p and 25 frames per second, roughly 60–80 MB per camera. On installations with many
  cameras, lowering `max_clip_duration_sec` reduces memory directly.
- **Disk:** videos are encoded with H.264 `ultrafast`; a 5-second 1080p video is roughly 0.3–0.7 MB. When
  the quota is full, the oldest videos are deleted; the event record and its snapshot remain
  (`clip_expired`).

## What `.gitignore` covers

| Kept out | Why |
| :--- | :--- |
| `.env` | Access key. |
| `WebInterface/backend/*.json`, `recordings/`, `change_refs/`, `static/` | Run-time data; contains camera passwords. |
| `*.pt`, `*.onnx`, `*.plan`, `*.engine`, `*.trt`, `*.ts`, `*.pkl` | Model weights (large, machine-specific). |
| `*.mp4`, `*.avi`, `*.png`, `*.jpg`, `*.jpeg` | Videos and images. |
| `.conda/`, `venv/`, `__pycache__/`, `.text_feat_cache/` | Environments and caches. |
| `*.log`, `Camera_System_Simulator/recordings/` | Logs and simulator output. |

The `*.png` / `*.jpg` rule also blocks images in the documentation; `!docs/images/*` is the exception for
the screenshots. Images elsewhere need their own exception.
