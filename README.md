# Smart Surveillance System (AegisVision)

A security surveillance system that aggregates IP cameras into a unified interface, detects unusual activity and natural language rule violations, and logs them with video clips, snapshots, and concise text summaries.

- **Live Monitoring:** 1 / 4 / 6 / 12 camera wall grid; cameras with active alarms are highlighted.
- **Anomaly Detection:** Works without rule definitions (fights, panic, running, etc.).
- **Rule Zones:** Draw regions on the camera feed and define trigger criteria in natural language
  ("If someone without a hard hat enters", "If someone enters between 22:00 and 06:00") or select from presets.
  The system indicates if a request is unsupported; rules can be scheduled to run only during designated hours.
- **Obstruction Monitoring:** Monitors areas that must remain clear, such as emergency exits and fire hose cabinets.
- **Event Logging:** Single continuous video per event, snapshot at time of incident, text summary, and operator review.
- **Reports:** Event counts by date, rule, and camera, false alarm rates; printable.

## Interface

| Live Monitoring | Events |
| --- | --- |
| ![Live monitoring wall](docs/images/canli-izleme.jpg) | ![Events list](docs/images/olaylar.jpg) |
| Camera wall grid; layout, zones, and detection overlays can be toggled from the top bar. | Recorded events; search, filter, and one-click true / false alarm review. |

| Event Details | Rule Editor |
| --- | --- |
| ![Event modal](docs/images/olay-penceresi.jpg) | ![Rule editor](docs/images/kural-duzenleyici.jpg) |
| Event video, concise text summary, and operator review. | Draw zones on video feed and define trigger criteria in plain language. |

| Cameras | Settings |
| --- | --- |
| ![Cameras](docs/images/kameralar.jpg) | ![Settings](docs/images/ayarlar.jpg) |
| Network camera discovery, manual addition, status monitoring, and editing. | Detection sensitivity, recording duration, and storage management. |

Screenshots are captured from test video playback via `Camera_System_Simulator`.

## Quick Start

Requirements: Linux, NVIDIA GPU, Docker + NVIDIA Container Toolkit, Python 3.10, ffmpeg.
Detailed setup instructions and model file installation: [docs/02-kurulum.md](docs/02-kurulum.md).

```bash
conda create -p ./.conda python=3.10 -y && ./.conda/bin/pip install -r requirements.txt
```
```bash
cp .env.example .env        # Set the LLM service API key (optional)
```
```bash
./Object_Detection/start_triton_docker.sh                        # 1. Start inference server
```
```bash
cd Camera_System_Simulator && ./start.sh --dir ../TestVideoSet   # 2. If no physical cameras are available
```
```bash
./WebInterface/run.sh                                            # 3. http://localhost:8500
```

In the web interface: **Cameras → Scan network for cameras → Add all**, then navigate to **Live Monitoring**.

## Documentation

| | |
| :--- | :--- |
| [Overview](docs/01-genel-bakis.md) | What the system does, components, terminology |
| [Installation & Setup](docs/02-kurulum.md) | Requirements, models, startup procedure, ports |
| [User Guide](docs/03-kullanim-kilavuzu.md) | Step-by-step guide for the five interface pages |
| [Architecture](docs/04-mimari.md) | Processes, threads, data flow, design decisions |
| [Backend Modules](docs/05-backend.md) | `WebInterface/backend` module reference |
| [API Reference](docs/06-api.md) | All endpoints, example requests and responses |
| [Frontend Architecture](docs/07-frontend.md) | `WebInterface/frontend` structure and conventions |
| [Rules and Analytics](docs/08-kurallar-ve-analiz.md) | Rule compilation, condition types, event lifecycle, summaries |
| [Data and Configuration](docs/09-veri-ve-yapilandirma.md) | Files, storage formats, settings, environment variables |
| [Development and Testing](docs/10-gelistirme-ve-test.md) | Development workflow, system testing, common modifications |
| [Troubleshooting](docs/11-sorun-giderme.md) | Symptom-based solutions, known limitations |

## Repository Layout

| Directory | Content |
| :--- | :--- |
| `WebInterface/` | **Product:** Web server (`backend/`), UI (`frontend/`), system tests (`tests/`). |
| `Rule_Generator_LLM/` | Rule compiler, object tracking, condition evaluator, event summarizer, LLM service configs. |
| `Object_Detection/` | Object detection library and Triton model repository. |
| `Anomaly_Detection/` | Anomaly model training code (git submodule; not part of the runtime system). |
| `Camera_System_Simulator/` | Simulated cameras for development (RTSP + ONVIF). |
| `TestVideoSet/` | Sample videos streamed by the simulator (not tracked in repository). |
| `docs/` | Documentation. |

## Data Flow

```
Camera (RTSP) ──► camera_service ──► Browser (Live view via WebSocket)
                       │
                       ├─► anomaly_service ──► Triton: anomaly_detector ──► Score ──► Event
                       │
                       └─► live_detection_service ──► Triton: Object Detection ──► Rule Evaluation ──► Event

Event ──► event_journal (persistence) + evidence_store (video, snapshot) + vlm_summarizer (brief summary)
      ──► event_stream ──► Open browser pages
```

## Testing

```bash
.conda/bin/python WebInterface/tests/system_check.py --sim-ip <IP address of this machine>
```

Spins up an isolated server instance with temporary data on its own port and tests the entire web interface and API (134 checks); does not touch the running system. Should be run after every change.

Measuring **system accuracy** is handled separately: `WebInterface/tests/accuracy_check.py`
streams labeled test videos into the system like cameras and counts detected events, missed detections, and false alarms
(see [docs/10](docs/10-gelistirme-ve-test.md#doğruluk-ölçümü)).

The same check runs on every push via GitHub Actions (`.github/workflows/ci.yml`); since cameras and
GPUs are not available in CI, the live video portion is skipped and the remaining 112 checks are executed.

`Object_Detection/run_tests.py` loads models and requires several gigabytes of GPU memory; do not run while the live system is active.

## Developer Handoff Notes

- **Access Key / API Key:** Keys reside only in `.env` and are never committed. However, a previously
  used key **remains in git history**; it must be rotated.
- **No Authentication:** The web UI and API are accessible to anyone on the network; this must be addressed before exposing beyond a local network.
- **JSON File-Based Storage:** Designed for a single-server setup (atomic writes, directory lock);
  must be migrated to a database for multi-server deployments.
- **Large Functions Remaining:** `Rule_Generator_LLM/compiler.py: _normalize_plan_data` (~230 lines),
  `live_detection_service.py: _process_camera` (~190 lines), `camera_service.py: probe_and_register`
  (~125 lines). They are functional; refactoring them should be handled as a separate task since the first two can only be tested with real model outputs.
- **Untested Areas:** Physical camera hardware, Firefox, continuous multi-day operation.
  Full list: [docs/11-sorun-giderme.md](docs/11-sorun-giderme.md#bilinen-sınırlar) ("Known limitations").
