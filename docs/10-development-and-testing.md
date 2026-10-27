# 10 — Development and testing

## Working set-up

The easiest way to work without disturbing the running system is to start a second instance of the same
code with its own data directory:

```bash
AEGIS_DATA_DIR=/tmp/aegis-dev EVREN_API_KEY="" .conda/bin/python -m uvicorn WebInterface.backend.server:app --port 8502 --reload --reload-dir WebInterface/backend
```

- `AEGIS_DATA_DIR`: the real cameras, rules and events are not touched.
- `EVREN_API_KEY=""`: no calls to the external service (no quota spent). Leave this variable out to try
  rule compilation or summaries.
- Interface files are read from disk on every request; for an HTML / CSS / JS change, reloading the
  browser is enough. On a Python change `--reload` restarts the server.

Changes under `Rule_Generator_LLM/` and `Object_Detection/` are not watched by `--reload`; restart the
server by hand.

## System check

```bash
.conda/bin/python WebInterface/tests/system_check.py --sim-ip <this machine's IP address>
```

The script starts a separate server on its own port, in a **temporary data directory**, with external
service calls switched off; runs 137 checks; and cleans up after itself. It does not touch the running
system. It takes about two minutes. The exit code is `0` only if every check passed. `--keep` keeps the
temporary directory.

| Group | What it verifies |
| :--- | :--- |
| 1. Start-up and interface files | The server does not load torch (memory < 300 MB), every file `index.html` refers to exists, there are no duplicate `id`s, every element the scripts look up exists on the page, cache headers. |
| 2. Idle behaviour | No CPU is used without cameras and clients. |
| 3. Settings | Invalid values are pulled into range; reset works. |
| 4. Camera registration | Input validation; an unreachable device is stored as offline; the password is not in the response. |
| 5. Rules | Create, update, delete, compile status, error codes. |
| 6. Event log | Test event, labelling, snapshot, storage counts, path traversal attempts. |
| 7. Live notification | A new event arrives at once over SSE. |
| 8. Live video | WebSocket delivers the source's frame rate, every frame is different, rate limit, MJPEG, anomaly score, obstruction zone, deleting a camera also deletes its rules. |
| 9. Load | No errors with 300 concurrent requests and p95 < 250 ms. |
| 10. Persistence | Records survive a restart, a half-done event does not stay "ongoing", "delete all" also deletes the files. |
| 11. Shutdown and single instance | Fast shutdown with open connections; a second server on the same data directory is refused; no tracebacks in the log. |
| 12. Summary shaping | Model answers are forced into headline + details + advice and the verdict is parsed (no model needed). |
| 13. Tracking and rule logic | Object tracking, condition evaluation, working hours, report figures and compiler answers (no model needed). |
| 14. Interface translations | The English catalogue is valid, and every `t("…")` text and every `index.html` text has an English entry (no server needed). |

Group 8 runs if the camera simulator is running and is reported as `SKIP` otherwise. The anomaly and
obstruction zone checks also need the analysis server.

**Run this check after every change.** When you add an endpoint or a behaviour, add a `check(...)` line to
the relevant group.

## Continuous integration (GitHub Actions)

`.github/workflows/ci.yml` runs on every push to `main` and on every pull request:

1. Sets up Python 3.10 and installs `requirements.txt` (with the system libraries of ffmpeg and OpenCV).
2. Compiles the Python files (`compileall`) and checks the syntax of the interface scripts with
   `node --check`.
3. Runs the system check.

GitHub's machines have no graphics card, analysis server or cameras. The system check notices this
itself: it reports group 8, which needs live video, as `SKIP` and runs the other **115 checks**
(interface files, settings, camera registration, rules, event log, live notification, load, persistence,
shutdown, summary shaping, object tracking, rule logic, working hours, report figures and translations).
The live video, anomaly and obstruction zone checks (22 checks) only run on a machine with the simulator
and Triton running; **running the full check by hand on the development machine before merging is
therefore still necessary.**

If the check fails, the last step of the workflow prints the server's log. No external service key is
needed; the check switches language model calls off itself.

The result appears in the repository's **Actions** tab on GitHub and as the mark next to every commit. To
protect the `main` branch: under *Settings → Branches → Add rule → Require status checks to pass*, choose
"Sistem testi".

No automatic deployment (CD) is defined: the system runs on a single local machine with a graphics card
and has no target in the cloud. If the full check should run automatically too, the development machine
can be connected to GitHub as a "self-hosted runner"; if the repository is public, this is not
recommended, because it lets pull requests from strangers run code on that machine.

## Accuracy measurement

The system check answers "does it work"; `accuracy_check.py` answers "how accurate is it".

```bash
.conda/bin/python WebInterface/tests/accuracy_check.py                    # every labelled video
.conda/bin/python WebInterface/tests/accuracy_check.py --only Test_Videos  # those whose path contains this text
.conda/bin/python WebInterface/tests/accuracy_check.py --no-summaries      # without calling the language model
```

**What it does.** For each group of videos it starts a private media server and a private backend (own
ports, temporary data directory; the running system is not touched), publishes the videos **once, in real
time** as RTSP cameras, and looks at what unusual activity detection does with them. While a video plays,
it samples the camera's score; when it ends, it reads the events the system recorded from the log.
Nothing is mocked: the figures are those of the real pipeline (stream, model, thresholds, event logic,
summary).

**Labels** are in `WebInterface/tests/accuracy_labels.json`:

```json
{"file": "Anomaly_Detection/Test_Videos/test_video_15.mp4", "expect": "event", "what": "Kişi kapı önünde düşüyor", "window": [2, 8]}
```

| Field | Meaning |
| :--- | :--- |
| `file` | Video path relative to the repository root (the videos are not in the repository; a missing file is skipped). |
| `expect` | `event`: an event is expected. `none`: no event; every alarm is a false alarm. `unknown`: played and reported but not counted. |
| `window` | Optional `[start, end]` in seconds: the event counts only if caught within this range (±3 s); alarms outside it are false alarms. |
| `what` | Description for people; no effect on the measurement. |

The first list in the label file is a **draft**: it was derived from small frames of the videos. The
figures should not be taken as final until someone who knows the videos has reviewed it.

**Report** (`accuracy_report/report.md` and `report.json`; elsewhere with `--out`):

- **Summary:** in how many videos with an incident an event was caught, and which were missed; how many
  false alarms in videos without incidents, and how many per hour; what the summary's "real / ordinary"
  verdict said on real incidents and on false alarms; into how many separate records one incident was
  split.
- **What other thresholds would do:** from each video's highest score, how many incidents would be caught
  and how many videos without incidents would alarm if the warning threshold were 10, 20, … 90. Use this
  table to choose a threshold.
- **Videos:** for each video the expectation, the result, the highest score, and the second, score and
  summary of each alarm.

**Things to know**

- Thresholds and recording settings are taken from the **running installation's** `settings.json`
  (another file can be given with `--settings`); the report therefore describes the system as it is
  currently set. Unusual activity detection is always on during the measurement.
- It runs in real time: the duration is close to the total length of the videos (`--parallel` videos play
  at once). It shares the analysis server with the running system; do not run other heavy work meanwhile.
- With summaries on, the language model is called once per event; if the service's daily quota is
  limited, use `--no-summaries`.
- The first frame of each video is held for 8 seconds (so the system can connect to the stream); times are
  relative to what follows.
- Needs the analysis server, `ffmpeg` and the simulator's MediaMTX binary. Does not run in CI.

### First measurement (9 October 2026)

With the draft labels and the installation's settings of that day (warning threshold 39, critical 40,
event merge 1 s):

| Measure | Result |
| :--- | :--- |
| 11 videos with an incident | An event was caught in 10 (91 %). Missed: a car hitting someone in a street at night (highest score 23). |
| 63 videos without incidents, 73 minutes | 2 false alarms (1.6 per hour): a change of light colour on a standing person, and the first second of a video of a walking crowd. |
| With threshold 60 | Still 10 / 11 incidents, 0 false alarms. With threshold 20: 11 / 11 incidents, alarms in 3 videos without incidents. |
| Records one incident was split into | 3.7 on average (merge 1 s). 2.7 with a 5 s merge. |
| The summary's verdict | Called about a third of the alarms belonging to real incidents "real" and half of them "ordinary"; confirmed at least one alarm in 7–8 of the 10 incidents. It could not see falls that were not obvious (a worker falling in front of a forklift, a person falling at a door). |

Three changes to improve the summary's verdict were measured on the same videos and **none made a
difference**: giving the summary more footage around the incident, doubling the frame size, and merging
events over a longer time. The verdict should therefore stay information only and not be used to suppress
alarms; improving it needs another approach (more frames, a stronger model, or one that sees the video
directly).

Limits: the labels are a draft; 11 incident videos are few (one video moves the result by 9 points); all
of the footage without incidents comes from a single office; the videos are collected clips, not footage
from customer cameras.

## Unit tests

```bash
.conda/bin/python Object_Detection/run_tests.py
```

These are the detection library's tests. **They load models and need several GB of memory.** On the 16 GB
development machine, running them while the live system, the simulator and Triton were running exhausted
the memory and the kernel killed processes. Check with `free -h` first and stop the web server if needed.

## Deliberately untested

- **Rule compilation and incident summaries** need real language model answers; the system check runs
  with them off. To try them by hand, start the development instance without `EVREN_API_KEY` (i.e. with
  the key in `.env`), save a rule and regenerate an event's summary.
- **The visual behaviour of the interface** is not tested automatically; only its structural consistency
  (group 1) and translation coverage (group 14) are.
- **Real hardware cameras** have not been tested; all verification was done with the simulator.

## Common changes

### A new API endpoint

1. Write the business logic in the relevant service (`backend/*.py`).
2. Add the endpoint to the right router under `backend/api/`; if it needs a body, add a model to
   `api/schemas.py`. Make blocking calls through `asyncio.to_thread`.
3. Add its counterpart to `frontend/js/api.js`.
4. Add at least one success and one failure check to `tests/system_check.py`.
5. Update `docs/06-api.md` (and `docs/tr/06-api.md`).

### A new setting

1. `settings_service.py`: add the default to `DEFAULT_SETTINGS` and the range to `_sanitize`.
2. Add it to the `_load_settings` / `reload_settings` function of the service that reads it.
3. `frontend/index.html`: add a control with a `data-setting="section.field"` attribute to the Settings
   form (usually no JavaScript is needed) and its English entry to `js/i18n-en.js`.
4. Add it to the table in `docs/09-data-and-configuration.md` (and the Turkish chapter).

### A new rule condition

1. `Rule_Generator_LLM/schema.py`: add it to `ConditionType`; add fields to `Condition` if needed.
2. `Rule_Generator_LLM/evaluator.py`: add a branch to `_evaluate_condition` and an `_eval_<name>`
   function; write the violation message in plain Turkish.
3. `Rule_Generator_LLM/prompts.py`: add the condition and an example of it to the compiler prompt.
4. `frontend/js/labels.js`: add its plain-language name to `CONDITION_LABELS`, the English entry to the
   catalogue, and a pattern to `alarmText()` if the violation message is new.
5. Add it to the table in `docs/08-rules-and-analysis.md` (and the Turkish chapter).

### A new model class or model

- For the class name to read naturally in the interface: `frontend/js/labels.js` (`CLASS_LABELS`) and its
  catalogue entry, `Rule_Generator_LLM/evaluator.py` (`_CLASS_LABELS`) and `Rule_Generator_LLM/manual.py`
  (`_CLASS_LABELS_EN`).
- For the compiler to know the class: the class lists at the top of `Rule_Generator_LLM/compiler.py`.
- For a new Triton model: `Object_Detection/model_repository/<name>/config.pbtxt` and the model mapping in
  `Object_Detection/detector.py`.

### A new interface page
See [07 — Interface code](07-frontend.md), "Adding a page".

### A new interface text
Write it in Turkish inside `t("…")` or in `index.html` and add the English entry to `js/i18n-en.js`; the
system check (group 14) names any text without one. See [07 — Interface code](07-frontend.md),
"Interface language".

## Code conventions

**Python**
- A docstring at the top of each module saying what it is for; comments say "why".
- Times, thresholds and limits are named constants at the top of the module.
- Services import each other directly; `api/` only calls services.
- `logging` instead of `print`; in new modules the logger name has the form `aegis.<topic>`.
- Error messages returned to the user are in Turkish and actionable (and have a catalogue entry so they
  are shown in English too).
- Disk writes go through `paths.atomic_write_json`; long loops check `SHUTTING_DOWN`.

**JavaScript / CSS**
See [07 — Interface code](07-frontend.md), "Rules".

**Documentation**
The chapters exist in English (`docs/`) and Turkish (`docs/tr/`); a change to one belongs in the other.

No automatic formatter or linter (ruff, eslint) is set up in the repository; adding one is a good first
task.

## Version control

- Run-time data, model weights, videos and `.env` do not enter the repository
  (see [09](09-data-and-configuration.md), "What `.gitignore` covers").
- `Anomaly_Detection/` is a submodule: `git submodule update --init`.
- Before a commit: check with `git status` that only source files are added, and run the system check.
