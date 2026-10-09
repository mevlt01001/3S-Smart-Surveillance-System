/**
 * Backend client. Every HTTP / WebSocket / SSE address used by the interface lives here,
 * so pages never build URLs or parse error bodies themselves.
 */

/** Error carrying the reason given by the server, ready to be shown to the user. */
export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function errorDetail(payload, fallback) {
  const detail = payload && (payload.detail ?? payload.error ?? payload.message);
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((item) => (item && item.msg) || String(item)).join("; ");
  }
  return fallback;
}

/**
 * JSON request with a timeout. Rejects with an ApiError whose message can be shown as is.
 * @param {string} path
 * @param {{method?: string, body?: unknown, timeoutMs?: number}} [options]
 */
async function request(path, { method = "GET", body, timeoutMs = 15000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = err && err.name === "AbortError";
    throw new ApiError(timedOut ? "Sunucu zamanında yanıt vermedi" : "Sunucuya ulaşılamıyor");
  } finally {
    clearTimeout(timer);
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    /* empty or non-JSON body */
  }
  if (!response.ok) {
    throw new ApiError(errorDetail(payload, `İstek başarısız oldu (${response.status})`), response.status);
  }
  return payload;
}

const id = encodeURIComponent;

/* ------------------------------------------------------------------ System */
export const getSystemStats = () => request("/api/system/stats", { timeoutMs: 6000 });

/* ----------------------------------------------------------------- Cameras */
export const listCameras = async () => (await request("/api/cameras")).cameras || [];
export const scanNetwork = (timeoutSec = 2.5) =>
  request(`/api/onvif/scan?timeout=${timeoutSec}`, { method: "POST", timeoutMs: 20000 });
export const addCamera = async (camera) =>
  (await request("/api/cameras/add", { method: "POST", body: camera, timeoutMs: 45000 })).camera;
export const updateCamera = (cameraId, changes) =>
  request(`/api/cameras/${id(cameraId)}`, { method: "PUT", body: changes });
export const deleteCamera = (cameraId) => request(`/api/cameras/${id(cameraId)}`, { method: "DELETE" });
export const reconnectCamera = async (cameraId) =>
  (await request(`/api/cameras/${id(cameraId)}/reconnect`, { method: "POST", timeoutMs: 45000 })).camera;

/** Address of a camera's current picture; `stamp` defeats caching (pass a fixed value for a stable URL). */
export const snapshotUrl = (cameraId, stamp = Date.now()) => `/api/cameras/${id(cameraId)}/snapshot?t=${stamp}`;

/** WebSocket address of a camera's live JPEG stream; `maxFps` 0 means the camera's own rate. */
export function streamSocketUrl(cameraId, maxFps = 0) {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  const query = maxFps > 0 ? `?fps=${maxFps}` : "";
  return `${scheme}//${location.host}/api/cameras/${id(cameraId)}/ws${query}`;
}

/* -------------------------------------------------------------- Live state */
/** Anomaly state per camera (`fleet`) and rule detections (`detections`) in one call. */
export const getLiveState = () => request("/api/live/state", { timeoutMs: 6000 });
export const getFleetStatus = () => request("/api/anomaly/status", { timeoutMs: 6000 });
export const captureReference = (cameraId, zoneId) =>
  request(`/api/change-detection/${id(cameraId)}/${id(zoneId)}/capture-reference`, { method: "POST" });

/* ------------------------------------------------------------------- Rules */
export const listRules = () => request("/api/rules");
export const createRule = async (rule) => (await request("/api/rules", { method: "POST", body: rule })).rule;
export const updateRule = async (ruleId, changes) =>
  (await request(`/api/rules/${id(ruleId)}`, { method: "PUT", body: changes })).rule;
export const deleteRule = (ruleId) => request(`/api/rules/${id(ruleId)}`, { method: "DELETE" });
export const recompileRule = (ruleId) => request(`/api/rules/${id(ruleId)}/compile`, { method: "POST" });

/* ------------------------------------------------------------------ Events */
export function listEvents({ cameraId = "", limit = 300 } = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cameraId) params.set("camera_id", cameraId);
  return request(`/api/anomaly/journal?${params}`);
}
export const getEventStats = async () => (await request("/api/anomaly/stats")).stats || {};
export const labelEvent = async (eventId, label) =>
  (await request(`/api/anomaly/${id(eventId)}/label`, { method: "POST", body: { label, notes: "" } })).entry;
export const summarizeEvent = (eventId) => request(`/api/anomaly/${id(eventId)}/summarize`, { method: "POST" });
export const getEventFrames = (eventId) => request(`/api/anomaly/${id(eventId)}/frames`, { timeoutMs: 30000 });
export const clearEvents = () => request("/api/anomaly/clear", { method: "POST" });
export const openEventStream = () => new EventSource("/api/anomaly/events-stream");

/* ----------------------------------------------------------------- Storage */
export const getStorage = () => request("/api/anomaly/storage");
export const cleanOrphanClips = () => request("/api/anomaly/storage/cleanup-orphans", { method: "POST" });

/* ---------------------------------------------------------------- Settings */
export const getSettings = async () => (await request("/api/settings")).settings;
export const saveSettings = async (settings) =>
  (await request("/api/settings", { method: "POST", body: settings })).settings;
export const resetSettings = async () => (await request("/api/settings/reset", { method: "POST" })).settings;
