/**
 * HOME.JS - AegisVision Surveillance Fleet Controller
 * Handles fleet rendering, flicker-free snapshot updates,
 * multi-NIC ONVIF WS-Discovery scanning, and telemetry.
 */

import {
  fetchSystemStats,
  fetchInterfaces,
  triggerOnvifScan,
  fetchCameras,
  addCamera,
  deleteCamera,
  reconnectCamera,
  updateCamera,
  getSnapshotUrl
} from "./api.js";

// Global State
let registeredCameras = [];
let snapshotTimer = null;
let telemetryTimer = null;
let modalFeedTimer = null;
let currentEditingCam = null;

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  initClock();
  initTelemetry();
  loadFleet();
  initModals();

  // Refresh Button Click
  const refreshBtn = document.getElementById("btn-refresh-fleet");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      loadFleet(true);
    });
  }

  // Radar Scan Button Click
  const scanBtn = document.getElementById("btn-start-scan");
  if (scanBtn) {
    scanBtn.addEventListener("click", startRadarScanFlow);
  }

  // Manual Add Button Click
  const manualAddBtn = document.getElementById("btn-manual-add");
  if (manualAddBtn) {
    manualAddBtn.addEventListener("click", () => {
      openModal("modal-manual-add");
    });
  }

  // Manual Add Form Submit
  const manualForm = document.getElementById("manual-add-form");
  if (manualForm) {
    manualForm.addEventListener("submit", handleManualAddSubmit);
  }

  // Camera Edit & Identify Form Submit ("Uygula")
  const editForm = document.getElementById("camera-edit-form");
  if (editForm) {
    editForm.addEventListener("submit", handleCameraEditSubmit);
  }

  // Camera Edit Quick Chips Click
  const chipsContainer = document.getElementById("edit-camera-desc-chips");
  if (chipsContainer) {
    chipsContainer.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip-btn");
      if (!chip) return;
      const descInput = document.getElementById("edit-camera-desc-input");
      if (descInput) {
        const text = chip.getAttribute("data-desc") || "";
        descInput.value = text;
        descInput.focus();
      }
    });
  }
});

/* --------------------------------------------------------------------------
   Live Clock & System Telemetry
   -------------------------------------------------------------------------- */
function initClock() {
  const clockEl = document.getElementById("nav-clock");
  if (!clockEl) return;
  const update = () => {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString("tr-TR", { hour12: false });
  };
  update();
  setInterval(update, 1000);
}

async function initTelemetry() {
  async function poll() {
    const data = await fetchSystemStats();
    if (!data) return;

    // Triton Server Status
    const tritonBadge = document.getElementById("telemetry-triton-status");
    if (tritonBadge && data.triton) {
      if (data.triton.status === "READY") {
        tritonBadge.className = "status-pill ready";
        tritonBadge.innerHTML = `<span class="status-dot-pulse"></span> READY (${data.triton.models_ready.length} Model)`;
      } else {
        tritonBadge.className = "status-pill offline";
        tritonBadge.innerHTML = `<span class="status-dot-pulse"></span> ÇEVRİMDIŞI`;
      }
    }

    // GPU Telemetry
    if (data.gpu && data.gpu.available) {
      const gpuNameEl = document.getElementById("telemetry-gpu-name");
      const vramTextEl = document.getElementById("telemetry-vram-text");
      const vramFillEl = document.getElementById("telemetry-vram-fill");
      const gpuTempEl = document.getElementById("telemetry-gpu-temp");

      if (gpuNameEl) gpuNameEl.textContent = data.gpu.name;
      if (vramTextEl) {
        vramTextEl.textContent = `${data.gpu.vram_used_mb} / ${data.gpu.vram_total_mb} MB`;
      }
      if (vramFillEl) {
        const pct = Math.min(100, Math.round((data.gpu.vram_used_mb / data.gpu.vram_total_mb) * 100));
        vramFillEl.style.width = `${pct}%`;
      }
      if (gpuTempEl) {
        gpuTempEl.textContent = `${data.gpu.temperature_c}°C (${data.gpu.utilization_gpu_pct}% Yük)`;
      }
    }
  }

  await poll();
  telemetryTimer = setInterval(poll, 4000);
}

/* --------------------------------------------------------------------------
   Fleet Loading & Rendering
   -------------------------------------------------------------------------- */
async function loadFleet(forceFeedback = false) {
  const gridEl = document.getElementById("camera-fleet-grid");
  if (!gridEl) return;

  if (forceFeedback) {
    const refreshBtn = document.getElementById("btn-refresh-fleet");
    if (refreshBtn) refreshBtn.style.transform = "rotate(180deg)";
    setTimeout(() => {
      if (refreshBtn) refreshBtn.style.transform = "none";
    }, 400);
  }

  const res = await fetchCameras();
  registeredCameras = res.cameras || [];

  updateSummaryMetrics(registeredCameras);
  renderFleetGrid(registeredCameras);
  startSnapshotRefreshLoop();
}

function updateSummaryMetrics(cameras) {
  const totalEl = document.getElementById("stat-total-cameras");
  const onlineEl = document.getElementById("stat-online-cameras");
  const profilesEl = document.getElementById("stat-profiles-count");

  const total = cameras.length;
  const online = cameras.filter(c => c.status === "online").length;

  let sCount = 0;
  let tCount = 0;
  cameras.forEach(c => {
    const pro = c.profiles_supported || [];
    if (pro.includes("Profile S")) sCount++;
    if (pro.includes("Profile T")) tCount++;
  });

  if (totalEl) totalEl.textContent = total;
  if (onlineEl) onlineEl.textContent = `${online} / ${total}`;
  if (profilesEl) profilesEl.textContent = `S:${sCount} | T:${tCount}`;
}

function renderFleetGrid(cameras) {
  const gridEl = document.getElementById("camera-fleet-grid");
  if (!gridEl) return;

  if (cameras.length === 0) {
    gridEl.innerHTML = `
      <div class="empty-fleet-container">
        <div class="empty-radar-icon">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5"></path>
            <path d="M8.5 8.5a5 5 0 0 0 7 7"></path>
            <circle cx="12" cy="12" r="1"></circle>
          </svg>
        </div>
        <h2>Sistemde Kayıtlı Kamera Bulunamadı</h2>
        <p>Ağdaki fiziksel ONVIF kameraları (Hikvision, Dahua, Axis vb.) otomatik keşfetmek için radar taramasını başlatın veya doğrudan IP adresi ile ekleyin.</p>
        <div style="display: flex; gap: 12px; margin-top: 8px;">
          <button class="btn-primary" onclick="document.getElementById('btn-start-scan').click()">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10"></path></svg>
            Ağda Kamera Tara (ONVIF WS-Discovery)
          </button>
          <button class="btn-secondary" onclick="document.getElementById('btn-manual-add').click()">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            Manuel Kamera Ekle
          </button>
        </div>
      </div>
    `;
    return;
  }

  gridEl.innerHTML = cameras.map(cam => createCameraCardHTML(cam)).join("");

  // Attach event listeners for each card
  cameras.forEach(cam => {
    // 1. Tıklanabilir Büyüt & Tanıt alanları: Viewport, Açıklama kutusu ve Tanıt Butonu
    const viewportEl = document.getElementById(`viewport-${cam.id}`);
    if (viewportEl) {
      viewportEl.addEventListener("click", () => {
        openCameraEditModal(cam);
      });
    }

    const descSnippetEl = document.getElementById(`desc-snippet-${cam.id}`);
    if (descSnippetEl) {
      descSnippetEl.addEventListener("click", () => {
        openCameraEditModal(cam);
      });
    }

    const editBtn = document.getElementById(`btn-edit-${cam.id}`);
    if (editBtn) {
      editBtn.addEventListener("click", () => {
        openCameraEditModal(cam);
      });
    }

    // Copy RTSP
    const copyBtn = document.getElementById(`btn-copy-${cam.id}`);
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(cam.stream_uri);
        const originalText = copyBtn.innerHTML;
        copyBtn.innerHTML = `✓ Kopyalandı`;
        copyBtn.style.color = "var(--primary)";
        setTimeout(() => {
          copyBtn.innerHTML = originalText;
          copyBtn.style.color = "";
        }, 1500);
      });
    }

    // Reconnect
    const reconBtn = document.getElementById(`btn-recon-${cam.id}`);
    if (reconBtn) {
      reconBtn.addEventListener("click", async () => {
        reconBtn.disabled = true;
        reconBtn.textContent = "Bağlanıyor...";
        await reconnectCamera(cam.id);
        await loadFleet();
      });
    }

    // Details Modal
    const detailBtn = document.getElementById(`btn-detail-${cam.id}`);
    if (detailBtn) {
      detailBtn.addEventListener("click", () => {
        openCameraDetails(cam);
      });
    }

    // Delete
    const delBtn = document.getElementById(`btn-del-${cam.id}`);
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        if (confirm(`'${cam.name}' kamerasını sistemden silmek istediğinize emin misiniz?`)) {
          await deleteCamera(cam.id);
          await loadFleet();
        }
      });
    }
  });
}

function escapeHTML(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function createCameraCardHTML(cam) {
  const statusClass = cam.status === "online" ? "online" : (cam.status === "auth_error" ? "auth_error" : "offline");
  const profiles = cam.profiles_supported || ["Profile S"];
  const profilesBadges = profiles.map(p => {
    let pClass = "profile-s";
    if (p.includes("T")) pClass = "profile-t";
    if (p.includes("G")) pClass = "profile-g";
    return `<span class="profile-tag ${pClass}">${p}</span>`;
  }).join("");

  const descText = cam.description && cam.description.trim() ? cam.description.trim() : "";
  const descSnippetHTML = descText
    ? `<div class="card-desc-snippet" id="desc-snippet-${cam.id}" title="Açıklamayı Düzenlemek / Büyütmek İçin Tıklayın">
         <span class="desc-icon">📝</span>
         <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHTML(descText)}</span>
       </div>`
    : `<div class="card-desc-snippet empty" id="desc-snippet-${cam.id}" title="Açıklama Eklemek / Büyütmek İçin Tıklayın">
         <span class="desc-icon">➕</span>
         <span>Bu kameraya güvenlik amacı / açıklama ekle...</span>
       </div>`;

  return `
    <div class="camera-card" id="card-${cam.id}">
      <div class="card-header">
        <div class="card-title-group" style="cursor: pointer;" onclick="document.getElementById('btn-edit-${cam.id}')?.click()" title="Kamera Bilgilerini Düzenle">
          <span class="status-dot ${statusClass}" title="${cam.status_message || cam.status}"></span>
          <div class="camera-name" title="${cam.name}">${escapeHTML(cam.name)}</div>
        </div>
        <div class="camera-ip-badge">${cam.ip}:${cam.port}</div>
      </div>

      <div class="card-profiles-bar">
        ${profilesBadges}
      </div>

      <div class="camera-viewport" id="viewport-${cam.id}" title="Kamera Canlı Yayınını Büyüt ve Tanıt">
        <img class="camera-snapshot-img" id="snapshot-img-${cam.id}" src="${getSnapshotUrl(cam.id)}" alt="${cam.name}">
        <div class="hud-live-tag">
          <span class="hud-live-dot"></span> CANLI
        </div>
        <div class="hud-specs-tag">${cam.resolution || "1920x1080"} @ ${cam.framerate || 25} FPS</div>
        <div class="hud-codec-tag">${cam.encoding || "H.264"}</div>
        <div class="viewport-expand-overlay">
          <span class="viewport-expand-btn">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line><line x1="11" y1="8" x2="11" y2="14"></line><line x1="8" y1="11" x2="14" y2="11"></line></svg>
            Büyüt & Tanıt
          </span>
        </div>
      </div>

      ${descSnippetHTML}

      <div class="card-stream-row">
        <span class="stream-url-text" title="${cam.stream_uri}">${cam.stream_uri}</span>
        <button class="btn-copy-rtsp" id="btn-copy-${cam.id}" title="RTSP Akış Adresini Kopyala">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          Kopyala
        </button>
      </div>

      <div class="card-footer">
        <div class="card-footer-actions">
          <button class="btn-card-action" id="btn-edit-${cam.id}" title="Kamera Tanıtımı & Açıklama Ekle" style="color: var(--primary); border-color: rgba(255, 133, 51, 0.4);">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
            Tanıt & Açıklama
          </button>
          <button class="btn-card-action" id="btn-recon-${cam.id}" title="Yeniden Bağlan">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
            Yenile
          </button>
          <button class="btn-card-action" id="btn-detail-${cam.id}" title="Donanım Detayları">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
            Detay
          </button>
        </div>
        <button class="btn-card-delete" id="btn-del-${cam.id}" title="Kamerayı Kaldır">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>
      </div>
    </div>
  `;
}

/* --------------------------------------------------------------------------
   Flicker-Free Live Snapshot Refresh Loop
   -------------------------------------------------------------------------- */
const inFlightSnapshots = new Set();

function startSnapshotRefreshLoop() {
  if (snapshotTimer) clearInterval(snapshotTimer);

  snapshotTimer = setInterval(() => {
    registeredCameras.forEach(cam => {
      // Avoid stacking requests if previous snapshot is still in-flight
      if (inFlightSnapshots.has(cam.id)) return;

      const imgEl = document.getElementById(`snapshot-img-${cam.id}`);
      if (!imgEl) return;

      inFlightSnapshots.add(cam.id);
      const nextUrl = getSnapshotUrl(cam.id);
      const preloader = new Image();

      let finished = false;
      const finish = () => {
        if (!finished) {
          finished = true;
          inFlightSnapshots.delete(cam.id);
        }
      };

      const safetyTimer = setTimeout(finish, 3000);

      preloader.onload = () => {
        clearTimeout(safetyTimer);
        imgEl.src = nextUrl;
        finish();
      };
      preloader.onerror = () => {
        clearTimeout(safetyTimer);
        finish();
      };
      preloader.src = nextUrl;
    });
  }, 1800);
}

/* --------------------------------------------------------------------------
   Radar Scan Modal (ONVIF WS-Discovery)
   -------------------------------------------------------------------------- */
async function startRadarScanFlow() {
  openModal("modal-radar-scan");

  const statusTitle = document.getElementById("radar-status-title");
  const statusDesc = document.getElementById("radar-status-desc");
  const listEl = document.getElementById("discovered-cameras-container");

  if (statusTitle) statusTitle.textContent = "Ağ Arayüzleri Taranıyor...";
  if (statusDesc) statusDesc.textContent = "Sistemdeki aktif fiziksel ağ kartları belirleniyor...";
  if (listEl) listEl.innerHTML = "";

  // 1. Fetch interfaces
  const ifData = await fetchInterfaces();
  const ifList = (ifData.interfaces || []).map(i => `${i.name} (${i.ip})`).join(", ");
  if (statusDesc) {
    statusDesc.textContent = ifList ? `Ağ Kartları: ${ifList}. UDP Multicast (239.255.255.250:3702) probe basılıyor...` : "Varsayılan arayüz taranıyor...";
  }

  // 2. Trigger Scan
  const scanResult = await triggerOnvifScan(2.5);
  const devices = scanResult.devices || [];

  if (statusTitle) {
    statusTitle.textContent = devices.length > 0 ? `${devices.length} ONVIF Kamera Keşfedildi!` : "Tarama Tamamlandı";
  }
  if (statusDesc) {
    statusDesc.textContent = devices.length > 0 ? "Aşağıdaki cihazları tek tıkla veya topluca sisteme dahil edebilirsiniz." : "Ağda yeni bir ONVIF kamera yanıt vermedi. Kamera açık ve aynı alt ağda mı?";
  }

  if (listEl) {
    if (devices.length === 0) {
      listEl.innerHTML = `<div style="text-align: center; color: var(--text-dim); padding: 20px;">Ağda yanıt veren ONVIF cihaz bulunamadı. Cihazınızı 'Manuel Kamera Ekle' ile de ekleyebilirsiniz.</div>`;
    } else {
      // Check already registered IPs and ports
      const registeredKeys = new Set(registeredCameras.map(c => `${c.ip}:${c.port}`));

      const headerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding: 10px 14px; background: rgba(255, 133, 51, 0.08); border-radius: var(--radius-sm); border: 1px solid rgba(255, 133, 51, 0.2);">
          <span style="font-size: 0.85rem; color: var(--text-main); font-weight: 500;">
            Bulunan Cihazlar (${devices.length})
          </span>
          <button class="btn-primary" style="padding: 6px 14px; font-size: 0.8rem;" id="btn-import-all">
            ⚡ Tümünü Sisteme Dahil Et
          </button>
        </div>
      `;

      const itemsHTML = devices.map((dev, idx) => {
        const isRegistered = registeredKeys.has(`${dev.ip}:${dev.port}`);
        return `
          <div class="discovered-item" id="disc-item-${idx}">
            <div class="discovered-info">
              <h5>${dev.name || dev.hardware || 'ONVIF IP Kamera'}</h5>
              <p>IP: <strong>${dev.ip}:${dev.port}</strong> | Arayüz: ${dev.discovered_via || 'eth'} | Profiller: ${(dev.profiles || ['Profile S']).join(', ')}</p>
            </div>
            ${isRegistered ? `
              <span class="status-pill ready" style="padding: 6px 12px; font-size: 0.78rem;">
                ✓ Kayıtlı
              </span>
            ` : `
              <button class="btn-primary" style="padding: 6px 14px; font-size: 0.8rem;" id="btn-import-${idx}">
                + Sisteme Dahil Et
              </button>
            `}
          </div>
        `;
      }).join("");

      listEl.innerHTML = headerHTML + itemsHTML;

      // Import All Button
      const importAllBtn = document.getElementById("btn-import-all");
      if (importAllBtn) {
        importAllBtn.addEventListener("click", async () => {
          importAllBtn.disabled = true;
          importAllBtn.textContent = "Tümü Ekleniyor...";
          const unregDevices = devices.filter(d => !registeredKeys.has(`${d.ip}:${d.port}`));
          for (const dev of unregDevices) {
            try {
              await addCamera({
                ip: dev.ip,
                port: dev.port,
                username: "admin",
                password: "admin123",
                name: dev.name
              });
            } catch (err) {
              console.error("Camera import error:", err);
            }
          }
          importAllBtn.textContent = "✓ Tamamı Eklendi";
          importAllBtn.style.background = "var(--status-online)";
          await loadFleet();
        });
      }

      // Attach individual import buttons
      devices.forEach((dev, idx) => {
        const importBtn = document.getElementById(`btn-import-${idx}`);
        if (importBtn) {
          importBtn.addEventListener("click", async () => {
            importBtn.disabled = true;
            importBtn.textContent = "Kaydediliyor...";
            try {
              await addCamera({
                ip: dev.ip,
                port: dev.port,
                username: "admin",
                password: "admin123",
                name: dev.name
              });
              importBtn.textContent = "✓ Eklendi";
              importBtn.style.background = "var(--status-online)";
              await loadFleet();
            } catch (err) {
              importBtn.textContent = "Hata";
            }
          });
        }
      });
    }
  }
}

/* --------------------------------------------------------------------------
   Manual Camera Add Submission
   -------------------------------------------------------------------------- */
async function handleManualAddSubmit(e) {
  e.preventDefault();
  const form = e.target;
  const submitBtn = document.getElementById("btn-manual-submit");

  const ip = document.getElementById("manual-ip").value.trim();
  const port = parseInt(document.getElementById("manual-port").value, 10) || 80;
  const rtspPort = parseInt(document.getElementById("manual-rtsp-port").value, 10) || 554;
  const username = document.getElementById("manual-username").value.trim();
  const password = document.getElementById("manual-password").value;
  const name = document.getElementById("manual-name").value.trim();

  if (!ip) {
    alert("Lütfen geçerli bir IP adresi girin.");
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "ONVIF El Sıkışması Yapılıyor...";
  }

  try {
    const res = await addCamera({
      ip,
      port,
      rtsp_port: rtspPort,
      username,
      password,
      name
    });

    closeModal("modal-manual-add");
    form.reset();
    await loadFleet();
  } catch (err) {
    alert(`Kamera eklenirken bir hata oluştu: ${err.message}`);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Bağlantıyı Doğrula & Sisteme Ekle";
    }
  }
}

/* --------------------------------------------------------------------------
   Camera Details Modal
   -------------------------------------------------------------------------- */
function openCameraDetails(cam) {
  const container = document.getElementById("camera-details-content");
  if (!container) return;

  container.innerHTML = `
    <table style="width: 100%; border-collapse: collapse; font-size: 0.88rem;">
      <tr style="border-bottom: 1px solid var(--border-subtle);"><td style="padding: 8px; color: var(--text-muted);">Cihaz Adı</td><td style="padding: 8px; font-weight: 600;">${cam.name}</td></tr>
      <tr style="border-bottom: 1px solid var(--border-subtle);"><td style="padding: 8px; color: var(--text-muted);">Üretici / Model</td><td style="padding: 8px;">${cam.manufacturer || 'Generic'} - ${cam.model || 'IP Cam'}</td></tr>
      <tr style="border-bottom: 1px solid var(--border-subtle);"><td style="padding: 8px; color: var(--text-muted);">IP & Port</td><td style="padding: 8px; font-family: monospace;">${cam.ip}:${cam.port} (RTSP: ${cam.rtsp_port})</td></tr>
      <tr style="border-bottom: 1px solid var(--border-subtle);"><td style="padding: 8px; color: var(--text-muted);">Firmware Versiyonu</td><td style="padding: 8px; font-family: monospace;">${cam.firmware_version || 'N/A'}</td></tr>
      <tr style="border-bottom: 1px solid var(--border-subtle);"><td style="padding: 8px; color: var(--text-muted);">Seri Numarası</td><td style="padding: 8px; font-family: monospace;">${cam.serial_number || 'N/A'}</td></tr>
      <tr style="border-bottom: 1px solid var(--border-subtle);"><td style="padding: 8px; color: var(--text-muted);">Çözünürlük & FPS</td><td style="padding: 8px;">${cam.resolution} @ ${cam.framerate} FPS (${cam.encoding})</td></tr>
      <tr style="border-bottom: 1px solid var(--border-subtle);"><td style="padding: 8px; color: var(--text-muted);">Desteklenen Profiller</td><td style="padding: 8px;">${(cam.profiles_supported || []).join(", ")}</td></tr>
      <tr style="border-bottom: 1px solid var(--border-subtle);"><td style="padding: 8px; color: var(--text-muted);">RTSP Canlı Akış URI</td><td style="padding: 8px; font-family: monospace; word-break: break-all; color: var(--primary);">${cam.stream_uri}</td></tr>
      <tr><td style="padding: 8px; color: var(--text-muted);">Durum Mesajı</td><td style="padding: 8px;">${cam.status_message}</td></tr>
    </table>
  `;

  openModal("modal-camera-details");
}

/* --------------------------------------------------------------------------
   Camera Identify & Enlarged Live Feed Modal
   -------------------------------------------------------------------------- */
function openCameraEditModal(cam) {
  currentEditingCam = cam;

  const titleEl = document.getElementById("edit-camera-modal-title");
  const idInput = document.getElementById("edit-camera-id");
  const nameInput = document.getElementById("edit-camera-name-input");
  const descInput = document.getElementById("edit-camera-desc-input");
  const specsEl = document.getElementById("edit-camera-hud-specs");
  const codecEl = document.getElementById("edit-camera-hud-codec");
  const rtspEl = document.getElementById("edit-camera-hud-rtsp");
  const ipPortEl = document.getElementById("edit-camera-ip-port");
  const statusPill = document.getElementById("edit-camera-status-pill");
  const largeFeedImg = document.getElementById("edit-camera-large-feed");

  if (titleEl) titleEl.textContent = `${cam.name} - Tanıtım & Canlı İzleme`;
  if (idInput) idInput.value = cam.id;
  if (nameInput) nameInput.value = cam.name || "";
  if (descInput) descInput.value = cam.description || "";
  if (specsEl) specsEl.textContent = `${cam.resolution || "1920x1080"} @ ${cam.framerate || 25} FPS`;
  if (codecEl) codecEl.textContent = cam.encoding || "H.264";
  if (rtspEl) {
    rtspEl.textContent = cam.stream_uri;
    rtspEl.title = cam.stream_uri;
  }
  if (ipPortEl) ipPortEl.textContent = `IP: ${cam.ip}:${cam.port}`;

  if (statusPill) {
    const isOnline = cam.status === "online";
    statusPill.className = isOnline ? "status-pill ready" : "status-pill offline";
    statusPill.innerHTML = `<span class="status-dot-pulse"></span> ${isOnline ? "BAĞLANTI AKTİF" : "ÇEVRİMDIŞI"}`;
  }

  // İlk görüntüyü anında bas
  if (largeFeedImg) {
    largeFeedImg.src = getSnapshotUrl(cam.id);
  }

  // Büyütülmüş canlı akış timer'ı: modal açıkken akıcı görüntü tazeleme
  if (modalFeedTimer) clearInterval(modalFeedTimer);
  let inFlightModalSnap = false;

  modalFeedTimer = setInterval(() => {
    const modalEl = document.getElementById("modal-camera-edit");
    if (!modalEl || !modalEl.classList.contains("open")) {
      clearInterval(modalFeedTimer);
      modalFeedTimer = null;
      return;
    }

    if (inFlightModalSnap || !largeFeedImg) return;
    inFlightModalSnap = true;

    const snapTimer = setTimeout(() => {
      inFlightModalSnap = false;
    }, 2000);

    const nextUrl = getSnapshotUrl(cam.id);
    const preloader = new Image();
    preloader.onload = () => {
      clearTimeout(snapTimer);
      largeFeedImg.src = nextUrl;
      inFlightModalSnap = false;
    };
    preloader.onerror = () => {
      clearTimeout(snapTimer);
      inFlightModalSnap = false;
    };
    preloader.src = nextUrl;
  }, 800);

  openModal("modal-camera-edit");
  if (nameInput) setTimeout(() => nameInput.focus(), 150);
}

async function handleCameraEditSubmit(e) {
  e.preventDefault();
  const idInput = document.getElementById("edit-camera-id");
  const nameInput = document.getElementById("edit-camera-name-input");
  const descInput = document.getElementById("edit-camera-desc-input");
  const submitBtn = document.getElementById("btn-save-camera-edit");

  const camId = idInput ? idInput.value : "";
  const name = nameInput ? nameInput.value.trim() : "";
  const description = descInput ? descInput.value.trim() : "";

  if (!camId) return;

  const originalBtnHTML = submitBtn ? submitBtn.innerHTML : "";
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="animation: spin 1s linear infinite;">
        <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
        <path d="M12 2a10 10 0 0 1 10 10"></path>
      </svg>
      Kaydediliyor...
    `;
  }

  try {
    await updateCamera(camId, { name, description });
    closeModal("modal-camera-edit");
    await loadFleet();
  } catch (err) {
    alert(`Kamera bilgileri kaydedilirken hata oluştu: ${err.message}`);
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalBtnHTML;
    }
  }
}

/* --------------------------------------------------------------------------
   Modal Helpers
   -------------------------------------------------------------------------- */
function initModals() {
  document.querySelectorAll("[data-close-modal]").forEach(btn => {
    btn.addEventListener("click", () => {
      const modalId = btn.getAttribute("data-close-modal");
      closeModal(modalId);
    });
  });

  // Close when clicking overlay
  document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) {
        closeModal(overlay.id);
      }
    });
  });
}

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("open");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("open");
  if (id === "modal-camera-edit" && modalFeedTimer) {
    clearInterval(modalFeedTimer);
    modalFeedTimer = null;
  }
}
