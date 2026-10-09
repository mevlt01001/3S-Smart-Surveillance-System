/**
 * Settings page. Every control carries the path of the value it edits in a `data-setting`
 * attribute (for example "recording.padding_sec"), so this module reads and writes the
 * form generically and never needs to know the individual settings.
 */

import { cleanOrphanClips, getSettings, getStorage, resetSettings, saveSettings } from "./api.js";
import { subscribeSystemStats } from "./shell.js";
import { $, $$, confirmDialog, escapeHTML, showError, showToast, withBusy } from "./ui.js";

const NORMAL = "anomaly.threshold_normal";
const WARNING = "anomaly.threshold_warning";

let saved = null;
let wired = false;
let unsubscribeStats = null;

const controls = () => $$("#settings-form [data-setting]");
const control = (path) => $(`#settings-form [data-setting="${path}"]`);
const getPath = (object, path) => path.split(".").reduce((value, key) => (value == null ? value : value[key]), object);

function setPath(object, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  const target = keys.reduce((node, key) => (node[key] = node[key] || {}), object);
  target[last] = value;
}

/* ------------------------------------------------------------ Form values */
function readControl(input) {
  if (input.type === "checkbox") return input.checked;
  if (input.type === "range" || input.type === "number") return Number(input.value);
  return input.value.trim();
}

function writeControl(input, value) {
  if (input.type === "checkbox") {
    input.checked = Boolean(value);
    return;
  }
  if (input.type === "range") {
    // A stored value outside the slider's usual range must stay as it is, not be silently clamped
    if (Number(value) < Number(input.min)) input.min = value;
    if (Number(value) > Number(input.max)) input.max = value;
  }
  input.value = value ?? "";
}

function renderOutputs() {
  $$("#settings-form output[data-output]").forEach((output) => {
    const input = control(output.dataset.output);
    if (!input) return;
    const unit = output.dataset.unit || "";
    output.textContent = unit === "%" ? `%${input.value}` : `${input.value}${unit}`;
  });
  const normal = Number(control(NORMAL).value);
  const warning = Number(control(WARNING).value);
  const [okPart, warnPart, dangerPart] = $("#threshold-scale").children;
  okPart.style.flexBasis = `${normal}%`;
  warnPart.style.flexBasis = `${warning - normal}%`;
  dangerPart.style.flexBasis = `${100 - warning}%`;
}

function fill(settings) {
  controls().forEach((input) => writeControl(input, getPath(settings, input.dataset.setting)));
  renderOutputs();
  renderDirty();
}

/** The settings as edited: the stored object with every control's current value applied. */
function collect() {
  const edited = JSON.parse(JSON.stringify(saved));
  controls().forEach((input) => setPath(edited, input.dataset.setting, readControl(input)));
  return edited;
}

const isDirty = () =>
  Boolean(saved) && controls().some((input) => readControl(input) !== getPath(saved, input.dataset.setting));

function renderDirty() {
  $("#settings-save-bar").hidden = !isDirty();
}

/** The critical level always stays above the warning level, whichever slider is moved. */
function keepThresholdsOrdered(movedPath) {
  const normal = control(NORMAL);
  const warning = control(WARNING);
  if (Number(warning.value) > Number(normal.value)) return;
  if (movedPath === NORMAL) writeControl(warning, Number(normal.value) + 1);
  else writeControl(normal, Number(warning.value) - 1);
}

/* ----------------------------------------------------------------- Storage */
async function loadStorage() {
  let storage;
  try {
    storage = await getStorage();
  } catch (_) {
    $("#storage-text").textContent = "Depolama bilgisi alınamadı.";
    return;
  }
  const percent = storage.max_storage_mb ? Math.min(100, Math.round((storage.clip_mb / storage.max_storage_mb) * 100)) : 0;
  $("#storage-percent").textContent = `%${percent}`;
  const bar = $("#storage-fill");
  bar.style.width = `${percent}%`;
  bar.classList.toggle("is-high", percent >= 90);
  $("#storage-text").textContent =
    `${storage.clip_count} video, ${Math.round(storage.clip_mb)} MB / ${storage.max_storage_mb} MB · ${storage.snapshot_count} fotoğraf`;

  const orphans = storage.orphan_clip_count || 0;
  $("#storage-orphans").hidden = orphans === 0;
  $("#storage-orphans-text").textContent =
    `${orphans} video (${Math.round(storage.orphan_clip_mb)} MB) hiçbir olaya bağlı değil; yalnızca yer kaplıyor.`;
}

async function cleanStorage() {
  const confirmed = await confirmDialog({
    title: "Kullanılmayan videolar silinsin mi?",
    message: "Hiçbir olaya bağlı olmayan videolar kalıcı olarak silinecek. Olay kayıtlarınız etkilenmez.",
    confirmText: "Sil",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const result = await withBusy($("#storage-clean"), "Siliniyor…", cleanOrphanClips);
    showToast(`${result.deleted_count} video silindi, ${result.freed_mb} MB yer açıldı.`, "success");
  } catch (err) {
    showError("Temizlenemedi", err);
  }
  loadStorage();
}

/* ------------------------------------------------------------- System info */
function renderSystemInfo(stats) {
  const analysis = stats.triton || {};
  const gpu = stats.gpu || {};
  const milliseconds = (value) => (value == null ? "—" : `${Math.round(value)} ms`);
  const rows = [
    ["Analiz sunucusu", analysis.status === "READY" ? "Çalışıyor" : "Ulaşılamıyor"],
    ["Hareket analizi süresi", milliseconds(analysis.anomaly_detection_latency_ms)],
    ["Kural analizi süresi", milliseconds(analysis.object_detection_latency_ms)],
  ];
  if (gpu.available) {
    rows.push(
      ["Ekran kartı", gpu.name],
      ["Ekran kartı belleği", `${gpu.vram_used_mb} / ${gpu.vram_total_mb} MB`],
      ["Sıcaklık", `${gpu.temperature_c} °C`],
    );
  }
  $("#system-info").innerHTML = rows.map(([label, value]) => `<dt>${label}</dt><dd>${escapeHTML(value)}</dd>`).join("");
}

/* ----------------------------------------------------------------- Actions */
async function save(event) {
  event.preventDefault();
  if (!saved) return;
  try {
    saved = await withBusy($("#settings-save"), "Kaydediliyor…", () => saveSettings(collect()));
    fill(saved);
    showToast("Ayarlar kaydedildi.", "success");
    loadStorage();
  } catch (err) {
    showError("Ayarlar kaydedilemedi", err);
  }
}

async function reset() {
  const confirmed = await confirmDialog({
    title: "Varsayılan ayarlara dönülsün mü?",
    message: "Bu sayfadaki tüm ayarlar ilk kurulumdaki değerlerine döner. Kameralarınız, kurallarınız ve olay kayıtlarınız etkilenmez.",
    confirmText: "Varsayılana dön",
    danger: true,
  });
  if (!confirmed) return;
  try {
    saved = await resetSettings();
    fill(saved);
    showToast("Ayarlar varsayılan değerlerine döndü.", "success");
  } catch (err) {
    showError("Ayarlar sıfırlanamadı", err);
  }
}

function wire() {
  wired = true;
  const form = $("#settings-form");
  form.addEventListener("input", (event) => {
    const path = event.target.dataset.setting;
    if (path === NORMAL || path === WARNING) keepThresholdsOrdered(path);
    renderOutputs();
    renderDirty();
  });
  form.addEventListener("submit", save);
  $("#settings-discard").addEventListener("click", () => fill(saved));
  $("#settings-reset").addEventListener("click", reset);
  $("#storage-clean").addEventListener("click", cleanStorage);
  // The theme is this device's own choice: it applies at once and is not part of the saved settings
  $("#theme-options").addEventListener("click", (event) => {
    const option = event.target.closest("[data-theme-name]");
    if (!option) return;
    window.aegisTheme.set(option.dataset.themeName);
    renderTheme();
  });
}

function renderTheme() {
  const current = window.aegisTheme.get();
  $$("#theme-options [data-theme-name]").forEach((option) => {
    option.setAttribute("aria-checked", String(option.dataset.themeName === current));
  });
}

/* --------------------------------------------------------------- Lifecycle */
export async function mount() {
  if (!wired) wire();
  renderTheme();
  unsubscribeStats = unsubscribeStats || subscribeSystemStats(renderSystemInfo);
  loadStorage();
  // Coming back with unsaved edits keeps them; otherwise show what the server has now
  if (isDirty()) return;
  try {
    saved = await getSettings();
    fill(saved);
  } catch (err) {
    showError("Ayarlar yüklenemedi", err);
  }
}

export function unmount() {
  if (unsubscribeStats) unsubscribeStats();
  unsubscribeStats = null;
}

/** Leaving with unsaved changes asks first. */
export async function canLeave() {
  if (!isDirty()) return true;
  const leave = await confirmDialog({
    title: "Değişiklikler kaydedilmedi",
    message: "Ayarlarda yaptığınız değişiklikler kaybolacak.",
    confirmText: "Kaydetmeden çık",
    danger: true,
  });
  if (leave) fill(saved);
  return leave;
}
