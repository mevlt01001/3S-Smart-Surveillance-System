/**
 * API.JS - AegisVision REST API Client
 */

const API_BASE = "";

export async function fetchSystemStats() {
  try {
    const res = await fetch(`${API_BASE}/api/system/stats`);
    if (!res.ok) throw new Error("Failed to fetch system stats");
    return await res.json();
  } catch (err) {
    console.error("[API] fetchSystemStats error:", err);
    return null;
  }
}

export async function fetchInterfaces() {
  try {
    const res = await fetch(`${API_BASE}/api/onvif/interfaces`);
    if (!res.ok) throw new Error("Failed to fetch interfaces");
    return await res.json();
  } catch (err) {
    console.error("[API] fetchInterfaces error:", err);
    return { interfaces: [] };
  }
}

export async function triggerOnvifScan(timeout = 3.0) {
  try {
    const res = await fetch(`${API_BASE}/api/onvif/scan?timeout=${timeout}`, {
      method: "POST"
    });
    if (!res.ok) throw new Error("ONVIF scan failed");
    return await res.json();
  } catch (err) {
    console.error("[API] triggerOnvifScan error:", err);
    return { success: false, devices: [] };
  }
}

export async function fetchCameras() {
  try {
    const res = await fetch(`${API_BASE}/api/cameras`);
    if (!res.ok) throw new Error("Failed to fetch cameras");
    return await res.json();
  } catch (err) {
    console.error("[API] fetchCameras error:", err);
    return { cameras: [] };
  }
}

export async function addCamera(cameraData) {
  try {
    const res = await fetch(`${API_BASE}/api/cameras/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cameraData)
    });
    if (!res.ok) throw new Error("Failed to register camera");
    return await res.json();
  } catch (err) {
    console.error("[API] addCamera error:", err);
    throw err;
  }
}

export async function deleteCamera(cameraId) {
  try {
    const res = await fetch(`${API_BASE}/api/cameras/${cameraId}`, {
      method: "DELETE"
    });
    return res.ok;
  } catch (err) {
    console.error("[API] deleteCamera error:", err);
    return false;
  }
}

export async function reconnectCamera(cameraId) {
  try {
    const res = await fetch(`${API_BASE}/api/cameras/${cameraId}/reconnect`, {
      method: "POST"
    });
    return await res.json();
  } catch (err) {
    console.error("[API] reconnectCamera error:", err);
    return null;
  }
}

export async function updateCamera(cameraId, cameraData) {
  try {
    const res = await fetch(`${API_BASE}/api/cameras/${cameraId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cameraData)
    });
    if (!res.ok) throw new Error("Failed to update camera");
    return await res.json();
  } catch (err) {
    console.error("[API] updateCamera error:", err);
    throw err;
  }
}

export function getSnapshotUrl(cameraId) {
  return `${API_BASE}/api/cameras/${cameraId}/snapshot?t=${Date.now()}`;
}

export async function fetchRules(cameraId = null) {
  try {
    const url = cameraId ? `${API_BASE}/api/rules?camera_id=${encodeURIComponent(cameraId)}` : `${API_BASE}/api/rules`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to fetch rules");
    return await res.json();
  } catch (err) {
    console.error("[API] fetchRules error:", err);
    return { rules: [] };
  }
}

export async function createRule(ruleData) {
  try {
    const res = await fetch(`${API_BASE}/api/rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ruleData)
    });
    if (!res.ok) throw new Error("Failed to create rule");
    return await res.json();
  } catch (err) {
    console.error("[API] createRule error:", err);
    throw err;
  }
}

export async function updateRule(ruleId, updates) {
  try {
    const res = await fetch(`${API_BASE}/api/rules/${ruleId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates)
    });
    if (!res.ok) throw new Error("Failed to update rule");
    return await res.json();
  } catch (err) {
    console.error("[API] updateRule error:", err);
    throw err;
  }
}

export async function deleteRule(ruleId) {
  try {
    const res = await fetch(`${API_BASE}/api/rules/${ruleId}`, {
      method: "DELETE"
    });
    return res.ok;
  } catch (err) {
    console.error("[API] deleteRule error:", err);
    return false;
  }
}
