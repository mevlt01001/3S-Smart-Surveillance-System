/**
 * Live view: the camera wall, alarm highlighting and the single-camera view with its
 * recent history.
 */

import { captureReference, getLiveState, getSettings, listCameras, listEvents, listRules, snapshotUrl } from "./api.js";
import { eventSeconds, eventTitle, levelBadge, openEventDetail } from "./event-detail.js";
import { clearOverlay, drawOverlay } from "./overlay.js";
import { navigate } from "./router.js";
import { startStream } from "./stream.js";
import {
  $, $$, bindSegmented, downloadBlob, escapeHTML, formatDuration, icon, isAnyModalOpen, showError, showToast,
} from "./ui.js";

const POLL_INTERVAL_MS = 400;
const RULES_REFRESH_MS = 10000;
const REDUCED_STREAM_FPS = 8;
const TIMELINE_MINUTES = 30;
const TIMELINE_SEGMENTS = 36;
const LAYOUTS = ["grid-1x1", "grid-2x2", "grid-3x2", "grid-4x3"];
const ALARM_LEVELS = ["warn", "danger", "offline"];

let cameras = [];
let rules = [];
let fleet = {};
let detections = {};
let wall = { default_layout: "grid-3x2", alarm_borders: true, hud_badges: true, click_to_focus: true, zero_latency_mode: true };

let layout = "grid-3x2";
let layoutChosenByUser = false;
let focusedId = null;
let onlyAlarms = false;
let showZones = true;
let showDetections = true;

let mounted = false;
let wired = false;
let pollTimer = null;
let rulesLoadedAt = 0;
let renderedIds = "";
let setActiveLayout = () => {};
const streams = new Map();
let tileObserver = null;
let recentEvents = new Map();

const grid = () => $("#live-grid");

/* -------------------------------------------------------------------- Data */
async function loadCamerasAndRules() {
  const [cameraList, ruleData] = await Promise.all([listCameras(), listRules()]);
  cameras = cameraList;
  rules = ruleData.rules || [];
  rulesLoadedAt = Date.now();
}

async function loadWallSettings() {
  try {
    const settings = await getSettings();
    wall = { ...wall, ...(settings.live_wall || {}) };
  } catch (_) {
    /* keep the defaults */
  }
}

/** Zones evaluated on a camera: its own enabled rules plus the rules that apply everywhere. */
function zonesFor(cameraId) {
  return rules
    .filter((rule) => rule.enabled !== false && (rule.camera_id === cameraId || rule.scope === "system"))
    .flatMap((rule) => rule.zones || []);
}

const changeZonesFor = (cameraId) => zonesFor(cameraId).filter((zone) => zone.zone_type === "change_detection");

/** What a tile should tell the operator right now. */
function tileState(cameraId) {
  const state = fleet[cameraId];
  const rule = detections[cameraId];
  if (state && state.stream_live === false) {
    return state.stream_connecting || state.stream_standby
      ? { level: "connecting", text: "Bağlanıyor…" }
      : { level: "offline", text: "Sinyal yok" };
  }
  if (rule && rule.alarm) return { level: "danger", text: rule.alarm_text || "Kural ihlali" };
  if (state && state.analyzed && state.tier === "critical") return { level: "danger", text: "Kritik hareket" };
  if (state && state.analyzed && state.tier === "warning") return { level: "warn", text: "Şüpheli hareket" };
  return { level: "ok", text: "" };
}

function visibleCameras() {
  if (focusedId) return cameras.filter((camera) => camera.id === focusedId);
  if (onlyAlarms) return cameras.filter((camera) => ALARM_LEVELS.includes(tileState(camera.id).level));
  return cameras;
}

/* --------------------------------------------------------------- Rendering */
function tileHTML(camera) {
  const name = escapeHTML(camera.name || "Kamera");
  const referenceButton = changeZonesFor(camera.id).length
    ? `<button type="button" class="tile-button has-text" data-action="reference"
               title="Bölgenin şu anki boş hâlini karşılaştırma görüntüsü olarak kaydet">Referans al</button>`
    : "";
  return `
    <article class="tile" data-camera="${escapeHTML(camera.id)}">
      <img class="tile-video" src="${snapshotUrl(camera.id)}" alt="${name}">
      <canvas class="tile-overlay"></canvas>
      <header class="tile-top">
        <span class="tile-name" title="${name}"><span class="status-dot"></span><span class="tile-name-text">${name}</span></span>
        <span class="tile-badge" hidden></span>
      </header>
      <footer class="tile-actions">
        ${referenceButton}
        <button type="button" class="tile-button" data-action="snapshot" title="Fotoğraf çek ve indir" aria-label="Fotoğraf çek">${icon("photo")}</button>
        <button type="button" class="tile-button" data-action="focus" title="${focusedId ? "Tüm kameralara dön" : "Bu kamerayı büyüt"}" aria-label="Büyüt">${icon(focusedId ? "live" : "expand")}</button>
      </footer>
    </article>`;
}

function emptyHTML() {
  if (cameras.length === 0) {
    return `
      <div class="empty">
        ${icon("camera")}
        <p class="empty-title">Henüz kamera eklenmedi</p>
        <p>Canlı izlemeye başlamak için önce bir kamera ekleyin.</p>
        <div class="empty-actions"><button type="button" class="btn btn-primary" data-action="go-cameras">Kamera ekle</button></div>
      </div>`;
  }
  return `
    <div class="empty">
      ${icon("check")}
      <p class="empty-title">Şu anda alarm veren kamera yok</p>
      <p>Bir kamera uyarı verdiğinde veya sinyali kesildiğinde burada görünür.</p>
    </div>`;
}

function render() {
  stopStreams();
  const visible = visibleCameras();
  renderedIds = visible.map((camera) => camera.id).join("|");

  const focused = cameras.find((camera) => camera.id === focusedId);
  $("#live-focus-bar").hidden = !focused;
  $("#live-history").hidden = !focused;
  if (focused) $("#live-focus-name").textContent = focused.name || "Kamera";
  setActiveLayout(focused ? "" : layout);

  const container = grid();
  container.className = `live-grid ${focused ? "is-focused" : layout}`;
  container.classList.toggle("has-alarm-borders", wall.alarm_borders !== false);
  container.classList.toggle("is-clickable", wall.click_to_focus !== false);
  container.innerHTML = visible.length ? visible.map(tileHTML).join("") : emptyHTML();

  $$(".tile-video", container).forEach((image) => {
    // The overlay depends on the picture's proportions, known once the first frame arrived
    image.addEventListener("load", () => drawTile(image.closest(".tile")), { once: true });
  });

  watchTiles();
  applyStates();
  if (focused) loadHistory(focused.id);
}

function applyStates() {
  const badgesEnabled = wall.hud_badges !== false;
  $$(".tile", grid()).forEach((tile) => {
    const state = tileState(tile.dataset.camera);
    ["is-warn", "is-danger", "is-offline", "is-connecting"].forEach((name) => tile.classList.remove(name));
    if (state.level !== "ok") tile.classList.add(`is-${state.level}`);

    const dot = $(".status-dot", tile);
    dot.className = `status-dot ${{ ok: "is-ok", warn: "is-warn", danger: "is-danger", connecting: "is-busy", offline: "" }[state.level]}`;

    const badge = $(".tile-badge", tile);
    const signalProblem = state.level === "offline" || state.level === "connecting";
    badge.hidden = !state.text || !(badgesEnabled || signalProblem);
    badge.textContent = state.text;
    badge.title = state.text;
    drawTile(tile);
  });

  const total = cameras.length;
  const online = cameras.filter((camera) => tileState(camera.id).level !== "offline").length;
  const count = $("#live-count");
  count.textContent = total ? `${online}/${total} çevrimiçi` : "";
  count.className = `badge ${online === total ? "is-ok" : "is-warn"}`;
}

function drawTile(tile) {
  if (!tile) return;
  const cameraId = tile.dataset.camera;
  const canvas = $(".tile-overlay", tile);
  const state = fleet[cameraId];
  if (state && state.stream_live === false) {
    clearOverlay(canvas);
    return;
  }
  const detection = detections[cameraId] || {};
  drawOverlay(canvas, $(".tile-video", tile), {
    zones: zonesFor(cameraId),
    detections: detection.detections || [],
    changeResults: detection.change_results || [],
    showZones,
    showDetections,
  });
}

/* ----------------------------------------------------------------- Streams */
function stopStreams() {
  if (tileObserver) tileObserver.disconnect();
  tileObserver = null;
  streams.forEach((stop) => stop());
  streams.clear();
}

/** Only tiles that are on screen receive video; scrolled-away tiles are paused. */
function watchTiles() {
  const maxFps = wall.zero_latency_mode === false ? REDUCED_STREAM_FPS : 0;
  tileObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      const cameraId = entry.target.dataset.camera;
      if (entry.isIntersecting && !streams.has(cameraId) && !document.hidden) {
        streams.set(cameraId, startStream(cameraId, $(".tile-video", entry.target), maxFps));
      } else if (!entry.isIntersecting && streams.has(cameraId)) {
        streams.get(cameraId)();
        streams.delete(cameraId);
      }
    });
  }, { rootMargin: "120px", threshold: 0.01 });
  $$(".tile", grid()).forEach((tile) => tileObserver.observe(tile));
}

/* ----------------------------------------------------------------- Polling */
function stopPolling() {
  clearTimeout(pollTimer);
  pollTimer = null;
}

function startPolling() {
  stopPolling();
  const tick = async () => {
    await poll();
    if (mounted && !document.hidden) pollTimer = setTimeout(tick, POLL_INTERVAL_MS);
  };
  tick();
}

async function poll() {
  let data;
  try {
    data = await getLiveState();
  } catch (_) {
    return; // the status line reports connection problems
  }
  if (!mounted) return;
  detections = data.detections || {};
  const reported = (data.fleet && data.fleet.cameras) || [];
  fleet = Object.fromEntries(reported.map((state) => [state.camera_id, state]));

  try {
    // Cameras added or removed elsewhere: rebuild the wall
    const knownIds = cameras.map((camera) => camera.id).sort().join("|");
    if (reported.map((state) => state.camera_id).sort().join("|") !== knownIds) {
      await loadCamerasAndRules();
      if (!cameras.some((camera) => camera.id === focusedId)) focusedId = null;
      render();
      return;
    }
    if (Date.now() - rulesLoadedAt > RULES_REFRESH_MS && (await rulesChanged())) {
      render();
      return;
    }
  } catch (_) {
    return;
  }

  if (visibleCameras().map((camera) => camera.id).join("|") !== renderedIds) render();
  else applyStates();
}

/** Rules edited on another screen show up on the wall without a reload. */
async function rulesChanged() {
  rulesLoadedAt = Date.now();
  const signature = (list) => JSON.stringify(list.map((rule) => [rule.id, rule.enabled, rule.updated_at]));
  const next = (await listRules()).rules || [];
  const changed = signature(next) !== signature(rules);
  rules = next;
  return changed;
}

/* ----------------------------------------------------------------- Actions */
function setFocus(cameraId) {
  focusedId = cameraId;
  render();
  $("#content").scrollTop = 0;
}

async function takeSnapshot(cameraId) {
  const camera = cameras.find((item) => item.id === cameraId);
  try {
    const response = await fetch(snapshotUrl(cameraId));
    if (!response.ok) throw new Error("görüntü alınamadı");
    const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "_").slice(0, 15);
    const name = String((camera && camera.name) || cameraId).replace(/[^\w-]+/g, "_").slice(0, 40);
    downloadBlob(await response.blob(), `${name}_${stamp}.jpg`);
    showToast("Fotoğraf indirildi.", "success", 2500);
  } catch (err) {
    showError("Fotoğraf çekilemedi", err);
  }
}

async function takeReference(cameraId, button) {
  const zones = changeZonesFor(cameraId);
  button.disabled = true;
  let saved = 0;
  let lastError = "";
  for (const zone of zones) {
    try {
      await captureReference(cameraId, zone.id);
      saved += 1;
    } catch (err) {
      lastError = err.message;
    }
  }
  button.disabled = false;
  if (saved === zones.length) {
    showToast("Referans görüntü kaydedildi. Bölge artık izleniyor.", "success");
  } else {
    showToast(`Referans kaydedilemedi: ${lastError || "kamera görüntüsü yok"}`, "error", 6000);
  }
}

function onGridClick(event) {
  const actionButton = event.target.closest("[data-action]");
  if (actionButton && actionButton.dataset.action === "go-cameras") {
    navigate("cameras");
    return;
  }
  const tile = event.target.closest(".tile");
  if (!tile) return;
  const cameraId = tile.dataset.camera;
  const action = actionButton ? actionButton.dataset.action : wall.click_to_focus !== false ? "focus" : "";
  if (action === "snapshot") takeSnapshot(cameraId);
  else if (action === "reference") takeReference(cameraId, actionButton);
  else if (action === "focus") setFocus(focusedId === cameraId ? null : cameraId);
}

/* ------------------------------------------------- Single-camera history */
async function loadHistory(cameraId) {
  let entries;
  try {
    entries = (await listEvents({ cameraId, limit: 60 })).journal || [];
  } catch (_) {
    return;
  }
  if (focusedId !== cameraId) return;
  recentEvents = new Map(entries.map((entry) => [entry.id, entry]));
  renderHistory();
}

function renderHistory() {
  const entries = Array.from(recentEvents.values());
  const now = Date.now() / 1000;
  const windowSec = TIMELINE_MINUTES * 60;
  const segmentSec = windowSec / TIMELINE_SEGMENTS;
  const weight = { critical: 2, warning: 1 };

  $("#live-timeline").innerHTML = Array.from({ length: TIMELINE_SEGMENTS }, (_, index) => {
    const from = now - windowSec + index * segmentSec;
    const to = from + segmentSec;
    const worst = entries
      .filter((entry) => entry.timestamp < to && (entry.is_ongoing || entry.timestamp + eventSeconds(entry) >= from))
      .sort((a, b) => (weight[b.tier] || 0) - (weight[a.tier] || 0))[0];
    const time = new Date(from * 1000).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    if (!worst) return `<span class="timeline-segment" title="${time}"></span>`;
    const level = worst.tier === "critical" ? "is-danger" : "is-warn";
    return `<button type="button" class="timeline-segment ${level}" data-event="${escapeHTML(worst.id)}"
                    title="${time} — ${escapeHTML(eventTitle(worst))}"></button>`;
  }).join("");

  $("#live-history-list").innerHTML = entries.length
    ? entries.slice(0, 30).map((entry) => `
        <button type="button" class="history-item" data-event="${escapeHTML(entry.id)}">
          ${levelBadge(entry)}
          <span class="history-title">${escapeHTML(eventTitle(entry))}</span>
          <span class="history-time">${escapeHTML(entry.date_str || "")} ${escapeHTML(entry.timestamp_str || "")}${entry.is_ongoing ? " · sürüyor" : eventSeconds(entry) ? ` · ${formatDuration(eventSeconds(entry))}` : ""}</span>
        </button>`).join("")
    : `<p class="hint">Bu kamerada kayıtlı olay yok.</p>`;
}

function onHistoryClick(event) {
  const item = event.target.closest("[data-event]");
  if (!item) return;
  openEventDetail(recentEvents.get(item.dataset.event), (updated) => {
    recentEvents.set(updated.id, updated);
    renderHistory();
  });
}

/* --------------------------------------------------------------- Lifecycle */
function wire() {
  wired = true;
  setActiveLayout = bindSegmented($("#live-layouts"), "layout", (value) => {
    layout = value;
    layoutChosenByUser = true;
    focusedId = null;
    render();
  });
  $("#live-only-alarms").addEventListener("change", (event) => {
    onlyAlarms = event.target.checked;
    render();
  });
  $("#live-show-zones").addEventListener("change", (event) => {
    showZones = event.target.checked;
    applyStates();
  });
  $("#live-show-detections").addEventListener("change", (event) => {
    showDetections = event.target.checked;
    applyStates();
  });
  $("#live-exit-focus").addEventListener("click", () => setFocus(null));
  grid().addEventListener("click", onGridClick);
  $("#live-history").addEventListener("click", onHistoryClick);

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (!mounted) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(applyStates, 150);
  });
  document.addEventListener("visibilitychange", () => {
    if (!mounted) return;
    if (document.hidden) {
      // A hidden tab must not keep decoding video
      stopPolling();
      stopStreams();
    } else {
      watchTiles();
      startPolling();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mounted && focusedId && !isAnyModalOpen()) setFocus(null);
  });
}

/** @param {{cameraId?: string}} [params] camera to open in the single-camera view */
export async function mount(params = {}) {
  mounted = true;
  if (!wired) wire();
  if (params.cameraId) focusedId = params.cameraId;
  if (!cameras.length) grid().innerHTML = `<div class="loading"><div class="spinner"></div><span>Kameralar yükleniyor…</span></div>`;

  try {
    await Promise.all([loadCamerasAndRules(), loadWallSettings()]);
  } catch (err) {
    if (!mounted) return;
    grid().innerHTML = `<div class="empty"><p class="empty-title">Kameralar yüklenemedi</p><p>${escapeHTML(err.message)}</p></div>`;
    renderedIds = "load-failed"; // the first successful poll rebuilds the wall
    startPolling();
    return;
  }
  if (!mounted) return;
  if (!layoutChosenByUser && LAYOUTS.includes(wall.default_layout)) layout = wall.default_layout;
  if (!cameras.some((camera) => camera.id === focusedId)) focusedId = null;
  render();
  if (!document.hidden) startPolling();
}

export function unmount() {
  mounted = false;
  stopPolling();
  stopStreams();
  grid().innerHTML = "";
  renderedIds = "";
  focusedId = null;
}
