"""
Live Detection & Rule Evaluation Service
Runs real-time object detection and spatial rule evaluation on live camera feeds
using NVIDIA Triton Server (safety_detector, coco_detector, yoloe_detector) and ConditionEvaluator.
Provides real-time bounding boxes, labels, and rule alarm telemetry for the Live Video Wall.
Also runs SSIM-based change detection for emergency exit / fire cabinet zones.
"""

import logging
import threading
import time
from typing import Dict, List, Optional, Any, Tuple


from Object_Detection import YOLODetector
from Rule_Generator_LLM.evaluator import ConditionEvaluator
from Rule_Generator_LLM.schema import DetectionPlan
from WebInterface.backend.camera_service import camera_service
from WebInterface.backend.rules_service import rules_service
from WebInterface.backend.change_detector import change_detector
from WebInterface.backend.settings_service import settings_service
from WebInterface.backend.paths import SHUTTING_DOWN

logger = logging.getLogger("live_detection_service")

PPE_KEYWORDS = ("hardhat", "no-hardhat", "vest", "safety vest", "no-safety vest", "mask", "no-mask")


class LiveDetectionService:
    # Upper bound for full evaluation passes per second. The loop additionally only
    # re-evaluates a camera when it delivered a new frame.
    MIN_CYCLE_SEC = 0.08
    # Sleep while no camera has an enabled rule (the loop must never spin).
    IDLE_SLEEP_SEC = 0.5
    # Minimum spacing of journal entries for the same camera + rule.
    RULE_LOG_COOLDOWN_SEC = 30.0

    def __init__(self, triton_url: Optional[str] = None):
        self.triton_url = triton_url or self._configured_triton_url()
        self.detector: Optional[YOLODetector] = None
        self.evaluator = ConditionEvaluator()
        self.latest_detections: Dict[str, Dict[str, Any]] = {}
        self._last_rule_log: Dict[Tuple[str, str], float] = {}
        self._plan_cache: Dict[Tuple[str, str], Tuple[float, Optional[DetectionPlan], set]] = {}
        self._last_frame_seq: Dict[str, int] = {}
        self._lock = threading.Lock()
        self.running = True
        # Smoothed latency of real inferences; stays None until one actually ran
        self.last_latency_ms: Optional[float] = None
        self.last_inference_ts: float = 0.0
        self.detector_ready: bool = False
        self._last_alive_check: float = 0.0
        self._next_connect_at: float = 0.0
        self._connect_backoff: float = 2.0
        self._last_connect_error: Optional[str] = None

        # Background live evaluation loop
        self.worker_thread = threading.Thread(
            target=self._detection_loop, daemon=True, name="LiveDetectionWorker"
        )
        self.worker_thread.start()

    # ------------------------------------------------------------------ Triton
    @staticmethod
    def _configured_triton_url() -> str:
        return settings_service.get_section("anomaly").get("triton_url") or "localhost:8000"

    def reload_settings(self):
        """Applies a changed AI server address without restarting the service."""
        url = self._configured_triton_url()
        if url != self.triton_url:
            self.triton_url = url
            self.detector = None
            self.detector_ready = False
            self._next_connect_at = 0.0
            self._connect_backoff = 2.0

    def _ensure_detector(self) -> bool:
        """
        Returns True when the inference backend is reachable. Reconnects with a growing
        back-off and never re-creates heavyweight state while the AI server is down.
        """
        now = time.time()
        if self.detector is not None and self.detector_ready:
            if now - self._last_alive_check < 5.0:
                return True
            self._last_alive_check = now
            try:
                self.detector_ready = bool(self.detector.backend and self.detector.backend.is_alive())
            except Exception:
                self.detector_ready = False
            if self.detector_ready:
                return True

        if now < self._next_connect_at:
            return False

        try:
            if self.detector is None:
                self.detector = YOLODetector(
                    backend="triton",
                    triton_url=self.triton_url,
                    conf_thres=0.20,
                    iou_thres=0.45,
                )
                self.detector_ready = True
            else:
                self.detector_ready = self.detector.reconnect()
        except Exception as e:
            # Logged once per distinct cause: a silent failure here would leave every rule
            # "active" on screen while nothing is actually being detected.
            reason = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"
            if reason != self._last_connect_error:
                self._last_connect_error = reason
                logger.warning(f"[LiveDetectionService] Nesne tespit motoru başlatılamadı: {reason}")
            self.detector_ready = False

        if self.detector_ready:
            self._connect_backoff = 2.0
            self._last_alive_check = now
            self._last_connect_error = None
            logger.info("[LiveDetectionService] YOLODetector Triton modunda hazır.")
        else:
            self._next_connect_at = now + self._connect_backoff
            self._connect_backoff = min(self._connect_backoff * 1.5, 15.0)
        return self.detector_ready

    # -------------------------------------------------------------- plan cache
    def _get_plan(self, rule: Dict[str, Any], zone: Dict[str, Any]) -> Tuple[Optional[DetectionPlan], set]:
        """
        Returns the validated DetectionPlan of a zone plus the set of class names relevant
        for it. Parsing a stored plan (with its compile logs) is costly, so the result is
        cached until the rule changes instead of being rebuilt for every single frame.
        """
        key = (rule.get("id", ""), zone.get("id", ""))
        version = rule.get("updated_at", 0.0)
        cached = self._plan_cache.get(key)
        if cached and cached[0] == version:
            return cached[1], cached[2]

        plan: Optional[DetectionPlan] = None
        classes: set = set()
        dp_data = zone.get("detection_plan")
        if dp_data:
            try:
                plan = DetectionPlan(**dp_data) if isinstance(dp_data, dict) else dp_data
            except Exception:
                plan = None

        if plan is not None:
            targets_lower = {t.class_name.strip().lower() for t in (getattr(plan, "detection_targets", None) or [])}
            cond_targets = set()
            for cond in (getattr(plan, "conditions", None) or []):
                for t in (getattr(cond, "targets", None) or []):
                    cond_targets.add(t.strip().lower())
                for r in (getattr(cond, "required", None) or []):
                    cond_targets.add(r.strip().lower())
            all_t = targets_lower | cond_targets

            # Smart model selection: If rule only targets 'person' without PPE equipment requirements,
            # ensure coco_detector is used so ALL pedestrians across all camera angles are captured.
            has_ppe = any(k in all_t for k in PPE_KEYWORDS)
            if "person" in all_t and not has_ppe:
                plan.selected_model = "coco_detector"
                plan.triton_model_name = "coco_detector"

            # Exactly which classes are relevant to this rule (used to filter the HUD overlay)
            classes = {c.strip().lower() for c in plan.get_yoloe_classes()} | all_t
            for cond in (getattr(plan, "conditions", None) or []):
                if getattr(cond, "subject", None):
                    classes.add(cond.subject.strip().lower())

            # Paired context classes (e.g. if checking hardhat, also allow compliant Hardhat)
            if "no-hardhat" in classes:
                classes.add("hardhat")
            if "hardhat" in classes:
                classes.add("no-hardhat")
            if "no-safety vest" in classes or "no-vest" in classes:
                classes.add("safety vest")
            if "safety vest" in classes:
                classes.add("no-safety vest")

        self._plan_cache[key] = (version, plan, classes)
        return plan, classes

    # --------------------------------------------------------------- main loop
    def _publish(self, cam_id: str, payload: Dict[str, Any]):
        with self._lock:
            self.latest_detections[cam_id] = payload

    def _empty_state(self, cam_id: str, has_rules: bool, stream_live: bool = True) -> Dict[str, Any]:
        return {
            "camera_id": cam_id,
            "timestamp": time.time(),
            "has_rules": has_rules,
            "stream_live": stream_live,
            "detector_ready": self.detector_ready,
            "alarm": False,
            "alarm_text": "",
            "detections_count": 0,
            "detections": [],
            "change_results": [],
        }

    def _detection_loop(self):
        """Continuously checks live camera frames and evaluates active rules."""
        while self.running and not SHUTTING_DOWN.is_set():
            cycle_start = time.perf_counter()
            try:
                cameras = camera_service.get_all()
                known_ids = {c.get("id") for c in cameras}

                # Forget cameras that were removed from the fleet
                with self._lock:
                    for stale_id in [cid for cid in self.latest_detections if cid not in known_ids]:
                        del self.latest_detections[stale_id]
                        self._last_frame_seq.pop(stale_id, None)

                active: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
                for cam in cameras:
                    cam_id = cam.get("id")
                    if not cam_id:
                        continue
                    cam_rules = rules_service.get_all(camera_id=cam_id, enabled_only=True)
                    if cam_rules:
                        active.append((cam, cam_rules))
                    else:
                        # Only run object detections on cameras with active rules
                        prev = self.latest_detections.get(cam_id)
                        if prev is None or prev.get("has_rules"):
                            self._publish(cam_id, self._empty_state(cam_id, has_rules=False))
                            self._last_frame_seq.pop(cam_id, None)

                if not active:
                    time.sleep(self.IDLE_SLEEP_SEC)
                    continue

                needs_detector = any(
                    z.get("zone_type", "detection") != "change_detection" and z.get("detection_plan")
                    for _, cam_rules in active for r in cam_rules for z in r.get("zones", [])
                )
                detector_ok = self._ensure_detector() if needs_detector else False

                for cam, cam_rules in active:
                    if not self.running:
                        break
                    self._process_camera(cam, cam_rules, detector_ok)

            except Exception as e:
                logger.error(f"[LiveDetectionService] Loop error: {e}")
                time.sleep(1.0)

            # Pace the loop: never busy-spin, leave the GIL to the video workers
            elapsed = time.perf_counter() - cycle_start
            time.sleep(max(0.01, self.MIN_CYCLE_SEC - elapsed))

    def _process_camera(self, cam: Dict[str, Any], cam_rules: List[Dict[str, Any]], detector_ok: bool):
        cam_id = cam["id"]

        worker = camera_service.get_worker(cam_id)
        if worker is None:
            s_uri = cam.get("stream_uri")
            if s_uri and s_uri.startswith("rtsp://"):
                worker = camera_service.get_or_start_worker(cam_id, s_uri)
        if worker is None:
            return

        _, seq, _ = worker.get_frame_info(touch=True)
        if not worker.is_live():
            # Never evaluate rules on a frozen frame of a camera that lost its signal
            prev = self.latest_detections.get(cam_id)
            if prev is None or prev.get("stream_live", True):
                self._publish(cam_id, self._empty_state(cam_id, has_rules=True, stream_live=False))
            self._last_frame_seq.pop(cam_id, None)
            return

        if self._last_frame_seq.get(cam_id) == seq:
            return  # no new frame since the last evaluation
        bgr_frame = worker.get_bgr_frame(touch=True)
        if bgr_frame is None:
            return
        self._last_frame_seq[cam_id] = seq

        h, w = bgr_frame.shape[:2]
        is_alarm = False
        triggered_conditions: List[str] = []
        triggered_rules: Dict[str, Dict[str, Any]] = {}
        all_detections: List[Dict[str, Any]] = []
        change_results: List[Dict[str, Any]] = []
        # One GPU round-trip per (model, class list) per frame, shared by all zones that use it
        infer_cache: Dict[Tuple[str, Optional[Tuple[str, ...]]], Any] = {}

        def _mark(rule: Dict[str, Any], descriptions: List[str]):
            entry = triggered_rules.setdefault(rule.get("id", ""), {"rule": rule, "conditions": []})
            entry["conditions"].extend(descriptions)

        for rule in cam_rules:
            for zone in rule.get("zones", []):
                zone_pts = zone.get("points", [])

                # ----------------------------------------------------------------
                # CHANGE DETECTION zones (SSIM – no YOLO inference)
                # ----------------------------------------------------------------
                if zone.get("zone_type", "detection") == "change_detection":
                    if zone_pts and len(zone_pts) >= 3:
                        cr = change_detector.check_frame(
                            camera_id=cam_id,
                            zone_id=zone.get("id", ""),
                            frame_bgr=bgr_frame,
                            points_normalized=zone_pts,
                            frame_wh=(w, h),
                        )
                        change_results.append(cr)
                        if cr["alarm"]:
                            is_alarm = True
                            z_name = zone.get("name", cr["zone_name"] or "Bölge")
                            desc = f"{z_name}: bölgede engel veya değişiklik var"
                            triggered_conditions.append(desc)
                            _mark(rule, [desc])
                    continue

                # ----------------------------------------------------------------
                # OBJECT DETECTION zones (YOLO inference)
                # ----------------------------------------------------------------
                if not detector_ok:
                    continue
                plan, rule_target_classes = self._get_plan(rule, zone)
                if plan is None:
                    continue

                target_model = getattr(plan, "triton_model_name", None) or getattr(plan, "selected_model", "yoloe_detector")
                if target_model in ("safety_detector", "coco_detector"):
                    cache_key = (target_model, None)
                else:
                    cache_key = (target_model, tuple(plan.get_yoloe_classes()))

                det_result = infer_cache.get(cache_key)
                if det_result is None:
                    try:
                        t_infer_0 = time.perf_counter()
                        det_result = self.detector.detect_with_plan(bgr_frame, plan)
                        lat_infer_ms = (time.perf_counter() - t_infer_0) * 1000.0
                        self.last_inference_ts = time.time()
                        prev_l = self.last_latency_ms
                        self.last_latency_ms = round(
                            lat_infer_ms if prev_l is None else 0.25 * lat_infer_ms + 0.75 * prev_l, 1
                        )
                        infer_cache[cache_key] = det_result
                    except Exception as e:
                        logger.warning(f"[LiveDetection] Inference error on {cam_id} ({target_model}): {e}")
                        # Force a fresh liveness check on the next pass
                        self._last_alive_check = 0.0
                        continue

                # Zone polygon points (normalized)
                zone_poly = None
                if zone_pts and len(zone_pts) >= 3:
                    zone_poly = [(p.get("x", 0.0), p.get("y", 0.0)) for p in zone_pts]
                zone_poly_px = [(p[0] * w, p[1] * h) for p in zone_poly] if zone_poly else None

                # Evaluate condition
                eval_res = self.evaluator.evaluate(
                    plan=plan,
                    detections=det_result.boxes,
                    zone_polygon=zone_poly,
                    frame_shape=(h, w),
                    zone_id=zone.get("id"),
                )

                if eval_res.alarm:
                    is_alarm = True
                    triggered_conditions.extend(eval_res.triggered_conditions)
                    _mark(rule, eval_res.triggered_conditions)

                # Format detections - ONLY include classes that the rule is inspecting!
                for b in det_result.boxes:
                    b_cls_lower = b.cls_name.strip().lower()
                    if rule_target_classes and b_cls_lower not in rule_target_classes:
                        # Skip unrelated objects (e.g. machinery or cones if rule is only about hardhat/person)
                        continue

                    in_this_zone = True
                    if zone_poly_px:
                        in_this_zone = self.evaluator.is_detection_in_zone(b, zone_poly_px)

                    # Check if this box is a direct violation
                    is_violation = False
                    if b.cls_name in ("NO-Hardhat", "NO-Safety Vest", "NO-Mask"):
                        if b_cls_lower in rule_target_classes:
                            is_violation = True
                    elif eval_res.alarm and in_this_zone:
                        if not rule_target_classes or b_cls_lower in rule_target_classes:
                            is_violation = True

                    all_detections.append({
                        "class_name": b.cls_name,
                        "confidence": round(float(b.conf), 3),
                        "bbox": b.xyxy,
                        "bbox_normalized": [
                            round(b.xyxy[0] / w, 4),
                            round(b.xyxy[1] / h, 4),
                            round(b.xyxy[2] / w, 4),
                            round(b.xyxy[3] / h, 4),
                        ],
                        "in_zone": in_this_zone,
                        "zone_name": zone.get("name", "Bölge"),
                        "is_violation": is_violation,
                        "rule_title": rule.get("title", ""),
                    })

        # Deduplicate overlapping detections of same class
        unique_detections = self._deduplicate_detections(all_detections)
        alarm_summary = " | ".join(dict.fromkeys(triggered_conditions)) if triggered_conditions else ""

        self._publish(cam_id, {
            "camera_id": cam_id,
            "timestamp": time.time(),
            "has_rules": True,
            "stream_live": True,
            "detector_ready": detector_ok,
            "alarm": is_alarm,
            "alarm_text": alarm_summary,
            "detections_count": len(unique_detections),
            "detections": unique_detections,
            "change_results": change_results,
        })

        # Record each violated rule into the persistent journal (with an MP4 evidence clip),
        # attributed to the rule that actually fired, at most once per cooldown window.
        if is_alarm:
            now_log = time.time()
            for rule_id, info in triggered_rules.items():
                key = (cam_id, rule_id)
                if now_log - self._last_rule_log.get(key, 0.0) < self.RULE_LOG_COOLDOWN_SEC:
                    continue
                self._last_rule_log[key] = now_log
                rule = info["rule"]
                message = " | ".join(dict.fromkeys(info["conditions"])) or "Kural ihlali tespit edildi"
                try:
                    from WebInterface.backend.anomaly_service import anomaly_service
                    anomaly_service.record_rule_violation(
                        camera_id=cam_id,
                        rule_title=rule.get("title", "Güvenlik Kuralı"),
                        message=message,
                        severity=rule.get("severity", "warning"),
                    )
                except Exception as ex:
                    logger.error(f"[LiveDetectionService] Olay günlüğüne yazma hatası: {ex}")

    @staticmethod
    def _deduplicate_detections(detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicates redundant detections of the same class with high spatial overlap."""
        if len(detections) <= 1:
            return detections

        out = []
        for d in detections:
            # Check if similar box exists
            b = d["bbox"]
            dup = None
            for existing in out:
                if existing["class_name"] == d["class_name"]:
                    eb = existing["bbox"]
                    # Calculate IoU
                    xA = max(b[0], eb[0])
                    yA = max(b[1], eb[1])
                    xB = min(b[2], eb[2])
                    yB = min(b[3], eb[3])
                    inter = max(0, xB - xA) * max(0, yB - yA)
                    if inter > 0:
                        areaA = (b[2] - b[0]) * (b[3] - b[1])
                        areaB = (eb[2] - eb[0]) * (eb[3] - eb[1])
                        iou = inter / float(areaA + areaB - inter)
                        if iou > 0.6:
                            dup = existing
                            break
            if dup is None:
                out.append(d)
            elif d.get("is_violation") and not dup.get("is_violation"):
                # The same object seen through two rules: keep it flagged if either rule is violated
                dup["is_violation"] = True
                dup["rule_title"] = d.get("rule_title", dup.get("rule_title"))
                dup["zone_name"] = d.get("zone_name", dup.get("zone_name"))
        return out

    def get_detections(self, camera_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns latest detection results for all or a specific camera."""
        with self._lock:
            if camera_id:
                return self.latest_detections.get(camera_id) or self._empty_state(camera_id, has_rules=False)
            return dict(self.latest_detections)


# Global singleton instance
live_detection_service = LiveDetectionService()
