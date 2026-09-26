/**
 * RULES.JS - AegisVision Multi-Polygon Spatial Zone & Rule Definition Controller
 * - Interactive multi-polygon drawing on HTML5 Canvas over live camera feed.
 * - Supports unlimited independent polygon zones per camera or system-wide rule.
 * - Per-zone rule formulation: each zone has its own custom name, AI prompt description, severity and actions.
 * - Distinct harmonious glowing palettes (Amber, Cyan, Emerald, Violet, Rose, Gold) per zone.
 * - Interactive zone management: click any zone on canvas, in chip bar, or in tabs to edit its specific rule.
 * - Normalized coordinate system (0.0 to 1.0) for resolution independence.
 * - Camera-wise vs System-wise rule scopes.
 * - Rule creation, fleet list rendering, enable/disable toggling, and deletion.
 */

import {
  fetchCameras,
  fetchRules,
  createRule,
  updateRule,
  deleteRule,
  getSnapshotUrl
} from "./api.js";

// Global State
let camerasList = [];
let rulesList = [];
let currentScope = "camera"; // 'camera' or 'system'
let selectedCameraId = null;

// Multi-Polygon & Per-Zone State
// Each element: { id: string, name: string, description: string, severity: string, points: [{x, y}, ...], colorIdx: number }
let completedPolygons = [];
let activePolygonPoints = []; // [{x: float, y: float}] points of in-progress polygon
let selectedPolygonId = null; // ID of currently clicked / focused polygon
let hoveredPointIndex = -1; // Node index hovered in active polygon
let cursorPosition = null; // {x, y} relative canvas pixels
let isDrawingActive = true;

// Distinct harmonious glowing color themes for multi-zone visual distinction
const ZONE_COLORS = [
  { stroke: "#FF8533", fill: "rgba(255, 133, 51, 0.22)", glow: "rgba(255, 133, 51, 0.75)", text: "#FF8533" }, // Amber (Primary)
  { stroke: "#38BDF8", fill: "rgba(56, 189, 248, 0.22)", glow: "rgba(56, 189, 248, 0.75)", text: "#38BDF8" }, // Sky / Cyan
  { stroke: "#34D399", fill: "rgba(52, 211, 153, 0.22)", glow: "rgba(52, 211, 153, 0.75)", text: "#34D399" }, // Emerald
  { stroke: "#C084FC", fill: "rgba(192, 132, 252, 0.22)", glow: "rgba(192, 132, 252, 0.75)", text: "#C084FC" }, // Violet
  { stroke: "#F43F5E", fill: "rgba(244, 63, 94, 0.22)", glow: "rgba(244, 63, 94, 0.75)", text: "#F43F5E" },   // Rose
  { stroke: "#FBBF24", fill: "rgba(251, 191, 36, 0.22)", glow: "rgba(251, 191, 36, 0.75)", text: "#FBBF24" }    // Amber-Gold
];

// Canvas elements
let canvas, ctx, canvasWrapper, bgImage, systemGrid;

export function initRulesModule() {
  canvas = document.getElementById("polygon-drawing-canvas");
  if (!canvas) return;
  ctx = canvas.getContext("2d");
  canvasWrapper = document.getElementById("canvas-viewport-wrapper");
  bgImage = document.getElementById("canvas-camera-bg");
  systemGrid = document.getElementById("canvas-system-grid");

  initCanvasEvents();
  initScopeSelector();
  initFormControls();
  initPresetChips();
  initToolButtons();

  loadCamerasForRules();
  loadRulesTable();

  // Resize canvas to match container resolution
  window.addEventListener("resize", resizeCanvas);
  setTimeout(resizeCanvas, 150);
}

/* --------------------------------------------------------------------------
   Point-in-Polygon (Ray Casting) Algorithm
   -------------------------------------------------------------------------- */
function isPointInPolygon(point, polygon) {
  const x = point.x, y = point.y;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x, yi = polygon[i].y;
    const xj = polygon[j].x, yj = polygon[j].y;
    const intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

/* --------------------------------------------------------------------------
   Canvas Sizing & Drawing Pipeline
   -------------------------------------------------------------------------- */
function resizeCanvas() {
  if (!canvas || !canvasWrapper) return;
  const rect = canvasWrapper.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = rect.height;
  redrawCanvas();
}

function redrawCanvas() {
  if (!ctx || !canvas) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const w = canvas.width;
  const h = canvas.height;

  // 1. Draw all completed polygons
  completedPolygons.forEach((poly, pIdx) => {
    if (!poly.points || poly.points.length === 0) return;
    const color = ZONE_COLORS[(poly.colorIdx !== undefined ? poly.colorIdx : pIdx) % ZONE_COLORS.length];
    const isSelected = (selectedPolygonId === poly.id);

    // Draw polygon area & border
    ctx.beginPath();
    ctx.moveTo(poly.points[0].x * w, poly.points[0].y * h);
    for (let i = 1; i < poly.points.length; i++) {
      ctx.lineTo(poly.points[i].x * w, poly.points[i].y * h);
    }
    ctx.closePath();

    // Fill with glowing tint
    ctx.fillStyle = isSelected ? color.fill.replace("0.22", "0.40") : color.fill;
    ctx.fill();

    // Glowing border
    ctx.strokeStyle = isSelected ? "#FFFFFF" : color.stroke;
    ctx.lineWidth = isSelected ? 3.2 : 2.2;
    ctx.setLineDash([]);
    ctx.shadowColor = color.glow;
    ctx.shadowBlur = isSelected ? 16 : 8;
    ctx.stroke();
    ctx.shadowBlur = 0; // reset

    // Vertices / Nodes
    poly.points.forEach((pt) => {
      const px = pt.x * w;
      const py = pt.y * h;
      ctx.beginPath();
      ctx.arc(px, py, isSelected ? 5.5 : 4.5, 0, Math.PI * 2);
      ctx.fillStyle = isSelected ? "#FFFFFF" : color.stroke;
      ctx.fill();
      ctx.strokeStyle = "#0A0D14";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });

    // Centroid Badge showing the zone name
    if (poly.points.length >= 3) {
      let cx = 0, cy = 0;
      poly.points.forEach(p => { cx += p.x * w; cy += p.y * h; });
      cx /= poly.points.length;
      cy /= poly.points.length;

      const badgeName = (poly.name || `BÖLGE ${pIdx + 1}`).toUpperCase();

      ctx.font = "bold 11px Outfit, sans-serif";
      const textWidth = ctx.measureText(badgeName).width;
      const badgeW = Math.max(textWidth + 24, 78);
      const badgeH = 26;

      ctx.fillStyle = isSelected ? "rgba(18, 24, 38, 0.95)" : "rgba(10, 14, 24, 0.9)";
      ctx.beginPath();
      ctx.roundRect(cx - badgeW / 2, cy - badgeH / 2, badgeW, badgeH, 6);
      ctx.fill();
      ctx.strokeStyle = isSelected ? color.stroke : color.stroke;
      ctx.lineWidth = isSelected ? 2.0 : 1.0;
      ctx.stroke();

      ctx.fillStyle = isSelected ? "#FFFFFF" : color.text;
      ctx.textAlign = "center";
      ctx.fillText(badgeName, cx, cy + 4);
      ctx.textAlign = "start"; // reset
    }
  });

  // 2. Draw currently active in-progress polygon
  if (activePolygonPoints.length > 0) {
    const activeColor = ZONE_COLORS[completedPolygons.length % ZONE_COLORS.length];

    ctx.beginPath();
    ctx.moveTo(activePolygonPoints[0].x * w, activePolygonPoints[0].y * h);
    for (let i = 1; i < activePolygonPoints.length; i++) {
      ctx.lineTo(activePolygonPoints[i].x * w, activePolygonPoints[i].y * h);
    }

    ctx.strokeStyle = activeColor.stroke;
    ctx.lineWidth = 2.2;
    ctx.setLineDash([6, 4]);
    ctx.stroke();

    // Rubber-band dashed line to cursor
    if (cursorPosition && isDrawingActive) {
      const lastPt = activePolygonPoints[activePolygonPoints.length - 1];
      ctx.beginPath();
      ctx.moveTo(lastPt.x * w, lastPt.y * h);
      ctx.lineTo(cursorPosition.x, cursorPosition.y);
      ctx.strokeStyle = activeColor.glow;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
    }

    // Nodes for in-progress polygon
    activePolygonPoints.forEach((pt, idx) => {
      const px = pt.x * w;
      const py = pt.y * h;
      const isHovered = (idx === hoveredPointIndex);
      const isStartNode = (idx === 0);

      ctx.beginPath();
      ctx.arc(px, py, isHovered ? 8.5 : (isStartNode ? 7 : 5), 0, Math.PI * 2);

      if (isStartNode && activePolygonPoints.length >= 3) {
        ctx.fillStyle = isHovered ? "#FFD000" : activeColor.stroke;
        ctx.shadowColor = activeColor.stroke;
        ctx.shadowBlur = 12;
      } else {
        ctx.fillStyle = isHovered ? "#FFA05C" : "#FFFFFF";
        ctx.shadowColor = "rgba(255, 133, 51, 0.6)";
        ctx.shadowBlur = 6;
      }

      ctx.fill();
      ctx.strokeStyle = "#0A0D14";
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Node number badge
      ctx.fillStyle = "#CBD5E1";
      ctx.font = "10px Inter, sans-serif";
      ctx.fillText(`${idx + 1}`, px + 8, py - 6);
    });
  }

  updateHUDInfo();
}

function updateHUDInfo() {
  const coordHUD = document.getElementById("canvas-coord-hud");
  const statusHUD = document.getElementById("canvas-status-hud");

  let totalPoints = activePolygonPoints.length;
  completedPolygons.forEach(p => { totalPoints += p.points.length; });

  if (coordHUD) {
    if (cursorPosition && canvas) {
      const normX = (cursorPosition.x / canvas.width).toFixed(3);
      const normY = (cursorPosition.y / canvas.height).toFixed(3);
      coordHUD.textContent = `X: ${normX} | Y: ${normY} | ${completedPolygons.length} Bölge (${totalPoints} Nokta)`;
    } else {
      coordHUD.textContent = `${completedPolygons.length} Bölge | ${totalPoints} Nokta`;
    }
  }

  if (statusHUD) {
    if (activePolygonPoints.length > 0) {
      statusHUD.innerHTML = `<span class="status-dot-pulse"></span> Çizim Yapılıyor (Bölge ${completedPolygons.length + 1}, ${activePolygonPoints.length} Nokta)`;
    } else if (completedPolygons.length > 0) {
      const activeZone = completedPolygons.find(p => p.id === selectedPolygonId);
      const activeName = activeZone ? activeZone.name : "Bir bölge";
      statusHUD.innerHTML = `<span style="color: #10B981;">✓</span> ${completedPolygons.length} Bölge Tanımlı. (${activeName} düzenleniyor)`;
    } else {
      statusHUD.textContent = "Nokta Eklemek İçin Tıklayın";
    }
  }
}

/* --------------------------------------------------------------------------
   Zone Selection & Active Editor Synchronization
   -------------------------------------------------------------------------- */
function selectZone(zoneId) {
  selectedPolygonId = zoneId;
  const activeZone = completedPolygons.find(p => p.id === zoneId);

  const container = document.getElementById("zone-editor-container");
  const dotEl = document.getElementById("active-zone-dot");
  const titleText = document.getElementById("active-zone-title-text");
  const nameInput = document.getElementById("zone-name-input");
  const descPrompt = document.getElementById("zone-description-prompt");
  const pointsBadge = document.getElementById("zone-points-count-badge");
  const severityPills = document.querySelectorAll(".severity-pill");

  if (activeZone) {
    const idx = completedPolygons.indexOf(activeZone);
    const color = ZONE_COLORS[(activeZone.colorIdx !== undefined ? activeZone.colorIdx : idx) % ZONE_COLORS.length];

    if (container) {
      container.classList.add("has-active-zone");
      container.style.setProperty("--active-zone-border", color.stroke);
      container.style.setProperty("--active-zone-glow", color.glow);
    }
    if (dotEl) {
      dotEl.style.backgroundColor = color.stroke;
      dotEl.style.boxShadow = `0 0 10px ${color.stroke}`;
    }
    if (titleText) {
      titleText.textContent = `📍 ${activeZone.name} Düzenleniyor`;
    }
    if (nameInput) {
      nameInput.value = activeZone.name || "";
      nameInput.disabled = false;
    }
    if (descPrompt) {
      descPrompt.value = activeZone.description || "";
      descPrompt.disabled = false;
    }
    if (pointsBadge) {
      pointsBadge.textContent = `${activeZone.points.length} Köşe Noktası`;
      pointsBadge.style.color = color.stroke;
    }
    // Update severity pill
    const curSev = activeZone.severity || "warning";
    severityPills.forEach(p => {
      if (p.getAttribute("data-severity") === curSev) {
        p.classList.add("active");
      } else {
        p.classList.remove("active");
      }
    });

    // Synchronize Task Type mode (Counting vs Security)
    const activeType = activeZone.task_type || (activeZone.severity === "info" ? "counting" : "security");
    if (typeof setTaskTypeMode === "function") {
      setTaskTypeMode(activeType, false);
    }
  } else {
    // No zone active
    if (container) {
      container.classList.remove("has-active-zone");
    }
    if (dotEl) {
      dotEl.style.backgroundColor = "var(--primary)";
      dotEl.style.boxShadow = "none";
    }
    if (titleText) {
      titleText.textContent = "Bölge Seçilmedi (Kamerada Çizin veya Seçin)";
    }
    if (nameInput) {
      nameInput.value = "";
    }
    if (descPrompt) {
      descPrompt.value = "";
    }
    if (pointsBadge) {
      pointsBadge.textContent = "0 Nokta";
      pointsBadge.style.color = "var(--text-dim)";
    }
  }

  redrawCanvas();
  renderZonesBar();
  renderZoneEditorTabs();
  renderConfiguredZonesSummary();
}

/* --------------------------------------------------------------------------
   Multi-Zone Chips Bar Rendering & Actions
   -------------------------------------------------------------------------- */
function renderZonesBar() {
  const barEl = document.getElementById("zones-chip-bar");
  const listEl = document.getElementById("zones-chip-list");
  if (!barEl || !listEl) return;

  if (completedPolygons.length === 0) {
    barEl.style.display = "none";
    listEl.innerHTML = "";
    return;
  }

  barEl.style.display = "flex";
  listEl.innerHTML = completedPolygons.map((poly, idx) => {
    const color = ZONE_COLORS[(poly.colorIdx !== undefined ? poly.colorIdx : idx) % ZONE_COLORS.length];
    const isSelected = (selectedPolygonId === poly.id);
    return `
      <div class="zone-chip ${isSelected ? 'active' : ''}" 
           style="--chip-stroke: ${color.stroke}; --chip-glow: ${color.glow};"
           data-zone-id="${poly.id}"
           title="Bu bölgeyi seçip kuralını düzenlemek için tıklayın">
        <span class="zone-chip-color-dot" style="background-color: ${color.stroke};"></span>
        <span>${poly.name} (${poly.points.length} Nokta)</span>
        <span class="zone-chip-del" data-del-zone="${poly.id}" title="Bu bölgeyi sil">✕</span>
      </div>
    `;
  }).join("") + `
    <button type="button" class="btn-add-zone" id="btn-add-another-zone" title="Yeni bir poligon bölgesi çizmeye başla">
      + Yeni Bölge Çiz
    </button>
  `;

  // Attach chip click events
  completedPolygons.forEach(poly => {
    const chip = listEl.querySelector(`.zone-chip[data-zone-id="${poly.id}"]`);
    if (chip) {
      chip.addEventListener("click", (e) => {
        if (e.target.classList.contains("zone-chip-del")) return;
        selectZone(poly.id);
      });
    }

    const delBtn = listEl.querySelector(`.zone-chip-del[data-del-zone="${poly.id}"]`);
    if (delBtn) {
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteCompletedPolygon(poly.id);
      });
    }
  });

  const addAnotherBtn = document.getElementById("btn-add-another-zone");
  if (addAnotherBtn) {
    addAnotherBtn.addEventListener("click", () => {
      startNewPolygonDrawing();
    });
  }
}

/* --------------------------------------------------------------------------
   Zone Editor Tabs Rendering (Inside Formulation Card)
   -------------------------------------------------------------------------- */
function renderZoneEditorTabs() {
  const tabsEl = document.getElementById("zone-editor-tabs");
  if (!tabsEl) return;

  if (completedPolygons.length === 0) {
    tabsEl.innerHTML = "";
    return;
  }

  tabsEl.innerHTML = completedPolygons.map((poly, idx) => {
    const color = ZONE_COLORS[(poly.colorIdx !== undefined ? poly.colorIdx : idx) % ZONE_COLORS.length];
    const isSelected = (selectedPolygonId === poly.id);
    return `
      <button type="button" class="zone-tab ${isSelected ? 'active' : ''}" 
              style="--tab-stroke: ${color.stroke}; --tab-glow: ${color.glow};"
              data-zone-tab="${poly.id}"
              title="${poly.name} kuralını düzenle">
        <span class="zone-tab-dot" style="background-color: ${color.stroke};"></span>
        <span>${poly.name}</span>
      </button>
    `;
  }).join("") + `
    <button type="button" class="btn-add-zone" id="btn-tab-add-new-zone" title="Yeni bir bölge çizmeye başla">+ Yeni</button>
  `;

  completedPolygons.forEach(poly => {
    const tab = tabsEl.querySelector(`.zone-tab[data-zone-tab="${poly.id}"]`);
    if (tab) {
      tab.addEventListener("click", () => {
        selectZone(poly.id);
      });
    }
  });

  const addTabBtn = document.getElementById("btn-tab-add-new-zone");
  if (addTabBtn) {
    addTabBtn.addEventListener("click", () => {
      startNewPolygonDrawing();
    });
  }
}

/* --------------------------------------------------------------------------
   Configured Zones Live Summary List
   -------------------------------------------------------------------------- */
function renderConfiguredZonesSummary() {
  const summaryWrapper = document.getElementById("configured-zones-summary");
  const countSpan = document.getElementById("zones-total-count");
  const listEl = document.getElementById("configured-zones-list");
  if (!summaryWrapper || !listEl) return;

  if (completedPolygons.length === 0) {
    summaryWrapper.style.display = "none";
    listEl.innerHTML = "";
    return;
  }

  summaryWrapper.style.display = "block";
  if (countSpan) countSpan.textContent = completedPolygons.length;

  listEl.innerHTML = completedPolygons.map((poly, idx) => {
    const color = ZONE_COLORS[(poly.colorIdx !== undefined ? poly.colorIdx : idx) % ZONE_COLORS.length];
    const isSelected = (selectedPolygonId === poly.id);
    const descText = poly.description && poly.description.trim()
      ? poly.description.trim()
      : '<span style="color: var(--text-dim); font-style: italic;">Bu bölgeye henüz kural açıklaması girilmedi</span>';
    let sevLabel = (poly.severity || "warning").toUpperCase();
    if (poly.severity === "info") sevLabel = "📊 SAYIM & TAKİP";
    else if (poly.severity === "critical") sevLabel = "🚨 KRİTİK İHLAL";
    else if (poly.severity === "warning") sevLabel = "⚠️ UYARI";

    return `
      <div class="configured-zone-item ${isSelected ? 'active' : ''}" 
           style="--zone-item-stroke: ${color.stroke}; --zone-item-glow: ${color.glow};"
           data-zone-id="${poly.id}">
        <div class="configured-zone-left">
          <span class="zone-chip-color-dot" style="background-color: ${color.stroke};"></span>
          <div class="configured-zone-info">
            <div style="display: flex; align-items: center; gap: 6px;">
              <span class="configured-zone-name">${poly.name}</span>
              <span class="severity-badge ${poly.severity || 'warning'}" style="font-size: 0.65rem; padding: 1px 6px;">${sevLabel}</span>
              <span style="font-size: 0.68rem; color: var(--text-dim); font-family: monospace;">(${poly.points.length} nokta)</span>
            </div>
            <div class="configured-zone-prompt">${descText}</div>
          </div>
        </div>
        <div class="configured-zone-actions">
          <button type="button" class="btn-zone-edit-mini" data-edit-zone="${poly.id}">Düzenle</button>
          <span class="zone-chip-del" data-del-zone="${poly.id}" title="Bu bölgeyi sil">✕</span>
        </div>
      </div>
    `;
  }).join("");

  completedPolygons.forEach(poly => {
    const item = listEl.querySelector(`.configured-zone-item[data-zone-id="${poly.id}"]`);
    if (item) {
      item.addEventListener("click", (e) => {
        if (e.target.classList.contains("zone-chip-del")) return;
        selectZone(poly.id);
      });
    }

    const editBtn = listEl.querySelector(`.btn-zone-edit-mini[data-edit-zone="${poly.id}"]`);
    if (editBtn) {
      editBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        selectZone(poly.id);
        const descPrompt = document.getElementById("zone-description-prompt");
        if (descPrompt) descPrompt.focus();
      });
    }

    const delBtn = listEl.querySelector(`.zone-chip-del[data-del-zone="${poly.id}"]`);
    if (delBtn) {
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteCompletedPolygon(poly.id);
      });
    }
  });
}

function deleteCompletedPolygon(zoneId) {
  completedPolygons = completedPolygons.filter(p => p.id !== zoneId);
  completedPolygons.forEach((p, idx) => {
    p.colorIdx = idx % ZONE_COLORS.length;
  });

  if (selectedPolygonId === zoneId) {
    selectedPolygonId = completedPolygons.length > 0 ? completedPolygons[0].id : null;
  }

  if (selectedPolygonId) {
    selectZone(selectedPolygonId);
  } else {
    selectZone(null);
  }
}

function completeActivePolygon() {
  if (activePolygonPoints.length < 3) {
    alert("Bir poligon bölgesini tamamlamak için en az 3 köşe noktası eklemelisiniz.");
    return false;
  }

  const activeTypeBtn = document.querySelector(".task-type-btn.active");
  const currentTaskType = activeTypeBtn ? activeTypeBtn.getAttribute("data-task-type") : "counting";
  const zoneNumber = completedPolygons.length + 1;
  const newZone = {
    id: `zone_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
    name: `Bölge ${zoneNumber}`,
    description: "",
    task_type: currentTaskType,
    severity: currentTaskType === "counting" ? "info" : "warning",
    points: [...activePolygonPoints],
    colorIdx: completedPolygons.length % ZONE_COLORS.length
  };

  completedPolygons.push(newZone);
  activePolygonPoints = [];
  hoveredPointIndex = -1;

  // Activate the new zone immediately for editing
  selectZone(newZone.id);

  // Automatically focus the zone-specific rule textarea so the user can immediately describe this zone
  const descPrompt = document.getElementById("zone-description-prompt");
  if (descPrompt) {
    descPrompt.focus();
  }

  // Suggest rule title if empty
  const titleInput = document.getElementById("rule-title-input");
  if (titleInput && !titleInput.value.trim()) {
    let camName = "Kamera";
    if (currentScope === "camera" && selectedCameraId) {
      const cam = camerasList.find(c => c.id === selectedCameraId);
      if (cam) camName = cam.name || cam.ip;
    }
    titleInput.value = `${camName} Güvenlik ve Bölge Kuralları`;
  }

  return true;
}

function startNewPolygonDrawing() {
  if (activePolygonPoints.length >= 3) {
    completeActivePolygon();
  } else {
    activePolygonPoints = [];
  }
  selectedPolygonId = null;
  redrawCanvas();
  renderZonesBar();
  renderZoneEditorTabs();
}

/* --------------------------------------------------------------------------
   Canvas Mouse & Touch Events
   -------------------------------------------------------------------------- */
function initCanvasEvents() {
  canvas.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    cursorPosition = { x, y };

    // Check if hovering near starting point of active in-progress polygon
    if (activePolygonPoints.length >= 3) {
      const firstX = activePolygonPoints[0].x * canvas.width;
      const firstY = activePolygonPoints[0].y * canvas.height;
      const dist = Math.hypot(x - firstX, y - firstY);
      hoveredPointIndex = dist <= 16 ? 0 : -1;
    } else {
      hoveredPointIndex = -1;
    }

    redrawCanvas();
  });

  canvas.addEventListener("mouseleave", () => {
    cursorPosition = null;
    hoveredPointIndex = -1;
    redrawCanvas();
  });

  canvas.addEventListener("click", (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    // 1. If currently drawing and clicking on start point with >= 3 points, close this polygon
    if (activePolygonPoints.length >= 3) {
      const firstX = activePolygonPoints[0].x * canvas.width;
      const firstY = activePolygonPoints[0].y * canvas.height;
      if (Math.hypot(x - firstX, y - firstY) <= 16) {
        completeActivePolygon();
        return;
      }
    }

    const normPt = {
      x: parseFloat((x / canvas.width).toFixed(4)),
      y: parseFloat((y / canvas.height).toFixed(4))
    };

    // 2. If not drawing, check if user clicked inside an already completed polygon to select it!
    if (activePolygonPoints.length === 0 && completedPolygons.length > 0) {
      const clickedPoly = completedPolygons.slice().reverse().find(poly => isPointInPolygon(normPt, poly.points));
      if (clickedPoly) {
        selectZone(clickedPoly.id);
        return;
      }
    }

    // 3. Otherwise add new normalized point to active polygon
    // Prevent duplicate consecutive points from double-click or fast clicking
    if (activePolygonPoints.length > 0) {
      const lastPt = activePolygonPoints[activePolygonPoints.length - 1];
      if (Math.hypot(normPt.x - lastPt.x, normPt.y - lastPt.y) < 0.008) {
        return;
      }
    }

    activePolygonPoints.push(normPt);
    redrawCanvas();
  });

  canvas.addEventListener("dblclick", () => {
    // Double click closes in-progress polygon if at least 3 points
    if (activePolygonPoints.length >= 3) {
      completeActivePolygon();
    }
  });
}

/* --------------------------------------------------------------------------
   Scope & Camera Selector
   -------------------------------------------------------------------------- */
function initScopeSelector() {
  const btnCamera = document.getElementById("btn-scope-camera");
  const btnSystem = document.getElementById("btn-scope-system");
  const cameraGroup = document.getElementById("camera-select-group");
  const cameraSelect = document.getElementById("rule-camera-select");

  if (btnCamera && btnSystem) {
    btnCamera.addEventListener("click", () => {
      currentScope = "camera";
      btnCamera.classList.add("active");
      btnSystem.classList.remove("active");
      if (cameraGroup) cameraGroup.style.display = "flex";
      if (bgImage) bgImage.style.display = "block";
      if (systemGrid) systemGrid.style.display = "none";
      updateCameraBackdrop();
    });

    btnSystem.addEventListener("click", () => {
      currentScope = "system";
      btnSystem.classList.add("active");
      btnCamera.classList.remove("active");
      if (cameraGroup) cameraGroup.style.display = "none";
      if (bgImage) bgImage.style.display = "none";
      if (systemGrid) systemGrid.style.display = "flex";
    });
  }

  if (cameraSelect) {
    cameraSelect.addEventListener("change", (e) => {
      selectedCameraId = e.target.value;
      updateCameraBackdrop();
    });
  }
}

async function loadCamerasForRules() {
  const res = await fetchCameras();
  camerasList = res.cameras || [];
  const select = document.getElementById("rule-camera-select");
  if (!select) return;

  select.innerHTML = "";
  if (camerasList.length === 0) {
    select.innerHTML = `<option value="">Kayıtlı Kamera Yok</option>`;
    return;
  }

  camerasList.forEach((cam, idx) => {
    const opt = document.createElement("option");
    opt.value = cam.id;
    opt.textContent = `${cam.name || 'Kamera'} (${cam.ip}:${cam.port})`;
    select.appendChild(opt);
    if (idx === 0) selectedCameraId = cam.id;
  });

  updateCameraBackdrop();
}

function updateCameraBackdrop() {
  if (currentScope !== "camera" || !selectedCameraId || !bgImage) return;
  bgImage.src = getSnapshotUrl(selectedCameraId);
}

/* --------------------------------------------------------------------------
   Canvas Tool Buttons
   -------------------------------------------------------------------------- */
function initToolButtons() {
  // Undo Button
  const btnUndo = document.getElementById("btn-canvas-undo");
  if (btnUndo) {
    btnUndo.addEventListener("click", () => {
      if (activePolygonPoints.length > 0) {
        activePolygonPoints.pop();
      } else if (completedPolygons.length > 0) {
        const lastPoly = completedPolygons.pop();
        activePolygonPoints = [...lastPoly.points];
        if (selectedPolygonId === lastPoly.id) {
          selectedPolygonId = completedPolygons.length > 0 ? completedPolygons[completedPolygons.length - 1].id : null;
        }
      }
      redrawCanvas();
      renderZonesBar();
      renderZoneEditorTabs();
      renderConfiguredZonesSummary();
    });
  }

  // Clear All Button
  const btnClear = document.getElementById("btn-canvas-clear");
  if (btnClear) {
    btnClear.addEventListener("click", () => {
      if (completedPolygons.length > 0 || activePolygonPoints.length > 0) {
        if (confirm("Tüm tanımlı poligon bölgelerini ve kurallarını sıfırlamak istediğinize emin misiniz?")) {
          completedPolygons = [];
          activePolygonPoints = [];
          selectedPolygonId = null;
          selectZone(null);
        }
      }
    });
  }

  // Close Active Polygon Button
  const btnClose = document.getElementById("btn-canvas-close");
  if (btnClose) {
    btnClose.addEventListener("click", () => {
      completeActivePolygon();
    });
  }

  // New Polygon Button
  const btnNewPoly = document.getElementById("btn-canvas-new-poly");
  if (btnNewPoly) {
    btnNewPoly.addEventListener("click", () => {
      startNewPolygonDrawing();
    });
  }
}

/* --------------------------------------------------------------------------
   Task Type Management (Counting / Business Intelligence vs Security Violations)
   -------------------------------------------------------------------------- */
function setTaskTypeMode(type, syncActiveZone = true) {
  const btnCounting = document.getElementById("task-type-btn-counting");
  const btnSecurity = document.getElementById("task-type-btn-security");
  const explanationBox = document.getElementById("task-mode-explanation-box");
  const explanationText = document.getElementById("task-mode-explanation-text");
  const actCount = document.getElementById("action-count-stats");
  const actScreen = document.getElementById("action-alert-screen");
  const alertHint = document.getElementById("action-alert-hint");
  const alertTitle = document.getElementById("action-alert-title");
  const pills = document.querySelectorAll(".severity-pill");

  if (type === "counting") {
    btnCounting?.classList.add("active");
    btnSecurity?.classList.remove("active");
    if (explanationBox) {
      explanationBox.className = "task-mode-explanation-box counting";
      if (explanationText) {
        explanationText.innerHTML = `<strong>Sayım & İstatistik Modu:</strong> "Bu kapıdan giriş çıkış yapanları say" gibi durumlar bir <u>kural ihlali değildir</u>. İnsanların kapıdan geçişi olağan operasyonel akıştır; sistem her geçişte canlı sayacı artırır (+1 Giriş / +1 Çıkış) ve istatistik tablosuna işler. Güvenlik alarm sireni çalmaz.`;
      }
    }
    // Set severity pill to info (Sayım & İstatistik)
    pills.forEach(p => p.classList.remove("active"));
    const infoPill = document.querySelector('.severity-pill[data-severity="info"]');
    if (infoPill) infoPill.classList.add("active");

    // Action defaults for counting:
    if (actCount) actCount.checked = true;
    if (actScreen) actScreen.checked = false;
    if (alertHint) alertHint.textContent = "Sayım analizlerinde kural ihlali oluşmadığı için siren ve acil uyarı penceresi kapalıdır (Sayaç artırılır).";
    if (alertTitle) alertTitle.textContent = "🚨 Kural İhlali Alarmı (Sayım Görevinde Pasiftir)";
  } else {
    btnSecurity?.classList.add("active");
    btnCounting?.classList.remove("active");
    if (explanationBox) {
      explanationBox.className = "task-mode-explanation-box security";
      if (explanationText) {
        explanationText.innerHTML = `<strong>Güvenlik ve İhlal Modu:</strong> Yasak alana yetkisiz giriş, baret takmama veya ters yön gibi durumlar bir <u>kural ihlalidir</u>. Sistem ihlali tespit ettiğinde derhal güvenlik alarmı üretir ve operatör ekranında kırmızı pencereyle siren çalar.`;
      }
    }
    // Set severity pill to warning (İhlal)
    pills.forEach(p => p.classList.remove("active"));
    const warnPill = document.querySelector('.severity-pill[data-severity="warning"]');
    if (warnPill) warnPill.classList.add("active");

    // Action defaults for security:
    if (actCount) actCount.checked = false;
    if (actScreen) actScreen.checked = true;
    if (alertHint) alertHint.textContent = "Güvenlik ihlali tespit edildiğinde ekranda kırmızı uyarı penceresi açar ve siren çalar.";
    if (alertTitle) alertTitle.textContent = "🚨 Sesli & Görsel Alarm Uyarısı Göster";
  }

  if (syncActiveZone && selectedPolygonId) {
    const activeZone = completedPolygons.find(p => p.id === selectedPolygonId);
    if (activeZone) {
      activeZone.task_type = type;
      activeZone.severity = type === "counting" ? "info" : "warning";
      renderConfiguredZonesSummary();
    }
  }
}

/* --------------------------------------------------------------------------
   Rule Formulation Form & Reactive Per-Zone Event Handling
   -------------------------------------------------------------------------- */
function initFormControls() {
  // Task Type Mode Selector (Counting vs Security)
  const btnCounting = document.getElementById("task-type-btn-counting");
  const btnSecurity = document.getElementById("task-type-btn-security");
  if (btnCounting) {
    btnCounting.addEventListener("click", () => setTaskTypeMode("counting", true));
  }
  if (btnSecurity) {
    btnSecurity.addEventListener("click", () => setTaskTypeMode("security", true));
  }

  // Severity Pills: Updates active zone's severity!
  const pills = document.querySelectorAll(".severity-pill");
  pills.forEach(pill => {
    pill.addEventListener("click", () => {
      pills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      const sev = pill.getAttribute("data-severity");

      if (sev === "info") {
        setTaskTypeMode("counting", false);
      } else {
        setTaskTypeMode("security", false);
      }

      if (selectedPolygonId) {
        const activeZone = completedPolygons.find(p => p.id === selectedPolygonId);
        if (activeZone) {
          activeZone.severity = sev;
          activeZone.task_type = sev === "info" ? "counting" : "security";
          renderConfiguredZonesSummary();
        }
      }
    });
  });

  // Zone Name Input: updates active zone in real time
  const zoneNameInput = document.getElementById("zone-name-input");
  if (zoneNameInput) {
    zoneNameInput.addEventListener("input", (e) => {
      if (selectedPolygonId) {
        const activeZone = completedPolygons.find(p => p.id === selectedPolygonId);
        if (activeZone) {
          activeZone.name = e.target.value.trim() || `Bölge ${completedPolygons.indexOf(activeZone) + 1}`;
          const titleText = document.getElementById("active-zone-title-text");
          if (titleText) titleText.textContent = `📍 ${activeZone.name} Düzenleniyor`;
          redrawCanvas();
          renderZonesBar();
          renderZoneEditorTabs();
          renderConfiguredZonesSummary();
        }
      }
    });
  }

  // Zone Description / AI Prompt: updates active zone in real time
  const zoneDescPrompt = document.getElementById("zone-description-prompt");
  if (zoneDescPrompt) {
    zoneDescPrompt.addEventListener("input", (e) => {
      if (selectedPolygonId) {
        const activeZone = completedPolygons.find(p => p.id === selectedPolygonId);
        if (activeZone) {
          activeZone.description = e.target.value;
          renderConfiguredZonesSummary();
        }
      }
    });
  }

  // Submit Button
  const form = document.getElementById("create-rule-form");
  if (form) {
    form.addEventListener("submit", handleCreateRuleSubmit);
  }
}

function initPresetChips() {
  const chips = document.querySelectorAll(".chip-btn");
  const textarea = document.getElementById("zone-description-prompt");
  if (!textarea) return;

  chips.forEach(chip => {
    chip.addEventListener("click", () => {
      const template = chip.getAttribute("data-prompt") || chip.textContent.trim();
      if (!textarea.value.trim()) {
        textarea.value = template;
      } else {
        textarea.value += " " + template;
      }

      // Automatically switch task mode based on chip type
      if (chip.classList.contains("chip-counting")) {
        setTaskTypeMode("counting", true);
      } else if (chip.classList.contains("chip-security")) {
        setTaskTypeMode("security", true);
      }

      if (selectedPolygonId) {
        const activeZone = completedPolygons.find(p => p.id === selectedPolygonId);
        if (activeZone) {
          activeZone.description = textarea.value;
          renderConfiguredZonesSummary();
        }
      }
      textarea.focus();
    });
  });
}

async function handleCreateRuleSubmit(e) {
  e.preventDefault();
  const submitBtn = document.getElementById("btn-save-rule");

  const title = document.getElementById("rule-title-input").value.trim();
  const activeSeverityPill = document.querySelector(".severity-pill.active");
  const fallbackSeverity = activeSeverityPill ? activeSeverityPill.getAttribute("data-severity") : "warning";

  if (!title) {
    alert("Lütfen kural grubu veya kamera için bir başlık girin.");
    return;
  }

  if (currentScope === "camera" && !selectedCameraId) {
    alert("Lütfen kuralın uygulanacağı kamerayı seçin.");
    return;
  }

  // If in-progress polygon has >= 3 points, complete it automatically
  if (activePolygonPoints.length >= 3) {
    completeActivePolygon();
  }

  // Check if zones have descriptions
  if (completedPolygons.length > 0) {
    const missingDescZones = completedPolygons.filter(z => !z.description || !z.description.trim());
    if (missingDescZones.length > 0) {
      const zoneNames = missingDescZones.map(z => z.name).join(", ");
      const confirmSave = confirm(`${zoneNames} için henüz bir kural açıklaması yazılmadı.\nBu bölgeleri açıklamasız kaydetmek istediğinize emin misiniz?`);
      if (!confirmSave) {
        selectZone(missingDescZones[0].id);
        const descEl = document.getElementById("zone-description-prompt");
        if (descEl) descEl.focus();
        return;
      }
    }
  }

  // Selected camera name
  let cameraName = "Tüm Sistem (Global)";
  if (currentScope === "camera" && selectedCameraId) {
    const cam = camerasList.find(c => c.id === selectedCameraId);
    if (cam) cameraName = cam.name || cam.ip;
  }

  // Actions
  const actions = [];
  const actScreen = document.getElementById("action-alert-screen");
  if (actScreen && actScreen.checked) actions.push("alert_screen");
  const actCount = document.getElementById("action-count-stats");
  if (actCount && actCount.checked) actions.push("count_stats");
  const actSnap = document.getElementById("action-snapshot");
  if (actSnap && actSnap.checked) actions.push("snapshot");
  const actNvr = document.getElementById("action-nvr-bookmark");
  if (actNvr && actNvr.checked) actions.push("nvr_bookmark");

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Kaydediliyor...";
  }

  // Prepare full per-zone rule objects
  const zonesData = completedPolygons.map((p, idx) => ({
    id: p.id || `zone_${idx + 1}`,
    name: p.name || `Bölge ${idx + 1}`,
    description: (p.description || "").trim(),
    severity: p.severity || fallbackSeverity,
    actions,
    points: p.points,
    color_idx: p.colorIdx !== undefined ? p.colorIdx : idx
  }));

  // Aggregated natural language summary description for high-level rule table
  let aggregatedDescription = "";
  if (zonesData.length > 0) {
    aggregatedDescription = zonesData.map(z => `${z.name}: ${z.description || 'Kural açıklaması girilmedi'}`).join(" | ");
  } else {
    aggregatedDescription = "Sistem geneli izleme kuralı";
  }

  const assigneeName = document.getElementById("rule-assignee-name")?.value.trim() || "Ahmet Yılmaz";
  const assigneeRole = document.getElementById("rule-assignee-role")?.value.trim() || "Saha Şefi";
  const escalationName = document.getElementById("rule-escalation-name")?.value.trim() || "Mehmet Kaya (İSG Müdürü)";
  const escalationTimeout = parseInt(document.getElementById("rule-escalation-timeout")?.value || "5");

  try {
    await createRule({
      title,
      scope: currentScope,
      camera_id: currentScope === "camera" ? selectedCameraId : null,
      camera_name: cameraName,
      severity: zonesData.length > 0 ? zonesData[0].severity : fallbackSeverity,
      description: aggregatedDescription,
      zones: zonesData,
      actions,
      assignee: {
        name: assigneeName,
        role: assigneeRole,
        phone: "Dahili 104"
      },
      escalation: {
        supervisor_name: escalationName,
        supervisor_role: "İSG Departman Yöneticisi",
        timeout_minutes: escalationTimeout
      }
    });

    // Reset Form & Canvas
    document.getElementById("rule-title-input").value = "";
    completedPolygons = [];
    activePolygonPoints = [];
    selectedPolygonId = null;
    selectZone(null);

    // Reload Rules List
    await loadRulesTable();
    const zoneCountText = zonesData.length > 0 ? `${zonesData.length} özel bölge kuralı` : 'global kural';
    alert(`'${title}' kuralı (${zoneCountText}) başarıyla tanımlandı ve sisteme kaydedildi.`);
  } catch (err) {
    alert(`Kural kaydedilemedi: ${err.message}`);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "💾 Tanımlanan Görev ve Kuralları Kaydet";
    }
  }
}

/* --------------------------------------------------------------------------
   Rules List Table & Actions
   -------------------------------------------------------------------------- */
async function loadRulesTable() {
  const tbody = document.getElementById("rules-table-tbody");
  const countEl = document.getElementById("rules-count-badge");
  if (!tbody) return;

  const res = await fetchRules();
  rulesList = res.rules || [];

  if (countEl) countEl.textContent = `${rulesList.length} Görev / Kural`;

  if (rulesList.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; color: var(--text-dim); padding: 32px;">
          Henüz tanımlanmış bir kural veya bölge bulunmuyor. Yukarıdaki çizim editörü ile ilk kuralınızı oluşturun.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = rulesList.map(rule => {
    const scopeBadge = rule.scope === "system"
      ? `<span class="scope-badge system">🌐 Sistem Geneli</span>`
      : `<span class="scope-badge camera">📷 ${rule.camera_name || 'Kamera'}</span>`;

    let severityLabel = rule.severity.toUpperCase();
    if (rule.severity === "critical") severityLabel = "🚨 KRİTİK İHLAL";
    else if (rule.severity === "warning") severityLabel = "⚠️ UYARI";
    else if (rule.severity === "info") severityLabel = "📊 SAYIM & TAKİP";

    const severityBadge = `<span class="severity-badge ${rule.severity}">${severityLabel}</span>`;

    // Multi-polygon badge logic
    const polyCount = (rule.zones && rule.zones.length > 0)
      ? rule.zones.length
      : ((rule.polygons && rule.polygons.length > 0) 
          ? rule.polygons.length 
          : (rule.polygon && rule.polygon.length > 0 ? 1 : 0));
    
    let totalPts = 0;
    if (rule.zones && rule.zones.length > 0) {
      rule.zones.forEach(z => { totalPts += (z.points ? z.points.length : 0); });
    } else if (rule.polygons && rule.polygons.length > 0) {
      rule.polygons.forEach(p => { totalPts += (p.length || 0); });
    } else if (rule.polygon) {
      totalPts = rule.polygon.length || 0;
    }

    const polyBadge = polyCount > 0
      ? `<span style="font-family: monospace; color: var(--primary);">📐 ${polyCount} Bölge (${totalPts} Nokta)</span>`
      : `<span style="color: var(--text-dim); font-size: 0.8rem;">Bölge Yok (Global)</span>`;

    const isChecked = rule.enabled !== false ? "checked" : "";

    // Render per-zone descriptions cleanly in table cell
    let descriptionsCellHtml = "";
    if (rule.zones && rule.zones.length > 0) {
      descriptionsCellHtml = `
        <div class="rule-zones-cell-list">
          ${rule.zones.map((z, zIdx) => {
            const col = ZONE_COLORS[(z.color_idx !== undefined ? z.color_idx : zIdx) % ZONE_COLORS.length];
            const zonePrompt = z.description && z.description.trim() ? z.description.trim() : 'Açıklama girilmedi';
            return `
              <div class="rule-zone-cell-item" title="${z.name}: ${zonePrompt}">
                <span class="zone-dot-mini" style="background-color: ${col.stroke};"></span>
                <span><strong style="color: var(--text-main);">${z.name || 'Bölge'}:</strong> <span style="color: var(--text-secondary);">${zonePrompt}</span></span>
              </div>
            `;
          }).join("")}
        </div>
      `;
    } else {
      descriptionsCellHtml = `
        <div style="max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${rule.description || ''}">
          ${rule.description || '<em style="color: var(--text-dim);">Açıklama girilmedi</em>'}
        </div>
      `;
    }

    return `
      <tr id="rule-row-${rule.id}">
        <td><strong>${rule.title}</strong></td>
        <td>${scopeBadge}</td>
        <td>${severityBadge}</td>
        <td style="max-width: 320px;">
          ${descriptionsCellHtml}
        </td>
        <td>${polyBadge}</td>
        <td>
          <label class="switch">
            <input type="checkbox" id="toggle-${rule.id}" ${isChecked}>
            <span class="slider"></span>
          </label>
        </td>
        <td>
          <div style="display: flex; gap: 8px;">
            <button class="btn-card-action" style="padding: 4px 8px; font-size: 0.75rem;" id="btn-load-${rule.id}" title="Tüm Bölgeleri ve Kuralları Editöre Yükle">
              Editörde Aç
            </button>
            <button class="btn-card-delete" id="btn-delete-${rule.id}" title="Kuralı Sil">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  // Attach event handlers
  rulesList.forEach(rule => {
    // Toggle switch
    const toggle = document.getElementById(`toggle-${rule.id}`);
    if (toggle) {
      toggle.addEventListener("change", async (e) => {
        await updateRule(rule.id, { enabled: e.target.checked });
      });
    }

    // Load to editor
    const loadBtn = document.getElementById(`btn-load-${rule.id}`);
    if (loadBtn) {
      loadBtn.addEventListener("click", () => {
        loadRuleIntoEditor(rule);
      });
    }

    // Delete
    const delBtn = document.getElementById(`btn-delete-${rule.id}`);
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        if (confirm(`'${rule.title}' kuralını silmek istediğinize emin misiniz?`)) {
          await deleteRule(rule.id);
          await loadRulesTable();
        }
      });
    }
  });
}

function loadRuleIntoEditor(rule) {
  // Set title
  const titleInput = document.getElementById("rule-title-input");
  if (titleInput) titleInput.value = rule.title;

  // Set Scope
  if (rule.scope === "system") {
    const btnSys = document.getElementById("btn-scope-system");
    if (btnSys) btnSys.click();
  } else {
    const btnCam = document.getElementById("btn-scope-camera");
    if (btnCam) btnCam.click();
    if (rule.camera_id) {
      const select = document.getElementById("rule-camera-select");
      if (select) {
        select.value = rule.camera_id;
        selectedCameraId = rule.camera_id;
        updateCameraBackdrop();
      }
    }
  }

  // Restore Multi-Polygons and per-zone rules
  completedPolygons = [];
  if (rule.zones && Array.isArray(rule.zones) && rule.zones.length > 0) {
    completedPolygons = rule.zones.map((z, idx) => ({
      id: z.id || `zone_${idx}_${Date.now()}`,
      name: z.name || `Bölge ${idx + 1}`,
      description: z.description || "",
      severity: z.severity || rule.severity || "warning",
      points: (z.points || []).map(p => ({ x: p.x, y: p.y })),
      colorIdx: z.color_idx !== undefined ? z.color_idx : (idx % ZONE_COLORS.length)
    }));
  } else if (rule.polygons && Array.isArray(rule.polygons) && rule.polygons.length > 0) {
    completedPolygons = rule.polygons.map((pts, idx) => ({
      id: `zone_${idx}_${Date.now()}`,
      name: `Bölge ${idx + 1}`,
      description: rule.description || "",
      severity: rule.severity || "warning",
      points: pts.map(p => ({ x: p.x, y: p.y })),
      colorIdx: idx % ZONE_COLORS.length
    }));
  } else if (rule.polygon && Array.isArray(rule.polygon) && rule.polygon.length > 0) {
    completedPolygons = [{
      id: `zone_0_${Date.now()}`,
      name: "Bölge 1",
      description: rule.description || "",
      severity: rule.severity || "warning",
      points: rule.polygon.map(p => ({ x: p.x, y: p.y })),
      colorIdx: 0
    }];
  }

  activePolygonPoints = [];
  selectedPolygonId = null;

  // Activate first zone if available
  if (completedPolygons.length > 0) {
    selectZone(completedPolygons[0].id);
  } else {
    selectZone(null);
  }

  // Scroll to editor smoothly
  const viewRulesEl = document.getElementById("view-rules");
  if (viewRulesEl && viewRulesEl.scrollIntoView) {
    viewRulesEl.scrollIntoView({ behavior: "smooth" });
  }
}
