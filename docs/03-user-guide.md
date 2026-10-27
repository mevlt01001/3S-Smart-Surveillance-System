# 03 — User guide

The six pages of the interface are in the menu on the left (at the bottom of the screen on a phone). The
line at the bottom of the menu says how the system is doing:

| Indicator | Meaning |
| :--- | :--- |
| ● System running | Cameras are watched and analysed. |
| ● Analysis stopped | The analysis server cannot be reached. Live video works; event detection and rules are stopped. The same warning also appears as a red line at the top of every page. |
| ● No connection | The browser cannot reach the server. A red band also appears at the top of the screen; the information on screen may be out of date. |

The number next to "Events" is the number of events nobody has reviewed yet.

The interface is in Turkish by default; English is chosen under **Settings → Appearance**. Button names
below are given as they read in English.

---

## Live view

The start page.

| Control | Function |
| :--- | :--- |
| **1 / 4 / 6 / 12** | Screen layout: 1, 2, 3 or 4 cameras per row. More cameras scroll downwards. |
| **Alarms only** | Shows only cameras with a warning, an alarm or a lost signal. |
| **Zones** | Draws the zones of your rules on the picture. |
| **Detections** | Outlines the people and objects detected; shows the state of obstruction zones. |
| **n/m online** | Number of cameras delivering a picture. |

### Camera tile

- Top left: the camera's name and a status dot — green (normal), orange (warning), red (alarm), blinking
  blue (connecting), grey (no signal).
- The label at the top right appears only when there is something to say: **Suspicious movement**,
  **Critical movement**, the reason of a rule violation, **Connecting…** or **No signal**.
- In an alarm the frame is coloured; in a critical one it flashes.
- When the signal is lost, the last frame stays faded and grey; a frozen picture is never shown as live.
- Bottom right buttons: **photo** (downloads the current frame) and **enlarge**.
- A camera with an obstruction / change zone also has a **Take reference** button (see below).

### Single camera view

Clicking a tile enlarges the camera and opens two things below it:

- The **Last 30 minutes** strip: each slice is green (no event), orange (warning) or red (critical).
  Clicking a coloured slice opens that event.
- The list of **recent events of this camera**.

To leave, press "All cameras", click the picture or press `Esc`.

---

## Events

Every recorded alarm is listed here. New events appear at the top of the list without reloading.

A rule violation is **one event** for as long as it lasts: its card says "Ongoing"; when the violation
ends, its duration is shown (for example "22 min"). Its video shows the moment the violation started.

### Filtering

| Control | Options |
| :--- | :--- |
| Search | Searches camera names, event titles, rule descriptions and summaries. |
| Camera | Cameras that have events. |
| Time | All time, last 15 minutes, last hour, last 6 hours, today. |
| Type | Critical, Warning, Rule violation. |
| Status | Not reviewed, True alarm, False alarm. |

The two buttons on the right switch between card and list view. **Export** downloads the currently
filtered events as a CSV file that opens in Excel. **Delete all** deletes every event permanently with
its video and photo (asks for confirmation).

### Event card

Photo (with a play symbol if there is a video), duration, level badge, date and time, title, camera and,
when available, a one-line summary. For unusual activity the title is "Unusual activity" until the
summary is written; then it becomes the summary's sentence saying what happened.

A grey **Looks ordinary** badge next to the level means the summary saw nothing unusual in the footage.
It is only a hint: the summary looks at a few small frames and can be wrong, so the event is neither
deleted nor downgraded. Watch the video and decide yourself. The **True** / **False** buttons below mark
the event without opening it; pressing the selected button again withdraws the verdict.

### Event window

Opens when a card is clicked.

- **Video.** Below the player: −2 s, +2 s and speed (1× → 0.5× → 0.25× → 2×) buttons. **Show frames**
  lays out eight evenly spaced frames of the video; clicking a frame enlarges it. **Download** saves the
  video as MP4.
- **Details.** Camera, time range and duration; for a rule violation what the rule saw, for unusual
  activity the movement level.
- **Event summary.** A one-sentence headline, at most two details and one piece of advice. The summary
  arrives by itself a few seconds after the event ends. **Regenerate** writes it again. Summaries are
  written in Turkish, whatever the interface language.
- **Was this alarm right?** True alarm / False alarm.
- **Watch this camera live.** Opens the single camera view of this camera in Live view.

Without a video (recording switched off, or the video deleted to free storage) the snapshot is shown.

---

## Rules

The list shows each rule's name, what it looks for, which camera it applies to and whether it is on.

| Badge | Meaning |
| :--- | :--- |
| Preparing | The description is being processed; the rule starts working in a few seconds. |
| Running with a generic setting | The description could not be fully understood. Simplify it or press **Retry**. |
| Not ready / Could not be prepared | The rule is not running. Press **Retry**; if that does not help, check the status line at the bottom left. |
| Not possible | Your request is not something a camera can observe (it needs sound or reading number plates, for example). Hover over the badge for the reason and what you can ask instead. The rule does not run; change the description. |
| No camera | The rule's camera has been deleted. Edit the rule and move it to another camera. |
| Off hours | The rule is on but outside its working hours, so it is not being checked right now. |

An orange note under a zone means the rule runs, but **differently from what you asked**. When asked for
something it cannot do, the system builds the closest possible rule and tells you the difference. Writing
"tell me if Ahmet leaves his desk", for instance, gives the note: "I cannot tell people apart by name.
Instead I alert when nobody is left in the zone; if someone else takes Ahmet's place, I will not alert."
The same note is shown as a notification when the rule is saved.

Without a badge the rule is ready. The switch in the row turns the rule on and off; the pencil edits it,
the bin deletes it.

### New rule

1. Press **New rule**.
2. Choose where the rule applies: **Single camera** (and the camera) or **All cameras**.
3. Click the picture (tap on a phone) to mark the corners of the zone, then press **Finish zone**.
   Clicking the first point, double-clicking or `Enter` also closes the zone. `Backspace` and **Undo**
   remove the last point, `Esc` cancels the drawing. The edges of a zone cannot cross; a corner that would
   make them cross is refused. A rule can have several zones; each becomes a label in the "Zones" row.
4. For the selected zone, answer **What should be watched?**:
   - **People and objects, in your own words:** write what should trigger an alert in the zone. You can
     start from one of the ready-made sentences below the field.
   - **People and objects, from lists:** choose what to look for (person, vehicle, person without a hard
     hat, person without a safety vest, forklift, bag) and when to alert (when seen, when staying longer
     than a set time, when absent for a set time, when the count exceeds or drops below a limit); enter the
     time or count where needed. This way needs no language service, and the rule works as soon as it is
     saved.
   - **Obstruction or change:** no description needed (for places that must stay clear, such as the area
     in front of an emergency exit or a fire hose cabinet).
5. **When should the rule run?** The default is "Always". With "Only at certain hours" you set a time
   window and the days; if the end time is before the start time, the window runs past midnight (22:00 to
   06:00). If your sentence mentions hours ("between 23:00 and 05:00 at night…"), you need not fill this
   in: the system reads the hours from the sentence and shows them in the rule list. Hours chosen in the
   form take precedence over those in the sentence.
6. Give the rule a name and press **Save**.

Under each zone, the rule list says **what the system understood** ("Person stays in the zone longer
than 20 seconds"), together with the working hours if any.

### Writing a good description

| Write | Do not write |
| :--- | :--- |
| "Alert if someone without a hard hat enters the zone." | "Watch out for safety." |
| "Alert if a person waits in the zone for more than 30 seconds." | "Catch suspicious behaviour." |
| "Alert if there are more than 5 people in the zone." | "No crowding." |
| "Alert if a vehicle enters the zone." | "Watch the vehicles." |

Sentences with one condition, a concrete object and, where needed, a number or a duration work best.
Descriptions are understood in Turkish; English sentences usually work as well, but the rule notes and
explanations are written in Turkish.

What rules **cannot do:** recognise people (name, role, authorised / unauthorised), read number plates or
text, recognise behaviour (running, smoking; unusual activity such as fights or falls is watched
separately without any rule), direction and line crossing, counting people in and out, measuring
distances, a specific date or holiday, and sound. For vague times such as "after hours" the system
assumes reasonable hours and says which. When asked for something it cannot do, the system either builds
the closest rule and states the difference, or explains why it cannot.
The supported conditions are described in [08 — Rules and analysis](08-rules-and-analysis.md).

### Reference for an obstruction / change zone

After such a rule is saved, the zone waits, because it does not yet know what "empty" looks like. While
the zone is clear, press **Take reference** once on the camera's tile in **Live view**. From then on an
alarm is raised when something is placed in the zone. If the camera moves or the lighting changes for
good, take the reference again.

---

## Reports

Summarises what happened in the chosen period (**Today**, **7 days**, **30 days**).

- **Figures at the top:** total events, rule violations, unusual activity, events awaiting review and the
  **false alarm rate** (the share of the reviewed events you marked "False").
- **Chart:** events per day (per hour for "Today"); blue for rule violations, orange for unusual activity.
  Hovering over a column shows its figures. **Show as table** shows the same data as a table.
- **By rule:** how often each rule was violated, the **total duration** of the violations, and your verdicts.
- **By camera:** the events of each camera and your verdicts. Below it: how often the summaries' own
  verdict agreed with yours.

**Print / PDF** sends the report to the printer; choose "Save as PDF" instead of a printer to get a file.
The rates become meaningful as you mark events **True** / **False**. The event log keeps a limited number
of events (Settings → Recording); when it is full, older events are missing from long periods and the page
says so.

---

## Cameras

| Task | How |
| :--- | :--- |
| Finding cameras on the network | **Find cameras** → enter the user name and password → **Add** one by one or **Add all**. |
| Adding by address | **Add manually** → IP address, user name, password. Ports are under "Connection settings"; most cameras do not need them changed. |
| Name and description | Pencil icon. The description ("What does this camera see?") makes incident summaries more accurate. |
| Reconnecting | Arrow icon; probes the camera again with the stored details. |
| Technical details | Info icon: make / model, address, resolution, serial number, stream address (can be copied). |
| Deleting | Bin icon. The rules defined for the camera are deleted too; recorded events remain. |

| Status | Meaning and what to do |
| :--- | :--- |
| Live | The picture arrives. |
| Ready | The camera is reachable; nobody is watching or analysing it right now, so the connection was released. It reconnects by itself when watched. |
| Connecting… | The connection is being made (up to 20 seconds at start-up is normal). |
| No signal | No picture arrives. Check that the camera is on and on the network. |
| Wrong password | Add the same address again with "Add manually" and the right details. |

---

## Settings

When you change a value, an "There are unsaved changes" bar appears at the bottom right. **Save** applies
the change immediately; the server does not need a restart. Leaving the page without saving asks first.

### Appearance

Theme and language apply **only on this device** (a phone can be light and in English while the control
room screen stays dark and in Turkish) and take effect immediately, without saving.

| Theme | Look |
| :--- | :--- |
| Light (default) | Light background, navy menu; blue buttons, light orange accents. |
| Navy | Dark navy background; buttons and accents in light orange. |
| Dark | Neutral dark grey background, orange accents. |

**Language:** Türkçe (default) or English. The page reloads once to redraw everything in the chosen
language. Texts that were written once and stored — incident summaries, notes of the rule compiler, names
you typed — stay in the language they were written in.

### Detection

| Setting | Effect |
| :--- | :--- |
| Detect unusual activity | When off, only the defined rules run and the graphics card is freed. |
| Warning level | When the movement score exceeds this value, a **Warning** event opens. Lowering it makes the system more sensitive and raises false alarms. |
| Critical level | When the score exceeds this value, the event counts as **Critical**. Always above the warning level. |

### Live view

Opening layout; frame highlight on alarm; status label; enlarge on click; full frame rate (when off, the
picture drops to 8 frames per second, for slow connections).

### Recording

| Setting | Effect |
| :--- | :--- |
| Record events as video | When off, events are recorded with a photo only. |
| Before and after the event | Time added to the video before the event starts and after it ends. |
| Longest video | An event that lasts longer continues as a new event. |
| Storage for recordings | When it is full, the oldest videos are deleted; the event record and its photo remain. |

The "Space used" box shows how full the storage is. If some videos belong to no event, their number and a
**Clear** button appear here.

### Advanced

Should only be changed by the person who installed the system: analysis server address, analysis model
name, number of cameras analysed at once, event merge time (alarms closer together than this count as one
event), maximum number of videos. Below them: system status (analysis server, analysis times, graphics
memory and temperature) and the **Restore default settings** button.

Limits and defaults of every setting: [09 — Data and configuration](09-data-and-configuration.md).
