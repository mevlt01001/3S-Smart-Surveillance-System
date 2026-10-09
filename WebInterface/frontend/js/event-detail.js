/**
 * The event window: video (or photo) of one event, what happened, the written summary,
 * and the operator's verdict. Used by the Events page and by the live view's history.
 */

import { getEventFrames, labelEvent, listEvents, summarizeEvent } from "./api.js";
import { levelOf } from "./labels.js";
import { navigate } from "./router.js";
import { refreshEventsBadge } from "./shell.js";
import {
  $, $$, NO_IMAGE, closeModal, escapeHTML, formatDuration, openModal, showError, showImage, showToast,
} from "./ui.js";

const MODAL_ID = "modal-event";
const SPEEDS = [1, 0.5, 0.25, 2];
const FOLLOW_INTERVAL_MS = 3000;

let current = null;
let onChange = () => {};
let followTimer = null;
let wired = false;

/* --------------------------------------------------------- Shared wording */
export const isRuleEvent = (entry) =>
  String(entry.id).startsWith("rule_") || String(entry.anomaly_type || "").startsWith("Kural");

/** Short title of an event: the broken rule, or the kind of unusual movement. */
export function eventTitle(entry) {
  if (isRuleEvent(entry)) {
    return entry.rule_title || String(entry.anomaly_type || "").replace("Kural İhlali:", "").trim() || "Kural ihlali";
  }
  return entry.anomaly_type || "Olağandışı hareket";
}

/** Text and colour class of the badge that tells how serious an event is. */
export function levelInfo(entry) {
  const level = levelOf(entry.tier);
  return { text: isRuleEvent(entry) ? "Kural ihlali" : level.label, className: `badge ${level.badge}` };
}

export function levelBadge(entry) {
  const info = levelInfo(entry);
  return `<span class="${info.className}">${info.text}</span>`;
}

/** First sentence of the written summary, used as a one-line description in lists. */
export function summaryHeadline(entry) {
  const match = /\*\*Özet Başlık:\*\*\s*(.+)/.exec(entry.ai_summary || "");
  return match ? match[1].replace(/\*\*/g, "").trim() : "";
}

const inlineMarkup = (text) => escapeHTML(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

/** Turns the summary text (paragraphs, "- " bullets, **bold**) into safe HTML. */
function formatSummary(text) {
  let html = "";
  let listOpen = false;
  const closeList = () => {
    if (listOpen) html += "</ul>";
    listOpen = false;
  };
  String(text || "").trim().split("\n").forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      return;
    }
    const bullet = /^[-•]\s+(.*)$/.exec(line);
    if (bullet) {
      if (!listOpen) html += "<ul>";
      listOpen = true;
      html += `<li>${inlineMarkup(bullet[1])}</li>`;
    } else {
      closeList();
      html += `<p>${inlineMarkup(line.replace(/^\*\*Özet Başlık:\*\*\s*/, ""))}</p>`;
    }
  });
  closeList();
  return html;
}

/* --------------------------------------------------------------- Rendering */
function renderFacts(entry) {
  const facts = [["Kamera", escapeHTML(entry.camera_name || entry.camera_id)]];
  const start = entry.start_time_str || entry.timestamp_str || "";
  const end = entry.is_ongoing ? "" : entry.end_time_str || "";
  let when = end && end !== start ? `${start} – ${end}` : start;
  if (entry.is_ongoing) when += " (sürüyor)";
  else if (entry.duration_sec) when += ` · ${formatDuration(entry.duration_sec)}`;
  facts.push(["Saat", escapeHTML(when)]);
  if (isRuleEvent(entry)) {
    const detail = entry.rule_description || entry.message || "";
    if (detail) facts.push(["Kural", escapeHTML(detail)]);
  } else {
    facts.push(["Hareket seviyesi", `%${Math.round(Number(entry.score) || 0)}`]);
  }
  $("#event-facts").innerHTML = facts.map(([label, value]) => `<dt>${label}</dt><dd>${value}</dd>`).join("");
}

function renderSummary(entry) {
  const text = $("#event-summary-text");
  const button = $("#event-summarize");
  button.hidden = !entry.clip_url;
  button.disabled = entry.ai_status === "generating";
  button.textContent = entry.ai_summary ? "Yeniden oluştur" : "Özet oluştur";

  if (entry.ai_status === "generating") {
    text.innerHTML = `<div class="loading"><div class="spinner"></div><span>Video inceleniyor, özet birazdan burada görünecek…</span></div>`;
  } else if (entry.ai_summary) {
    text.innerHTML = formatSummary(entry.ai_summary);
  } else {
    let reason = "Bu olay için henüz özet yazılmadı.";
    if (entry.is_ongoing) reason = "Olay sürüyor. Özet, olay bittikten sonra yazılır.";
    else if (!entry.clip_url) reason = "Bu olayın videosu olmadığı için özet yazılamıyor.";
    else if (entry.ai_status === "error" || entry.ai_status === "interrupted") reason = "Özet yazılamadı. Yeniden deneyebilirsiniz.";
    text.innerHTML = `<p class="hint">${reason}</p>`;
  }
}

function renderLabel(entry) {
  $$("#event-label button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.label === entry.operator_label);
  });
}

function renderMedia(entry) {
  const video = $("#event-video");
  const image = $("#event-image");
  const hasClip = Boolean(entry.clip_url);
  video.hidden = !hasClip;
  image.hidden = hasClip;
  if (hasClip) {
    if (!video.src.endsWith(entry.clip_url)) {
      video.src = entry.clip_url;
      video.playbackRate = 1;
      video.play().catch(() => {});
    }
  } else {
    video.removeAttribute("src");
    image.src = entry.snapshot_url || NO_IMAGE;
  }
  ["#event-back", "#event-forward", "#event-speed", "#event-frames-toggle", "#event-download"].forEach((selector) => {
    $(selector).hidden = !hasClip;
  });
  if (hasClip) {
    const download = $("#event-download");
    download.href = entry.clip_url;
    download.download = `${entry.camera_id}_${entry.id}.mp4`;
  }
}

function render(entry) {
  const info = levelInfo(entry);
  const badge = $("#event-level");
  badge.className = info.className;
  badge.textContent = info.text;
  $("#event-title").textContent = eventTitle(entry);
  $("#event-when").textContent = `${entry.date_str || ""} ${entry.timestamp_str || ""}`.trim();
  renderFacts(entry);
  renderMedia(entry);
  renderSummary(entry);
  renderLabel(entry);
}

/* ----------------------------------------------------------------- Actions */
async function applyLabel(label) {
  if (!current) return;
  // Pressing the selected verdict again withdraws it
  const next = current.operator_label === label ? "unlabeled" : label;
  try {
    const updated = await labelEvent(current.id, next);
    update({ ...current, ...updated });
    refreshEventsBadge();
  } catch (err) {
    showError("Karar kaydedilemedi", err);
  }
}

async function requestSummary() {
  if (!current) return;
  const previous = current.ai_status;
  update({ ...current, ai_status: "generating" });
  try {
    await summarizeEvent(current.id);
    follow();
  } catch (err) {
    update({ ...current, ai_status: previous });
    showError("Özet başlatılamadı", err);
  }
}

async function toggleFrames() {
  const strip = $("#event-frames");
  if (!strip.hidden) {
    strip.hidden = true;
    $("#event-frames-toggle").textContent = "Kareleri göster";
    return;
  }
  strip.hidden = false;
  $("#event-frames-toggle").textContent = "Kareleri gizle";
  strip.innerHTML = `<div class="loading"><div class="spinner"></div></div>`;
  const entryId = current.id;
  try {
    const data = await getEventFrames(entryId);
    if (!current || current.id !== entryId) return;
    const frames = data.frames || [];
    strip.innerHTML = frames.length
      ? frames.map((frame, index) => {
          const second = data.timestamps && data.timestamps[index] !== undefined ? `${data.timestamps[index]} sn` : "";
          return `<button type="button" class="event-frame" data-caption="${escapeHTML(second)}">
                    <img src="data:image/jpeg;base64,${frame}" alt="Kare ${index + 1}"><span>${escapeHTML(second)}</span>
                  </button>`;
        }).join("")
      : `<p class="hint">Bu videodan kare alınamadı.</p>`;
  } catch (err) {
    strip.innerHTML = `<p class="hint">Kareler alınamadı: ${escapeHTML(err.message)}</p>`;
  }
}

function cycleSpeed() {
  const video = $("#event-video");
  const next = SPEEDS[(SPEEDS.indexOf(video.playbackRate) + 1) % SPEEDS.length];
  video.playbackRate = next;
  $("#event-speed").textContent = `${next}×`;
}

function seek(deltaSec) {
  const video = $("#event-video");
  video.currentTime = Math.max(0, Math.min(video.duration || 0, video.currentTime + deltaSec));
}

/* ------------------------------------------------------ Following an event */
/** While an event is still running or its summary is being written, keep the window current. */
function follow() {
  clearTimeout(followTimer);
  if (!current || !(current.is_ongoing || current.ai_status === "generating")) return;
  followTimer = setTimeout(async () => {
    if (!current) return;
    try {
      const data = await listEvents({ cameraId: current.camera_id, limit: 100 });
      const fresh = (data.journal || []).find((entry) => entry.id === current.id);
      if (fresh) update(fresh);
    } catch (_) {
      /* try again on the next round */
    }
    follow();
  }, FOLLOW_INTERVAL_MS);
}

function update(entry) {
  current = entry;
  render(entry);
  onChange(entry);
}

function wire() {
  wired = true;
  $("#event-label").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-label]");
    if (button) applyLabel(button.dataset.label);
  });
  $("#event-summarize").addEventListener("click", requestSummary);
  $("#event-frames-toggle").addEventListener("click", toggleFrames);
  $("#event-frames").addEventListener("click", (event) => {
    const frame = event.target.closest(".event-frame");
    if (frame) showImage(frame.querySelector("img").src, frame.dataset.caption);
  });
  $("#event-speed").addEventListener("click", cycleSpeed);
  $("#event-back").addEventListener("click", () => seek(-2));
  $("#event-forward").addEventListener("click", () => seek(2));
  $("#event-image").addEventListener("click", (event) => showImage(event.target.src));
  $("#event-go-live").addEventListener("click", () => {
    const cameraId = current && current.camera_id;
    closeModal(MODAL_ID);
    if (cameraId) navigate("live", { cameraId });
  });
  document.getElementById(MODAL_ID).addEventListener("modal:closed", () => {
    clearTimeout(followTimer);
    const video = $("#event-video");
    video.pause();
    video.removeAttribute("src");
    video.load();
    current = null;
    onChange = () => {};
  });
}

/* -------------------------------------------------------------- Public API */
/**
 * Opens the window for an event.
 * @param {object} entry  an event as returned by the journal API
 * @param {(entry: object) => void} [changed] called whenever the event changes (verdict, summary…)
 */
export function openEventDetail(entry, changed = () => {}) {
  if (!wired) wire();
  if (!entry) {
    showToast("Bu olay kaydı artık yok.", "warning");
    return;
  }
  current = entry;
  onChange = changed;
  $("#event-frames").hidden = true;
  $("#event-frames-toggle").textContent = "Kareleri göster";
  $("#event-speed").textContent = "1×";
  render(entry);
  openModal(MODAL_ID);
  follow();
}

/** Lets the Events page push a server update into the window when it shows that event. */
export function syncEventDetail(entry) {
  if (current && entry && current.id === entry.id) {
    current = entry;
    render(entry);
    follow();
  }
}
