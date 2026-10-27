/**
 * Reports page: how many events there were over the last days, by day, rule and camera,
 * what the operator decided about them and how often the written summaries agreed.
 * The page prints cleanly (the browser's "save as PDF" gives the report as a file).
 */

import { getReport } from "./api.js";
import { locale, t } from "./i18n.js";
import { $, bindSegmented, escapeHTML, formatDuration, formatPercent, setHTML } from "./ui.js";

const MAX_AXIS_LABELS = 8;

let days = 7;
let wired = false;
let requestId = 0;

const number = (value) => Number(value || 0).toLocaleString(locale);

/* ------------------------------------------------------------------ Tiles */
function tilesHTML(report) {
  const totals = report.totals;
  const reviewed = totals.correct + totals.false_positive;
  const tiles = [
    [t("Toplam olay"), number(totals.events), t("{date} tarihinden beri", { date: report.from_text })],
    [t("Kural ihlali"), number(totals.rule), ""],
    [t(report.movement_label), number(totals.movement), ""],
    [t("İncelenmeyi bekleyen"), number(totals.unreviewed), totals.events ? t("{n} olay incelendi", { n: number(reviewed) }) : ""],
    [t("Hatalı alarm oranı"), totals.false_alarm_pct === null ? "—" : formatPercent(totals.false_alarm_pct),
      reviewed
        ? t("incelenen {n} olayın {k} tanesi", { n: number(reviewed), k: number(totals.false_positive) })
        : t("Henüz incelenen olay yok")],
  ];
  return tiles.map(([label, value, note]) => `
    <div class="stat-tile">
      <span class="stat-label">${escapeHTML(label)}</span>
      <strong class="stat-value">${escapeHTML(value)}</strong>
      <span class="stat-note">${escapeHTML(note)}</span>
    </div>`).join("");
}

/* ------------------------------------------------------------------ Chart */
/** A "nice" top for the value axis: the smallest of 1, 2, 5, 10, 20, 50... that is not below the peak. */
function axisTop(peak) {
  if (peak <= 4) return 4;
  const power = 10 ** Math.floor(Math.log10(peak));
  return [1, 2, 5, 10].map((step) => step * power).find((candidate) => candidate >= peak);
}

/** Draws the bars and the value axis into the chart frame of the page. */
function renderChart(report) {
  const buckets = report.buckets;
  const top = axisTop(Math.max(...buckets.map((bucket) => bucket.rule + bucket.movement), 0));
  const labelEvery = Math.ceil(buckets.length / MAX_AXIS_LABELS);
  setHTML($("#report-axis"), `<span>${number(top)}</span><span>${number(top / 2)}</span><span>0</span>`);
  setHTML($("#report-plot"), buckets.map((bucket, index) => {
    const segment = (count, kind) => (count ? `<span class="bar-segment is-${kind}" style="--size: ${(count / top) * 100}%"></span>` : "");
    return `
      <div class="bar-column" tabindex="0" data-index="${index}"
           aria-label="${escapeHTML(t("{label}: {rule} kural ihlali, {movement} olağandışı hareket", { label: bucket.label, rule: bucket.rule, movement: bucket.movement }))}">
        <div class="bar-stack">${segment(bucket.movement, "movement")}${segment(bucket.rule, "rule")}</div>
        <span class="bar-label">${index % labelEvery === 0 ? escapeHTML(bucket.label) : ""}</span>
      </div>`;
  }).join(""));
  $("#report-tooltip").hidden = true;
}

function showTooltip(column) {
  const tooltip = $("#report-tooltip");
  const bucket = column && current.buckets[Number(column.dataset.index)];
  if (!bucket) {
    tooltip.hidden = true;
    return;
  }
  tooltip.innerHTML = `
    <strong>${escapeHTML(bucket.label)}</strong>
    <span><i class="legend-swatch is-rule"></i>${t("Kural ihlali")} <b>${number(bucket.rule)}</b></span>
    <span><i class="legend-swatch is-movement"></i>${escapeHTML(t(current.movement_label))} <b>${number(bucket.movement)}</b></span>`;
  tooltip.hidden = false;
  const chart = $("#report-bars").getBoundingClientRect();
  const box = column.getBoundingClientRect();
  const left = box.left + box.width / 2 - chart.left;
  // Centred on the bar, but kept inside the chart at its edges
  tooltip.style.setProperty("--x", `${Math.min(Math.max(left, 80), chart.width - 80)}px`);
}

/* ----------------------------------------------------------------- Tables */
const decisionCells = (row) => `<td>${number(row.correct)}</td><td>${number(row.false_positive)}</td><td>${number(row.unreviewed)}</td>`;

function rulesTableHTML(rows) {
  if (!rows.length) return `<p class="hint">${t("Bu dönemde kural ihlali kaydedilmedi.")}</p>`;
  return `
    <div class="table-wrap"><table class="table">
      <thead><tr><th>${t("Kural")}</th><th>${t("İhlal")}</th><th>${t("Toplam süre")}</th><th>${t("Doğru")}</th><th>${t("Hatalı")}</th><th>${t("İncelenmedi")}</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr><td>${escapeHTML(row.name)}${row.ongoing ? ` <span class="badge is-warn">${t("Sürüyor")}</span>` : ""}</td>
            <td>${number(row.events)}</td><td>${row.total_sec ? formatDuration(row.total_sec) : "—"}</td>${decisionCells(row)}</tr>`).join("")}
      </tbody>
    </table></div>`;
}

function camerasTableHTML(rows, movementLabel) {
  if (!rows.length) return `<p class="hint">${t("Bu dönemde olay kaydedilmedi.")}</p>`;
  return `
    <div class="table-wrap"><table class="table">
      <thead><tr><th>${t("Kamera")}</th><th>${t("Olay")}</th><th>${t("Kural ihlali")}</th><th>${escapeHTML(t(movementLabel))}</th><th>${t("Doğru")}</th><th>${t("Hatalı")}</th><th>${t("İncelenmedi")}</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr><td>${escapeHTML(row.name)}</td><td>${number(row.events)}</td><td>${number(row.rule)}</td>
            <td>${number(row.events - row.rule)}</td>${decisionCells(row)}</tr>`).join("")}
      </tbody>
    </table></div>`;
}

function bucketsTableHTML(report) {
  const rows = report.buckets.filter((bucket) => bucket.rule + bucket.movement > 0);
  if (!rows.length) return `<p class="hint">${t("Bu dönemde olay kaydedilmedi.")}</p>`;
  return `
    <div class="table-wrap"><table class="table">
      <thead><tr><th>${t(report.days === 1 ? "Saat" : "Gün")}</th><th>${t("Kural ihlali")}</th><th>${escapeHTML(t(report.movement_label))}</th><th>${t("Toplam")}</th></tr></thead>
      <tbody>${rows.map((bucket) => `
        <tr><td>${escapeHTML(bucket.label)}</td><td>${number(bucket.rule)}</td><td>${number(bucket.movement)}</td><td>${number(bucket.rule + bucket.movement)}</td></tr>`).join("")}
      </tbody>
    </table></div>`;
}

function verdictLine(verdict) {
  if (!verdict.compared) return "";
  const percent = Math.round((verdict.agreed / verdict.compared) * 100);
  return t("Olay özetlerinin “gerçek / olağan” değerlendirmesi, incelediğiniz {n} olayın {k} tanesinde sizin kararınızla aynıydı ({percent}).",
    { n: number(verdict.compared), k: number(verdict.agreed), percent: formatPercent(percent) });
}

/* ------------------------------------------------------------------- Page */
let current = null;

function render(report) {
  current = report;
  $("#report-period").textContent = `${report.from_text} – ${report.to_text}`;
  const notice = $("#report-notice");
  notice.hidden = !report.incomplete;
  setHTML($("#report-tiles"), tilesHTML(report));
  $("#report-chart-title").textContent = t(report.days === 1 ? "Saatlere göre olaylar" : "Günlere göre olaylar");
  renderChart(report);
  setHTML($("#report-buckets-table"), bucketsTableHTML(report));
  setHTML($("#report-rules"), rulesTableHTML(report.by_rule));
  setHTML($("#report-cameras"), camerasTableHTML(report.by_camera, report.movement_label));
  const line = verdictLine(report.summary_verdict);
  $("#report-verdict").hidden = !line;
  $("#report-verdict").textContent = line;
}

async function load() {
  const mine = ++requestId;
  try {
    const report = await getReport(days);
    if (mine === requestId) render(report);
  } catch (err) {
    setHTML($("#report-tiles"), `<div class="empty"><p class="empty-title">${t("Rapor yüklenemedi")}</p><p>${escapeHTML(err.message)}</p></div>`);
  }
}

function wire() {
  const setRange = bindSegmented($("#report-range"), "days", (value) => {
    days = Number(value);
    setRange(value);
    load();
  });
  $("#report-print").addEventListener("click", () => window.print());
  $("#report-table-toggle").addEventListener("click", (event) => {
    const table = $("#report-buckets-table");
    table.hidden = !table.hidden;
    event.currentTarget.textContent = t(table.hidden ? "Tablo olarak göster" : "Tabloyu gizle");
  });
  const chart = $("#report-chart");
  const columnOf = (event) => event.target.closest(".bar-column");
  chart.addEventListener("mouseover", (event) => showTooltip(columnOf(event)));
  chart.addEventListener("focusin", (event) => showTooltip(columnOf(event)));
  chart.addEventListener("mouseleave", () => showTooltip(null));
  chart.addEventListener("focusout", () => showTooltip(null));
}

export function mount() {
  if (!wired) {
    wire();
    wired = true;
  }
  load();
}

export function unmount() {
  requestId += 1; // an answer still on its way belongs to a page that is no longer shown
}
