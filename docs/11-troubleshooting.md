# 11 — Troubleshooting

First look at the status line at the bottom of the menu and at the server's terminal output. Quick status
queries:

```bash
curl -s localhost:8500/api/system/stats | python3 -m json.tool
```
```bash
curl -s localhost:8500/api/anomaly/status | python3 -m json.tool
```

## The server does not start

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| "Another AegisVision server is using this data directory (…)" | A server with the same data directory is running. | Find it with `pgrep -fa uvicorn` and stop it, or give a different `AEGIS_DATA_DIR`. |
| `Address already in use` | Port 8500 is taken. | Stop the old process. |
| `ModuleNotFoundError` | Wrong Python or a missing package. | Use `./WebInterface/run.sh`; `./.conda/bin/pip install -r requirements.txt`. |
| It starts but restarts at once | `--reload` saw a Python file change. | Expected behaviour. |

## Interface

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| The old interface appears or the page is blank | The browser shows the previous version from its cache. | Press F5 once. If it persists, Ctrl+Shift+R. |
| Red "Connection to the server lost" band at the top | The browser cannot reach the server. | Check that the server runs and the network is reachable; the band disappears by itself when the connection returns. |
| "Analysis stopped" | Triton cannot be reached. | Check with `docker ps` that `triton_yoloe_server` is running; check the address under Settings → Advanced. |
| The page is open but the video does not move | The tab is in the background. | Video is deliberately stopped in a hidden tab; it starts when you return to the tab. |
| Some texts are Turkish in English mode | They are stored texts (summaries, rule notes, names) or the server-drawn "no signal" card. | Expected; see "Known limits". Any other Turkish text is a missing catalogue entry: the system check (group 14) names it. |
| The language or theme reset itself | The browser does not keep site data (private window, cleared storage). | Choose it again under Settings → Appearance; it is stored per browser. |

## Cameras

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| The scan finds no camera | The camera is on another subnet or multicast is blocked. | Type its IP address with "Add manually". |
| "Wrong password" | The ONVIF account is wrong. | Add the same address again with "Add manually" and the right details (the record is updated). |
| "No signal" | The stream cannot be opened: camera off, RTSP port closed, address changed. | Try `ffprobe <stream address>` (address: the camera's info window). If the address changed, delete it and add it again. |
| "Connecting…" for a while at start-up | Normal; can take up to 20 seconds. | Wait. |
| Says "Ready" but no picture | The connection was released because the camera was not in use. | It connects when opened in Live view. |
| The picture stutters | Not enough network or CPU. | Switch off Settings → "Full frame rate" (8 frames per second); choose a layout with fewer cameras. |

## Events

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| No events at all | Detection is off, the analysis server is down, or the threshold is high. | Settings → Detection; the status at the bottom of the menu; lower the warning level. |
| Too many events | The threshold is low for the scene. | Raise the warning level; increase the "Event merge time". |
| The event has no video | Recording is off; the camera had just connected (< 1 s of footage); the video was deleted by the quota. | Settings → Recording; for the quota, "Storage for recordings". |
| The video plays too slowly or too fast | — | The frame rate is computed from the capture times; if it persists, report it as a bug. |
| No summary arrives | No key, the service is down, or the quota is used up. | The note in the event window gives the reason. Check `EVREN_API_KEY` in `.env`; restart the server. |
| The summary is wrong or irrelevant | The model writes from eight small frames. | Enter a description for the camera (Cameras → edit); "Regenerate". |

## Rules

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| "Could not be prepared" | The language model service cannot be reached or there is no key. | Check the key and network access; "Retry". Or define the zone from lists, which needs no service. |
| "Running with a generic setting" | The description could not be turned into a plan. | Write a concrete sentence with one condition (see the user guide). |
| The rule is ready but never alarms | The rule is off or outside its working hours; the object is not a class the model knows; the object is outside the zone. | Switch on "Detections" in Live view and see whether boxes are drawn. To see the plan: `GET /api/rules/{id}/plan`. |
| It alarms all the time | The condition is always met in the scene (e.g. someone already works in the zone). | Make the zone smaller or the description more precise. |
| Obstruction zone "waiting for reference" | No reference was taken. | While the zone is clear: Live view → "Take reference". |
| Obstruction zone always in alarm | The light or the camera angle changed for good. | Take the reference again. |

## Analysis server

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| The container does not start | Docker or the NVIDIA Container Toolkit is missing. | `python Object_Detection/check_environment.py`. |
| A model does not load | `model.plan` was built on another graphics card. | Rebuild the engines on this machine (`convert_to_tensorrt.sh`). |
| Out of memory | Four models are at the limit on a 4 GB card. | Remove an unused model from the repository; lower `batch_size`. |

## Memory

The server's memory grows with the number of cameras and with `max_clip_duration_sec` (see
[09](09-data-and-configuration.md), "Memory and disk"). If the machine has no swap, the kernel kills a
random process when memory runs out; the symptom is a process vanishing without a trace. Check:
`journalctl -k | grep -i "out of memory"`.

## Known limits

| Topic | Status |
| :--- | :--- |
| Authentication | None. The interface and the API are open to everyone on the network; CORS allows every origin. |
| Camera passwords | Plain text in the data directory. |
| Access key | An old key remains in the git history; it must be rotated. |
| Scale | One process, one machine; data in JSON files. Tested with 9 cameras. |
| Recording | No continuous recording; event videos only. |
| Object tracking | Within one camera and by box position only; no direction, line crossing or in/out counting. |
| Person recognition | None. |
| Browser | Tested in Chromium-based browsers; Firefox not tested. |
| Hardware | Tested with the simulator, not with real cameras. |
| Language | The interface is in Turkish and English. Incident summaries, rule compiler notes and the server-drawn status cards are Turkish only; rule descriptions are understood in Turkish (English usually works). |
