# 08 — Rules and analysis

The system examines the picture along two independent paths: **unusual activity** (no rule needed) and
**rules** (zones the user draws). Both end in the same event recording path.

---

## A. Unusual activity

Code: `WebInterface/backend/anomaly_service.py`. Model: `anomaly_detector` on Triton.

### Producing the score

1. The last **16 frames** of each camera are taken as 224×224 RGB. If the stream has just connected and
   there are fewer than 16 frames, the oldest frame is repeated to fill the clip.
2. At most `batch_size` (default 4, at most 8) cameras are sent in one request. Tensor shape
   `[K, 3, 16, 224, 224]`, `float32` between 0 and 1.
3. The model output (`logits`, one number per camera) goes through a sigmoid and is multiplied by 100:
   **a score from 0 to 100**.
4. Only cameras that **brought a new frame** since the last round are scored. One round is 0.25 seconds.

### Smoothing

- If the score is **above** the warning level, it is used as is: alarms are not delayed.
- If it is **below**, it is blended with the previous value (`0.15 × previous + 0.85 × new`): the score
  does not flicker in a calm scene.

### Levels

| Score | `tier` | In the interface |
| :--- | :--- | :--- |
| < warning level (`threshold_normal`, default 25) | `normal` | — |
| ≥ warning level | `warning` | Suspicious movement / Warning |
| ≥ critical level (`threshold_warning`, default 50) | `critical` | Critical movement / Critical |

For historical reasons the setting names are confusing: `threshold_normal` is "where normal ends", i.e.
the **warning** threshold; `threshold_warning` is "where warning ends", i.e. the **critical** threshold.

The model only knows that the movement is unusual, not what it is. The title in the record
(`anomaly_type`) is therefore always **"Olağandışı hareket"** (`UNUSUAL_MOVEMENT`, shown as "Unusual
activity"); as soon as the summary is written, the interface shows the summary's headline instead ("A
person dropped a box from a pallet truck").

### Event life cycle

| State | Condition | What happens |
| :--- | :--- | :--- |
| Opening | Score ≥ warning level and no open event on the camera | A record is created (`anom_…`, `is_ongoing: true`); the current frame is stored as the snapshot. |
| Continuing | Score ≥ warning level | The last activity time moves on; if the score rose, the peak moment is updated. |
| Short pause | Score dropped, for ≤ `tolerance_sec` | The event continues (counted as one event). |
| Splitting | Duration ≥ `max_clip_duration_sec` | The event closes; if the movement continues, a new one opens in the next round. |
| Closing | Calm > `tolerance_sec` | The steps below. |

On closing (`_close_incident`):

1. Video range: `[start − padding_sec, last activity + padding_sec]`. The frames come from the camera's
   buffer in memory.
2. The record is updated: highest score and level, exact times, duration, `is_ongoing: false`. The
   snapshot taken at the opening is replaced with the frame of the **peak moment**.
3. If the frames cover at least 1 second of real footage and video recording is on, the video is encoded
   (in a separate thread). When encoding finishes, the disk quota is applied.
4. If the summary service is available, a summary is requested (in a separate thread).

Open events are closed when their time runs out even while analysis is off or the analysis server cannot
be reached.

---

## B. Rules

A rule consists of one or more **zones**. There are two zone types.

| | Person / object rule (`detection`) | Obstruction / change (`change_detection`) |
| :--- | :--- | :--- |
| Definition | Polygon + plain sentence, or choices from lists | Polygon only |
| Preparation | The sentence is turned into a plan once by the language model | "Take reference" while the zone is clear |
| Operation | Object detection + condition evaluation | Comparing the live picture with the reference |
| Needs the language model | Yes, for sentences (only when saving); no for choices from lists | No |
| Needs the analysis server | Yes | No |

### B.1 Compilation: from sentence to plan

Code: `WebInterface/backend/rule_compilation.py` → `Rule_Generator_LLM/compiler.py` (`RuleCompiler`),
prompt: `Rule_Generator_LLM/prompts.py`.

1. The response returns as soon as the rule is saved; compilation starts in the background
   (`compile_status: compiling`).
2. The compiler sends the zone description with the prompt to the language model and asks for a JSON
   plan.
3. The response is cleaned (code fences and thinking tags removed), corrected with `_normalize_plan_data`
   (model choice, mapping class names to the model's real classes, missing fields) and validated against
   the `DetectionPlan` schema.
4. The plan is written into the zone record. If the rule changed during compilation, the result is
   discarded.
5. If the language model does not answer or gives an invalid answer, a generic **fallback plan** is
   produced (`fallback`): the rule runs but may not fully match the description.

**Capability limits.** The prompt lists one by one what the system can do (is there an object of a given
kind in the zone, has the zone been left empty, is equipment missing, waiting time, count limit, working
hours) and what it cannot do (recognising people, reading text, recognising behaviour, direction / line
crossing, counters and reports, distances, dates and holidays, information beyond the picture such as
sound, details such as colour). The model puts every request into one of three cases and writes it in its
answer:

| `feasibility` | What happens |
| :--- | :--- |
| `full` | The plan does what was asked. |
| `partial` | Part of the request cannot be done; the plan closest to the purpose is compiled and a note for the operator is written in `user_note`: what could not be done and what the rule does instead. Example: "I cannot tell people apart by name. Instead I alert when nobody is left in the zone; if someone else takes Ahmet's place, I will not alert." The note is shown under the zone in the rule list and in the save notification. |
| `none` | No rule that serves the purpose can be built (it needs sound, for example). The compiler raises `UnsupportedRule`: it is not retried and does not fall back to a fallback plan; the rule stays `unsupported` and the model's explanation is shown to the operator. |

Notes and explanations are written by the model in Turkish and stored; they are not translated.

When a new capability is added to the system, this list in the prompt must be updated as well; otherwise
the compiler keeps answering that request with "not possible".

**Working hours** (`Rule_Generator_LLM/schedule.py`). A rule can run in one time window per day on chosen
days: `{"start": "22:00", "end": "06:00", "days": [0-6]}` (0 is Monday). If the end is not after the
start, the window runs past midnight and **belongs to the day it starts** (Friday 22:00–06:00 covers
Saturday morning). Hours come from two places:

- **From the form** (`source: user`): what the user chose always takes precedence.
- **From the sentence** (`source: text`): the model writes explicit hours and days into the plan's
  `schedule` field; `compiled_changes` carries them over to the rule. For a vague phrase such as "after
  hours" the model assumes reasonable hours, sets `feasibility: partial` and says in the note which hours
  it chose.

`describe(schedule, lang)` writes the window as text ("22:00–06:00 · Weekdays") in Turkish or English.
The rule loop skips a rule outside its hours as if it were switched off (`is_active`); an ongoing
violation event closes by itself after 10 seconds.

**Rules defined from lists** (`Rule_Generator_LLM/manual.py`). If a zone has a `manual` choice, the plan
is built directly with `build_plan`: no language model is involved, the rule works immediately and can be
defined without the service. `describe_plan(plan, lang)` describes every plan in one sentence, whether the
model or the form produced it ("More than 3 people in the zone"); this is what the rule list shows, so the
user always sees **what the system understood**. The sentence is written in the language the interface
asks for.

If a zone's description did not change (only its name, corners or the rule's title changed), the plan is
kept and not compiled again.

**Compilation states**

| `compile_status` | Meaning | In the interface |
| :--- | :--- | :--- |
| `compiling` | Compilation in progress | Preparing |
| `compiled` | Every zone has its plan | (no badge) |
| `not_required` | The rule has only obstruction zones | (no badge) |
| `fallback` | At least one zone runs on a fallback plan | Running with a generic setting |
| `pending` | No plan; the service is available | Not ready |
| `unavailable` | No plan; the service is not available | Could not be prepared |
| `error` | Compilation failed | Could not be prepared |
| `unsupported` | The request could not be turned into something a camera can observe (`compile_note` says why) | Not possible |

### B.2 Detection plan

Schema: `Rule_Generator_LLM/schema.py`, `DetectionPlan`.

```json
{
  "source_prompt": "Baret takmayan biri bölgeye girerse haber ver.",
  "selected_model": "safety_detector",
  "triton_model_name": "safety_detector",
  "model_classes": ["NO-Hardhat"],
  "detection_targets": [{"class_name": "NO-Hardhat", "role": "trigger"}],
  "conditions": [{"type": "zone_presence", "targets": ["NO-Hardhat"], "logic": "ANY", "min_confidence": 0.3}],
  "alert_on": "ANY_CONDITION_MET",
  "status": "success"
}
```

| Field | Meaning |
| :--- | :--- |
| `selected_model` / `triton_model_name` | Which model: `safety_detector`, `coco_detector`, `yoloe_detector`. |
| `model_classes` | Classes to request from the model. |
| `detection_targets[].role` | `trigger`, `subject`, `required_equipment`, `forbidden`, `counter`. |
| `conditions[]` | Conditions to evaluate (below). |
| `alert_on` | `ANY_CONDITION_MET` (one is enough) or `ALL_CONDITIONS_MET`. |
| `expanded_classes` | Synonyms for `yoloe_detector` (e.g. forklift → reach truck, pallet jack…). |
| `status` | `success` / `fallback`. |

**Model choice**

| Model | When |
| :--- | :--- |
| `safety_detector` | Workplace safety classes: `Hardhat`, `NO-Hardhat`, `Safety Vest`, `NO-Safety Vest`, `Mask`, `NO-Mask`, `Person`, `Safety Cone`, `machinery`, `vehicle`. |
| `coco_detector` | One of the 80 COCO classes: person, car, truck, backpack, suitcase… |
| `yoloe_detector` | Objects not in the above; the class name is given as text. |

If a plan looks only for "person" and involves no safety equipment, it is routed to `coco_detector` at
run time (`live_detection_service._get_plan`): it is more consistent at detecting people.

### B.3 Condition types

Code: `Rule_Generator_LLM/evaluator.py`, `ConditionEvaluator`. A detection counts as **in the zone** if
one of these four points of its box is inside the polygon: centre, bottom middle (feet), 25 % from the
top (torso), 75 % from the top (hips). This catches both standing and sitting people in zones drawn on
the floor.

| Condition | Alarm when | Parameters | Example sentence |
| :--- | :--- | :--- | :--- |
| `zone_presence` | One (`ANY`) or all (`ALL`) of the target classes are in the zone | `targets`, `logic`, `min_confidence` | "Alert if a vehicle enters the zone." |
| `zone_absence` (equipment) | The subject in the zone does not overlap with the required equipment | `subject`, `required`, `overlap_iou_threshold` | "Alert if someone works without a vest." |
| `zone_absence` (leaving) | The target is absent from the zone for `duration_sec` | `targets`, `duration_sec` | "Alert if the guard leaves for more than 10 seconds." |
| `object_count` | The count in the zone meets the threshold | `targets`, `count_threshold`, `count_operator` (`gt`, `gte`, `lt`, `lte`, `eq`) | "Alert if there are more than 5 people." |
| `loitering` | The same subject stays in the zone for `duration_sec` (default 30) | `subject`, `duration_sec` | "Alert if a person waits for more than 30 seconds." |
| `unauthorized_object` | A forbidden class is in the zone | `targets` | "Alert if a bag is left in the zone." |
| `line_crossing` | The target was seen in the zone | `targets` | (only in old plans; the compiler no longer produces it) |

**Object tracking** (`Rule_Generator_LLM/tracker.py`, `ObjectTracker`). Before evaluation, detections go
through one tracker per camera and model; each detection gets an id (`track_id`):

| Concept | Value | Meaning |
| :--- | :--- | :--- |
| Matching | same class; overlap (IoU ≥ 0.15), otherwise closer than one box diagonal | Which object in the previous frame is this detection? |
| Confirmation | `CONFIRM_HITS` = 2 frames | A detection seen in a single frame is not an object; rules only look at confirmed objects. |
| Coasting | `COAST_SEC` = 0.8 s | A confirmed object the detector missed is assumed to be at its last position. |
| Forgetting | `FORGET_SEC` = 2 s | The id of an object unseen for this long ends. |

Effect on rules: a one-frame false detection does not raise an alarm; a hard hat missed in one frame does
not trigger a "no hard hat" alarm; the count stays steady even if detections flicker; `loitering` time is
measured **per object** (if one person leaves as another enters, the time starts again; a gap shorter
than 1.5 seconds does not reset it).

Limits:

- Tracking is within one camera and looks only at box positions (no motion model, no appearance
  features). In a crowd, or when objects pass in front of each other, ids can be swapped; an object lost
  for more than 2 seconds gets a new id.
- There is no direction, line crossing or in/out counting. The tracker now provides the id these need;
  what is missing is a line-drawing tool and a place to show the counters.
- There is no person recognition: a "Is Ahmet at his desk?" rule is compiled as "is there a person in the
  zone", and the user is told so (see B.1, capability limits).

The violation messages shown to the operator are produced here too, in Turkish: "Bölgede görüldü:
baretsiz kişi", "Kişi 12 saniyedir bölgede bekliyor", "Bölgedeki sayı sınırı aşıldı: 6 kişi". In English
mode the interface rewrites them ("Seen in the zone: person without a hard hat", "Person has been waiting
in the zone for 12 seconds", "Count limit in the zone exceeded: 6 people").

### B.4 The run loop

Code: `WebInterface/backend/live_detection_service.py`.

In every round (at least 80 ms apart), for each camera that **has an active rule** and **brought a new
frame**:

1. The rules that apply to the camera are gathered: its own rules + the `scope: system` rules, only those
   that are on (and within their working hours).
2. For each zone:
   - Obstruction zone → `change_detector.check_frame`.
   - Person / object zone → detection with the plan's model and classes, then object tracking. If the
     same model and classes are needed by several zones in the same frame, both are done once.
   - `ConditionEvaluator.evaluate(plan, confirmed objects, polygon)` → is the condition met.
3. A rule counts as an **alarm** only if it has been violated without interruption for
   `RULE_CONFIRM_SEC` (1 s).
4. The camera's state is published (`/api/live/state` → `detections`): the boxes in that frame (with
   `track_id`), the alarm and the alarm text.
5. For every rule in alarm, `anomaly_service.rule_violated` is called (on every frame).

If no camera has an active rule, the loop sleeps 0.5 seconds; the detection model is never loaded.

### B.5 Obstruction / change zones

Code: `WebInterface/backend/change_detector.py`.

- **Reference:** the live frame at the moment of "Take reference" is masked with the polygon, reduced to
  160×120 greyscale and stored under `change_refs/`. Without a live picture no reference is taken (setting
  it from a frozen frame would cause a permanent false alarm).
- **Comparison:** on every frame the same zone is brought to the same form and **SSIM** (structural
  similarity, 0–1) against the reference is computed. The share of the area covered by regions larger
  than 400 pixels in the difference image (`change_pct`) is also found.

| SSIM | `alarm_level` | Alarm |
| :--- | :--- | :--- |
| < 0.72 | `alarm` | Yes |
| 0.72 – 0.88 | `warning` | Yes if the changed area exceeds 10 % |
| ≥ 0.88 | `clear` | No |

SSIM is more robust to small lighting changes than a pixel difference; still, a lasting lighting change
or a moved camera causes false alarms. The cure is to take the reference again.

### B.6 Recording a rule violation

`rule_violated(camera, rule, rule title, message, severity)` is called on every frame for as long as the
rule is violated:

| Stage | Condition | Action |
| :--- | :--- | :--- |
| Opening | No open event for this camera + rule | A record is created (`is_ongoing: true`, no end time); video and summary are started. |
| Continuing | An open event exists | Only the last-seen time is updated; the record is not touched. |
| Closing | The rule has not been violated for `RULE_QUIET_SEC` (10 s) | `is_ongoing: false`, `end_time_str` the last violation moment, `incident_sec` the total duration of the violation. |

Closing is done by the anomaly loop (`_close_silent_incidents`); because that loop also runs while
analysis is off, an event does not stay open even if the rule is deleted or switched off, or the analysis
server stops. If the server restarts, open events are closed as `interrupted`.

- Record id `rule_…`; `tier` is `warning` or `critical` depending on the rule's severity; fixed score 75.
- Video: the 5 seconds **before** the start of the violation (from the camera's buffer); however long the
  violation lasts, the video is this long (`duration_sec`), and the duration of the violation is kept
  separately (`incident_sec`). If the camera has just connected, whatever exists; under 1 second no video
  is stored, only the snapshot remains.
- Summary: the same path as for unusual activity; in addition, the rule's title and the violation message
  are given to the model as context.

---

## C. Incident summary

Code: `Rule_Generator_LLM/vlm_summarizer.py`.

1. **8 evenly spaced** frames are chosen from the event's frames (the first and last frames are skipped)
   and their long edge is reduced to 256 pixels.
2. The frames and a short prompt are sent to the vision-language model. The prompt asks for this format
   (in Turkish, since summaries are written in Turkish):

   ```
   **Değerlendirme:** GERÇEK, OLAĞAN or BELİRSİZ.       (verdict: REAL, ORDINARY or UNCLEAR)
   **Özet Başlık:** one short sentence on what happened (at most 12 words).
   - At most 2 points: information not in the headline that helps the decision.
   **Öneri:** one imperative sentence for the guard (omitted if not needed).
   ```

   The verdict line is the model's own decision: REAL means the reason for the alarm (for a rule violation
   the violation of the rule; for unusual activity a situation that needs attention, such as a fight, a
   fall or an accident) is clearly visible in the frames; ORDINARY means only everyday movement; UNCLEAR
   means the frames are not enough.

   Rules: 60 words in total; only what is visible in the frames; no repetition, no trivial details such
   as clothing colour, no general safety advice; no system / rule / model names or technical terms; if the
   frames do not confirm the alarm, say so in the headline.
3. The answer is **forced** into this format by `compact_summary`: one headline, at most two points that
   do not repeat the headline (each cut to its first sentence), one piece of advice. Even if the model
   ignores the prompt, no long text enters the record. The verdict line does not enter the summary text;
   it is turned into a separate field.
4. The result is written into the record: `ai_summary`, `ai_headline`, `ai_verdict` (`confirmed` /
   `normal` / `unclear`; `null` if the model wrote no verdict line), `ai_status: completed`.

**The verdict is only information.** An event judged `normal` is not deleted, hidden or downgraded; it
gets a grey **Looks ordinary** badge in the list and in the event window. The reason: the model looks at
eight small frames and can miss a real incident (in a trial it called a video in which a worker fell in
front of a forklift "ordinary"). Until it is measured how well the verdict agrees with the operators'
decisions, alarms must not be suppressed on its basis.

If the summary cannot be written (`ai_status: fallback`), the record gets an honest one-line note: "The
summary could not be written because the footage could not be examined (reason)". Reasons: no frames could
be taken from the video, the service is not available, the service could not be reached, the daily usage
quota is used up.

To change the length and format of the summary, see the constants at the top of the file
(`SUMMARY_MAX_WORDS`, `SUMMARY_MAX_DETAILS`, `SUMMARY_MAX_TOKENS`, `FRAME_COUNT`) and the `_prompt`
function.

**Cost:** every event is one model call. In a busy scene unusual activity detection can produce several
events per minute; if the service quota is limited, raise the warning level or leave the key empty.
