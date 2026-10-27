# 01 — Overview

## What the system does

AegisVision gathers the IP cameras of a network into one web interface and examines their video
continuously in two ways:

1. **Unusual activity detection.** The latest frames of every camera are given to an anomaly model.
   Movement that does not fit the normal flow — fights, panic, running — opens an event.
2. **Rule checking.** The user draws a zone on a camera picture and says what should trigger an alert
   there, either in a plain sentence ("if someone without a hard hat enters") or by choosing from lists.
   The system turns the sentence into a detection plan once, then applies the plan to every frame.

Every event is recorded with its video, a snapshot of the key moment and a short written summary. The
operator watches the event and marks it as a "true alarm" or a "false alarm".

## Key capabilities

| Capability | Description |
| :--- | :--- |
| Camera discovery | Finds ONVIF cameras on the network automatically; cameras can also be added by address. |
| Live view | 1 / 4 / 6 / 12-camera wall, at each camera's own frame rate, without delay. |
| Alarm highlight | The frame of a camera in alarm is coloured and its corner names the reason. |
| Unusual activity | Works without any rule; sensitivity is set with two thresholds. |
| Rule zones | A polygon plus a plain sentence or choices from lists; person / object rules and obstruction / change monitoring. A rule can have working hours; the system says when a request is beyond what it can observe. |
| Event records | One video per event, the snapshot of its key moment, a written summary, the operator's verdict. |
| Export | The filtered event list is downloaded as CSV. |
| Reports | Event counts by day, rule and camera, false alarm rate, total violation time; printable. |
| Storage management | A quota for recordings; when it is full, the oldest videos are deleted. |
| Languages | The interface is in Turkish (default) or English, chosen per device; light, navy and dark themes. |

## Components

```
┌───────────────┐   RTSP    ┌──────────────────────────────────────────┐   HTTP    ┌──────────────┐
│ IP cameras    │──────────►│ Web server (WebInterface/backend)        │──────────►│ Analysis     │
│ (or the       │   ONVIF   │  • camera workers (one per camera)       │   tensors │ server       │
│  simulator)   │◄──────────│  • anomaly loop                          │◄──────────│ (Triton, GPU)│
└───────────────┘           │  • rule loop                             │    scores └──────────────┘
                            │  • event log, video / snapshot storage   │
                            │  • HTTP API + interface files            │   HTTPS   ┌──────────────┐
                            └───────────────┬──────────────────────────┘──────────►│ Language     │
                                            │ HTTP / WebSocket / SSE                │ model service│
                                            ▼                                       │ (EVREN)      │
                                   ┌─────────────────┐                              └──────────────┘
                                   │ Browser         │
                                   └─────────────────┘
```

| Component | Directory | Role |
| :--- | :--- | :--- |
| Web server | `WebInterface/backend/` | Takes video from the cameras, runs the analysis, records events, serves the API. |
| Interface | `WebInterface/frontend/` | The six-page application running in the browser. |
| Rule engine | `Rule_Generator_LLM/` | Turns sentences into plans, tracks objects across frames, evaluates plans, writes incident summaries. |
| Detection library | `Object_Detection/` | `YOLODetector`, which sends detection requests to Triton, and the model repository. |
| Analysis server | Docker: `triton_yoloe_server` | Runs the four models on the GPU. |
| Language model service | external service | Rule compilation and incident summaries. If it is unreachable, the rest of the system keeps working. |
| Simulator | `Camera_System_Simulator/` | Publishes video files as cameras, for development. |
| Model training | `Anomaly_Detection/` | Training code of the anomaly model (submodule); not part of the running system. |

## Models on the analysis server

| Model | Input | Purpose |
| :--- | :--- | :--- |
| `anomaly_detector` | 16-frame clip, 224×224 | Unusual activity score (0–100). |
| `safety_detector` | one frame | Workplace safety classes: hard hat, vest, mask and their absence, person, vehicle, machinery, cone. |
| `coco_detector` | one frame | Everyday objects (80 COCO classes): person, car, bag… |
| `yoloe_detector` | one frame + class names | Open-vocabulary detection: objects not in the lists above (forklift, pallet…). |

The rule compiler decides which rule uses which model (see chapter 08).

## Terms

| Term | Meaning |
| :--- | :--- |
| Event | A recorded alarm: unusual activity or a rule violation. |
| Level (`tier`) | The importance of an event: `warning` or `critical`. Cameras also have `normal` and `offline`. |
| Score | The anomaly model's output, between 0 and 100. The thresholds apply to this number. |
| Zone | A polygon drawn on the picture. Corners are stored between 0 and 1, independent of resolution. |
| Detection plan | The compiled form of a zone description: which model, which classes, which condition. |
| Reference picture | The "empty" state of an obstruction / change zone; the live picture is compared with it. |
| Evidence | The video (clip) and snapshot of an event. |
| Camera worker | The background thread that decodes a camera's RTSP stream. |
| Data directory | Where cameras, rules, settings and events are stored (`AEGIS_DATA_DIR`). |
