/**
 * Reports page: how many events there were over the last days, by day, rule and camera,
 * what the operator decided about them and how often the written summaries agreed.
 * The page prints cleanly (the browser's "save as PDF" gives the report as a file).
 */

import { getReport } from "./api.js";
import { $, bindSegmented, escapeHTML, formatDuration, setHTML } from "./ui.js";

const MAX_AXIS_LABELS = 8;

let days = 7;
let wired = false;
let requestId = 0;

const number = (value) => Number(value || 0).toLocaleString("tr-TR");

/* ------------------------------------------------------------------ Tiles */
function tilesHTML(report) {
  const totals = report.totals;
  const reviewed = totals.correct + totals.false_positive;
  const tiles = [
    ["Toplam olay", number(totals.events), `${report.from_text} tarihinden beri`],
    ["Kural ihlali", number(totals.rule), ""],
    [report.movement_label, number(totals.movement), ""],
    ["İncelenmeyi bekleyen", number(totals.unreviewed), totals.events ? `${number(reviewed)} olay incelendi` : ""],
    ["Hatalı alarm oranı", totals.false_alarm_pct === null ? "—" : `%${String(totals.false_alarm_pct).replace(".", ",")}`,
      reviewed ? `incelenen ${number(reviewed)} olayın ${number(totals.false_positive)} tanesi` : "Henüz incelenen olay yok"],
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
    const segment = (count, kind) => (count ? `<span class="bar-segment is-${kind}" style="height: ${(count / top) * 100}%"></span>` : "");
    return `
      <div class="bar-column" tabindex="0" data-index="${index}"
           aria-label="${escapeHTML(bucket.label)}: ${bucket.rule} kural ihlali, ${bucket.movement} ${escapeHTML(report.movement_label.toLocaleLowerCase("tr"))}">
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
    <span><i class="legend-swatch is-rule"></i>Kural ihlali <b>${number(bucket.rule)}</b></span>
    <span><i class="legend-swatch is-movement"></i>${escapeHTML(current.movement_label)} <b>${number(bucket.movement)}</b></span>`;
  tooltip.hidden = false;
  const chart = $("#report-bars").getBoundingClientRect();
  const box = column.getBoundingClientRect();
  const left = box.left + box.width / 2 - chart.left;
  // Kept inside the chart: flipped to the other side near the right edge
  tooltip.style.left = `${Math.min(Math.max(left, 80), chart.width - 80)}px`;
}

/* ----------------------------------------------------------------- Tables */
const decisionCells = (row) => `<td>${number(row.correct)}</td><td>${number(row.false_positive)}</td><td>${number(row.unreviewed)}</td>`;

function rulesTableHTML(rows) {
  if (!rows.length) return `<p class="hint">Bu dönemde kural ihlali kaydedilmedi.</p>`;
  return `
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Kural</th><th>İhlal</th><th>Toplam süre</th><th>Doğru</th><th>Hatalı</th><th>İncelenmedi</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr><td>${escapeHTML(row.name)}${row.ongoing ? ` <span class="badge is-warn">Sürüyor</span>` : ""}</td>
            <td>${number(row.events)}</td><td>${row.total_sec ? formatDuration(row.total_sec) : "—"}</td>${decisionCells(row)}</tr>`).join("")}
      </tbody>
    </table></div>`;
}

function camerasTableHTML(rows, movementLabel) {
  if (!rows.length) return `<p class="hint">Bu dönemde olay kaydedilmedi.</p>`;
  return `
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Kamera</th><th>Olay</th><th>Kural ihlali</th><th>${escapeHTML(movementLabel)}</th><th>Doğru</th><th>Hatalı</th><th>İncelenmedi</th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr><td>${escapeHTML(row.name)}</td><td>${number(row.events)}</td><td>${number(row.rule)}</td>
            <td>${number(row.events - row.rule)}</td>${decisionCells(row)}</tr>`).join("")}
      </tbody>
    </table></div>`;
}

function bucketsTableHTML(report) {
  const rows = report.buckets.filter((bucket) => bucket.rule + bucket.movement > 0);
  if (!rows.length) return `<p class="hint">Bu dönemde olay kaydedilmedi.</p>`;
  return `
    <div class="table-wrap"><table class="table">
      <thead><tr><th>${report.days === 1 ? "Saat" : "Gün"}</th><th>Kural ihlali</th><th>${escapeHTML(report.movement_label)}</th><th>Toplam</th></tr></thead>
      <tbody>${rows.map((bucket) => `
        <tr><td>${escapeHTML(bucket.label)}</td><td>${number(bucket.rule)}</td><td>${number(bucket.movement)}</td><td>${number(bucket.rule + bucket.movement)}</td></tr>`).join("")}
      </tbody>
    </table></div>`;
}

function verdictLine(verdict) {
  if (!verdict.compared) return "";
  const percent = Math.round((verdict.agreed / verdict.compared) * 100);
  return `Olay özetlerinin “gerçek / olağan” değerlendirmesi, incelediğiniz ${number(verdict.compared)} olayın ${number(verdict.agreed)} tanesinde sizin kararınızla aynıydı (%${percent}).`;
}

/* ------------------------------------------------------------------- Page */
let current = null;

function render(report) {
  current = report;
  $("#report-period").textContent = `${report.from_text} – ${report.to_text}`;
  const notice = $("#report-notice");
  notice.hidden = !report.incomplete;
  setHTML($("#report-tiles"), tilesHTML(report));
  $("#report-chart-title").textContent = report.days === 1 ? "Saatlere göre olaylar" : "Günlere göre olaylar";
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
    setHTML($("#report-tiles"), `<div class="empty"><p class="empty-title">Rapor yüklenemedi</p><p>${escapeHTML(err.message)}</p></div>`);
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
    event.currentTarget.textContent = table.hidden ? "Tablo olarak göster" : "Tabloyu gizle";
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
