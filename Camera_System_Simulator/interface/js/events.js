/**
 * AEGIS-PRO Real-Time AI Event Hub & Audio Alarm Chime
 * Synthesizes authentic CCTV security room beeps via Web Audio API,
 * manages the live event ticker, and highlights triggered camera cells.
 */

class EventHub {
  constructor(app) {
    this.app = app;
    this.events = [];
    this.isMuted = false;
    this.audioCtx = null;
    this.initAudio();
    this.setupListeners();
  }

  initAudio() {
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      this.audioCtx = new AudioContext();
    } catch (e) {
      console.warn("Web Audio not available:", e);
    }
  }

  playAlarmBeep(severity = "warning") {
    if (this.isMuted || !this.audioCtx) return;

    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }

    try {
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();

      osc.type = severity === "danger" ? "sawtooth" : "sine";
      // Danger = high pitch alternating beep (1200Hz), Warning = 800Hz
      const freq = severity === "danger" ? 1280 : 880;
      osc.frequency.setValueAtTime(freq, this.audioCtx.currentTime);

      gain.gain.setValueAtTime(0.08, this.audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + 0.35);

      osc.connect(gain);
      gain.connect(this.audioCtx.destination);

      osc.start();
      osc.stop(this.audioCtx.currentTime + 0.35);
    } catch (e) {
      // Audio error ignored
    }
  }

  setupListeners() {
    const muteBtn = document.getElementById("btnMuteAudio");
    if (muteBtn) {
      muteBtn.addEventListener("click", () => {
        this.isMuted = !this.isMuted;
        muteBtn.classList.toggle("active", this.isMuted);
        muteBtn.innerHTML = this.isMuted ? "🔇" : "🔔";
        this.app.showToast(this.isMuted ? "🔇 Alarm Audio Muted" : "🔔 Alarm Audio Active");
      });
    }
  }

  pushEvent(eventData) {
    if (!eventData) return;
    this.events.unshift(eventData);
    if (this.events.length > 40) this.events.pop();

    this.renderEventList();

    // Sound alert
    if (eventData.severity === "danger" || eventData.severity === "warning") {
      this.playAlarmBeep(eventData.severity);
      this.flashCameraCell(eventData.camera_id);
    }
  }

  flashCameraCell(camId) {
    const cell = document.querySelector(`.camera-cell[data-cam-id="${camId}"]`);
    if (cell) {
      cell.classList.add("alarm-flash");
      setTimeout(() => cell.classList.remove("alarm-flash"), 3500);
    }
  }

  renderEventList() {
    const listEl = document.getElementById("eventListContainer");
    if (!listEl) return;
    listEl.innerHTML = "";

    this.events.forEach((ev) => {
      const card = document.createElement("div");
      card.className = `event-card severity-${ev.severity}`;
      card.dataset.camId = ev.camera_id;

      card.innerHTML = `
        <div class="ev-top">
          <span class="ev-label">${ev.label}</span>
          <span class="ev-time">${ev.time_str}</span>
        </div>
        <div class="ev-bottom">
          <span class="ev-cam-tag">${ev.camera_name ? ev.camera_name.split('-')[0].trim() : ev.camera_id.toUpperCase()}</span>
          <span class="ev-conf-tag">CONF: ${Math.round((ev.confidence || 0.9) * 100)}%</span>
        </div>
      `;

      card.addEventListener("click", () => {
        this.app.selectCamera(ev.camera_id);
        this.app.showToast(`🎯 Focused on ${ev.camera_name || ev.camera_id}`);
      });

      listEl.appendChild(card);
    });

    const badge = document.getElementById("alarmCountBadge");
    if (badge) {
      const dangerCount = this.events.filter(e => e.severity === "danger").length;
      badge.textContent = `${dangerCount} ALERTS`;
      badge.style.display = dangerCount > 0 ? "inline-block" : "none";
    }
  }
}

window.EventHub = EventHub;
