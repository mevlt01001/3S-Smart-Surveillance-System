/**
 * AegisVision Live Video Wall Module (live.js)
 * Displays real-time camera grid with dynamic zone overlays and layout options.
 */

let cameras = [];
let rules = [];
let liveRefreshTimer = null;
let currentGridMode = "grid-3x2";
let showZonesOverlay = true;

export async function initLiveModule() {
  await fetchFleetAndRules();
  setupLiveToolbar();
  renderLiveGrid();
  startLiveFeedPolling();
}

async function fetchFleetAndRules() {
  try {
    const [cRes, rRes] = await Promise.all([
      fetch("/api/cameras"),
      fetch("/api/rules")
    ]);
    const cData = await cRes.json();
    const rData = await rRes.json();
    cameras = cData.cameras || [];
    rules = rData.rules || [];
  } catch (e) {
    console.error("[Live] Data fetch failed:", e);
  }
}

function setupLiveToolbar() {
  const btn1x1 = document.getElementById("btn-layout-1x1");
  const btn2x2 = document.getElementById("btn-layout-2x2");
  const btn3x2 = document.getElementById("btn-layout-3x2");
  const gridContainer = document.getElementById("live-grid-container");

  const layoutBtns = [btn1x1, btn2x2, btn3x2];

  function setActiveLayout(mode, btn) {
    currentGridMode = mode;
    layoutBtns.forEach(b => b?.classList.remove("active"));
    btn?.classList.add("active");
    if (gridContainer) {
      gridContainer.className = `live-video-grid ${mode}`;
    }
  }

  btn1x1?.addEventListener("click", () => setActiveLayout("grid-1x1", btn1x1));
  btn2x2?.addEventListener("click", () => setActiveLayout("grid-2x2", btn2x2));
  btn3x2?.addEventListener("click", () => setActiveLayout("grid-3x2", btn3x2));

  const toggleZones = document.getElementById("toggle-live-zones");
  if (toggleZones) {
    toggleZones.addEventListener("change", (e) => {
      showZonesOverlay = e.target.checked;
      document.querySelectorAll(".live-tile-canvas").forEach(canvas => {
        canvas.style.display = showZonesOverlay ? "block" : "none";
      });
    });
  }
}

function renderLiveGrid() {
  const container = document.getElementById("live-grid-container");
  const countBadge = document.getElementById("live-stream-count-badge");
  if (!container) return;

  if (cameras.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 48px; text-align: center; color: var(--text-dim);">
        Kayıtlı kamera bulunamadı. Lütfen Kamera Yönetim (Home) sekmesinden kamera ekleyin.
      </div>
    `;
    return;
  }

  if (countBadge) {
    countBadge.textContent = `${cameras.length} Kamera Yayında`;
  }

  container.className = `live-video-grid ${currentGridMode}`;
  container.innerHTML = cameras.map((cam, idx) => {
    const camRules = rules.filter(r => r.camera_id === cam.id);
    const totalZones = camRules.reduce((acc, r) => acc + (r.zones ? r.zones.length : 0), 0);

    return `
      <div class="live-camera-tile" id="live-tile-${cam.id}">
        <div class="live-tile-header">
          <span class="live-tile-name">
            <span class="status-dot-pulse"></span>
            ${cam.name || `Kamera ${idx + 1}`}
          </span>
          <span style="font-size: 0.72rem; color: var(--text-dim); font-family: monospace;">
            ${cam.ip} : ${cam.rtsp_port || 554}
          </span>
        </div>

        <div class="live-tile-feed">
          <img class="live-tile-image" id="live-img-${cam.id}" 
               src="/api/cameras/${cam.id}/snapshot?t=${Date.now()}" 
               alt="${cam.name}" 
               onerror="this.src='/static/img/cam_placeholder.jpg'">
          
          <canvas class="live-tile-canvas" id="live-canvas-${cam.id}"></canvas>

          <div class="live-tile-osd">
            <span class="live-rec-dot"></span>
            <span>RTSP CANLI</span>
            <span style="color: var(--primary); margin-left: 4px;">• ${totalZones} Bölge</span>
          </div>
        </div>

        <div class="live-tile-footer">
          <span>${camRules.length > 0 ? camRules[0].title : 'Standart Gözetim'}</span>
          <div class="live-tile-actions">
            <button class="btn-card-action" style="padding: 2px 7px; font-size: 0.72rem;" onclick="window.open('/api/cameras/${cam.id}/snapshot', '_blank')">
              Snapshot
            </button>
          </div>
        </div>
      </div>
    `;
  }).join("");

  // Draw zones on tile canvases
  setTimeout(drawAllTileCanvases, 200);
}

function drawAllTileCanvases() {
  cameras.forEach(cam => {
    const canvas = document.getElementById(`live-canvas-${cam.id}`);
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width || 480;
    canvas.height = rect.height || 270;

    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const camRules = rules.filter(r => r.camera_id === cam.id);
    camRules.forEach(r => {
      (r.zones || []).forEach(zone => {
        if (!zone.points || zone.points.length < 3) return;

        ctx.beginPath();
        const first = zone.points[0];
        ctx.moveTo(first.x * canvas.width, first.y * canvas.height);

        for (let i = 1; i < zone.points.length; i++) {
          const pt = zone.points[i];
          ctx.lineTo(pt.x * canvas.width, pt.y * canvas.height);
        }
        ctx.closePath();

        const isCrit = (zone.severity === "critical");
        ctx.fillStyle = isCrit ? "rgba(239, 68, 68, 0.15)" : "rgba(255, 133, 51, 0.15)";
        ctx.fill();

        ctx.strokeStyle = isCrit ? "#EF4444" : "#FF8533";
        ctx.lineWidth = 2;
        ctx.shadowColor = isCrit ? "#EF4444" : "#FF8533";
        ctx.shadowBlur = 8;
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Label
        ctx.fillStyle = "#fff";
        ctx.font = "bold 11px sans-serif";
        ctx.fillText(zone.name || "Bölge", first.x * canvas.width + 5, first.y * canvas.height + 15);
      });
    });
  });
}

function startLiveFeedPolling() {
  if (liveRefreshTimer) clearInterval(liveRefreshTimer);
  liveRefreshTimer = setInterval(() => {
    cameras.forEach(cam => {
      const img = document.getElementById(`live-img-${cam.id}`);
      if (img) {
        img.src = `/api/cameras/${cam.id}/snapshot?t=${Date.now()}`;
      }
    });
  }, 2000); // 2 second live frame refresh
}
