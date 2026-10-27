# Smart Surveillance System — Web Interface and Server

> This is a short guide to the web layer, the part of the system that operators use and that ties every
> other component together. The full documentation is in [`docs/`](../docs/README.md) (English; Turkish in [`docs/tr/`](../docs/tr/README.md)).

The web layer discovers IP cameras on the network, streams them live, runs unusual-activity analysis and
rule checks on them, and records every incident with its video, key frame and summary. It is a FastAPI
server and a browser interface that needs no build step.

---

## 1. Running it

```bash
./WebInterface/run.sh
```

The interface opens at **http://localhost:8500** (and at the machine's address on the network).

| Environment variable | Default | Purpose |
| :--- | :--- | :--- |
| `AEGIS_DATA_DIR` | `WebInterface/backend` | Where cameras, rules, settings, events, clips and snapshots are stored. Pointing it elsewhere runs a second, fully separate instance without touching the real data; a second server can never start on the same directory. |
| `EVREN_API_KEY`, `EVREN_BASE_URL`, `EVREN_VLM_MODEL` | key empty | The language-model service that compiles rule sentences and writes incident summaries. The key goes into `.env` at the repository root (template: `.env.example`). Without a key no external call is made: rules can still be defined from lists, sentence rules show "Could not be prepared", and events are recorded without summaries. |

---

## 2. The interface

Six pages, ordered by how often they are used. Every page works on a phone as well as a desktop.

| Page | What it is for | Why it matters |
| :--- | :--- | :--- |
| **Canlı İzleme** (Live) | Camera wall in 1 / 4 / 6 / 12 layouts. A camera in alarm is outlined and labelled with the reason; "only cameras in alarm" filters the wall; clicking a camera enlarges it with its recent history. | The operator's attention goes straight to the camera that needs it. |
| **Olaylar** (Events) | Every recorded incident with video, snapshot and short summary. Search, filters, true / false verdict, CSV export. New events appear without reloading; an ongoing rule violation is shown as one event marked "Sürüyor". | Each alarm can be verified in seconds, and the verdicts feed the false-alarm statistics. |
| **Kurallar** (Rules) | Draw a zone on the camera picture and say what should trigger an alert — in a sentence or by choosing from lists — and, optionally, the hours in which the rule applies. Under each zone the system states in one sentence what it understood. | Site policies become automatic checks without programming, and the operator always sees what will actually be enforced. |
| **Raporlar** (Reports) | Events by day, rule and camera, false-alarm rate, total violation time; printable or saved as PDF. | Turns monitoring into measurable safety performance. |
| **Kameralar** (Cameras) | Network discovery, adding by address, renaming, reconnecting, removing. | Getting a site running takes minutes, not a technician's visit. |
| **Ayarlar** (Settings) | Detection sensitivity, live wall preferences, recording length and storage, theme. Installation values sit under "Gelişmiş". | Everyday settings are understandable; technical ones stay out of the way. |

The status line in the menu says in one phrase whether the system is working. If the analysis server is
unreachable, a red notice appears on every page — a rule that is not being checked never looks like one
that is. Technical details (stream address, resolution, GPU state, inference times) are kept out of the
daily screens and shown in the camera information window and under Settings → Gelişmiş.

---

## 3. Code structure

```
WebInterface/
├── run.sh                       Starts the server
├── backend/
│   ├── server.py                Application: start-up and shutdown, middleware, routers
│   ├── api/                     HTTP layer — one module per subject, no business logic
│   │   ├── cameras.py  live.py  rules.py  events.py  reports.py  settings.py  system.py
│   │   ├── frontend.py          Serves the interface files
│   │   └── schemas.py           Request bodies
│   ├── camera_service.py        Camera records, one RTSP worker per camera, live frame distribution
│   ├── anomaly_service.py       Unusual-activity analysis; turns scores and rule violations into events
│   ├── event_journal.py         Event log (persistent list, operator verdicts, counters)
│   ├── evidence_store.py        Event clips and snapshots (encoding, quota, orphaned files)
│   ├── event_stream.py          Live event notifications to open pages (SSE)
│   ├── live_detection_service.py  Evaluates rules on live video (detection, tracking, confirmation)
│   ├── rule_compilation.py      Turns zone descriptions into detection plans in the background
│   ├── reports.py               Report figures computed from the event log
│   ├── change_detector.py       Obstruction / change zones (comparison with a reference picture)
│   ├── rules_service.py  settings_service.py  system_stats.py
│   ├── onvif_core.py  onvif_auth.py   Camera discovery and ONVIF communication
│   └── paths.py                 Data directory, safe file writes, single-instance lock
├── frontend/
│   ├── index.html               Page skeleton (no inline styles or scripts)
│   ├── css/                     base → components → layout, then one file per page
│   └── js/
│       ├── theme.js                         Theme of this device, applied before the first paint
│       ├── i18n.js  i18n-en.js              Interface language (Turkish / English) and the English catalogue
│       ├── main.js  router.js  shell.js     Entry point, page switching, always-visible parts
│       ├── api.js                           The only module that talks to the server
│       ├── ui.js  labels.js                 Shared components and plain-language wording
│       ├── live.js  stream.js  overlay.js   Live wall, video streaming, overlays
│       ├── events.js  event-detail.js       Event list and event window
│       ├── rules.js  zone-editor.js         Rule list and form, zone drawing tool
│       ├── reports.js                       Reports page
│       └── cameras.js  settings.js
└── tests/
    ├── system_check.py          End-to-end system test (137 checks)
    ├── accuracy_check.py        Accuracy measurement on labelled videos
    └── accuracy_labels.json     Labels for the accuracy measurement
```

Conventions that keep the code predictable:

* Every page module exposes the same interface: `mount(params)`, `unmount()` and, where needed,
  `canLeave()`. A page that is not visible holds no timers and no open connections.
* Pages never build server URLs or call `fetch`; they use the functions of `api.js` only.
* Clicks are handled through `data-action` attributes and one listener per area; there are no global
  `window.*` functions and no inline `onclick`.
* Every text that comes from a user or from the server is escaped with `escapeHTML` before it reaches the page.
* Colours are never written directly: styles use role variables (`--primary`, `--accent`, `--warn`, …)
  defined per theme in `base.css`.
* Every interface text is written in Turkish inside `t("…")` and has an English entry in `js/i18n-en.js`;
  the system test fails on any text without one.
* No build step: the browser loads native ES modules. Files are served from `/ui/...` with
  `Cache-Control: no-cache`, so a browser always picks up the current version.

---

## 4. Testing

```bash
.conda/bin/python WebInterface/tests/system_check.py
```

The system test starts its own server on a free port with a **temporary data directory** (external calls
disabled), exercises the entire HTTP / WebSocket / SSE surface and cleans up after itself; the real data
is never touched. It also checks the interface itself: every file `index.html` references exists, every
element the scripts look up is present, and no id is duplicated. When the camera simulator and the
analysis server are running, the live checks run too (stream rate, signal loss, change detection, rule
violations that last, event snapshots); otherwise they are reported as `SKIP`. The exit code is `0` only
if every executed check passed.

```bash
.conda/bin/python WebInterface/tests/accuracy_check.py --no-summaries
```

The accuracy harness plays labelled videos to a private copy of the system as real cameras and reports
caught incidents, missed incidents, false alarms and what other thresholds would have given. Use it to
prove that a change to detection is an improvement. Details: [docs/10](../docs/10-development-and-testing.md#accuracy-measurement).

---

## 5. Connecting to cameras (ONVIF)

Real installations are messy: several network cards, cameras with wrong clocks, and browsers that cannot
play RTSP. The web layer handles all three.

### A. Discovery on every network interface
A Linux host often has several interfaces (Wi-Fi, Ethernet, Docker bridges). The server:
1. finds every active physical interface with an IPv4 address;
2. sends WS-Discovery probes to `239.255.255.250:3702` through each of them (`IP_MULTICAST_IF`);
3. sends both `dn:NetworkVideoTransmitter` and `tds:Device` probes, so older and newer cameras both answer.

### B. Clock-tolerant authentication (WS-Security PasswordDigest)
Cameras reject requests whose timestamp disagrees with their own clock (`401 Unauthorized` or
`wsse:FailedAuthentication`). The server:
1. reads the camera's UTC time with the unauthenticated `GetSystemDateAndTime` call;
2. computes the offset $\Delta t = t_{camera} - t_{client}$;
3. applies it to every request, so `wsu:Created` is valid from the camera's point of view:
   $$\text{PasswordDigest} = \text{Base64}\Big(\text{SHA-1}\big(\text{nonce bytes} + \text{UTC time} + \text{password}\big)\Big)$$

### C. Live video
Browsers cannot play `rtsp://` directly. One background worker per camera decodes the stream, and live
viewing, analysis and event clips all share that single source of frames — a camera is opened once, no
matter how many viewers or rules use it. Frames reach the browser over WebSocket at the camera's own
rate; a slow client skips frames but never falls behind.

---

## 6. API

Interactive documentation is served at `http://localhost:8500/docs` while the server runs; the full
reference with examples is [docs/06](../docs/06-api.md).

| Subject | Endpoints |
| :--- | :--- |
| System | `GET /api/health`, `GET /api/system/stats`, `POST /api/onvif/scan` |
| Cameras | `GET /api/cameras`, `POST /api/cameras/add`, `PUT` / `DELETE /api/cameras/{id}`, `POST /api/cameras/{id}/reconnect`, `GET /api/cameras/{id}/snapshot`, `GET /api/cameras/{id}/stream` (MJPEG), `WS /api/cameras/{id}/ws` |
| Live state | `GET /api/live/state`, `GET /api/cameras/{id}/live-detections`, `GET /api/change-detection/{camera}/{zone}`, `POST …/capture-reference`, `DELETE …/reference` |
| Rules | `GET` / `POST /api/rules`, `GET` / `PUT` / `DELETE /api/rules/{id}`, `GET /api/rules/{id}/plan` (diagnostics), `POST /api/rules/{id}/compile` |
| Events | `GET /api/anomaly/journal`, `GET /api/anomaly/stats`, `GET /api/anomaly/status`, `GET /api/anomaly/events-stream` (SSE), `POST /api/anomaly/{id}/label`, `POST /api/anomaly/{id}/summarize`, `GET /api/anomaly/{id}/frames`, `POST /api/anomaly/clear`, `POST /api/anomaly/simulate`, `GET /api/anomaly/clips/{file}`, `GET /api/anomaly/snapshots/{file}`, `GET /api/anomaly/storage`, `POST /api/anomaly/storage/cleanup-orphans` |
| Reports | `GET /api/reports/summary?days=1..90` |
| Settings | `GET` / `POST /api/settings`, `POST /api/settings/reset` |

Event endpoints live under `/api/anomaly/` for historical reasons; they cover rule violations too.
