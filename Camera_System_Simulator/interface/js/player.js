/**
 * AEGIS-PRO Video Streaming Engine
 * Ultra-low-latency WebRTC (WHEP) player with zero-delay host ICE,
 * seamless 30/60 fps synchronized NVR playback, digital zoom/pan,
 * snapshot downloads, and clip recording.
 */

class CameraPlayer {
  constructor(camId, containerEl, camData) {
    this.camId = camId;
    this.container = containerEl;
    this.camData = camData;
    this.videoEl = null;
    this.peerConnection = null;
    this.isStreaming = false;
    this.isPlaybackMode = false;
    this.reconnectTimer = null;

    // Digital Zoom & Pan state
    this.scale = 1.0;
    this.panX = 0;
    this.panY = 0;
    this.isPanning = false;
    this.startX = 0;
    this.startY = 0;

    this.mediaRecorder = null;
    this.recordedChunks = [];
    this.isRecordingClip = false;

    this.initPlayer();
  }

  initPlayer() {
    this.videoEl = this.container.querySelector('.cam-video-element');
    this.setupZoomAndPan();
    this.connectWebRTC();
  }

  async connectWebRTC() {
    if (this.isPlaybackMode) return;

    // WHEP proxy endpoint on same origin/port to eliminate CORS/firewall issues
    const whepUrl = `/api/whep/${this.camId}`;

    try {
      if (this.peerConnection) {
        this.peerConnection.close();
        this.peerConnection = null;
      }

      // Zero-delay host ICE: no external STUN lookup needed on local network
      this.peerConnection = new RTCPeerConnection({
        iceServers: [],
        bundlePolicy: 'max-bundle'
      });

      this.peerConnection.addTransceiver('video', { direction: 'recvonly' });

      this.peerConnection.ontrack = (event) => {
        if (event.streams && event.streams[0]) {
          this.videoEl.srcObject = event.streams[0];
          this.videoEl.play().catch(e => console.warn(`Autoplay on ${this.camId}:`, e));
          this.isStreaming = true;
          this.hideSpinner();
        }
      };

      this.peerConnection.onconnectionstatechange = () => {
        if (this.peerConnection && this.peerConnection.connectionState === 'connected') {
          this.isStreaming = true;
          this.hideSpinner();
        }
      };

      const offer = await this.peerConnection.createOffer();
      await this.peerConnection.setLocalDescription(offer);

      // Wait for host ICE candidates to gather so that offer contains local IP/port
      if (this.peerConnection.iceGatheringState !== 'complete') {
        await new Promise((resolve) => {
          const checkState = () => {
            if (this.peerConnection && this.peerConnection.iceGatheringState === 'complete') {
              this.peerConnection.removeEventListener('icegatheringstatechange', checkState);
              resolve();
            }
          };
          this.peerConnection.addEventListener('icegatheringstatechange', checkState);
          setTimeout(resolve, 400); // 400ms max timeout
        });
      }

      const sdpOffer = this.peerConnection.localDescription ? this.peerConnection.localDescription.sdp : offer.sdp;

      const res = await fetch(whepUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: sdpOffer
      });

      if (!res.ok) {
        throw new Error(`WHEP status ${res.status}`);
      }

      const answerSdp = await res.text();
      await this.peerConnection.setRemoteDescription(new RTCSessionDescription({
        type: 'answer',
        sdp: answerSdp
      }));

    } catch (err) {
      console.warn(`WebRTC for ${this.camId}: ${err.message}. Retrying in 2s...`);
      if (!this.isPlaybackMode) {
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => this.connectWebRTC(), 2000);
      }
    }
  }

  hideSpinner() {
    const spinner = this.container.querySelector('.cam-loading-spinner');
    if (spinner) spinner.style.display = 'none';
  }

  showSpinner(text = "CONNECTING...") {
    const spinner = this.container.querySelector('.cam-loading-spinner');
    if (spinner) {
      spinner.style.display = 'flex';
      const span = spinner.querySelector('span');
      if (span) span.textContent = text;
    }
  }

  enterPlaybackMode(startTimeSec = 0) {
    this.isPlaybackMode = true;

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.peerConnection) {
      this.peerConnection.close();
      this.peerConnection = null;
    }

    this.videoEl.srcObject = null;
    const setId = window.app ? window.app.activeSetId : 'set_1';
    const streamUrl = `/api/playback/video/${this.camId}?set_id=${setId}`;

    if (!this.videoEl.src.includes(`/api/playback/video/${this.camId}`)) {
      this.videoEl.src = streamUrl;
      this.videoEl.load();
    }

    this.videoEl.currentTime = Math.max(0, startTimeSec);
    const rate = window.app && window.app.timeline ? window.app.timeline.playbackRate : 1.0;
    this.videoEl.playbackRate = rate;
    this.isStreaming = false;
    this.hideSpinner();
  }

  seekPlayback(seconds) {
    if (this.videoEl) {
      this.videoEl.currentTime = Math.max(0, seconds);
    }
  }

  playPlayback() {
    if (this.videoEl) {
      this.videoEl.play().catch(() => {});
    }
  }

  pausePlayback() {
    if (this.videoEl) {
      this.videoEl.pause();
    }
  }

  stepPlayback(deltaSec = 0.166) {
    if (this.videoEl) {
      this.videoEl.pause();
      this.videoEl.currentTime = Math.max(0, this.videoEl.currentTime + deltaSec);
    }
  }

  setPlaybackRate(rate) {
    if (this.videoEl) {
      this.videoEl.playbackRate = rate;
    }
  }

  returnToLive() {
    this.isPlaybackMode = false;
    if (this.videoEl) {
      this.videoEl.pause();
      this.videoEl.removeAttribute('src');
      this.videoEl.load();
    }

    this.showSpinner(`CANLI YAYINA BAĞLANILIYOR (${this.camId.toUpperCase()})...`);
    this.connectWebRTC();
  }

  setupZoomAndPan() {
    const vContainer = this.container.querySelector('.cam-video-container');

    // Mouse wheel to zoom
    vContainer.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.2 : 0.83;
      const newScale = Math.min(Math.max(this.scale * zoomFactor, 1.0), 8.0);

      if (newScale === 1.0) {
        this.panX = 0;
        this.panY = 0;
      }
      this.scale = newScale;
      this.applyTransform();
    }, { passive: false });

    // Drag to pan when zoomed
    vContainer.addEventListener('mousedown', (e) => {
      if (this.scale > 1.0) {
        this.isPanning = true;
        this.startX = e.clientX - this.panX;
        this.startY = e.clientY - this.panY;
        vContainer.style.cursor = 'grab';
      }
    });

    window.addEventListener('mousemove', (e) => {
      if (!this.isPanning) return;
      this.panX = e.clientX - this.startX;
      this.panY = e.clientY - this.startY;
      this.applyTransform();
    });

    window.addEventListener('mouseup', () => {
      if (this.isPanning) {
        this.isPanning = false;
        vContainer.style.cursor = 'default';
      }
    });

    // Double click to reset zoom
    vContainer.addEventListener('dblclick', () => {
      this.scale = 1.0;
      this.panX = 0;
      this.panY = 0;
      this.applyTransform();
    });
  }

  applyTransform() {
    if (this.videoEl) {
      this.videoEl.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.scale})`;
    }
  }

  async takeSnapshot() {
    try {
      const res = await fetch(`/api/cameras/${this.camId}/snapshot`);
      if (!res.ok) throw new Error("Snapshot failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${this.camId}_snapshot_${Date.now()}.jpg`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      window.app.showToast(`📸 Snapshot kaydedildi: ${this.camData.name}`);
    } catch (e) {
      window.app.showToast(`⚠️ Snapshot hatası: ${e.message}`);
    }
  }

  toggleRecordClip() {
    if (this.isRecordingClip) {
      if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
        this.mediaRecorder.stop();
      }
      this.isRecordingClip = false;
      window.app.showToast(`⏺ Klip kaydedildi: ${this.camId}`);
    } else {
      try {
        const stream = this.videoEl.captureStream ? this.videoEl.captureStream() : this.videoEl.srcObject;
        if (!stream) {
          window.app.showToast(`⚠️ Kayıt başlatılamadı: Akış aktif değil`);
          return;
        }
        this.recordedChunks = [];
        this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
        this.mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) this.recordedChunks.push(e.data);
        };
        this.mediaRecorder.onstop = () => {
          const blob = new Blob(this.recordedChunks, { type: 'video/webm' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `${this.camId}_record_${Date.now()}.webm`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        };
        this.mediaRecorder.start();
        this.isRecordingClip = true;
        window.app.showToast(`🔴 Klip kaydediliyor (${this.camId})... Tamamlamak için tekrar tıklayın.`);
      } catch (err) {
        window.app.showToast(`⚠️ Kayıt desteklenmiyor: ${err.message}`);
      }
    }
  }

  destroy() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.peerConnection) {
      this.peerConnection.close();
      this.peerConnection = null;
    }
    if (this.videoEl) {
      this.videoEl.srcObject = null;
    }
  }
}

window.CameraPlayer = CameraPlayer;
