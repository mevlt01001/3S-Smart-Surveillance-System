# 04 — Architecture

## Processes

| Process | How it starts | State |
| :--- | :--- | :--- |
| Web server (uvicorn + FastAPI) | `WebInterface/run.sh` | JSON files and evidence files in the data directory |
| Analysis server (Triton) | `Object_Detection/start_triton_docker.sh` | None (stateless) |
| Language model service | External service | — |
| Browser | — | Theme and language preferences (`localStorage`) |

The web server is a single process and holds all of the business logic. It scales with threads inside
the process, not with several processes; for that reason a second server cannot run on the same data
directory.

## Inside the web server

```
                               ┌────────────────────────── asyncio event loop ─────────────────────────────┐
                               │  api/*  (HTTP routers, WebSocket, SSE)                                    │
                               └───────▲──────────────▲───────────────▲──────────────────▲─────────────────┘
                                       │ frames       │ state         │ events           │ notification
┌──────────────┐ frames  ┌─────────────┴───┐  ┌───────┴────────┐ ┌────┴───────────┐ ┌────┴─────────┐
│ CameraLive   ├────────►│ camera_service  │  │ anomaly_service│ │ event_journal  │ │ event_stream │
│ Worker × N   │         │ (registry +     │  │ (score → event)├►│ (stored list)  ├►│ (SSE)        │
│ thread       │         │  distribution)  │  └───────┬────────┘ └────────────────┘ └──────────────┘
└──────────────┘         └──────┬──────────┘          │ video, snapshot
                                │ frames              ▼
                                ▼              ┌────────────────┐
                       ┌───────────────────────┐ │ evidence_store │
                       │ live_detection_service│ │ (ffmpeg, quota)│
                       │ (rules → violation)   │ └────────────────┘
                       └───────────────────────┘
```

### Threads

| Thread | Count | What it does |
| :--- | :--- | :--- |
| Event loop | 1 | Runs HTTP requests and WebSocket and SSE connections. No blocking work is done here. |
| `CameraLiveWorker` | 1 per camera | Decodes the RTSP stream, keeps frames in memory, wakes those waiting. |
| Camera watchdog | 1 | Marks cameras that deliver no frames as offline. |
| `AnomalyWorker` | 1 | Sends cameras to the anomaly model in batches, opens and closes events. |
| `LiveDetectionWorker` | 1 | Runs object detection and rule evaluation on cameras with an active rule. |
| `RuleCompile_*` | per rule, temporary | Turns a rule's description into a plan with the language model. |
| `Clip-*`, `Summary-*` | per event, temporary | Encodes the video with ffmpeg; asks the language model for the summary. |

Every long-running or blocking job (model calls, ffmpeg, file scans) runs either in its own thread or
off the event loop through `asyncio.to_thread`; live video never waits for them.

## The journey of a frame

1. **Capture.** `CameraLiveWorker` opens the stream with OpenCV/FFmpeg over TCP with low-latency
   options. If the source is faster than 30 frames per second, the excess is dropped.
2. **Processed once.** Each frame is encoded to JPEG once (used by live video and event videos) and
   resized to 224×224 RGB once (used by the anomaly model).
3. **Kept in memory.** The JPEGs are kept with their timestamps in a ring buffer. Its length follows the
   longest event video that can be cut (longest video + both margins + merge time + 8 s).
4. **Distribution.** When a new frame arrives, waiting WebSocket connections are woken through the event
   loop (`loop.call_soon_threadsafe`); there is no polling. A slow client skips the frames in between.
5. **Analysis.** The anomaly loop and the rule loop only process cameras that **have a new frame**.

If nobody watches or analyses a camera, its worker releases the connection after 120 seconds ("Ready"
status) and reconnects on the first request.

## The journey of an event

### Unusual activity

```
score ≥ warning level ──► event opens (record + snapshot, "ongoing") ──► notification to the interface
        │
        ├─ while the score stays high: the peak moment is updated
        ├─ calm < merge time: the event continues
        ├─ duration ≥ longest video: the event closes; if movement continues, a new one opens
        ▼
calm > merge time ──► the event closes:
        • exact times, snapshot of the peak moment, record updated ──► notification to the interface
        • video: buffered frames [start − margin, end + margin] ──► ffmpeg ──► quota check
        • summary: eight of the same frames ──► language model ──► record updated ──► notification
```

### Rule violation

When a rule has been violated for at least 1 second, the rule loop calls
`anomaly_service.rule_violated` on every frame. The first call opens an event record with the frames of
the last 5 seconds (same video / summary path); later calls only keep the event open. When the rule has
not been violated for 10 seconds, the event closes with its real end time and duration. A violation that
lasts an hour is therefore one event.

## Design decisions

**One source, many consumers.** Live video, anomaly analysis, rule analysis and event videos share the
frames of the same camera worker. One RTSP connection is opened per camera.

**Events instead of polling.** Live frames are pushed over WebSocket; the event list is updated through
SSE. The only things the interface polls are status (`/api/live/state` every 400 ms,
`/api/system/stats` every 5 s).

**Showing the truth.** The server does not report a value it has not measured: the analysis time is
`null` if it was not measured in the last 15 seconds, and an anomaly score older than 10 seconds is
ignored. A camera whose signal is lost is reported as `offline`; a frozen frame is never shown as "live".

**The server does not load `torch`.** The web server does not run the models itself; it sends tensors to
Triton. The members of the `Object_Detection` package that need torch are loaded only on demand. Thanks to
this, the server uses about 110 MB of memory at start-up.

**Zero-copy Triton client.** An anomaly request for four cameras is 38 MB.
`Object_Detection/triton_fast_client.py` writes the NumPy buffer to the socket without copying it.

**Safe writes.** JSON files are written to a temporary file and renamed (`paths.atomic_write_json`); a
crash or a concurrent read never sees a half-written file. Videos are also encoded with a `tmp_` prefix
and renamed when done.

**Single-instance lock.** At start-up the server locks the `.aegis.lock` file in the data directory. A
second server on the same directory would rewrite the records from its own memory and overwrite the
other's data; the second process waits 20 seconds (the restart case) and exits with a clear message if
the lock is not released.

**Fast shutdown.** Browsers keep video and notification connections open indefinitely and the ASGI server
waits for open connections. On `SIGINT`/`SIGTERM`, `paths.SHUTTING_DOWN` is set first; every long-lived
loop sees it and exits.

**Interface cache.** The interface files are served under `/ui/` with `Cache-Control: no-cache`: the
browser asks on every load and gets `304` for an unchanged file. A new version therefore never mixes with
an old cache.

**Language on the client.** The interface is written in Turkish and translated in the browser from one
catalogue; the server only needs to know the language for the few sentences it writes on request (rule
plans, working hours), which it reads from the `Accept-Language` header. Stored texts are not translated.
Details: [07 — Frontend](07-frontend.md), "Interface language".

## Start-up order

When `server.py` is imported:

1. `backend/__init__.py` sets OpenCV's environment options (OpenCV reads them on first import).
2. `acquire_instance_lock()` locks the data directory — **before** the services load their records.
3. The service modules are imported; each creates one object at module level (`camera_service`,
   `anomaly_service`, …), loads its records and starts its thread.
4. The routers and the interface are attached to the application.

Module-level singleton services are a deliberate simplicity; the price is that importing a service starts
it. Tests therefore run the server in a separate process with a temporary data directory.

## Performance figures

Measured on the development machine (8 cameras, GTX 1650 Ti):

| Measure | Value |
| :--- | :--- |
| Server memory | 580–700 MB (with a 60 s frame buffer per camera) |
| Thread count | ~45 |
| CPU (8 cameras being watched) | ~125–135 % (one core = 100 %) |
| Frame rate reaching the browser | The source's rate (25 → 25, 30 → 30 frames per second) |
| API response time (p95) | 8–11 ms |
| Anomaly analysis | ~45–65 ms per camera, ~4 evaluations per second |
| Shutdown | < 1 s |
