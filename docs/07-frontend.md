# 07 — Interface code

Directory: `WebInterface/frontend/`. There is no build step, package manager or framework: the browser's
own ES modules, a single `index.html` and plain CSS.

```
frontend/
├── index.html            Page skeleton, six views, dialogs, icon set
├── css/
│   ├── base.css          Colour and size variables, reset, typography
│   ├── components.css    Button, form, badge, card, table, dialog, toast…
│   ├── layout.css        Sidebar, top bar, content area, responsive layout
│   └── live.css  events.css  rules.css  reports.css  cameras.css  settings.css     Page-specific styles
└── js/
    ├── theme.js          Theme choice; a plain script loaded before the styles
    ├── i18n.js           Interface language: t(), translatePage(), setLanguage()
    ├── i18n-en.js        English catalogue (Turkish text → English text)
    ├── main.js           Entry point: starts the shared parts, registers the pages
    ├── router.js         Page switching tied to the address bar
    ├── shell.js          Clock, system status line, events badge, connection warning
    ├── api.js            The only module that talks to the server
    ├── ui.js             Escaping, toast, dialog, confirm and formatting helpers
    ├── labels.js         Plain-language names for technical values
    ├── live.js           Live view page
    ├── stream.js         Live video into an <img> element (WebSocket)
    ├── overlay.js        Drawings over the picture (zones, detections)
    ├── events.js         Events page
    ├── event-detail.js   Event window
    ├── rules.js          Rules page (list + form)
    ├── zone-editor.js    Polygon drawing tool
    ├── reports.js        Reports page (figures, chart, tables, printing)
    ├── cameras.js        Cameras page and its dialogs
    └── settings.js       Settings page
```

## Rules

These rules hold across the code; new code must follow them too.

1. **Only `api.js` talks to the server.** Pages do not call `fetch` or build addresses. If a new endpoint
   is needed, a function is added to `api.js`.
2. **Every page exports the same interface:** `mount(params)`, `unmount()` and, if needed, `canLeave()`.
3. **A page that is not visible does not run.** `unmount` closes the page's timers and its WebSocket and
   SSE connections. Live video also stops when the tab goes to the background.
4. **Events are delegated.** Listeners are not attached to buttons one by one; one listener sits on the
   container and looks at the `data-action` attribute. There are no `onclick` attributes and no
   `window.*` functions.
5. **Every external text is escaped.** Camera names, rule titles, server messages… are written into HTML
   through `escapeHTML`. Toasts (`showToast`) are plain text.
6. **Visibility is changed with the `hidden` attribute**, not with `style.display`. States are expressed
   with `is-*` classes (`is-active`, `is-danger`, `is-open`…).
7. **No inline styles.** The only exception is passing a colour that comes from data as a CSS variable
   (`style="--zone-color: …"`).
8. **No magic numbers.** Times and limits are named constants at the top of the module.
9. **Every text goes through `t()`.** Texts are written in Turkish in the code and have an entry in
   `i18n-en.js` (see "Interface language").

The system check verifies some of these: no duplicate `id` in `index.html`, every element the scripts
look up with `$("#…")` exists on the page, every module resolves under `/ui/`, and every text has an
English entry.

## Page life cycle

```js
// main.js
registerView("live", { title: t("Canlı İzleme"), ...live });   // live.js: mount, unmount
startRouter("live");                                            // the page to open if the address is empty
```

`router.navigate(name, params)` in order:

1. Waits for the current page's `canLeave()` (asks the user if there are unsaved changes).
2. Calls the current page's `unmount()`.
3. Hides the sections other than `<section id="view-name">`, updates the menu and the title, sets the
   address to `#name`.
4. Calls the new page's `mount(params)`.

`params` travel in memory and are not written into the address. Example: the "Watch this camera live"
button in the event window calls `navigate("live", { cameraId })`.

The skeleton of a page:

```js
let mounted = false;
let wired = false;

function wire() {            // listeners are attached only once
  wired = true;
  $("#example-list").addEventListener("click", onListClick);
}

export function mount() {
  mounted = true;
  if (!wired) wire();
  load();                    // refresh the data on every visit
}

export function unmount() {
  mounted = false;
  clearInterval(timer);      // close whatever is open
}
```

## Interface language

Turkish is the source language and the default; English is chosen per device under Settings →
Appearance.

- **`t(text, params)`** (`i18n.js`) returns the text in the interface language. In English mode it looks
  the Turkish text up in `i18n-en.js` and falls back to the Turkish when there is no entry. `{name}`
  placeholders are filled from `params`:

  ```js
  showToast(t("Kural kaydedildi."));
  t("{n} olay", { n: 3 });            // "3 events" in English mode
  ```

  Pass the whole sentence to `t()`, never pieces glued together; word order differs between the two
  languages.
- **`translatePage()`** translates the static texts of `index.html` once at start-up: text nodes and the
  `placeholder`, `title`, `aria-label` and `alt` attributes. Texts are matched as written, ignoring the
  surrounding white space.
- **`setLanguage(lang)`** stores the choice in `localStorage` (`aegis-lang`) and reloads the page, so
  every page is drawn in the new language without re-rendering logic. `lang` and `locale` (`tr-TR` /
  `en-GB`) are exported for dates and numbers; `formatPercent` and `formatDuration` in `ui.js` follow
  them.
- **The catalogue** `i18n-en.js` is a JSON object between the `// catalogue:begin` and
  `// catalogue:end` markers, so the system check can read it. Keys are the Turkish texts exactly as they
  appear in the code. A value that continues a sentence keeps its leading space.
- **The server** writes the rule plan sentences and the working-hours text in the language of the
  `Accept-Language` header, which `api.js` sends on every request. Server error messages are Turkish and
  have catalogue entries.
- **Texts produced at run time in Turkish** — the rule engine's alarm sentences — are rewritten by
  `alarmText()` in `labels.js`. Texts written once and stored (incident summaries, rule compiler notes,
  user-entered names) stay in the language they were written in.

Adding a text: write it in Turkish inside `t("…")` (or in `index.html`) and add the entry to
`i18n-en.js`. The system check (group [14]) fails if any `t("…")` literal or any `index.html` text with
words has no entry.

## Modules

### `api.js`
One function per endpoint. All use the same `request()` helper: it applies a timeout, sends
`Accept-Language`, and turns a failed response into an `ApiError` carrying the server's `detail` text. The
caller:

```js
try {
  await updateCamera(id, { name });
} catch (err) {
  showError("Kamera kaydedilemedi", err);   // "Camera could not be saved: <the server's reason>"
}
```

### `ui.js`

| Export | Function |
| :--- | :--- |
| `escapeHTML`, `icon(name)`, `setHTML(element, html)` | Safe HTML; icon; content rewritten only if it changed. |
| `$`, `$$` | Shorthands for `querySelector` / `querySelectorAll`. |
| `showToast(message, kind, duration)`, `showError(prefix, error)` | Short-lived notification; both translate their text. |
| `openModal(id)`, `closeModal(id)`, `initModals()`, `isAnyModalOpen()` | Dialogs. The close button (`data-close`), a click on the backdrop and `Esc` are handled in one place; on close the element emits a `modal:closed` event. |
| `confirmDialog({title, message, confirmText, danger})` | Confirm dialog; `Promise<boolean>`. For dangerous actions the focus is on "Cancel". |
| `showImage(src, title)` | Full-screen image. |
| `bindSegmented(group, attribute, onChange)` | Turns a group of buttons into a single-choice control. |
| `withBusy(button, text, job)` | Locks the button while the job runs. |
| `formatDuration`, `formatPercent`, `maskCredentials`, `copyText`, `downloadBlob`, `NO_IMAGE` | Helpers. |

`setHTML` avoids redrawing lists from scratch on every update: if the generated HTML is the same as
before, the DOM is left alone, so hover, focus and scroll position are not disturbed.

### `shell.js`
Polls `/api/system/stats` every 5 seconds. After two failures in a row it shows the "connection lost"
band. If the analysis server does not answer, it opens the `#analysis-notice` line at the top of every
page (rules are not checked meanwhile; the rule list does not show this by itself).
`subscribeSystemStats(listener)` lets other modules receive the same data (the system status in
Settings). `refreshEventsBadge()` updates the number of unreviewed events in the menu.

### `stream.js`
`startStream(cameraId, img, maxFps)` → stop function. Hands every JPEG from the WebSocket to the `<img>`.
If a new frame arrives while the browser is decoding one, the waiting frame is replaced ("last frame
wins"); a busy tab therefore drops frames but never falls behind real time. If the connection drops, it
retries at growing intervals and meanwhile fetches a snapshot once per second.

### `overlay.js`
`drawOverlay(canvas, img, scene)`: rule zones, detection boxes and the state of obstruction zones. Because
the picture is fitted with `object-fit: contain`, the 0–1 coordinates are first mapped to the area the
picture actually covers.

### `live.js`
- `/api/live/state` is polled every 400 ms; a new request is not sent before the previous one answers.
- `tileState(id)` decides in one place what a tile shows: no signal → rule alarm → critical →
  suspicious → normal.
- Tiles are watched with `IntersectionObserver`; the stream of a tile that is off screen is stopped.
- If the camera list or the rules change from another screen, the wall is rebuilt.

### `events.js` and `event-detail.js`
`events.js` manages the list, filters, paging and the SSE connection; filtering happens in the browser (at
most 300 events are loaded). `event-detail.js` is the event window, used both by the Events page and by
the history in Live view: `openEventDetail(event, onChange)`. While the window is open and the event is
ongoing or its summary is being written, it refreshes itself every 3 seconds, so it stays current on a
page without SSE too.

### `rules.js` and `zone-editor.js`
`zone-editor.js` only knows about drawing: `createZoneEditor(canvas, { onChange, canDraw, onReject })`
returns an object (`setZones`, `getZones`, `getSelected`, `select`, `updateSelected`, `removeZone`,
`finishDrawing`, `cancelDrawing`, `undo`, `clear`, `resize`, `draftPoints`). Everything about the form is
in `rules.js`. Corners are stored between 0 and 1. A corner whose edge would cross an earlier edge is
refused (`onReject` is called); on a touch screen the area for closing the zone by tapping the first
corner is larger.

### `cameras.js`
List, network scan, adding, editing (with live preview), details and deleting. Thumbnails refresh every
2.5 seconds; each is loaded in memory first and then swapped in (no flicker).

### `settings.js`
The form is generic: each control says which setting it edits with `data-setting="section.field"`; the
module does not know setting names. Adding a new setting usually needs only a control in `index.html`
(and its catalogue entry).

```html
<label for="set-padding">Olay öncesi ve sonrası <output data-output="recording.padding_sec" data-unit=" sn"></output></label>
<input type="range" id="set-padding" data-setting="recording.padding_sec" min="0.5" max="5" step="0.5">
```

The theme and language pickers under Appearance are not settings: they act on this device immediately
(`window.aegisTheme.set`, `setLanguage`).

### `labels.js`
`classLabel("NO-Hardhat")` → "Baretsiz kişi" ("Person without a hard hat" in English mode);
`describePlan(plan_summary)` → "Baretsiz kişi — bölgede görülünce". An unknown class name is shown as it
is. When a new model class is added, it must be added here too (the server side of the same dictionary:
`Rule_Generator_LLM/evaluator.py`, `_CLASS_LABELS`; English rule sentences: `Rule_Generator_LLM/manual.py`,
`_CLASS_LABELS_EN`). `alarmText(text)` rewrites the rule engine's Turkish alarm sentences in English mode.

## Style system

- Colours, corner radii, type and basic sizes are variables in `base.css`. A new style does not hard-code
  colours; it uses variables. The only exception is the text and buttons over video (black background,
  white text): they do not depend on the theme.
- **Colour roles.** Every theme defines the same variables; a style chooses a colour by its role:

  | Variable | Role |
  | :--- | :--- |
  | `--bg`, `--surface`, `--surface-2`, `--surface-3`, `--border`, `--border-strong` | Backgrounds and lines |
  | `--text`, `--text-2`, `--text-3` | Text: main, secondary, faint |
  | `--primary`, `--primary-hover`, `--primary-soft`, `--on-primary` | **Action and control colour:** main button, switch, slider, focus ring, selected label |
  | `--accent`, `--accent-soft`, `--accent-ink`, `--on-accent` | **Brand accent (light orange):** logo, active menu item, "look here" highlights. `--accent-ink` is the darker shade of the same tone that reads as text |
  | `--ok`, `--warn`, `--danger`, `--info` (+ `-soft`) | Status colours, dark enough to read as text |
  | `--warn-solid`, `--on-warn-solid` | The filled or border form of a warning (bright amber) and the text on it |
  | `--series-rule`, `--series-movement` | The two series of the report chart; colour-blind separation and contrast measured against each theme's background |

- **Themes.** `<html data-theme="light | navy | dark">`; the default is `light` (the values in `:root`).
  `js/theme.js` is a plain script (not a module) loaded at the top of the page before the styles: it reads
  the choice from `localStorage` and applies it on the first frame, and offers `window.aegisTheme.get()` /
  `.set(name)`. In the light theme the menu is navy: `base.css` redefines the background and text
  variables inside `.sidebar`. Adding a theme: a `:root[data-theme="name"]` block in `base.css`, a line in
  the list in `theme.js` and a button in the picker in Settings.
- Shared parts are in `components.css`: `.btn` (`.btn-primary`, `.btn-danger`, `.btn-sm`), `.btn-icon`,
  `.input`, `.select`, `.textarea`, `.field`, `.switch`, `.check`, `.badge`, `.chip`, `.segmented`,
  `.card`, `.toolbar`, `.empty`, `.notice`, `.table`, `.modal`, `.toast`.
- Icons are in the SVG set at the top of `index.html`; in HTML `<svg class="icon"><use href="#i-name"/></svg>`,
  in JS `icon("name")`.
- Responsive layout: below 1100 pixels the sidebar shows icons only; below 640 pixels it moves to the
  bottom of the screen.

## Adding a page

1. `index.html`: add `<a class="nav-item" href="#report" data-view="report">` to the menu and
   `<section id="view-report" class="view" hidden>` to the content area.
2. `js/report.js`: export `mount` and `unmount`.
3. `js/main.js`: `registerView("report", { title: t("Raporlar"), ...report })`.
4. If the page needs its own style, create `css/report.css` and link it from `index.html`.
5. Add functions to `js/api.js` for the endpoints it needs.
6. Add the English entries of the new texts to `js/i18n-en.js`.

## Stored in the browser

| Key | Content |
| :--- | :--- |
| `aegis.events.layout` | Events: `cards` / `table` |
| `aegis.cameras.layout` | Cameras: `grid` / `list` |
| `aegis-theme` | Theme: `light` / `navy` / `dark` |
| `aegis-lang` | Language: `tr` / `en` |
| `aegis-ui-refreshed` (session) | Timestamp that prevents a reload loop from an old cache |
