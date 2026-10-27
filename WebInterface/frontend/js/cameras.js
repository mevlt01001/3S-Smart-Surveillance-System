/**
 * Cameras page: the list of cameras, finding cameras on the network, adding one by address,
 * renaming / describing a camera and removing it.
 */

import {
  addCamera, deleteCamera, getFleetStatus, listCameras, reconnectCamera, scanNetwork, snapshotUrl, updateCamera,
} from "./api.js";
import { t } from "./i18n.js";
import { startStream } from "./stream.js";
import {
  $, $$, bindSegmented, closeModal, confirmDialog, copyText, escapeHTML, icon, maskCredentials, openModal, setHTML,
  showError, showToast, withBusy,
} from "./ui.js";

const LAYOUT_KEY = "aegis.cameras.layout";
const SNAPSHOT_INTERVAL_MS = 2500;
const STATUS_INTERVAL_MS = 3000;
const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

let cameras = [];
let fleet = {};
let layout = localStorage.getItem(LAYOUT_KEY) === "list" ? "list" : "grid";
let mounted = false;
let wired = false;
let snapshotTimer = null;
let statusTimer = null;
let editingId = null;
let stopPreview = null;
let scanning = false;
let foundDevices = new Map();
// Thumbnails are first requested with one fixed stamp so that re-rendering the list leaves them alone
let thumbnailStamp = Date.now();
let setActiveLayout = () => {};
const loadingSnapshots = new Set();

/** Network address as people write it: the port is shown only when it is not the usual one. */
const addressOf = (device) => (Number(device.port) === 80 ? String(device.ip) : `${device.ip}:${device.port}`);

/* ------------------------------------------------------------------- State */
/** What the user needs to know about a camera's connection, in one word and one sentence. */
function connectionState(camera) {
  const stream = fleet[camera.id] || camera;
  if (camera.status === "auth_error") {
    return { level: "is-danger", text: t("Şifre hatalı"), hint: t("Kullanıcı adı veya şifre yanlış. “Elle ekle” ile aynı adresi doğru bilgilerle yeniden ekleyin.") };
  }
  if (stream.stream_live !== false) return { level: "is-ok", text: t("Canlı"), hint: "" };
  if (stream.stream_connecting) return { level: "is-busy", text: t("Bağlanıyor…"), hint: "" };
  if (stream.stream_standby) return { level: "is-ok", text: t("Hazır"), hint: "" };
  return { level: "is-danger", text: t("Sinyal yok"), hint: t(camera.status === "online"
    ? "Kameradan görüntü gelmiyor. Kameranın açık ve ağa bağlı olduğunu kontrol edin."
    : "Kameraya ulaşılamıyor. Adresini ve ağ bağlantısını kontrol edin.") };
}

function announceResult(camera, verb) {
  const name = camera.name || camera.ip;
  const params = { name, verb: t(verb) };
  if (camera.status === "online") showToast(t("“{name}” {verb}.", params), "success");
  else if (camera.status === "auth_error") showToast(t("“{name}” {verb}, ancak kullanıcı adı veya şifre yanlış.", params), "warning", 7000);
  else showToast(t("“{name}” {verb}, ancak kameraya ulaşılamıyor. Adresini kontrol edin.", params), "warning", 7000);
}

/* --------------------------------------------------------------- Rendering */
function actionsHTML() {
  return `
    <button type="button" class="btn-icon" data-action="edit" title="${t("Adını ve açıklamasını düzenle")}" aria-label="${t("Düzenle")}">${icon("edit")}</button>
    <button type="button" class="btn-icon" data-action="reconnect" title="${t("Yeniden bağlan")}" aria-label="${t("Yeniden bağlan")}">${icon("refresh")}</button>
    <button type="button" class="btn-icon" data-action="info" title="${t("Kamera bilgileri")}" aria-label="${t("Kamera bilgileri")}">${icon("info")}</button>
    <span class="toolbar-spacer"></span>
    <button type="button" class="btn-icon is-danger" data-action="delete" title="${t("Kamerayı sil")}" aria-label="${t("Kamerayı sil")}">${icon("trash")}</button>`;
}

function cardHTML(camera) {
  const state = connectionState(camera);
  const name = escapeHTML(camera.name || camera.ip);
  return `
    <article class="camera-card" data-camera="${escapeHTML(camera.id)}">
      <button type="button" class="camera-thumb" data-action="edit" aria-label="${t("{name} kamerasını düzenle", { name })}">
        <img class="camera-snapshot" src="${snapshotUrl(camera.id, thumbnailStamp)}" alt="" loading="lazy">
      </button>
      <div class="camera-info">
        <h3 class="camera-name" title="${name}"><span class="status-dot ${state.level}"></span><span>${name}</span></h3>
        <p class="camera-state ${state.level}" title="${escapeHTML(state.hint)}">${state.text}</p>
        <p class="camera-description">${escapeHTML(camera.description || "")}</p>
      </div>
      <footer class="camera-actions">${actionsHTML()}</footer>
    </article>`;
}

function rowHTML(camera) {
  const state = connectionState(camera);
  return `
    <tr data-camera="${escapeHTML(camera.id)}">
      <td><button type="button" class="camera-thumb is-small" data-action="edit" aria-label="${t("Düzenle")}"><img class="camera-snapshot" src="${snapshotUrl(camera.id, thumbnailStamp)}" alt="" loading="lazy"></button></td>
      <td><strong>${escapeHTML(camera.name || camera.ip)}</strong><span class="cell-sub">${escapeHTML(camera.description || "")}</span></td>
      <td><span class="camera-state ${state.level}" title="${escapeHTML(state.hint)}"><span class="status-dot ${state.level}"></span> ${state.text}</span></td>
      <td>${escapeHTML(addressOf(camera))}</td>
      <td><div class="cell-actions">${actionsHTML()}</div></td>
    </tr>`;
}

function render() {
  const online = cameras.filter((camera) => connectionState(camera).level !== "is-danger").length;
  $("#cameras-summary").textContent = cameras.length ? t("{n} kamera · {online} çevrimiçi", { n: cameras.length, online }) : "";
  const list = $("#cameras-list");
  list.className = layout === "list" || !cameras.length ? "" : "camera-grid";
  if (!cameras.length) {
    setHTML(list, `
      <div class="empty">
        ${icon("camera")}
        <p class="empty-title">${t("Henüz kamera yok")}</p>
        <p>${t("Ağınızdaki kameraları otomatik bulabilir veya adresini yazarak ekleyebilirsiniz.")}</p>
        <div class="empty-actions">
          <button type="button" class="btn btn-primary" data-action="scan">${t("Ağda kamera ara")}</button>
          <button type="button" class="btn" data-action="add">Elle ekle</button>
        </div>
      </div>`);
  } else if (layout === "list") {
    setHTML(list, `
      <div class="table-wrap"><table class="table">
        <thead><tr><th></th><th>${t("Kamera")}</th><th>${t("Durum")}</th><th>${t("Adres")}</th><th></th></tr></thead>
        <tbody>${cameras.map(rowHTML).join("")}</tbody>
      </table></div>`);
  } else {
    setHTML(list, cameras.map(cardHTML).join(""));
  }
}

/* -------------------------------------------------------------------- Data */
async function load() {
  try {
    cameras = await listCameras();
    render();
  } catch (err) {
    if (!cameras.length) {
      setHTML($("#cameras-list"), `<div class="empty"><p class="empty-title">${t("Kameralar yüklenemedi")}</p><p>${escapeHTML(err.message)}</p></div>`);
    }
  }
}

async function refreshStatus() {
  if (document.hidden) return;
  try {
    const reported = (await getFleetStatus()).cameras || [];
    fleet = Object.fromEntries(reported.map((state) => [state.camera_id, state]));
    // Cameras added or removed on another screen
    const known = cameras.map((camera) => camera.id).sort().join("|");
    if (reported.map((state) => state.camera_id).sort().join("|") !== known) await load();
    else render();
  } catch (_) {
    /* the status line reports connection problems */
  }
}

/** Replaces each visible thumbnail with a fresh picture once it has fully loaded (no flicker). */
function refreshSnapshots() {
  if (document.hidden) return;
  $$("#cameras-list [data-camera]").forEach((holder) => {
    const cameraId = holder.dataset.camera;
    const image = $(".camera-snapshot", holder);
    if (!image || loadingSnapshots.has(cameraId)) return;
    loadingSnapshots.add(cameraId);
    const next = new Image();
    const done = () => loadingSnapshots.delete(cameraId);
    next.onload = () => {
      image.src = next.src;
      done();
    };
    next.onerror = done;
    next.src = snapshotUrl(cameraId);
  });
}

/* ----------------------------------------------------------------- Actions */
async function removeCamera(camera) {
  const confirmed = await confirmDialog({
    title: "Kamera silinsin mi?",
    message: t("“{name}” kamerası ve bu kameraya tanımlı kurallar silinecek. Kaydedilmiş olaylar korunur.", { name: camera.name || camera.ip }),
    confirmText: "Kamerayı sil",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const result = await deleteCamera(camera.id);
    const removedRules = (result && result.removed_rules) || 0;
    showToast(removedRules ? t("Kamera ve {n} kuralı silindi.", { n: removedRules }) : t("Kamera silindi."), "success");
  } catch (err) {
    showError("Kamera silinemedi", err);
  }
  load();
}

async function reconnect(camera, button) {
  try {
    const updated = await withBusy(button, "…", () => reconnectCamera(camera.id));
    announceResult(updated || camera, "yeniden bağlandı");
  } catch (err) {
    showError("Yeniden bağlanılamadı", err);
  }
  load();
}

function showInfo(camera) {
  const state = connectionState(camera);
  const stream = fleet[camera.id] || camera;
  const rows = [
    ["Ad", escapeHTML(camera.name || "")],
    ["Durum", `${state.text}${state.hint ? ` — ${escapeHTML(state.hint)}` : ""}`],
    ["Marka / model", escapeHTML([camera.manufacturer, camera.model].filter(Boolean).join(" ") || "—")],
    ["Adres", `<span class="mono">${escapeHTML(addressOf(camera))}</span>`],
    ["Görüntü", escapeHTML(`${camera.resolution || "—"} · ${stream.stream_fps ? Math.round(stream.stream_fps) : camera.framerate || "—"} ${t("kare/sn")} · ${camera.encoding || "—"}`)],
    ["Seri numarası", `<span class="mono">${escapeHTML(camera.serial_number || "—")}</span>`],
    ["Yazılım sürümü", `<span class="mono">${escapeHTML(camera.firmware_version || "—")}</span>`],
    ["Yayın adresi", `<span class="mono">${escapeHTML(maskCredentials(camera.stream_uri) || "—")}</span>
       ${camera.stream_uri ? `<button type="button" class="btn btn-sm" data-copy="${escapeHTML(camera.stream_uri)}">${icon("copy")} ${t("Kopyala")}</button>` : ""}`],
  ];
  $("#camera-info").innerHTML = rows.map(([label, value]) => `<dt>${t(label)}</dt><dd>${value}</dd>`).join("");
  openModal("modal-camera-info");
}

function openEdit(camera) {
  editingId = camera.id;
  $("#edit-name").value = camera.name || "";
  $("#edit-description").value = camera.description || "";
  const state = connectionState(camera);
  const tag = $("#edit-preview-tag");
  tag.textContent = state.level === "is-ok" ? "" : state.text;
  tag.classList.toggle("is-danger", state.level === "is-danger");
  const preview = $("#edit-preview");
  preview.src = snapshotUrl(camera.id);
  if (stopPreview) stopPreview();
  stopPreview = startStream(camera.id, preview);
  openModal("modal-camera-edit");
  $("#edit-name").focus();
}

async function saveEdit(event) {
  event.preventDefault();
  const name = $("#edit-name").value.trim();
  if (!name) {
    showToast("Kameraya bir ad verin.", "warning");
    $("#edit-name").focus();
    return;
  }
  try {
    await withBusy($("#edit-submit"), "Kaydediliyor…", () =>
      updateCamera(editingId, { name, description: $("#edit-description").value.trim() }));
    closeModal("modal-camera-edit");
    showToast("Kamera güncellendi.", "success");
    load();
  } catch (err) {
    showError("Kamera kaydedilemedi", err);
  }
}

async function submitAdd(event) {
  event.preventDefault();
  const ip = $("#add-ip").value.trim();
  const port = Number($("#add-port").value) || 80;
  const rtspPort = Number($("#add-rtsp-port").value) || 554;
  if (!IPV4.test(ip)) {
    showToast("Geçerli bir IP adresi yazın (örn. 192.168.1.150).", "warning");
    $("#add-ip").focus();
    return;
  }
  if ([port, rtspPort].some((value) => value < 1 || value > 65535)) {
    showToast("Port 1 ile 65535 arasında olmalıdır.", "warning");
    return;
  }
  try {
    const camera = await withBusy($("#add-submit"), "Bağlanılıyor…", () => addCamera({
      ip,
      port,
      rtsp_port: rtspPort,
      username: $("#add-username").value.trim(),
      password: $("#add-password").value,
      name: $("#add-name").value.trim(),
    }));
    announceResult(camera, "eklendi");
    // A camera with a problem keeps the form open so the details can be corrected and retried
    if (camera.status === "online") {
      closeModal("modal-camera-add");
      event.target.reset();
    }
    load();
  } catch (err) {
    showError("Kamera eklenemedi", err);
  }
}

/* -------------------------------------------------------------------- Scan */
const deviceKey = (device) => `${device.ip}:${device.port}`;

function scanStatus(html) {
  $("#scan-status").innerHTML = html;
}

async function scan() {
  openModal("modal-scan");
  if (scanning) return;
  scanning = true;
  $("#scan-again").disabled = true;
  $("#scan-results").innerHTML = "";
  scanStatus(`<div class="loading"><div class="spinner"></div><span>${t("Ağdaki kameralar aranıyor…")}</span></div>`);

  let devices = [];
  try {
    const result = await scanNetwork();
    devices = result.devices || [];
    renderScanResults(devices);
  } catch (err) {
    scanStatus(`<p class="notice is-danger">${t("Arama yapılamadı: {reason}", { reason: escapeHTML(t(err.message)) })}</p>`);
  } finally {
    scanning = false;
    $("#scan-again").disabled = false;
  }
}

function renderScanResults(devices) {
  const registered = new Set(cameras.map(deviceKey));
  const fresh = devices.filter((device) => !registered.has(deviceKey(device)));
  if (!devices.length) {
    scanStatus(`<p class="hint">${t("Ağda kamera bulunamadı. Kameranın açık ve aynı ağda olduğundan emin olun ya da “Elle ekle”yi kullanın.")}</p>`);
    return;
  }
  scanStatus(`
    <div class="scan-head">
      <strong>${t("{n} kamera bulundu", { n: devices.length })}${fresh.length ? "" : ` — ${t("hepsi zaten ekli")}`}</strong>
      ${fresh.length > 1 ? `<button type="button" class="btn btn-primary btn-sm" data-action="add-all">${t("Tümünü ekle ({n})", { n: fresh.length })}</button>` : ""}
    </div>`);
  $("#scan-results").innerHTML = devices.map((device) => `
    <div class="scan-item" data-device="${escapeHTML(deviceKey(device))}">
      <div>
        <strong>${escapeHTML(device.name || device.hardware || t("Kamera"))}</strong>
        <span class="cell-sub">${escapeHTML(addressOf(device))}</span>
      </div>
      ${registered.has(deviceKey(device))
        ? `<span class="badge is-ok">${t("Zaten ekli")}</span>`
        : `<button type="button" class="btn btn-sm" data-action="add-device">${t("Ekle")}</button>`}
    </div>`).join("");
  foundDevices = new Map(devices.map((device) => [deviceKey(device), device]));
}

/** Adds one found device with the credentials typed in the scan window; returns the stored camera. */
async function addFoundDevice(item) {
  const device = foundDevices.get(item.dataset.device);
  const button = $('[data-action="add-device"]', item);
  if (!device || !button) return null;
  button.disabled = true;
  button.textContent = "Ekleniyor…";
  try {
    const camera = await addCamera({
      ip: device.ip,
      port: device.port,
      username: $("#scan-username").value.trim(),
      password: $("#scan-password").value,
      name: device.name,
    });
    const badge = { online: ["is-ok", "Eklendi"], auth_error: ["is-warn", "Şifre hatalı"] }[camera.status] || ["is-warn", "Ulaşılamıyor"];
    button.outerHTML = `<span class="badge ${badge[0]}">${t(badge[1])}</span>`;
    return camera;
  } catch (err) {
    button.disabled = false;
    button.textContent = "Yeniden dene";
    showError(`${addressOf(device)} eklenemedi`, err);
    return null;
  }
}

async function onScanClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  if (button.dataset.action === "add-device") {
    const camera = await addFoundDevice(button.closest(".scan-item"));
    if (camera) announceResult(camera, "eklendi");
  } else if (button.dataset.action === "add-all") {
    button.disabled = true;
    let added = 0;
    let problems = 0;
    for (const item of $$("#scan-results .scan-item")) {
      if (!$('[data-action="add-device"]', item)) continue;
      const camera = await addFoundDevice(item);
      if (camera && camera.status === "online") added += 1;
      else problems += 1;
    }
    button.hidden = true;
    if (problems) showToast(t("{added} kamera eklendi, {problems} kamerada sorun var. Kullanıcı adı ve şifreyi kontrol edin.", { added, problems }), "warning", 7000);
    else showToast(t("{n} kamera eklendi.", { n: added }), "success");
  }
  load();
}

/* --------------------------------------------------------------- Lifecycle */
function onListClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  if (action === "scan") {
    scan();
    return;
  }
  if (action === "add") {
    openModal("modal-camera-add");
    return;
  }
  const holder = button.closest("[data-camera]");
  const camera = holder && cameras.find((item) => item.id === holder.dataset.camera);
  if (!camera) return;
  if (action === "edit") openEdit(camera);
  else if (action === "info") showInfo(camera);
  else if (action === "reconnect") reconnect(camera, button);
  else if (action === "delete") removeCamera(camera);
}

function wire() {
  wired = true;
  setActiveLayout = bindSegmented($("#cameras-layout"), "mode", (mode) => {
    layout = mode;
    localStorage.setItem(LAYOUT_KEY, mode);
    setActiveLayout(mode);
    render();
  });
  setActiveLayout(layout);

  $("#cameras-scan").addEventListener("click", scan);
  $("#cameras-add").addEventListener("click", () => openModal("modal-camera-add"));
  $("#cameras-list").addEventListener("click", onListClick);

  $("#scan-again").addEventListener("click", scan);
  $("#modal-scan").addEventListener("click", onScanClick);
  $("#camera-add-form").addEventListener("submit", submitAdd);
  $("#camera-edit-form").addEventListener("submit", saveEdit);
  $("#edit-templates").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-template]");
    if (chip) $("#edit-description").value = chip.dataset.template;
  });
  $("#modal-camera-edit").addEventListener("modal:closed", () => {
    if (stopPreview) stopPreview();
    stopPreview = null;
    $("#edit-preview").removeAttribute("src");
  });
  $("#camera-info").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    const copied = await copyText(button.dataset.copy);
    showToast(copied ? "Yayın adresi kopyalandı." : "Kopyalanamadı.", copied ? "success" : "error", 2500);
  });
}

export function mount() {
  mounted = true;
  thumbnailStamp = Date.now();
  if (!wired) wire();
  if (!cameras.length) setHTML($("#cameras-list"), `<div class="loading"><div class="spinner"></div></div>`);
  load().then(() => mounted && refreshStatus());
  snapshotTimer = setInterval(refreshSnapshots, SNAPSHOT_INTERVAL_MS);
  statusTimer = setInterval(refreshStatus, STATUS_INTERVAL_MS);
}

export function unmount() {
  mounted = false;
  clearInterval(snapshotTimer);
  clearInterval(statusTimer);
  loadingSnapshots.clear();
}
