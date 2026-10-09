/**
 * Events page: the searchable list of everything the system recorded, updated live.
 */

import { clearEvents, getFleetStatus, labelEvent, listEvents, openEventStream } from "./api.js";
import {
  eventTitle, isRuleEvent, levelBadge, levelInfo, openEventDetail, summaryHeadline, syncEventDetail,
} from "./event-detail.js";
import { refreshEventsBadge, subscribeSystemStats } from "./shell.js";
import {
  $, NO_IMAGE, bindSegmented, confirmDialog, downloadBlob, escapeHTML, formatDuration, icon, setHTML, showError, showToast,
} from "./ui.js";

const LAYOUT_KEY = "aegis.events.layout";
const MAX_ENTRIES = 300;
const NEW_HIGHLIGHT_MS = 6000;
const REVIEW_LABELS = { correct: "Doğru alarm", false_positive: "Hatalı alarm" };

let entries = [];
let filters = { search: "", camera: "", time: "all", kind: "all", review: "all" };
let page = 1;
let pageSize = 12;
let layout = localStorage.getItem(LAYOUT_KEY) === "table" ? "table" : "cards";
let stream = null;
let unsubscribeStats = null;
let analysisServerReady = true;
let fleetNotice = "";
let wired = false;
let setActiveLayout = () => {};
const freshIds = new Set();

/* --------------------------------------------------------------- Filtering */
function sinceTimestamp(range) {
  const now = Date.now() / 1000;
  if (range === "15m") return now - 15 * 60;
  if (range === "1h") return now - 3600;
  if (range === "6h") return now - 6 * 3600;
  if (range === "today") return new Date().setHours(0, 0, 0, 0) / 1000;
  return 0;
}

const reviewOf = (entry) => (REVIEW_LABELS[entry.operator_label] ? entry.operator_label : "unlabeled");

function filteredEntries() {
  const since = sinceTimestamp(filters.time);
  const query = filters.search.trim().toLocaleLowerCase("tr");
  return entries.filter((entry) => {
    if (filters.camera && entry.camera_id !== filters.camera) return false;
    if ((entry.timestamp || 0) < since) return false;
    if (filters.kind === "rule" && !isRuleEvent(entry)) return false;
    if ((filters.kind === "critical" || filters.kind === "warning") && entry.tier !== filters.kind) return false;
    if (filters.review !== "all" && reviewOf(entry) !== filters.review) return false;
    if (!query) return true;
    const haystack = [entry.camera_name, eventTitle(entry), entry.rule_description, entry.message, entry.ai_summary]
      .filter(Boolean).join(" ").toLocaleLowerCase("tr");
    return haystack.includes(query);
  });
}

/* --------------------------------------------------------------- Rendering */
const describe = (entry) => summaryHeadline(entry) || (isRuleEvent(entry) ? entry.rule_description || "" : "");

function durationText(entry) {
  if (entry.is_ongoing) return "Sürüyor";
  return entry.duration_sec ? formatDuration(entry.duration_sec) : "";
}

function reviewButtons(entry) {
  const current = reviewOf(entry);
  return `
    <button type="button" class="chip ${current === "correct" ? "is-active is-ok" : ""}" data-action="label" data-label="correct" title="Bu alarm doğruydu">${icon("check")} Doğru</button>
    <button type="button" class="chip ${current === "false_positive" ? "is-active is-muted" : ""}" data-action="label" data-label="false_positive" title="Bu alarm hatalıydı">${icon("close")} Hatalı</button>`;
}

function cardHTML(entry) {
  const description = describe(entry);
  const duration = durationText(entry);
  return `
    <article class="event-card is-${escapeHTML(entry.tier || "normal")} ${freshIds.has(entry.id) ? "is-new" : ""}" data-event="${escapeHTML(entry.id)}">
      <button type="button" class="event-thumb" data-action="open" aria-label="Olayı aç">
        <img src="${escapeHTML(entry.snapshot_url || NO_IMAGE)}" alt="" loading="lazy">
        ${entry.clip_url ? `<span class="event-play">${icon("play")}</span>` : ""}
        ${duration ? `<span class="event-duration">${duration}</span>` : ""}
      </button>
      <div class="event-body" data-action="open">
        <div class="event-meta">${levelBadge(entry)}<time>${escapeHTML(entry.date_str || "")} ${escapeHTML(entry.timestamp_str || "")}</time></div>
        <h3 class="event-title">${escapeHTML(eventTitle(entry))}</h3>
        <p class="event-camera">${icon("camera")} ${escapeHTML(entry.camera_name || entry.camera_id)}</p>
        ${description ? `<p class="event-description">${escapeHTML(description)}</p>` : ""}
      </div>
      <footer class="event-review-bar">${reviewButtons(entry)}</footer>
    </article>`;
}

function rowHTML(entry) {
  return `
    <tr class="is-clickable ${freshIds.has(entry.id) ? "is-new" : ""}" data-event="${escapeHTML(entry.id)}" data-action="open">
      <td><time>${escapeHTML(entry.date_str || "")} ${escapeHTML(entry.timestamp_str || "")}</time></td>
      <td>${escapeHTML(entry.camera_name || entry.camera_id)}</td>
      <td>${escapeHTML(eventTitle(entry))}<span class="cell-sub">${escapeHTML(describe(entry))}</span></td>
      <td>${levelBadge(entry)}</td>
      <td>${durationText(entry)}</td>
      <td><div class="chip-row">${reviewButtons(entry)}</div></td>
    </tr>`;
}

function emptyHTML() {
  const nothingRecorded = entries.length === 0;
  return `
    <div class="empty">
      ${icon(nothingRecorded ? "events" : "search")}
      <p class="empty-title">${nothingRecorded ? "Henüz kayıtlı olay yok" : "Aramanıza uyan olay yok"}</p>
      <p>${nothingRecorded
        ? "Bir alarm oluştuğunda videosu ve fotoğrafıyla birlikte burada görünür."
        : "Filtreleri değiştirerek yeniden deneyin."}</p>
    </div>`;
}

function renderPager(total, pageCount) {
  const from = total ? (page - 1) * pageSize + 1 : 0;
  const to = Math.min(page * pageSize, total);
  $("#events-pager-info").textContent = total ? `${from}–${to} / ${total}` : "";

  const first = Math.max(1, Math.min(page - 2, pageCount - 4));
  const pages = Array.from({ length: Math.min(5, pageCount) }, (_, index) => first + index);
  const button = (label, target, { active = false, disabled = false } = {}) =>
    `<button type="button" class="btn btn-sm ${active ? "is-active" : ""}" data-page="${target}" ${disabled ? "disabled" : ""}>${label}</button>`;
  $("#events-pager-buttons").innerHTML = pageCount > 1
    ? button("‹", page - 1, { disabled: page === 1 })
      + pages.map((number) => button(number, number, { active: number === page })).join("")
      + button("›", page + 1, { disabled: page === pageCount })
    : "";
}

function renderSummary(shown) {
  const unreviewed = entries.filter((entry) => reviewOf(entry) === "unlabeled").length;
  const critical = entries.filter((entry) => entry.tier === "critical").length;
  const parts = [shown === entries.length ? `${entries.length} olay` : `${shown} olay gösteriliyor (toplam ${entries.length})`];
  if (critical) parts.push(`${critical} kritik`);
  if (unreviewed) parts.push(`${unreviewed} incelenmemiş`);
  $("#events-summary").textContent = entries.length ? parts.join(" · ") : "";
}

function render() {
  const filtered = filteredEntries();
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  page = Math.min(Math.max(1, page), pageCount);
  const visible = filtered.slice((page - 1) * pageSize, page * pageSize);

  const list = $("#events-list");
  if (!visible.length) {
    setHTML(list, emptyHTML());
  } else if (layout === "table") {
    setHTML(list, `
      <div class="table-wrap"><table class="table events-table">
        <thead><tr><th>Zaman</th><th>Kamera</th><th>Olay</th><th>Seviye</th><th>Süre</th><th>Karar</th></tr></thead>
        <tbody>${visible.map(rowHTML).join("")}</tbody>
      </table></div>`);
  } else {
    setHTML(list, `<div class="event-grid">${visible.map(cardHTML).join("")}</div>`);
  }
  renderSummary(filtered.length);
  renderPager(filtered.length, pageCount);
  renderCameraFilter();
}

function renderCameraFilter() {
  const select = $("#events-camera");
  const names = new Map(entries.map((entry) => [entry.camera_id, entry.camera_name || entry.camera_id]));
  const options = `<option value="">Tüm kameralar</option>` + Array.from(names, ([cameraId, name]) =>
    `<option value="${escapeHTML(cameraId)}">${escapeHTML(name)}</option>`).join("");
  if (select.dataset.rendered === options) return;
  select.innerHTML = options;
  select.dataset.rendered = options;
  select.value = names.has(filters.camera) ? filters.camera : "";
  filters.camera = select.value;
}

function renderNotice() {
  const notice = $("#events-notice");
  const text = analysisServerReady
    ? fleetNotice
    : "Analiz sunucusuna ulaşılamıyor. Sorun giderilene kadar yeni olay kaydedilmez.";
  notice.hidden = !text;
  notice.textContent = text;
}

/* -------------------------------------------------------------------- Data */
function upsert(entry) {
  const index = entries.findIndex((item) => item.id === entry.id);
  if (index === -1) {
    entries.unshift(entry);
    entries.length = Math.min(entries.length, MAX_ENTRIES);
    freshIds.add(entry.id);
    setTimeout(() => {
      freshIds.delete(entry.id);
      render();
    }, NEW_HIGHLIGHT_MS);
  } else {
    entries[index] = { ...entries[index], ...entry };
  }
  return entries[index === -1 ? 0 : index];
}

async function load() {
  try {
    entries = (await listEvents({ limit: MAX_ENTRIES })).journal || [];
    render();
  } catch (err) {
    setHTML($("#events-list"), `<div class="empty"><p class="empty-title">Olaylar yüklenemedi</p><p>${escapeHTML(err.message)}</p></div>`);
  }
}

async function loadFleetNotice() {
  try {
    const fleet = await getFleetStatus();
    if (fleet.analysis_enabled === false) {
      fleetNotice = "Olağandışı hareket algılama Ayarlar’dan kapatılmış. Yalnızca kural ihlalleri kaydedilir.";
    } else if (fleet.offline_count > 0) {
      fleetNotice = `${fleet.offline_count} kameradan görüntü alınamıyor; bu kameralarda olay algılanamaz.`;
    } else {
      fleetNotice = "";
    }
  } catch (_) {
    fleetNotice = "";
  }
  renderNotice();
}

function onStreamMessage(message) {
  let data;
  try {
    data = JSON.parse(message.data);
  } catch (_) {
    return;
  }
  if (data.type === "journal_cleared") {
    entries = [];
    page = 1;
  } else {
    const entry = data.entry || data;
    if (!entry || !entry.id || !entry.camera_id) return;
    syncEventDetail(upsert(entry));
  }
  render();
  refreshEventsBadge();
}

/* ----------------------------------------------------------------- Actions */
async function setLabel(entry, label) {
  // Pressing the selected verdict again withdraws it
  const next = reviewOf(entry) === label ? "unlabeled" : label;
  try {
    upsert({ ...entry, ...(await labelEvent(entry.id, next)) });
    render();
    refreshEventsBadge();
  } catch (err) {
    showError("Karar kaydedilemedi", err);
  }
}

function onListClick(event) {
  const target = event.target.closest("[data-action]");
  const holder = event.target.closest("[data-event]");
  if (!target || !holder) return;
  const entry = entries.find((item) => item.id === holder.dataset.event);
  if (!entry) return;
  if (target.dataset.action === "label") {
    setLabel(entry, target.dataset.label);
  } else {
    openEventDetail(entry, (updated) => {
      upsert(updated);
      render();
    });
  }
}

function exportEvents() {
  const rows = filteredEntries();
  if (!rows.length) {
    showToast("Dışa aktarılacak olay yok.", "info");
    return;
  }
  const cell = (value) => `"${String(value ?? "").replace(/"/g, '""').replace(/\s+/g, " ")}"`;
  const lines = [["Tarih", "Saat", "Kamera", "Olay", "Seviye", "Süre (sn)", "Karar", "Özet"].map(cell).join(";")];
  rows.forEach((entry) => {
    lines.push([
      entry.date_str, entry.timestamp_str, entry.camera_name, eventTitle(entry), levelInfo(entry).text,
      entry.duration_sec ?? "", REVIEW_LABELS[entry.operator_label] || "İncelenmedi", describe(entry),
    ].map(cell).join(";"));
  });
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  // The byte-order mark makes spreadsheet programs read the Turkish characters correctly
  downloadBlob(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }), `olaylar_${stamp}.csv`);
  showToast(`${rows.length} olay dışa aktarıldı.`, "success");
}

async function clearAll() {
  if (!entries.length) {
    showToast("Silinecek olay yok.", "info");
    return;
  }
  const confirmed = await confirmDialog({
    title: "Tüm olaylar silinsin mi?",
    message: `${entries.length} olay kaydı, videoları ve fotoğraflarıyla birlikte kalıcı olarak silinecek. Bu işlem geri alınamaz.`,
    confirmText: "Tümünü sil",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await clearEvents();
    entries = [];
    page = 1;
    render();
    refreshEventsBadge();
    showToast("Tüm olaylar silindi.", "success");
  } catch (err) {
    showError("Olaylar silinemedi", err);
  }
}

/* --------------------------------------------------------------- Lifecycle */
function wire() {
  wired = true;
  const bindFilter = (selector, key, eventName = "change") => {
    $(selector).addEventListener(eventName, (event) => {
      filters[key] = event.target.value;
      page = 1;
      render();
    });
  };
  bindFilter("#events-search", "search", "input");
  bindFilter("#events-camera", "camera");
  bindFilter("#events-time", "time");
  bindFilter("#events-kind", "kind");
  bindFilter("#events-review", "review");

  setActiveLayout = bindSegmented($("#events-layout"), "mode", (mode) => {
    layout = mode;
    localStorage.setItem(LAYOUT_KEY, mode);
    setActiveLayout(mode);
    render();
  });
  setActiveLayout(layout);

  $("#events-page-size").addEventListener("change", (event) => {
    pageSize = Number(event.target.value);
    page = 1;
    render();
  });
  $("#events-pager-buttons").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-page]");
    if (!button) return;
    page = Number(button.dataset.page);
    render();
    $("#content").scrollTop = 0;
  });
  $("#events-list").addEventListener("click", onListClick);
  $("#events-export").addEventListener("click", exportEvents);
  $("#events-clear").addEventListener("click", clearAll);
}

export function mount() {
  if (!wired) wire();
  if (!entries.length) setHTML($("#events-list"), `<div class="loading"><div class="spinner"></div></div>`);
  load();
  loadFleetNotice();

  if (!stream) {
    stream = openEventStream();
    stream.onmessage = onStreamMessage;
  }
  if (!unsubscribeStats) {
    unsubscribeStats = subscribeSystemStats((stats) => {
      analysisServerReady = Boolean(stats.triton && stats.triton.status === "READY");
      renderNotice();
    });
  }
}

export function unmount() {
  if (stream) stream.close();
  stream = null;
  if (unsubscribeStats) unsubscribeStats();
  unsubscribeStats = null;
}
