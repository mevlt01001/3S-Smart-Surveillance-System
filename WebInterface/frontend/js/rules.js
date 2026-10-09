/**
 * Rules page: the list of rules and the editor where a rule's zones are drawn on a camera
 * picture and described in plain words.
 */

import { createRule, deleteRule, listCameras, listRules, recompileRule, snapshotUrl, updateRule } from "./api.js";
import { describePlan } from "./labels.js";
import { $, bindSegmented, confirmDialog, escapeHTML, icon, isAnyModalOpen, setHTML, showError, showToast, withBusy } from "./ui.js";
import { ZONE_COLORS, createZoneEditor } from "./zone-editor.js";

const PREPARING_REFRESH_MS = 1500;
const DEFAULT_ACTIONS = ["alert_screen", "snapshot"];

/** How the preparation state of a rule is shown; states that need no attention have no entry. */
const STATUS_BADGES = {
  compiling: { className: "is-info is-busy", text: "Hazırlanıyor", hint: "Açıklamanız işleniyor. Kural birkaç saniye içinde çalışmaya başlar." },
  fallback: { className: "is-warn", text: "Genel ayarla çalışıyor", hint: "Açıklama tam çözümlenemedi; kural genel bir ayarla çalışıyor. Açıklamayı sadeleştirin veya yeniden deneyin.", retry: true },
  pending: { className: "is-warn", text: "Hazır değil", hint: "Bu kural henüz hazırlanmadı.", retry: true },
  unavailable: { className: "is-danger", text: "Hazırlanamadı", hint: "Kural hazırlama servisine ulaşılamadı. Kural şu anda çalışmıyor.", retry: true },
  error: { className: "is-danger", text: "Hazırlanamadı", hint: "Kural hazırlanırken hata oluştu. Kural şu anda çalışmıyor.", retry: true },
  unsupported: { className: "is-danger", text: "Yapılamıyor", hint: "Bu istek kameradan anlaşılabilecek bir duruma çevrilemedi. Kural çalışmıyor." },
};

/** Badge of a rule's preparation state; a request the system cannot serve carries its own explanation. */
function statusOf(rule) {
  const status = STATUS_BADGES[rule.compile_status];
  return status && rule.compile_note ? { ...status, hint: `${rule.compile_note} Kural çalışmıyor; açıklamayı değiştirin.` } : status;
}

let rules = [];
let cameras = [];
let editingId = null;
let scope = "camera";
let cameraId = null;
let dirty = false;
let justSavedId = null;
let editor = null;
let mounted = false;
let refreshTimer = null;
let setActiveScope = () => {};

const isEditorOpen = () => !$("#rule-editor-panel").hidden;
const hasChangeZone = (zones) => (zones || []).some((zone) => zone.zone_type === "change_detection");

/* -------------------------------------------------------------------- List */
function zoneSummaryHTML(rule) {
  const zones = rule.zones || [];
  if (!zones.length) return `<span class="cell-sub">${escapeHTML(rule.description || "")}</span>`;
  return zones.map((zone, index) => {
    const what = zone.zone_type === "change_detection"
      ? "Engel veya değişiklik izleniyor"
      : describePlan(zone.plan_summary) || zone.description || "";
    // Shown when the rule is only the closest thing to what was asked for
    const note = zone.plan_summary && zone.plan_summary.note
      ? `<span class="cell-sub rule-note">${icon("info")} ${escapeHTML(zone.plan_summary.note)}</span>` : "";
    return `<span class="cell-sub rule-zone"><i class="zone-dot" style="--zone-color: ${ZONE_COLORS[(zone.color_idx ?? index) % ZONE_COLORS.length]}"></i>${escapeHTML(zone.name || "Bölge")}: ${escapeHTML(what)}</span>${note}`;
  }).join("");
}

function rowHTML(rule) {
  const status = statusOf(rule);
  const badges = [];
  if (rule.camera_missing) {
    badges.push(`<span class="badge is-warn" title="Bu kuralın kamerası silinmiş. Düzenleyip başka bir kameraya taşıyabilirsiniz.">Kamerası yok</span>`);
  } else if (status) {
    badges.push(`<span class="badge ${status.className}" title="${escapeHTML(status.hint)}">${status.text}</span>`);
  }
  const where = rule.scope === "system" ? "Tüm kameralar" : rule.camera_name || "Kamera";
  return `
    <tr data-rule="${escapeHTML(rule.id)}">
      <td>
        <strong>${escapeHTML(rule.title)}</strong> ${badges.join(" ")}
        ${zoneSummaryHTML(rule)}
      </td>
      <td>${escapeHTML(where)}</td>
      <td><input type="checkbox" class="switch" data-action="toggle" ${rule.enabled !== false ? "checked" : ""} aria-label="Kural açık" title="Kuralı aç veya kapat"></td>
      <td>
        <div class="cell-actions">
          ${status && status.retry ? `<button type="button" class="btn btn-sm" data-action="retry">Yeniden dene</button>` : ""}
          <button type="button" class="btn-icon" data-action="edit" title="Düzenle" aria-label="Düzenle">${icon("edit")}</button>
          <button type="button" class="btn-icon is-danger" data-action="delete" title="Sil" aria-label="Sil">${icon("trash")}</button>
        </div>
      </td>
    </tr>`;
}

function renderList() {
  const active = rules.filter((rule) => rule.enabled !== false).length;
  $("#rules-summary").textContent = rules.length ? `${rules.length} kural · ${active} açık` : "";
  if (!rules.length) {
    setHTML($("#rules-list"), `
      <div class="empty">
        ${icon("rules")}
        <p class="empty-title">Henüz kural yok</p>
        <p>Bir kameranın görüntüsünde bölge çizip orada ne olunca haber almak istediğinizi yazın.</p>
        <div class="empty-actions"><button type="button" class="btn btn-primary" data-action="new">İlk kuralı oluştur</button></div>
      </div>`);
    return;
  }
  setHTML($("#rules-list"), `
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Kural</th><th>Kamera</th><th>Açık</th><th></th></tr></thead>
      <tbody>${rules.map(rowHTML).join("")}</tbody>
    </table></div>`);
}

async function loadList() {
  clearTimeout(refreshTimer);
  let data;
  try {
    data = await listRules();
  } catch (err) {
    setHTML($("#rules-list"), `<div class="empty"><p class="empty-title">Kurallar yüklenemedi</p><p>${escapeHTML(err.message)}</p></div>`);
    return;
  }
  rules = data.rules || [];
  const notice = $("#rules-notice");
  notice.hidden = data.compiler_available !== false;
  notice.textContent = "Kural hazırlama servisine ulaşılamıyor. Yeni kurallar kaydedilir, ancak servis geri gelene kadar çalışmaz.";
  renderList();
  announceSavedRule();
  // While a rule is being prepared, keep its status fresh
  if (mounted && rules.some((rule) => rule.compile_status === "compiling")) {
    refreshTimer = setTimeout(loadList, PREPARING_REFRESH_MS);
  }
}

/** Tells the user how the rule they just saved turned out once its preparation ended. */
function announceSavedRule() {
  const rule = rules.find((item) => item.id === justSavedId);
  if (!rule || rule.compile_status === "compiling") return;
  justSavedId = null;
  const status = statusOf(rule);
  const notes = (rule.zones || []).map((zone) => zone.plan_summary && zone.plan_summary.note).filter(Boolean);
  if (status) showToast(`“${rule.title}”: ${status.hint}`, "warning", 12000);
  else if (notes.length) showToast(`“${rule.title}” çalışıyor, ancak istediğinizden farklı: ${notes.join(" ")}`, "warning", 15000);
  else if (rule.enabled !== false) showToast(`“${rule.title}” çalışıyor.`, "success");
}

async function onListClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  if (button.dataset.action === "new") {
    openEditor(null);
    return;
  }
  const row = button.closest("[data-rule]");
  const rule = row && rules.find((item) => item.id === row.dataset.rule);
  if (!rule) return;

  if (button.dataset.action === "edit") {
    openEditor(rule);
  } else if (button.dataset.action === "toggle") {
    button.disabled = true;
    try {
      await updateRule(rule.id, { enabled: button.checked });
      rule.enabled = button.checked;
      renderList();
    } catch (err) {
      button.checked = !button.checked; // keep the switch truthful
      showError("Kural değiştirilemedi", err);
    } finally {
      button.disabled = false;
    }
  } else if (button.dataset.action === "retry") {
    try {
      await withBusy(button, "Deneniyor…", () => recompileRule(rule.id));
      justSavedId = rule.id;
    } catch (err) {
      showError("Kural hazırlanamadı", err);
    }
    loadList();
  } else if (button.dataset.action === "delete") {
    const confirmed = await confirmDialog({
      title: "Kural silinsin mi?",
      message: `“${rule.title}” kuralı silinecek. Daha önce kaydedilmiş olaylar korunur.`,
      confirmText: "Sil",
      danger: true,
    });
    if (!confirmed) return;
    try {
      await deleteRule(rule.id);
      showToast("Kural silindi.", "success");
    } catch (err) {
      showError("Kural silinemedi", err);
    }
    loadList();
  }
}

/* ------------------------------------------------------------------ Editor */
function renderZoneFields() {
  const zones = editor.getZones();
  const selected = editor.getSelected();

  setHTML($("#zone-chips"), zones.length
    ? zones.map((zone, index) => `
        <span class="chip zone-chip ${selected && selected.id === zone.id ? "is-active" : ""}" data-zone="${escapeHTML(zone.id)}">
          <i class="zone-dot" style="--zone-color: ${ZONE_COLORS[(zone.colorIndex ?? index) % ZONE_COLORS.length]}"></i>
          <button type="button" class="zone-chip-name" data-action="select">${escapeHTML(zone.name)}</button>
          <button type="button" class="zone-chip-remove" data-action="remove" title="Bu bölgeyi sil" aria-label="Bölgeyi sil">×</button>
        </span>`).join("")
    : `<span class="hint">Henüz bölge çizilmedi. Soldaki görüntüye tıklayarak başlayın.</span>`);

  $("#zone-fields").disabled = !selected;
  const isChange = Boolean(selected && selected.zone_type === "change_detection");
  $("#zone-detection-fields").hidden = isChange;
  $("#zone-change-hint").hidden = !isChange;
  // Do not overwrite the field the user is typing in
  const assign = (selector, value) => {
    const field = $(selector);
    if (document.activeElement !== field) field.value = value;
  };
  assign("#zone-name", selected ? selected.name : "");
  assign("#zone-description", selected ? selected.description || "" : "");
  $("#zone-type").value = selected ? selected.zone_type || "detection" : "detection";

  const points = editor.draftPoints();
  let status = "Bölge çizmek için görüntüye tıklayın";
  if (scope === "camera" && !cameraId) status = "Önce bir kamera ekleyin";
  else if (points >= 3) status = "Bölgeyi kapatmak için ilk noktaya tıklayın";
  else if (points > 0) status = `En az ${3 - points} nokta daha işaretleyin`;
  else if (zones.length) status = "";
  const statusBox = $("#zone-canvas-status");
  statusBox.hidden = !status;
  statusBox.textContent = status;
}

function showCameraPicture() {
  const background = $("#zone-canvas-bg");
  const wrap = $("#zone-canvas-wrap");
  const isCamera = scope === "camera";
  $("#rule-camera").hidden = !isCamera;
  $("#zone-canvas-system").hidden = isCamera;
  background.hidden = !isCamera;
  if (!isCamera || !cameraId) {
    wrap.style.aspectRatio = "";
    editor.resize();
    return;
  }
  background.onload = () => {
    // Match the drawing surface to the proportions of this camera's picture
    wrap.style.aspectRatio = `${background.naturalWidth} / ${background.naturalHeight}`;
    editor.resize();
  };
  background.onerror = () => showToast("Kamera görüntüsü alınamadı. Kameranın bağlantısını kontrol edin.", "warning");
  background.src = snapshotUrl(cameraId);
}

function setScope(next) {
  scope = next;
  setActiveScope(scope);
  showCameraPicture();
  renderZoneFields();
}

async function openEditor(rule) {
  try {
    cameras = await listCameras();
  } catch (err) {
    showError("Kameralar yüklenemedi", err);
    return;
  }
  editingId = rule ? rule.id : null;
  $("#rule-editor-title").textContent = rule ? "Kuralı düzenle" : "Yeni kural";
  $("#rule-title").value = rule ? rule.title : "";

  const select = $("#rule-camera");
  select.innerHTML = cameras.length
    ? cameras.map((camera) => `<option value="${escapeHTML(camera.id)}">${escapeHTML(camera.name || camera.ip)}</option>`).join("")
    : `<option value="">Kamera yok</option>`;
  const ruleCamera = rule && cameras.some((camera) => camera.id === rule.camera_id) ? rule.camera_id : null;
  cameraId = ruleCamera || (cameras[0] && cameras[0].id) || null;
  select.value = cameraId || "";
  if (rule && rule.scope !== "system" && !ruleCamera) {
    showToast("Bu kuralın kamerası silinmiş. Kaydettiğinizde kural seçili kameraya taşınır.", "warning", 7000);
  }

  $("#rules-list-panel").hidden = true;
  $("#rule-editor-panel").hidden = false;
  editor.setZones(((rule && rule.zones) || []).map((zone, index) => ({
    id: zone.id || `zone_${index}`,
    name: zone.name || `Bölge ${index + 1}`,
    description: zone.description || "",
    zone_type: zone.zone_type || "detection",
    points: (zone.points || []).map((point) => ({ x: point.x, y: point.y })),
    colorIndex: zone.color_idx,
  })));
  setScope(rule && rule.scope === "system" ? "system" : "camera");
  dirty = false;
  $("#rule-title").focus();
}

async function closeEditor() {
  if (dirty) {
    const leave = await confirmDialog({
      title: "Değişiklikler kaydedilmedi",
      message: "Bu kuralda yaptığınız değişiklikler kaybolacak.",
      confirmText: "Kaydetmeden çık",
      danger: true,
    });
    if (!leave) return false;
  }
  dirty = false;
  $("#rule-editor-panel").hidden = true;
  $("#rules-list-panel").hidden = false;
  loadList();
  return true;
}

/** Checks the form and returns the request body, or null after telling the user what is missing. */
function buildRule() {
  const title = $("#rule-title").value.trim();
  if (!title) {
    showToast("Kurala bir ad verin.", "warning");
    $("#rule-title").focus();
    return null;
  }
  if (scope === "camera" && !cameraId) {
    showToast("Önce Kameralar sayfasından bir kamera ekleyin.", "warning");
    return null;
  }
  if (editor.draftPoints() >= 3) editor.finishDrawing();
  else if (editor.draftPoints() > 0) {
    showToast("Yarım kalan bölgeyi tamamlayın veya Esc ile iptal edin.", "warning");
    return null;
  }
  const zones = editor.getZones();
  if (scope === "camera" && !zones.length) {
    showToast("Görüntü üzerinde en az bir bölge çizin.", "warning");
    return null;
  }
  const undescribed = zones.find((zone) => zone.zone_type !== "change_detection" && !(zone.description || "").trim());
  if (undescribed) {
    editor.select(undescribed.id);
    showToast(`“${undescribed.name}” bölgesinde ne olunca haber verileceğini yazın.`, "warning");
    $("#zone-description").focus();
    return null;
  }

  const camera = cameras.find((item) => item.id === cameraId);
  const zoneBodies = zones.map((zone, index) => ({
    id: zone.id,
    name: zone.name || `Bölge ${index + 1}`,
    description: (zone.description || "").trim(),
    severity: "warning",
    zone_type: zone.zone_type || "detection",
    actions: DEFAULT_ACTIONS,
    points: zone.points,
    color_idx: zone.colorIndex ?? index,
  }));
  return {
    title,
    scope,
    camera_id: scope === "camera" ? cameraId : null,
    camera_name: scope === "camera" ? (camera && (camera.name || camera.ip)) || "" : "Tüm kameralar",
    severity: "warning",
    description: zoneBodies.map((zone) => `${zone.name}: ${zone.description}`).join(" | ") || "Tüm kameralarda geçerli kural",
    zones: zoneBodies,
    actions: DEFAULT_ACTIONS,
  };
}

async function saveRule(event) {
  event.preventDefault();
  const body = buildRule();
  if (!body) return;
  try {
    const saved = await withBusy($("#rule-save"), "Kaydediliyor…", () =>
      editingId ? updateRule(editingId, body) : createRule(body));
    justSavedId = saved ? saved.id : null;
    dirty = false;
    showToast("Kural kaydedildi.", "success");
    if (hasChangeZone(body.zones)) {
      showToast("Son adım: Canlı İzleme’de bu kameranın üzerindeki “Referans al” düğmesine basın.", "info", 10000);
    }
    closeEditor();
  } catch (err) {
    showError("Kural kaydedilemedi", err);
  }
}

function wireEditor() {
  editor = createZoneEditor($("#zone-canvas"), {
    canDraw: () => {
      if (scope === "camera" && !cameraId) {
        showToast("Bölge çizmek için önce bir kamera ekleyin.", "warning");
        return false;
      }
      return true;
    },
    onReject: () => showToast("Bölgenin kenarları birbirini kesemez. Köşeyi başka bir yere koyun ya da Esc ile baştan çizin.", "warning"),
    onChange: () => {
      dirty = true;
      renderZoneFields();
    },
  });

  setActiveScope = bindSegmented($("#rule-scope"), "scope", setScope);
  $("#rule-camera").addEventListener("change", (event) => {
    cameraId = event.target.value;
    dirty = true;
    showCameraPicture();
  });
  $("#rule-title").addEventListener("input", () => {
    dirty = true;
  });
  $("#zone-undo").addEventListener("click", () => editor.undo());
  $("#zone-clear").addEventListener("click", async () => {
    if (!editor.getZones().length && !editor.draftPoints()) return;
    const confirmed = await confirmDialog({ title: "Tüm bölgeler silinsin mi?", message: "Çizdiğiniz bütün bölgeler kaldırılacak.", confirmText: "Sil", danger: true });
    if (confirmed) editor.clear();
  });

  $("#zone-chips").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-zone]");
    const button = event.target.closest("[data-action]");
    if (!chip || !button) return;
    if (button.dataset.action === "remove") editor.removeZone(chip.dataset.zone);
    else editor.select(chip.dataset.zone);
  });
  $("#zone-name").addEventListener("input", (event) => editor.updateSelected({ name: event.target.value.trim() || "Bölge" }));
  $("#zone-description").addEventListener("input", (event) => editor.updateSelected({ description: event.target.value }));
  $("#zone-type").addEventListener("change", (event) => editor.updateSelected({ zone_type: event.target.value }));
  $("#zone-detection-fields").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-template]");
    if (!chip) return;
    const field = $("#zone-description");
    field.value = chip.dataset.template;
    editor.updateSelected({ description: field.value });
    field.focus();
  });

  $("#rule-form").addEventListener("submit", saveRule);
  $("#view-rules").addEventListener("click", (event) => {
    if (event.target.closest('[data-action="close-editor"]')) closeEditor();
  });

  // Drawing shortcuts: Enter closes the polygon, Esc cancels it, Backspace removes the last point
  document.addEventListener("keydown", (event) => {
    if (!mounted || !isEditorOpen() || isAnyModalOpen() || !editor.draftPoints()) return;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    if (event.key === "Enter") editor.finishDrawing();
    else if (event.key === "Escape") editor.cancelDrawing();
    else if (event.key === "Backspace") editor.undo();
    else return;
    event.preventDefault();
  });
  window.addEventListener("resize", () => {
    if (mounted && isEditorOpen()) editor.resize();
  });
}

/* --------------------------------------------------------------- Lifecycle */
export function mount() {
  mounted = true;
  if (!editor) {
    wireEditor();
    $("#rules-new").addEventListener("click", () => openEditor(null));
    $("#rules-list").addEventListener("click", onListClick);
  }
  loadList();
}

export function unmount() {
  mounted = false;
  clearTimeout(refreshTimer);
  // Coming back to the page starts from the list (an unsaved rule was already confirmed in canLeave)
  $("#rule-editor-panel").hidden = true;
  $("#rules-list-panel").hidden = false;
  dirty = false;
}

/** Leaving the page with an unsaved rule asks first. */
export async function canLeave() {
  if (!isEditorOpen() || !dirty) return true;
  return closeEditor();
}
