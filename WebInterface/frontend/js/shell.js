/**
 * Parts of the interface that are always on screen: clock, system status line,
 * the unreviewed-events badge and the "connection lost" banner.
 */

import { getEventStats, getSystemStats } from "./api.js";
import { showToast } from "./ui.js";

const STATUS_POLL_MS = 5000;
const FAILURES_BEFORE_OFFLINE = 2;

const statsListeners = new Set();
let lastStats = null;
let failures = 0;
let online = true;

/** Calls `listener(stats)` now (if known) and after every status poll; returns an unsubscribe function. */
export function subscribeSystemStats(listener) {
  statsListeners.add(listener);
  if (lastStats) listener(lastStats);
  return () => statsListeners.delete(listener);
}

function startClock() {
  const clock = document.getElementById("clock");
  const tick = () => {
    clock.textContent = new Date().toLocaleTimeString("tr-TR", { hour12: false });
  };
  tick();
  setInterval(tick, 1000);
}

function setOnline(next) {
  if (next === online) return;
  online = next;
  document.body.classList.toggle("is-offline", !online);
  let banner = document.getElementById("connection-banner");
  if (!online) {
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "connection-banner";
      banner.className = "connection-banner";
      banner.setAttribute("role", "alert");
      banner.textContent = "Sunucu bağlantısı koptu. Ekrandaki bilgiler güncel olmayabilir; yeniden bağlanılıyor…";
      document.body.appendChild(banner);
    }
  } else {
    if (banner) banner.remove();
    showToast("Sunucu bağlantısı yeniden kuruldu.", "success", 3000);
  }
}

function renderStatus(stats) {
  const box = document.getElementById("system-status");
  const dot = box.querySelector(".status-dot");
  const text = document.getElementById("system-status-text");
  let state = "is-ok";
  let label = "Sistem çalışıyor";
  let detail = "Kameralar izleniyor, analiz çalışıyor.";
  if (!stats) {
    state = "is-danger";
    label = "Bağlantı yok";
    detail = "Sunucuya ulaşılamıyor.";
  } else if (!stats.triton || stats.triton.status !== "READY") {
    state = "is-danger";
    label = "Analiz durdu";
    detail = "Analiz sunucusuna ulaşılamıyor. Canlı görüntü çalışır; olay algılama ve kurallar durur.";
  }
  dot.className = `status-dot ${state}`;
  text.textContent = label;
  box.title = detail;
  // Said on every page as well: a rule that is not being checked looks like any other rule
  document.getElementById("analysis-notice").hidden = !stats || state === "is-ok";
}

/** Updates the number next to "Olaylar": events nobody has reviewed yet. */
export async function refreshEventsBadge() {
  const badge = document.getElementById("nav-events-badge");
  try {
    const stats = await getEventStats();
    const pending = Number(stats.unlabeled_count) || 0;
    badge.hidden = pending === 0;
    badge.textContent = pending > 99 ? "99+" : String(pending);
    badge.title = `${pending} incelenmemiş olay`;
  } catch (_) {
    /* the status line already reports connection problems */
  }
}

async function poll() {
  if (document.hidden) return;
  try {
    lastStats = await getSystemStats();
    failures = 0;
    setOnline(true);
    renderStatus(lastStats);
    statsListeners.forEach((listener) => listener(lastStats));
    refreshEventsBadge();
  } catch (_) {
    failures += 1;
    if (failures >= FAILURES_BEFORE_OFFLINE) {
      setOnline(false);
      renderStatus(null);
    }
  }
}

export function initShell() {
  startClock();
  poll();
  setInterval(poll, STATUS_POLL_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) poll();
  });
}
