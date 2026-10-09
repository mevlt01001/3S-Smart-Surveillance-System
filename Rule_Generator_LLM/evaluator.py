"""
ConditionEvaluator — Deterministic Runtime Engine

Takes YOLOE detection results + zone polygon + compiled DetectionPlan conditions
and produces a boolean verdict: should the alarm fire or not?

This module contains ZERO LLM calls. It is pure geometry + logic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


from .schema import Condition, ConditionType, DetectionPlan

# Detector class names as an operator would say them (violation messages are shown to people)
_CLASS_LABELS = {
    "person": "kişi",
    "hardhat": "baret",
    "no-hardhat": "baretsiz kişi",
    "safety vest": "yelek",
    "no-safety vest": "yeleksiz kişi",
    "mask": "maske",
    "no-mask": "maskesiz kişi",
    "safety cone": "koni",
    "machinery": "iş makinesi",
    "vehicle": "araç",
    "car": "araba",
    "truck": "kamyon",
    "forklift": "forklift",
}


def _names(classes) -> str:
    """Readable, de-duplicated list of detector classes: "baretsiz kişi, forklift"."""
    labels = [_CLASS_LABELS.get(str(name).strip().lower(), str(name)) for name in classes]
    return ", ".join(dict.fromkeys(labels))

logger = logging.getLogger("condition_evaluator")


@dataclass
class DetectionBox:
    """Lightweight detection box from YOLOE output."""
    xyxy: List[int]       # [x1, y1, x2, y2] pixel coords
    conf: float           # confidence score
    cls_name: str         # class name

    @property
    def center(self) -> Tuple[float, float]:
        """Returns center (cx, cy) of the bounding box."""
        return (
            (self.xyxy[0] + self.xyxy[2]) / 2.0,
            (self.xyxy[1] + self.xyxy[3]) / 2.0,
        )

    @property
    def area(self) -> float:
        return max(0, self.xyxy[2] - self.xyxy[0]) * max(0, self.xyxy[3] - self.xyxy[1])


@dataclass
class EvaluationResult:
    """Result of evaluating a DetectionPlan against YOLOE detections."""
    alarm: bool = False
    """Whether the alarm should fire."""

    triggered_conditions: List[str] = field(default_factory=list)
    """Human-readable descriptions of which conditions fired."""

    detections_in_zone: List[Dict[str, Any]] = field(default_factory=list)
    """List of detections that were inside the zone polygon."""

    evaluation_time_ms: float = 0.0
    """Time taken for evaluation in milliseconds."""

    detail: Dict[str, Any] = field(default_factory=dict)
    """Additional structured detail per condition type."""


class ConditionEvaluator:
    """
    Evaluates DetectionPlan conditions against YOLOE detection results.

    Usage:
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate(
            plan=compiled_plan,
            detections=[...],        # YOLOE DetectionBox list
            zone_polygon=[(x1,y1), (x2,y2), ...],  # pixel coordinates
            frame_shape=(1080, 1920)
        )
        if result.alarm:
            trigger_alert(result.triggered_conditions)
    """

    def __init__(self):
        # Loitering state: track per-object first-seen timestamps
        # Key: (zone_id, class_name, track_region) → first_seen_timestamp
        self._loiter_state: Dict[str, float] = {}
        # Zone absence state: track vacancy/desertion start timestamps
        # Key: (zone_id, target_classes) → first_absent_timestamp
        self._absence_state: Dict[str, float] = {}

    def evaluate(
        self,
        plan: DetectionPlan,
        detections: List[DetectionBox],
        zone_polygon: Optional[List[Tuple[float, float]]] = None,
        frame_shape: Optional[Tuple[int, int]] = None,
        zone_id: Optional[str] = None,
    ) -> EvaluationResult:
        """
        Evaluates all conditions in the plan against current detections.

        Args:
            plan: Compiled DetectionPlan.
            detections: List of DetectionBox from YOLOE.
            zone_polygon: Polygon points in pixel coordinates [(x, y), ...].
                          If None, entire frame is treated as the zone.
            frame_shape: (height, width) of the frame, used if polygon is
                         in normalized [0,1] coordinates.
            zone_id: Optional zone identifier for loitering state tracking.

        Returns:
            EvaluationResult with alarm status and details.
        """
        t0 = time.perf_counter()

        result = EvaluationResult()

        # Convert normalized polygon to pixel coords if needed
        poly_px = self._resolve_polygon(zone_polygon, frame_shape)

        # Filter detections that are inside the zone polygon
        in_zone: List[DetectionBox] = []
        out_zone: List[DetectionBox] = []

        for det in detections:
            if poly_px is None or self.is_detection_in_zone(det, poly_px):
                in_zone.append(det)
                result.detections_in_zone.append({
                    "class": det.cls_name,
                    "confidence": round(det.conf, 3),
                    "center": det.center,
                    "bbox": det.xyxy,
                })
            else:
                out_zone.append(det)

        # Evaluate each condition
        condition_results = []
        for cond in plan.conditions:
            fired, desc, detail = self._evaluate_condition(cond, in_zone, zone_id)
            condition_results.append((fired, desc, detail))
            if fired:
                result.triggered_conditions.append(desc)
                result.detail[cond.type.value] = detail

        # Apply alert logic
        if plan.alert_on.value == "ANY_CONDITION_MET":
            result.alarm = any(fired for fired, _, _ in condition_results)
        else:  # ALL_CONDITIONS_MET
            result.alarm = all(fired for fired, _, _ in condition_results) and len(condition_results) > 0

        result.evaluation_time_ms = round((time.perf_counter() - t0) * 1000, 2)
        return result

    # ------------------------------------------------------------------
    #  Condition Evaluators
    # ------------------------------------------------------------------

    def _evaluate_condition(
        self,
        cond: Condition,
        in_zone: List[DetectionBox],
        zone_id: Optional[str],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Dispatches to the appropriate condition evaluator.
        Returns: (fired: bool, description: str, detail: dict)
        """
        if cond.type == ConditionType.ZONE_PRESENCE:
            return self._eval_zone_presence(cond, in_zone)
        elif cond.type == ConditionType.ZONE_ABSENCE:
            return self._eval_zone_absence(cond, in_zone, zone_id)
        elif cond.type == ConditionType.OBJECT_COUNT:
            return self._eval_object_count(cond, in_zone)
        elif cond.type == ConditionType.UNAUTHORIZED_OBJECT:
            return self._eval_unauthorized_object(cond, in_zone)
        elif cond.type == ConditionType.LOITERING:
            return self._eval_loitering(cond, in_zone, zone_id)
        elif cond.type == ConditionType.LINE_CROSSING:
            return self._eval_line_crossing(cond, in_zone)
        else:
            return False, f"Bilinmeyen koşul tipi: {cond.type}", {}

    def _eval_zone_presence(
        self, cond: Condition, in_zone: List[DetectionBox]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Fires when target objects are detected inside the zone."""
        targets = {t.strip().lower() for t in (cond.targets or [])}
        conf_thr = cond.min_confidence or 0.30

        matched = [
            d for d in in_zone
            if d.cls_name.strip().lower() in targets and d.conf >= conf_thr
        ]

        if cond.logic == "ANY":
            fired = len(matched) > 0
        elif cond.logic == "ALL":
            found_classes = {d.cls_name.strip().lower() for d in matched}
            fired = targets.issubset(found_classes)
        else:
            fired = len(matched) > 0

        desc = ""
        if fired:
            classes_found = list({d.cls_name for d in matched})
            desc = f"Bölgede görüldü: {_names(classes_found)}"

        detail = {
            "matched_count": len(matched),
            "matched_classes": list({d.cls_name for d in matched}),
        }
        return fired, desc, detail

    def _eval_zone_absence(
        self, cond: Condition, in_zone: List[DetectionBox], zone_id: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Dual-mode zone absence evaluator:
        1. PPE / equipment check: When 'required' equipment is specified, fires when
           subject IS present but required equipment is missing on/near subject.
        2. Target vacancy / departure check: When 'required' is empty/None, fires when
           the target object (e.g. Person/guard) is absent from the zone, optionally
           enforcing duration_sec (e.g. 'ayrılırsa', 'kimse yoksa').
        """
        # Case 1: PPE / Equipment check if required equipment is specified
        if cond.required and len(cond.required) > 0:
            subject_cls = (cond.subject or "person").strip().lower()
            required_cls = {r.strip().lower() for r in cond.required}
            conf_thr = cond.min_confidence or 0.25
            iou_thr = cond.overlap_iou_threshold or 0.3

            # Find subjects in zone
            subjects = [d for d in in_zone if d.cls_name.strip().lower() == subject_cls and d.conf >= conf_thr]
            if not subjects:
                return False, "", {"subjects_found": 0}

            # Find equipment in zone
            equipment = [d for d in in_zone if d.cls_name.strip().lower() in required_cls and d.conf >= conf_thr]

            # For each subject, check if ALL required equipment overlaps
            violating_subjects = []
            for subj in subjects:
                missing = []
                for req_class in required_cls:
                    matching_equip = [
                        eq for eq in equipment
                        if eq.cls_name.strip().lower() == req_class
                        and self._compute_iou(subj.xyxy, eq.xyxy) >= iou_thr
                    ]
                    if not matching_equip:
                        missing.append(req_class)

                if cond.logic == "ANY_MISSING" and len(missing) > 0:
                    violating_subjects.append({"subject": subj, "missing": missing})
                elif cond.logic == "ALL" and len(missing) == len(required_cls):
                    violating_subjects.append({"subject": subj, "missing": missing})

            fired = len(violating_subjects) > 0
            desc = ""
            if fired:
                all_missing = set()
                for v in violating_subjects:
                    all_missing.update(v["missing"])
                desc = (
                    f"İSG İhlali: {len(violating_subjects)} kişide "
                    f"eksik ekipman: {', '.join(all_missing)}"
                )

            detail = {
                "subjects_found": len(subjects),
                "equipment_found": len(equipment),
                "violating_count": len(violating_subjects),
                "missing_equipment": list({
                    eq for v in violating_subjects for eq in v["missing"]
                }),
            }
            return fired, desc, detail

        # Case 2: Pure Zone Absence / Vacancy / Desertion Check
        # (e.g. "Berat burdan 2 saniye ayrılırsa bana uyarı ver" / "Bu alanda kimse yoksa uyarı ver")
        target_classes = [t.strip().lower() for t in (cond.targets or [cond.subject or "person"])]
        if not target_classes:
            target_classes = ["person"]

        conf_thr = cond.min_confidence or 0.25
        present_targets = [
            d for d in in_zone
            if d.cls_name.strip().lower() in target_classes and d.conf >= conf_thr
        ]

        state_key = f"absence_{zone_id or 'default'}_{'_'.join(sorted(target_classes))}"
        now = time.time()

        if present_targets:
            # Target is present in zone! Reset absence timer.
            self._absence_state.pop(state_key, None)
            return False, "", {"target_present": True, "count": len(present_targets)}

        # Target is NOT in zone!
        if state_key not in self._absence_state:
            self._absence_state[state_key] = now

        absence_sec = now - self._absence_state[state_key]
        duration_req = cond.duration_sec or 0.0

        if absence_sec >= duration_req:
            fired = True
            desc = f"{_names(target_classes).capitalize()} {absence_sec:.0f} saniyedir bölgede yok"
            detail = {
                "target_present": False,
                "absence_duration_sec": round(absence_sec, 1),
                "threshold_duration_sec": duration_req,
                "targets": target_classes,
            }
            return fired, desc, detail
        else:
            return False, "", {
                "target_present": False,
                "absence_duration_sec": round(absence_sec, 1),
                "waiting_for_sec": duration_req,
            }

    def _eval_object_count(
        self, cond: Condition, in_zone: List[DetectionBox]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Fires when object count exceeds/falls below threshold."""
        targets = {t.strip().lower() for t in (cond.targets or [])}
        conf_thr = cond.min_confidence or 0.30
        threshold = cond.count_threshold or 0
        operator = (cond.count_operator or "gt").lower()

        matched = [d for d in in_zone if d.cls_name.strip().lower() in targets and d.conf >= conf_thr]
        count = len(matched)

        ops = {
            "gt": count > threshold,
            "gte": count >= threshold,
            "lt": count < threshold,
            "lte": count <= threshold,
            "eq": count == threshold,
        }
        fired = ops.get(operator, count > threshold)

        desc = ""
        if fired:
            desc = f"Bölgedeki sayı sınırı aşıldı: {count} {_names(targets)}"

        detail = {"count": count, "threshold": threshold, "operator": operator}
        return fired, desc, detail

    def _eval_unauthorized_object(
        self, cond: Condition, in_zone: List[DetectionBox]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Fires when forbidden object types are detected in zone."""
        targets = {t.strip().lower() for t in (cond.targets or [])}
        conf_thr = cond.min_confidence or 0.30

        matched = [d for d in in_zone if d.cls_name.strip().lower() in targets and d.conf >= conf_thr]
        fired = len(matched) > 0

        desc = ""
        if fired:
            classes = list({d.cls_name for d in matched})
            desc = f"Bölgede olmaması gereken görüldü: {_names(classes)}"

        detail = {"unauthorized_count": len(matched)}
        return fired, desc, detail

    def _eval_loitering(
        self, cond: Condition, in_zone: List[DetectionBox], zone_id: Optional[str]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Fires when subject stays in zone longer than duration_sec.
        Uses a presence-based timer with a 1.5s grace period for short detection drops.
        """
        subject_cls = (cond.subject or "person").strip().lower()
        target_classes = {t.strip().lower() for t in (cond.targets or [])}
        if subject_cls:
            target_classes.add(subject_cls)

        conf_thr = cond.min_confidence or 0.30
        duration_thr = cond.duration_sec or 30.0

        subjects = [
            d for d in in_zone
            if (d.cls_name.strip().lower() in target_classes) and d.conf >= conf_thr
        ]
        now = time.time()
        state_key = f"{zone_id or 'default'}_{subject_cls}"

        if subjects:
            if state_key not in self._loiter_state or not isinstance(self._loiter_state[state_key], dict):
                self._loiter_state[state_key] = {"start": now, "last_seen": now}
            else:
                self._loiter_state[state_key]["last_seen"] = now

            elapsed = now - self._loiter_state[state_key]["start"]
            fired = elapsed >= duration_thr
        else:
            # Grace period of 1.5 seconds to handle detector frame drops
            if state_key in self._loiter_state and isinstance(self._loiter_state[state_key], dict):
                time_since_seen = now - self._loiter_state[state_key]["last_seen"]
                if time_since_seen <= 1.5:
                    elapsed = now - self._loiter_state[state_key]["start"]
                    fired = elapsed >= duration_thr
                else:
                    self._loiter_state.pop(state_key, None)
                    fired = False
                    elapsed = 0.0
            else:
                self._loiter_state.pop(state_key, None)
                fired = False
                elapsed = 0.0

        desc = ""
        if fired:
            desc = f"{_names([subject_cls]).capitalize()} {elapsed:.0f} saniyedir bölgede bekliyor"

        detail = {"elapsed_sec": round(elapsed, 1), "threshold_sec": duration_thr}
        return fired, desc, detail

    def _eval_line_crossing(
        self, cond: Condition, in_zone: List[DetectionBox]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Line crossing: Currently returns object presence near line.
        Full directional tracking requires multi-frame tracking (future work).
        """
        targets = {t.strip().lower() for t in (cond.targets or [])}
        conf_thr = cond.min_confidence or 0.30

        matched = [d for d in in_zone if d.cls_name.strip().lower() in targets and d.conf >= conf_thr]
        fired = len(matched) > 0

        desc = ""
        if fired:
            desc = f"Hattı geçen var: {_names(targets)}"

        detail = {"near_line_count": len(matched)}
        return fired, desc, detail

    # ------------------------------------------------------------------
    #  Geometry Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_polygon(
        polygon: Optional[List[Tuple[float, float]]],
        frame_shape: Optional[Tuple[int, int]],
    ) -> Optional[List[Tuple[float, float]]]:
        """
        Converts polygon to pixel coordinates if values are in [0,1] range.
        """
        if polygon is None or len(polygon) < 3:
            return None

        # Check if normalized (all values between 0 and 1)
        all_normalized = all(
            0 <= p[0] <= 1 and 0 <= p[1] <= 1 for p in polygon
        )

        if all_normalized and frame_shape:
            h, w = frame_shape
            return [(p[0] * w, p[1] * h) for p in polygon]

        return polygon

    def is_detection_in_zone(
        self,
        det: Any,
        polygon: List[Tuple[float, float]],
    ) -> bool:
        """
        Determines if a detected bounding box is inside or interacting with the zone polygon.
        Checks:
        1. Bounding box center
        2. Bottom-center (feet / floor contact point)
        3. Upper-torso (standing or leaning person)
        4. Lower-torso / pelvis (seated person)
        """
        if polygon is None or len(polygon) < 3:
            return True

        cx = (det.xyxy[0] + det.xyxy[2]) / 2.0
        cy = (det.xyxy[1] + det.xyxy[3]) / 2.0
        h = max(1.0, float(det.xyxy[3] - det.xyxy[1]))

        # 1. Geometric center
        if self._point_in_polygon((cx, cy), polygon):
            return True
        # 2. Base / feet (crucial for ground zones)
        if self._point_in_polygon((cx, float(det.xyxy[3])), polygon):
            return True
        # 3. Upper body / torso (at 25% height from top)
        if self._point_in_polygon((cx, det.xyxy[1] + h * 0.25), polygon):
            return True
        # 4. Hips / seated center (at 75% height)
        if self._point_in_polygon((cx, det.xyxy[1] + h * 0.75), polygon):
            return True

        return False

    @staticmethod
    def _point_in_polygon(
        point: Tuple[float, float],
        polygon: List[Tuple[float, float]],
    ) -> bool:
        """
        Ray-casting algorithm for point-in-polygon test.
        """
        x, y = point
        n = len(polygon)
        inside = False

        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]

            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i

        return inside

    @staticmethod
    def _compute_iou(box_a: List[int], box_b: List[int]) -> float:
        """
        Computes Intersection over Union between two [x1, y1, x2, y2] boxes.
        Used for checking if equipment overlaps with a person (PPE check).
        """
        x1 = max(box_a[0], box_b[0])
        y1 = max(box_a[1], box_b[1])
        x2 = min(box_a[2], box_b[2])
        y2 = min(box_a[3], box_b[3])

        inter_area = max(0, x2 - x1) * max(0, y2 - y1)
        if inter_area == 0:
            return 0.0

        area_a = max(0, box_a[2] - box_a[0]) * max(0, box_a[3] - box_a[1])
        area_b = max(0, box_b[2] - box_b[0]) * max(0, box_b[3] - box_b[1])

        # Use minimum area (not union) for PPE overlap: helmet bbox is much
        # smaller than person bbox, so standard IoU would always be very low.
        # "Overlap ratio" = intersection / smaller_box_area is more appropriate.
        min_area = min(area_a, area_b)
        if min_area == 0:
            return 0.0

        return inter_area / min_area
