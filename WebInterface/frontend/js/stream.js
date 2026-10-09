/**
 * Live video for one <img>: binary JPEG frames over a WebSocket.
 * - "Latest frame wins": while the browser decodes a frame, newer ones replace the waiting
 *   frame instead of queueing, so a busy tab drops frames but never falls behind real time.
 * - Reconnects with back-off; a one-per-second snapshot keeps the picture moving meanwhile.
 */

import { snapshotUrl, streamSocketUrl } from "./api.js";

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 8000;
const FALLBACK_INTERVAL_MS = 1000;

/**
 * @param {string} cameraId
 * @param {HTMLImageElement} image
 * @param {number} [maxFps] 0 plays at the camera's own frame rate
 * @returns {() => void} stops the stream and releases its resources
 */
export function startStream(cameraId, image, maxFps = 0) {
  let active = true;
  let socket = null;
  let reconnectTimer = null;
  let fallbackTimer = null;
  let reconnectDelay = RECONNECT_MIN_MS;
  let shownUrl = null;
  let waitingFrame = null;
  let decoding = false;

  async function showFrames() {
    decoding = true;
    while (active && waitingFrame) {
      const frame = waitingFrame;
      waitingFrame = null;
      const previousUrl = shownUrl;
      shownUrl = URL.createObjectURL(frame);
      image.src = shownUrl;
      try {
        await image.decode();
      } catch (_) {
        /* superseded or damaged frame: move on to the next one */
      }
      if (previousUrl) URL.revokeObjectURL(previousUrl);
    }
    decoding = false;
  }

  function stopFallback() {
    clearInterval(fallbackTimer);
    fallbackTimer = null;
  }

  function startFallback() {
    if (fallbackTimer || !active) return;
    fallbackTimer = setInterval(() => {
      const preloader = new Image();
      preloader.onload = () => {
        if (active && fallbackTimer) image.src = preloader.src;
      };
      preloader.src = snapshotUrl(cameraId);
    }, FALLBACK_INTERVAL_MS);
  }

  function scheduleReconnect() {
    startFallback();
    reconnectTimer = setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
  }

  function connect() {
    if (!active) return;
    try {
      socket = new WebSocket(streamSocketUrl(cameraId, maxFps));
    } catch (_) {
      scheduleReconnect();
      return;
    }
    socket.binaryType = "blob";
    socket.onopen = () => {
      reconnectDelay = RECONNECT_MIN_MS;
      stopFallback();
    };
    socket.onmessage = (event) => {
      if (!active || !(event.data instanceof Blob)) return;
      waitingFrame = event.data;
      if (!decoding) showFrames();
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      if (active) scheduleReconnect();
    };
  }

  connect();

  return function stop() {
    active = false;
    waitingFrame = null;
    clearTimeout(reconnectTimer);
    stopFallback();
    if (socket) {
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
      socket.close();
      socket = null;
    }
    if (shownUrl) {
      URL.revokeObjectURL(shownUrl);
      shownUrl = null;
    }
  };
}
