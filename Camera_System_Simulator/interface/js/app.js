/**
 * AEGIS-PRO Main VMS Application Controller
 * Coordinates camera matrices, telemetry, WebSockets, set switching,
 * local NVR disk storage quota, and synchronized playback.
 * PTZ and fake AI bounding box code has been completely destroyed.
 */

class SurveillanceApp {
  constructor() {
    this.activeSetId = "set_1";
    this.cameras = [];
    this.players = new Map();
    this.selectedCameraId = "cam1";
    this.currentGridLayout = "grid-3x2";
    this.ws = null;

    this.timeline = null;
    this.eventHub = null;

    this.init();
  }

  async init() {
    this.timeline = new PlaybackTimeline(this);
    this.eventHub = new EventHub(this);

    this.setupHeaderClock();
    this.setupLayoutControls();
    this.setupModals();
    this.setupStorageControls();
    this.setupWebSocket();

    await this.loadInitialData();
  }

  setupHeaderClock() {
    const clockEl = document.getElementById("masterClockDisplay");
    const updateTime = () => {
      const now = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      const timeStr = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
      if (clockEl) clockEl.textContent = timeStr;

      // Update per-camera OSD live clocks
      document.querySelectorAll(".osd-live-time").forEach(el => {
        el.textContent = timeStr;
      });
    };
    updateTime();
    setInterval(updateTime, 1000);
  }

  setupLayoutControls() {
    document.querySelectorAll(".btn-grid[data-grid]").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".btn-grid").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const gridClass = btn.getAttribute("data-grid");
        this.setGridLayout(gridClass);
      });
    });

    const fsBtn = document.getElementById("btnFullscreen");
    if (fsBtn) {
      fsBtn.addEventListener("click", () => {
        if (!document.fullscreenElement) {
          document.documentElement.requestFullscreen();
          fsBtn.classList.add("active");
        } else {
          document.exitFullscreen();
          fsBtn.classList.remove("active");
        }
      });
    }

    const scanlinesBtn = document.getElementById("btnToggleScanlines");
    if (scanlinesBtn) {
      scanlinesBtn.addEventListener("click", () => {
        document.querySelectorAll(".scanline-overlay").forEach(s => {
          s.style.display = s.style.display === "none" ? "block" : "none";
        });
        scanlinesBtn.classList.toggle("active");
        this.showToast("CRT Scanlines Toggled");
      });
    }
  }

  setGridLayout(gridClass) {
    const matrix = document.getElementById("cameraMatrixViewport");
    if (!matrix) return;
    matrix.className = `matrix-viewport ${gridClass}`;
    this.currentGridLayout = gridClass;
  }

  setupModals() {
    // Set switcher modal trigger
    const setBtn = document.getElementById("btnSetSelector");
    const setModal = document.getElementById("setSelectorModal");
    if (setBtn && setModal) {
      setBtn.addEventListener("click", () => {
        this.loadSetsGrid();
        setModal.classList.add("open");
      });
    }

    // Devices & Network modal trigger
    const devBtn = document.getElementById("btnDeviceManager");
    const devModal = document.getElementById("deviceManagerModal");
    if (devBtn && devModal) {
      devBtn.addEventListener("click", () => {
        this.loadDeviceTable();
        devModal.classList.add("open");
      });
    }

    // Modal close buttons
    document.querySelectorAll(".modal-close-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const modal = e.target.closest(".modal-overlay");
        if (modal) modal.classList.remove("open");
      });
    });

    // Close on backdrop click
    document.querySelectorAll(".modal-overlay").forEach(overlay => {
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) overlay.classList.remove("open");
      });
    });
  }

  setupStorageControls() {
    const btnOpen = document.getElementById("btnOpenStorageModal");
    const modal = document.getElementById("storageConfigModal");
    const inputQuota = document.getElementById("inputStorageQuota");
    const btnSave = document.getElementById("btnSaveStorageQuota");
    const usedText = document.getElementById("modalStorageUsedText");

    if (btnOpen && modal) {
      btnOpen.addEventListener("click", async () => {
        try {
          const res = await fetch("/api/storage/status");
          const data = await res.json();
          if (usedText) usedText.textContent = `${data.used_storage_mb} MB (${data.used_percent}%) - ${data.total_segments} Segment`;
          if (inputQuota) inputQuota.value = data.max_storage_mb;
        } catch (e) {}
        modal.classList.add("open");
      });
    }

    const applyQuota = async (newVal) => {
      const quota = parseFloat(newVal);
      if (isNaN(quota) || quota < 10) {
        this.showToast("⚠️ Lütfen en az 10 MB geçerli bir değer girin.");
        return;
      }
      try {
        const res = await fetch("/api/storage/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ max_storage_mb: quota })
        });
        const data = await res.json();
        this.showToast(`💾 NVR Disk Kapasitesi: ${quota} MB olarak güncellendi`);
        if (modal) modal.classList.remove("open");
      } catch (e) {
        this.showToast(`⚠️ Hata: ${e.message}`);
      }
    };

    if (btnSave && inputQuota) {
      btnSave.addEventListener("click", () => applyQuota(inputQuota.value));
    }

    // Preset buttons
    document.querySelectorAll(".btn-storage-preset").forEach(btn => {
      btn.addEventListener("click", () => {
        const q = btn.getAttribute("data-quota");
        if (inputQuota) inputQuota.value = q;
        applyQuota(q);
      });
    });
  }

  setupWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleTelemetry(msg);
      } catch (err) {
        console.warn("WS parse error:", err);
      }
    };

    this.ws.onclose = () => {
      setTimeout(() => this.setupWebSocket(), 3000);
    };
  }

  handleTelemetry(data) {
    // Update hardware ticker
    if (data.hardware) {
      const hw = data.hardware;
      const cpuEl = document.getElementById("telemCpu");
      const ramEl = document.getElementById("telemRam");
      const netEl = document.getElementById("telemNet");
      if (cpuEl) cpuEl.textContent = `${hw.cpu_percent}%`;
      if (ramEl) ramEl.textContent = `${hw.ram_used_gb}/${hw.ram_total_gb} GB`;
      if (netEl) netEl.textContent = `${hw.network.inbound_mbps} Mbps`;
    }

    // Update real storage quota display
    if (data.storage) {
      const st = data.storage;
      const stEl = document.getElementById("telemStorageVal");
      if (stEl) {
        stEl.textContent = `${st.used_storage_mb} MB / ${st.max_storage_mb} MB (${st.used_percent}%)`;
      }
    }

    // Update per-camera VBR bitrates and framerates
    if (data.cameras) {
      for (const [camId, stats] of Object.entries(data.cameras)) {
        const cell = document.querySelector(`.camera-cell[data-cam-id="${camId}"]`);
        if (cell) {
          const brEl = cell.querySelector(".osd-bitrate-val");
          const fpsEl = cell.querySelector(".osd-fps-val");
          if (brEl) brEl.textContent = `${stats.bitrate_kbps.toLocaleString()} kbps`;
          if (fpsEl) fpsEl.textContent = `${stats.fps} FPS`;
        }
      }
    }

    // Handle authentic system/storage event
    if (data.new_event) {
      this.eventHub.pushEvent(data.new_event);
    }
  }

  async loadInitialData() {
    try {
      const res = await fetch("/api/cameras");
      const data = await res.json();
      this.activeSetId = data.set_id;
      this.cameras = data.cameras;

      this.updateActiveSetDisplay();
      this.renderCameraTree();
      this.renderCameraGrid();
      this.timeline.loadTimelineData(this.activeSetId);

      // Load initial events
      const evRes = await fetch("/api/events");
      const evData = await evRes.json();
      if (evData.events) {
        evData.events.forEach(e => this.eventHub.pushEvent(e));
      }

    } catch (err) {
      console.error("Failed to load initial camera data:", err);
    }
  }

  updateActiveSetDisplay() {
    const setTag = document.getElementById("activeSetBadgeText");
    const setSector = document.getElementById("activeSetSector");
    if (setTag) {
      setTag.textContent = `${this.activeSetId.toUpperCase()} (${this.cameras.length} CAMS)`;
    }
    if (setSector && this.cameras[0]) {
      setSector.textContent = this.cameras[0].location.split("/")[0].trim();
    }
  }

  renderCameraTree() {
    const list = document.getElementById("cameraTreeList");
    if (!list) return;
    list.innerHTML = "";

    this.cameras.forEach(cam => {
      const card = document.createElement("div");
      card.className = `camera-tree-card ${cam.id === this.selectedCameraId ? 'active' : ''}`;
      card.dataset.camId = cam.id;

      card.innerHTML = `
        <div class="cam-card-top">
          <span class="cam-card-title">${cam.name}</span>
          <span class="cam-status-dot ${cam.status.toLowerCase()}"></span>
        </div>
        <div class="cam-card-details">
          <span class="cam-ip-badge">${cam.ip_address}</span>
          <span class="cam-res-badge">${cam.resolution}</span>
        </div>
      `;

      card.addEventListener("click", () => {
        this.selectCamera(cam.id);
      });

      list.appendChild(card);
    });
  }

  renderCameraGrid() {
    const matrix = document.getElementById("cameraMatrixViewport");
    if (!matrix) return;

    // Clean up existing players
    this.players.forEach(p => p.destroy());
    this.players.clear();
    matrix.innerHTML = "";

    // Set appropriate default grid based on count
    if (this.cameras.length <= 4) {
      this.setGridLayout("grid-2x2");
    } else if (this.cameras.length <= 6) {
      this.setGridLayout("grid-3x2");
    } else {
      this.setGridLayout("grid-3x3");
    }

    this.cameras.forEach(cam => {
      const cell = document.createElement("div");
      cell.className = `camera-cell ${cam.id === this.selectedCameraId ? 'selected' : ''}`;
      cell.dataset.camId = cam.id;

      // Note: <canvas class="ai-bbox-overlay"></canvas> has been completely removed
      cell.innerHTML = `
        <div class="cam-video-container">
          <video class="cam-video-element" autoplay muted playsinline></video>
          <div class="scanline-overlay"></div>
          
          <div class="cam-loading-spinner">
            <div class="spinner-ring"></div>
            <span>CONNECTING ${cam.id.toUpperCase()}...</span>
          </div>
        </div>

        <!-- CCTV OSD Top -->
        <div class="cctv-osd-top">
          <div class="osd-cam-title">
            <span class="osd-ch-badge">[CH 0${cam.channel}]</span>
            <span>${cam.name}</span>
          </div>
          <div class="osd-live-time">2026-09-24 18:15:00</div>
        </div>

        <!-- CCTV OSD Bottom -->
        <div class="cctv-osd-bottom">
          <div class="osd-rec-badge">
            <span class="rec-dot"></span>
            <span>REC 24/7 (5-FRAME NVR)</span>
          </div>
          <div class="osd-stream-stats">
            <span class="osd-stat-val osd-bitrate-val">2,450 kbps</span>
            <span class="osd-stat-val osd-fps-val">${cam.fps} FPS</span>
            <span>${cam.stream_codec}</span>
          </div>
        </div>

        <!-- Hover Action Toolbar -->
        <div class="cam-action-bar">
          <button class="cam-btn btn-snap" title="Take Snapshot">📸</button>
          <button class="cam-btn btn-rec" title="Record Quick Clip">⏺</button>
          <button class="cam-btn btn-solo" title="Maximize / Solo">⛶</button>
          <button class="cam-btn btn-rtsp" title="Copy RTSP URL for VLC">📋</button>
        </div>
      `;

      // Cell selection
      cell.addEventListener("click", (e) => {
        if (!e.target.closest(".cam-action-bar")) {
          this.selectCamera(cam.id);
        }
      });

      // Quick action buttons
      const snapBtn = cell.querySelector(".btn-snap");
      const recBtn = cell.querySelector(".btn-rec");
      const soloBtn = cell.querySelector(".btn-solo");
      const rtspBtn = cell.querySelector(".btn-rtsp");

      snapBtn.addEventListener("click", () => {
        const p = this.players.get(cam.id);
        if (p) p.takeSnapshot();
      });

      recBtn.addEventListener("click", () => {
        const p = this.players.get(cam.id);
        if (p) p.toggleRecordClip();
      });

      soloBtn.addEventListener("click", () => {
        if (this.currentGridLayout === "grid-1x1") {
          this.setGridLayout(this.cameras.length <= 4 ? "grid-2x2" : "grid-3x2");
        } else {
          this.setGridLayout("grid-1x1");
          this.selectCamera(cam.id);
        }
      });

      rtspBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(cam.rtsp_url);
        this.showToast(`📋 Copied RTSP: ${cam.rtsp_url}`);
      });

      matrix.appendChild(cell);

      // Initialize player
      const player = new CameraPlayer(cam.id, cell, cam);
      this.players.set(cam.id, player);
    });
  }

  selectCamera(camId) {
    this.selectedCameraId = camId;

    // Highlight cell
    document.querySelectorAll(".camera-cell").forEach(cell => {
      cell.classList.toggle("selected", cell.dataset.camId === camId);
    });

    // Highlight tree card
    document.querySelectorAll(".camera-tree-card").forEach(card => {
      card.classList.toggle("active", card.dataset.camId === camId);
    });
  }

  async loadSetsGrid() {
    const grid = document.getElementById("setsGridContainer");
    if (!grid) return;
    grid.innerHTML = "<p>Loading video sets catalog...</p>";

    try {
      const res = await fetch("/api/sets");
      const data = await res.json();
      grid.innerHTML = "";

      data.sets.forEach(setInfo => {
        const card = document.createElement("div");
        card.className = `set-card ${setInfo.id === this.activeSetId ? 'active-set' : ''}`;

        card.innerHTML = `
          <div class="set-card-header">
            <span class="set-card-title">${setInfo.id.toUpperCase()}: ${setInfo.title}</span>
            <div class="set-card-badges">
              <span class="badge-tag badge-cyan">${setInfo.camera_count} CAMS</span>
              <span class="badge-tag badge-purple">${setInfo.resolution_label}</span>
            </div>
          </div>
          <p class="set-card-desc">${setInfo.description}</p>
          <div class="set-card-footer">
            <span>SYNC DURATION: ${setInfo.sync_duration}s</span>
            <button class="btn-activate-set">${setInfo.id === this.activeSetId ? 'ACTIVE' : 'STREAM SET'}</button>
          </div>
        `;

        card.addEventListener("click", () => {
          this.switchSet(setInfo.id);
        });

        grid.appendChild(card);
      });
    } catch (e) {
      grid.innerHTML = `<p>Error loading sets: ${e.message}</p>`;
    }
  }

  async switchSet(newSetId) {
    if (newSetId === this.activeSetId) return;
    this.showToast(`⏳ Hot-swapping to ${newSetId.toUpperCase()}...`);
    document.getElementById("setSelectorModal")?.classList.remove("open");

    try {
      const res = await fetch("/api/sets/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ set_id: newSetId })
      });
      const data = await res.json();
      this.activeSetId = newSetId;
      await this.loadInitialData();
      this.showToast(`✅ Successfully streaming ${newSetId.toUpperCase()}`);
    } catch (e) {
      this.showToast(`⚠️ Failed to switch set: ${e.message}`);
    }
  }

  async loadDeviceTable() {
    const tableBody = document.getElementById("deviceTableBody");
    if (!tableBody) return;
    tableBody.innerHTML = "";

    this.cameras.forEach(cam => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${cam.id.toUpperCase()}</strong></td>
        <td>${cam.name}</td>
        <td><code>${cam.ip_address}</code></td>
        <td><code>${cam.mac_address}</code></td>
        <td><span class="cam-status-dot online"></span> ${cam.status}</td>
        <td><code>${cam.resolution} @ ${cam.fps}fps</code></td>
        <td>
          <button class="btn-copy-rtsp" data-rtsp="${cam.rtsp_url}">COPY RTSP (VLC)</button>
        </td>
      `;

      tr.querySelector(".btn-copy-rtsp").addEventListener("click", () => {
        navigator.clipboard.writeText(cam.rtsp_url);
        this.showToast(`📋 Copied: ${cam.rtsp_url}`);
      });

      tableBody.appendChild(tr);
    });
  }

  showToast(msg) {
    const container = document.getElementById("toastContainer");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => container.removeChild(toast), 300);
    }, 3000);
  }
}

// Start application when DOM is ready
window.addEventListener("DOMContentLoaded", () => {
  window.app = new SurveillanceApp();
});
