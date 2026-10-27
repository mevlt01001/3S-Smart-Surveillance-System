/**
 * Draws what the analysis sees on top of a live picture: rule zones, detected objects
 * and the state of "obstacle / change" zones. Coordinates are normalised (0..1) and are
 * mapped onto the area the picture really occupies inside its letter-boxed element.
 */

import { t } from "./i18n.js";
import { classLabel } from "./labels.js";

const FONT = '600 11px system-ui, -apple-system, "Segoe UI", sans-serif';
const COLORS = {
  zone: "#ff8533",
  object: "rgba(203, 213, 225, 0.85)",
  ok: "#2fbf71",
  warn: "#f5a524",
  danger: "#ef4444",
  muted: "#94a3b8",
};

/** Area of the picture inside an element that uses `object-fit: contain`. */
function pictureArea(canvas, image) {
  const pictureRatio = (image.naturalWidth || 16) / (image.naturalHeight || 9);
  const boxRatio = canvas.width / canvas.height;
  if (boxRatio > pictureRatio) {
    const width = canvas.height * pictureRatio;
    return { x: (canvas.width - width) / 2, y: 0, width, height: canvas.height };
  }
  const height = canvas.width / pictureRatio;
  return { x: 0, y: (canvas.height - height) / 2, width: canvas.width, height };
}

function tracePolygon(ctx, area, points) {
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = area.x + point.x * area.width;
    const y = area.y + point.y * area.height;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
}

function drawLabel(ctx, canvas, text, x, y, color) {
  ctx.font = FONT;
  const width = ctx.measureText(text).width + 10;
  const height = 17;
  const left = Math.max(2, Math.min(canvas.width - width - 2, x));
  const top = Math.max(2, Math.min(canvas.height - height - 2, y));
  ctx.fillStyle = "rgba(8, 11, 17, 0.78)";
  ctx.fillRect(left, top, width, height);
  ctx.fillStyle = color;
  ctx.fillText(text, left + 5, top + 12);
}

function drawRuleZone(ctx, canvas, area, zone) {
  tracePolygon(ctx, area, zone.points);
  ctx.fillStyle = "rgba(255, 133, 51, 0.12)";
  ctx.fill();
  ctx.strokeStyle = COLORS.zone;
  ctx.lineWidth = 1.5;
  ctx.stroke();
  const first = zone.points[0];
  drawLabel(ctx, canvas, zone.name || t("Bölge"), area.x + first.x * area.width, area.y + first.y * area.height - 19, COLORS.zone);
}

function drawChangeZone(ctx, canvas, area, zone, result) {
  let color = COLORS.ok;
  let status = "";
  if (!result || !result.has_reference) {
    color = COLORS.muted;
    status = t("referans bekleniyor");
  } else if (result.alarm_level === "alarm") {
    color = COLORS.danger;
    status = t("engel var");
  } else if (result.alarm_level === "warning") {
    color = COLORS.warn;
    status = t("değişiklik var");
  }
  tracePolygon(ctx, area, zone.points);
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = color;
  ctx.lineWidth = result && result.alarm_level === "alarm" ? 2 : 1.5;
  ctx.stroke();
  ctx.setLineDash([]);
  const first = zone.points[0];
  const name = zone.name || t("Bölge");
  drawLabel(ctx, canvas, status ? `${name}: ${status}` : name, area.x + first.x * area.width, area.y + first.y * area.height - 19, color);
}

function drawDetection(ctx, canvas, area, detection) {
  const box = detection.bbox_normalized;
  if (!box || box.length < 4) return;
  const x = area.x + box[0] * area.width;
  const y = area.y + box[1] * area.height;
  const width = Math.max(3, (box[2] - box[0]) * area.width);
  const height = Math.max(3, (box[3] - box[1]) * area.height);
  const color = detection.is_violation ? COLORS.danger : COLORS.object;
  ctx.strokeStyle = color;
  ctx.lineWidth = detection.is_violation ? 2 : 1;
  ctx.strokeRect(x, y, width, height);
  drawLabel(ctx, canvas, classLabel(detection.class_name), x, y - 19, color);
}

/**
 * @param {HTMLCanvasElement} canvas  overlay covering the picture element
 * @param {HTMLImageElement} image    the live picture
 * @param {{zones: object[], detections: object[], changeResults: object[],
 *          showZones: boolean, showDetections: boolean}} scene
 */
export function drawOverlay(canvas, image, scene) {
  const bounds = canvas.getBoundingClientRect();
  const width = Math.round(bounds.width);
  const height = Math.round(bounds.height);
  if (!width || !height) return;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  const area = pictureArea(canvas, image);

  scene.zones.forEach((zone) => {
    if (!zone.points || zone.points.length < 3) return;
    if (zone.zone_type === "change_detection") {
      if (scene.showDetections) {
        drawChangeZone(ctx, canvas, area, zone, scene.changeResults.find((r) => r.zone_id === zone.id));
      }
    } else if (scene.showZones) {
      drawRuleZone(ctx, canvas, area, zone);
    }
  });
  if (scene.showDetections) {
    scene.detections.forEach((detection) => drawDetection(ctx, canvas, area, detection));
  }
}

export function clearOverlay(canvas) {
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
}
