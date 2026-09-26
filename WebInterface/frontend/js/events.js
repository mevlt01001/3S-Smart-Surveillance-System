/**
 * AegisVision Incident & Escalation Center Module (events.js)
 * Manages active violations, assignees, escalation countdowns, and resolution verification loop.
 */

let incidents = [];
let currentFilter = "all"; // all, active, resolved
let timerInterval = null;

export async function initEventsModule() {
  setupEventsToolbar();
  await loadIncidents();
  startEscalationClock();
}

function setupEventsToolbar() {
  const btnAll = document.getElementById("btn-events-all");
  const btnActive = document.getElementById("btn-events-active");
  const btnResolved = document.getElementById("btn-events-resolved");
  const btnSimulate = document.getElementById("btn-simulate-incident");

  const tabBtns = [btnAll, btnActive, btnResolved];

  function setActiveTab(filter, btn) {
    currentFilter = filter;
    tabBtns.forEach(b => b?.classList.remove("active"));
    btn?.classList.add("active");
    renderIncidentsGrid();
  }

  btnAll?.addEventListener("click", () => setActiveTab("all", btnAll));
  btnActive?.addEventListener("click", () => setActiveTab("active", btnActive));
  btnResolved?.addEventListener("click", () => setActiveTab("resolved", btnResolved));

  btnSimulate?.addEventListener("click", async () => {
    btnSimulate.disabled = true;
    btnSimulate.textContent = "Simüle Ediliyor...";
    try {
      const res = await fetch("/api/events/simulate", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        await loadIncidents();
      }
    } catch (e) {
      alert("Simülasyon başlatılamadı: " + e.message);
    } finally {
      btnSimulate.disabled = false;
      btnSimulate.textContent = "⚡ Yeni İhlal Simülasyonu";
    }
  });
}

async function loadIncidents() {
  try {
    const res = await fetch("/api/events");
    const data = await res.json();
    incidents = data.events || [];
    updateMetrics();
    renderIncidentsGrid();
  } catch (e) {
    console.error("[Events] Load failed:", e);
  }
}

function updateMetrics() {
  const activeCount = incidents.filter(i => i.status === "active").length;
  const escalatedCount = incidents.filter(i => i.status === "escalated").length;
  const resolvedCount = incidents.filter(i => i.status === "resolved").length;

  const mActive = document.getElementById("metric-active-count");
  const mEscalated = document.getElementById("metric-escalated-count");
  const mResolved = document.getElementById("metric-resolved-count");
  const mTotal = document.getElementById("metric-total-count");

  if (mActive) mActive.textContent = activeCount;
  if (mEscalated) mEscalated.textContent = escalatedCount;
  if (mResolved) mResolved.textContent = resolvedCount;
  if (mTotal) mTotal.textContent = incidents.length;
}

function renderIncidentsGrid() {
  const container = document.getElementById("events-grid-container");
  if (!container) return;

  const filtered = incidents.filter(i => {
    if (currentFilter === "active") return i.status === "active" || i.status === "escalated";
    if (currentFilter === "resolved") return i.status === "resolved";
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; padding: 48px; text-align: center; color: var(--text-dim); background: var(--bg-card); border-radius: var(--radius-lg); border: 1px solid var(--border-card);">
        Bu filtrede gösterilecek olay bulunmuyor.
      </div>
    `;
    return;
  }

  container.innerHTML = filtered.map(evt => {
    const isResolved = evt.status === "resolved";
    const isEscalated = evt.status === "escalated";
    const sevLabel = evt.severity === "critical" ? "🚨 KRİTİK İHLAL" : "⚠️ İSG UYARISI";

    const assignee = evt.assignee || { name: "Saha Şefi", role: "Güvenlik Sorumlusu", phone: "Dahili 104" };
    const escalation = evt.escalation || { supervisor_name: "İSG Müdürü", timeout_minutes: 5 };

    const elapsedMin = Math.floor((Date.now() / 1000 - evt.created_at) / 60);
    const timeoutMin = escalation.timeout_minutes || 5;
    const remainingMin = Math.max(0, timeoutMin - elapsedMin);

    let escalationBadge = "";
    if (isResolved) {
      escalationBadge = `<span class="severity-badge" style="background: rgba(16, 185, 129, 0.15); color: #34D399; border-color: rgba(16, 185, 129, 0.4);">✅ ÇÖZÜLDÜ</span>`;
    } else if (isEscalated || remainingMin <= 0) {
      escalationBadge = `<span class="escalation-timer-badge escalated">⚠️ AMİRE ESKALASYON İLETİLDİ</span>`;
    } else {
      escalationBadge = `<span class="escalation-timer-badge">⏳ Eskalasyona ${remainingMin} dk</span>`;
    }

    return `
      <div class="incident-card ${evt.severity} ${evt.status}" id="incident-card-${evt.id}">
        <div class="incident-header">
          <div class="incident-title-box">
            <span class="incident-type-tag">
              <span class="status-dot-pulse" style="background: ${isResolved ? '#10B981' : '#EF4444'};"></span>
              ${evt.violation_type || 'Kural İhlali'}
            </span>
            <span class="incident-camera-zone">
              📹 ${evt.camera_name || 'Kamera'} &bull; 📍 ${evt.zone_name || 'Bölge'}
            </span>
          </div>
          <div>
            ${escalationBadge}
          </div>
        </div>

        <div class="incident-body">
          <div class="incident-media-preview">
            <img class="incident-snapshot-img" src="${evt.snapshot_url || '/api/cameras/' + evt.camera_id + '/snapshot'}?t=${evt.created_at}" alt="İhlal Snapshot">
            <span class="incident-snapshot-badge">📸 AI Snapshot</span>
          </div>

          <p style="font-size: 0.8rem; color: var(--text-secondary); line-height: 1.4; margin: 0;">
            ${evt.description || 'Alana ilişkin kural ihlali tespit edildi.'}
          </p>

          <!-- Sorumlu & Eskalasyon Strip -->
          <div class="incident-assignee-box">
            <div class="assignee-info-col">
              <span class="assignee-info-label">1. Derece Sorumlu</span>
              <span class="assignee-info-val">${assignee.name}</span>
              <span class="assignee-info-sub">${assignee.role} &bull; ${assignee.phone || ''}</span>
            </div>
            <div class="assignee-info-col">
              <span class="assignee-info-label">2. Derece Eskalasyon</span>
              <span class="assignee-info-val">${escalation.supervisor_name}</span>
              <span class="assignee-info-sub">Süre Sınırı: ${timeoutMin} dk</span>
            </div>
          </div>
        </div>

        <div class="incident-footer">
          <div class="incident-time-ago">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
            <span>${elapsedMin} dakika önce</span>
          </div>

          <div style="display: flex; gap: 8px;">
            ${!isResolved ? `
              <button type="button" class="btn-resolve-verify" data-resolve-id="${evt.id}">
                🔍 Olayı Çözüldü İşaretle
              </button>
            ` : `
              <span style="font-size: 0.76rem; color: #34D399; font-weight: 600;">Arşivlendi</span>
            `}
          </div>
        </div>
      </div>
    `;
  }).join("");

  // Attach resolve verification handlers
  document.querySelectorAll("[data-resolve-id]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const eventId = btn.getAttribute("data-resolve-id");
      await handleAttemptResolve(eventId, btn);
    });
  });
}

async function handleAttemptResolve(eventId, btn, forceOverride = false) {
  btn.disabled = true;
  btn.textContent = "AI Doğruluyor...";

  try {
    const res = await fetch(`/api/events/${eventId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator_name: "Nöbetçi İSG Operatörü",
        force_override: forceOverride,
        note: forceOverride ? "Yetkili amir kontrolü ile manuel kapatıldı." : "Saha denetimi yapıldı."
      })
    });
    const result = await res.json();

    if (!result.can_resolve && !forceOverride) {
      // Verification Failed! Show the user the exact system rejection logic!
      const userChoice = confirm(
        `${result.message}\n\n` +
        `--------------------------------------------------\n` +
        `Yapay zeka sahadaki ihlalin devam ettiğini tespit ettiği için olay otomatik olarak kapatılmadı.\n\n` +
        `Sorumlu amir olarak sahayı bizzat incelediyseniz ve YETKİLİ ONAYIYLA kapatmak istiyorsanız [Tamam]'a tıklayabilirsiniz.`
      );
      if (userChoice) {
        await handleAttemptResolve(eventId, btn, true);
        return;
      }
    } else {
      alert(result.message || "Olay başarıyla çözüldü.");
      await loadIncidents();
    }
  } catch (e) {
    alert("Hata oluştu: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "🔍 Olayı Çözüldü İşaretle";
  }
}

function startEscalationClock() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    // Refresh incidents periodically to update countdown timers and auto-escalations
    loadIncidents();
  }, 10000);
}
