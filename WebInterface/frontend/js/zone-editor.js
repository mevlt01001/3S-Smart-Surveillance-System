/**
 * Polygon editor used by the rule form. The user clicks corner points on a canvas laid over
 * a camera picture; finished polygons become zones. Points are stored normalised (0..1), so
 * a zone fits the picture at any size. The editor knows nothing about the surrounding form.
 */

export const ZONE_COLORS = ["#ff8533", "#38bdf8", "#34d399", "#c084fc", "#f43f5e", "#fbbf24"];

const MIN_POINTS = 3;
// How close to the first corner a click closes the polygon; a fingertip is less precise than a mouse
const CLOSE_RADIUS_PX = window.matchMedia("(pointer: coarse)").matches ? 30 : 16;
const MIN_POINT_DISTANCE = 0.008;
const LABEL_FONT = '600 12px system-ui, -apple-system, "Segoe UI", sans-serif';

const zoneColor = (zone, index) => ZONE_COLORS[(zone.colorIndex ?? index) % ZONE_COLORS.length];

/** Ray-casting test: is the normalised `point` inside `polygon`? */
function contains(polygon, point) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i];
    const b = polygon[j];
    if (a.y > point.y !== b.y > point.y && point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x) {
      inside = !inside;
    }
  }
  return inside;
}

const turn = (origin, a, b) => (a.x - origin.x) * (b.y - origin.y) - (a.y - origin.y) * (b.x - origin.x);

/** Do the segments a–b and c–d cross each other (touching at an end point does not count)? */
const segmentsCross = (a, b, c, d) => turn(c, d, a) * turn(c, d, b) < 0 && turn(a, b, c) * turn(a, b, d) < 0;

/** Would the edge from the last corner of `points` to `next` cut through an earlier edge? */
function edgeCrossesOutline(points, next) {
  const last = points[points.length - 1];
  return points.slice(0, -1).some((point, index) => segmentsCross(last, next, point, points[index + 1]));
}

/**
 * @param {HTMLCanvasElement} canvas
 * @param {{onChange: () => void, canDraw: () => boolean, onReject?: () => void}} hooks
 *        onChange: zones, selection or the unfinished polygon changed
 *        canDraw:  whether a click may start drawing (e.g. a camera is selected)
 *        onReject: a corner was refused because the outline would cross itself
 */
export function createZoneEditor(canvas, { onChange, canDraw, onReject = () => {} }) {
  const ctx = canvas.getContext("2d");
  let zones = [];
  let draft = [];
  let selectedId = null;
  let cursor = null;
  let nearStart = false;

  const toPixels = (point) => ({ x: point.x * canvas.width, y: point.y * canvas.height });

  function tracePath(points) {
    ctx.beginPath();
    points.forEach((point, index) => {
      const { x, y } = toPixels(point);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
  }

  function drawZone(zone, index) {
    const color = zoneColor(zone, index);
    const selected = zone.id === selectedId;
    tracePath(zone.points);
    ctx.closePath();
    ctx.globalAlpha = selected ? 0.35 : 0.18;
    ctx.fillStyle = color;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = selected ? "#ffffff" : color;
    ctx.lineWidth = selected ? 2.5 : 2;
    ctx.stroke();

    const centre = zone.points.reduce((sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }), { x: 0, y: 0 });
    const { x, y } = toPixels({ x: centre.x / zone.points.length, y: centre.y / zone.points.length });
    ctx.font = LABEL_FONT;
    const label = zone.name || `Bölge ${index + 1}`;
    const width = ctx.measureText(label).width + 16;
    ctx.fillStyle = "rgba(8, 11, 17, 0.85)";
    ctx.fillRect(x - width / 2, y - 11, width, 22);
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.fillText(label, x, y + 4);
    ctx.textAlign = "start";
  }

  function drawDraft() {
    if (!draft.length) return;
    const color = ZONE_COLORS[zones.length % ZONE_COLORS.length];
    tracePath(draft);
    if (cursor) ctx.lineTo(cursor.x, cursor.y);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.stroke();
    ctx.setLineDash([]);
    draft.forEach((point, index) => {
      const { x, y } = toPixels(point);
      const isStart = index === 0;
      ctx.beginPath();
      ctx.arc(x, y, isStart && nearStart ? 8 : isStart ? 6 : 4, 0, Math.PI * 2);
      ctx.fillStyle = isStart && draft.length >= MIN_POINTS ? color : "#ffffff";
      ctx.fill();
      ctx.strokeStyle = "#0b0e14";
      ctx.lineWidth = 2;
      ctx.stroke();
    });
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    zones.forEach(drawZone);
    drawDraft();
  }

  function changed() {
    draw();
    onChange();
  }

  function finishDrawing() {
    if (draft.length < MIN_POINTS) return false;
    // The closing edge must not cut through the outline either: a zone that crosses itself
    // has no clear inside
    if (edgeCrossesOutline(draft, draft[0])) {
      onReject();
      return false;
    }
    const zone = {
      id: `zone_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      name: `Bölge ${zones.length + 1}`,
      description: "",
      zone_type: "detection",
      points: draft,
      colorIndex: zones.length % ZONE_COLORS.length,
    };
    zones.push(zone);
    draft = [];
    nearStart = false;
    selectedId = zone.id;
    changed();
    return true;
  }

  function pointerPosition(event) {
    const bounds = canvas.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  }

  /** Is this position on the first corner of a polygon that has enough points to be closed? */
  function isNearStart(position) {
    if (draft.length < MIN_POINTS) return false;
    const start = toPixels(draft[0]);
    return Math.hypot(position.x - start.x, position.y - start.y) <= CLOSE_RADIUS_PX;
  }

  canvas.addEventListener("mousemove", (event) => {
    cursor = pointerPosition(event);
    nearStart = isNearStart(cursor);
    if (draft.length) draw();
  });

  canvas.addEventListener("mouseleave", () => {
    cursor = null;
    nearStart = false;
    draw();
  });

  canvas.addEventListener("click", (event) => {
    if (!canDraw()) return;
    const position = pointerPosition(event);
    // Checked here as well: touch screens send no pointer movement before a tap
    if (isNearStart(position)) {
      finishDrawing();
      return;
    }
    const point = {
      x: Number((position.x / canvas.width).toFixed(4)),
      y: Number((position.y / canvas.height).toFixed(4)),
    };
    if (!draft.length) {
      // Not drawing: a click inside a finished zone selects it instead of starting a new one
      const hit = [...zones].reverse().find((zone) => contains(zone.points, point));
      if (hit) {
        selectedId = hit.id;
        changed();
        return;
      }
    } else {
      const last = draft[draft.length - 1];
      if (Math.hypot(point.x - last.x, point.y - last.y) < MIN_POINT_DISTANCE) return;
      if (edgeCrossesOutline(draft, point)) {
        onReject();
        return;
      }
    }
    draft.push(point);
    changed();
  });

  canvas.addEventListener("dblclick", finishDrawing);

  return {
    /** Replaces everything (used when a rule is loaded or the form is reset). */
    setZones(next) {
      zones = next.map((zone, index) => ({ ...zone, colorIndex: zone.colorIndex ?? index % ZONE_COLORS.length }));
      draft = [];
      selectedId = zones.length ? zones[0].id : null;
      changed();
    },
    getZones: () => zones,
    getSelected: () => zones.find((zone) => zone.id === selectedId) || null,
    select(zoneId) {
      selectedId = zoneId;
      changed();
    },
    /** Changes fields of the selected zone (name, description, type). */
    updateSelected(changes) {
      const zone = zones.find((item) => item.id === selectedId);
      if (zone) Object.assign(zone, changes);
      changed();
    },
    removeZone(zoneId) {
      zones = zones.filter((zone) => zone.id !== zoneId);
      zones.forEach((zone, index) => {
        zone.colorIndex = index % ZONE_COLORS.length;
      });
      if (selectedId === zoneId) selectedId = zones.length ? zones[0].id : null;
      changed();
    },
    /** Number of corner points of the polygon being drawn (0 when not drawing). */
    draftPoints: () => draft.length,
    finishDrawing,
    cancelDrawing() {
      draft = [];
      nearStart = false;
      changed();
    },
    /** Removes the last corner point; when nothing is being drawn, reopens the last zone. */
    undo() {
      if (draft.length) {
        draft.pop();
      } else if (zones.length) {
        const last = zones.pop();
        draft = last.points;
        if (selectedId === last.id) selectedId = zones.length ? zones[zones.length - 1].id : null;
      }
      changed();
    },
    clear() {
      zones = [];
      draft = [];
      selectedId = null;
      changed();
    },
    /** Matches the drawing surface to its on-screen size; call after layout changes. */
    resize() {
      const bounds = canvas.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      canvas.width = Math.round(bounds.width);
      canvas.height = Math.round(bounds.height);
      draw();
    },
  };
}
