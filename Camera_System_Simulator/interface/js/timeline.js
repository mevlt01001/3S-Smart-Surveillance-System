/**
 * AEGIS-PRO Real Synchronized NVR Playback Timeline
 * Controls multi-channel playback directly from local NVR storage (200MB ring-buffer)
 * with buttery smooth 30/60 fps hardware decoding and "🔴 CANLIYA GEÇ (GO LIVE)" instant return.
 */

class PlaybackTimeline {
  constructor(app) {
    this.app = app;
    this.duration = 60.0;
    this.currentTime = 0.0;
    this.isLive = true;
    this.isPlaying = false;
    this.playbackRate = 1.0;
    this.playTimer = null;
    this.timelineData = null;

    this.needleEl = null;
    this.viewportEl = null;
    this.clockEl = null;
    this.modeEl = null;

    this.init();
  }

  init() {
    this.needleEl = document.getElementById("playheadNeedle");
    this.viewportEl = document.getElementById("timelineTracksViewport");
    this.clockEl = document.getElementById("timelineClockDisplay");
    this.modeEl = document.getElementById("timelineModeIndicator");

    this.setupTransportControls();
    this.setupNeedleInteraction();

    // Poll timeline data periodically to reflect newly recorded 5-frame segments
    setInterval(() => {
      if (this.isLive) {
        this.refreshTimelineData();
      }
    }, 2000);
  }

  async loadTimelineData(setId) {
    await this.refreshTimelineData();
  }

  async refreshTimelineData() {
    try {
      const res = await fetch(`/api/playback/timeline?set_id=${this.app.activeSetId}`);
      const data = await res.json();
      this.timelineData = data;
      this.duration = Math.max(data.duration || 10.0, 5.0);

      this.renderTracks();
      if (this.isLive) {
        this.currentTime = this.duration;
        this.updateNeedle();
      }
    } catch (e) {
      console.warn("Failed to load playback timeline:", e);
    }
  }

  renderTracks() {
    if (!this.timelineData || !this.viewportEl) return;
    const tracksContainer = document.getElementById("tracksContainer");
    if (!tracksContainer) return;
    tracksContainer.innerHTML = "";

    this.timelineData.timeline.forEach((item) => {
      const row = document.createElement("div");
      row.className = "channel-track-row";

      const label = document.createElement("div");
      label.className = "track-label";
      label.textContent = item.camera_name.split("-")[0].trim();
      label.title = `${item.camera_name} (${item.segment_count} segment)`;

      const lane = document.createElement("div");
      lane.className = "track-lane";
      lane.dataset.camId = item.camera_id;

      // Render genuine recorded segment block
      item.segments.forEach((seg) => {
        const segEl = document.createElement("div");
        segEl.className = "track-segment";
        const leftPct = (seg.start / this.duration) * 100;
        const widthPct = Math.max(((seg.end - seg.start) / this.duration) * 100, 2.0);
        segEl.style.left = `${leftPct}%`;
        segEl.style.width = `${widthPct}%`;
        segEl.style.backgroundColor = seg.color;
        segEl.title = `${seg.label} (0.0s - ${seg.end}s)`;
        lane.appendChild(segEl);
      });

      // Clicking on lane seeks to that position on disk
      lane.addEventListener("click", (e) => {
        const rect = lane.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const pct = Math.max(0, Math.min(1, clickX / rect.width));
        this.enterPlaybackMode(pct * this.duration);
      });

      row.appendChild(label);
      row.appendChild(lane);
      tracksContainer.appendChild(row);
    });
  }

  setupNeedleInteraction() {
    if (!this.viewportEl) return;

    let isDragging = false;
    this.viewportEl.addEventListener("mousedown", (e) => {
      if (e.target.closest(".track-lane") || e.target === this.viewportEl) {
        isDragging = true;
      }
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const lane = this.viewportEl.querySelector(".track-lane");
      if (!lane) return;
      const rect = lane.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const pct = Math.max(0, Math.min(1, clickX / rect.width));
      this.seekTo(pct * this.duration);
    });

    window.addEventListener("mouseup", () => {
      isDragging = false;
    });
  }

  setupTransportControls() {
    const btnGoLive = document.getElementById("btnGoLive");
    const playBtn = document.getElementById("btnPbPlay");
    const pauseBtn = document.getElementById("btnPbPause");
    const stepBtn = document.getElementById("btnPbStep");
    const speedBtn = document.getElementById("btnPbSpeed");

    if (btnGoLive) {
      btnGoLive.addEventListener("click", () => this.goLive());
    }

    if (playBtn) {
      playBtn.addEventListener("click", () => {
        if (this.isLive) {
          this.enterPlaybackMode(Math.max(0, this.duration - 10.0));
        }
        this.play();
      });
    }

    if (pauseBtn) {
      pauseBtn.addEventListener("click", () => {
        if (this.isLive) {
          this.enterPlaybackMode(Math.max(0, this.duration - 5.0));
        }
        this.pause();
      });
    }

    if (stepBtn) {
      stepBtn.addEventListener("click", () => {
        if (this.isLive) {
          this.enterPlaybackMode(Math.max(0, this.duration - 5.0));
        }
        this.step();
      });
    }

    if (speedBtn) {
      speedBtn.addEventListener("click", () => {
        const speeds = [1.0, 2.0, 4.0, 8.0];
        const nextIdx = (speeds.indexOf(this.playbackRate) + 1) % speeds.length;
        this.playbackRate = speeds[nextIdx];
        speedBtn.textContent = `${this.playbackRate}x`;
        this.app.players.forEach(p => p.setPlaybackRate(this.playbackRate));
        this.app.showToast(`⏩ Oynatma Hızı: ${this.playbackRate}x`);
      });
    }
  }

  enterPlaybackMode(offsetSec = 0) {
    this.isLive = false;
    const btnGoLive = document.getElementById("btnGoLive");
    if (btnGoLive) btnGoLive.classList.remove("active");

    if (this.modeEl) {
      this.modeEl.textContent = "KAYIT OYNATMA (YEREL DİSK 5-FRAME)";
      this.modeEl.style.color = "var(--primary-cyan)";
    }

    const liveBadge = document.getElementById("channelLiveBadge");
    if (liveBadge) {
      liveBadge.textContent = "⏺ REC PLAYBACK";
      liveBadge.style.color = "var(--primary-cyan)";
    }

    this.currentTime = Math.max(0, Math.min(offsetSec, this.duration));
    this.app.players.forEach(p => p.enterPlaybackMode(this.currentTime));

    this.updateNeedle();
    this.updateClock();
  }

  goLive() {
    this.isLive = true;
    this.pause();

    const btnGoLive = document.getElementById("btnGoLive");
    if (btnGoLive) btnGoLive.classList.add("active");

    if (this.modeEl) {
      this.modeEl.textContent = "CANLI YAYIN MODU";
      this.modeEl.style.color = "#fff";
    }

    const liveBadge = document.getElementById("channelLiveBadge");
    if (liveBadge) {
      liveBadge.textContent = "● LIVE";
      liveBadge.style.color = "var(--accent-emerald)";
    }

    if (this.clockEl) {
      this.clockEl.textContent = "CANLI YAYIN (0.0s gecikme)";
    }

    // Reconnect all camera players to live stream
    this.app.players.forEach(p => p.returnToLive());

    this.currentTime = this.duration;
    this.updateNeedle();

    this.app.showToast("🔴 Canlı RTSP/WebRTC yayınına dönüldü");
  }

  play() {
    if (this.isLive) {
      this.enterPlaybackMode(Math.max(0, this.duration - 10.0));
    }
    this.isPlaying = true;
    document.getElementById("btnPbPlay")?.classList.add("active");
    document.getElementById("btnPbPause")?.classList.remove("active");

    this.app.players.forEach(p => p.playPlayback());

    if (this.playTimer) clearInterval(this.playTimer);
    let lastTs = performance.now();
    this.playTimer = setInterval(() => {
      const now = performance.now();
      const deltaSec = ((now - lastTs) / 1000) * this.playbackRate;
      lastTs = now;

      this.currentTime += deltaSec;
      if (this.currentTime >= this.duration) {
        this.currentTime = 0;
        this.seekTo(0);
      }
      this.updateNeedle();
      this.updateClock();
    }, 50);

    this.app.showToast("▶ Senkronize Kayıt Oynatılıyor");
  }

  pause() {
    this.isPlaying = false;
    document.getElementById("btnPbPlay")?.classList.remove("active");
    document.getElementById("btnPbPause")?.classList.add("active");
    if (this.playTimer) {
      clearInterval(this.playTimer);
      this.playTimer = null;
    }
    this.app.players.forEach(p => p.pausePlayback());
  }

  step() {
    if (this.isLive) {
      this.enterPlaybackMode(Math.max(0, this.duration - 5.0));
    }
    this.pause();
    const stepDelta = 0.166; // Exactly 5 frames at 30fps
    this.currentTime = Math.min(this.duration, this.currentTime + stepDelta);
    this.app.players.forEach(p => p.stepPlayback(stepDelta));
    this.updateNeedle();
    this.updateClock();
    this.app.showToast("⏯ 5-Kare İleri Adımlandı (+0.16s)");
  }

  seekTo(seconds) {
    if (this.isLive) {
      this.enterPlaybackMode(seconds);
    }
    this.currentTime = Math.max(0, Math.min(seconds, this.duration));
    this.updateNeedle();
    this.updateClock();
    this.app.players.forEach(p => p.seekPlayback(this.currentTime));
  }

  updateNeedle() {
    if (!this.needleEl || !this.viewportEl) return;
    const lane = this.viewportEl.querySelector(".track-lane");
    if (!lane) return;
    const rect = lane.getBoundingClientRect();
    const viewportRect = this.viewportEl.getBoundingClientRect();
    const leftOffset = rect.left - viewportRect.left;
    const pct = this.duration > 0 ? (this.currentTime / this.duration) : 1;
    const needleX = leftOffset + (pct * rect.width);
    this.needleEl.style.left = `${needleX}px`;
  }

  updateClock() {
    if (!this.clockEl || this.isLive) return;
    const mins = Math.floor(this.currentTime / 60);
    const secs = Math.floor(this.currentTime % 60);
    const ms = Math.floor((this.currentTime % 1) * 1000);
    const pad = (n, len = 2) => String(n).padStart(len, "0");
    this.clockEl.textContent = `KAYIT: ${pad(mins)}:${pad(secs)}.${pad(ms, 3)} / ${pad(Math.floor(this.duration / 60))}:${pad(Math.floor(this.duration % 60))}.000`;
  }
}

window.PlaybackTimeline = PlaybackTimeline;
