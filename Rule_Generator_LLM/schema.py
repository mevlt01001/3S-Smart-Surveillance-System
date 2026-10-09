"""
DetectionPlan Schema
Pydantic models that define the structured output of the Rule Compiler.
A DetectionPlan is the "compiled" form of a human-language rule —
fully deterministic and executable by YOLOE + ConditionEvaluator.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


class ConditionType(str, enum.Enum):
    """Supported spatial / logical condition types."""
    ZONE_PRESENCE = "zone_presence"
    """Alarm when specified objects ARE inside the zone."""

    ZONE_ABSENCE = "zone_absence"
    """Alarm when a subject is present but required equipment is NOT detected (e.g. no helmet)."""

    OBJECT_COUNT = "object_count"
    """Alarm when object count inside zone exceeds / falls below a threshold."""

    LINE_CROSSING = "line_crossing"
    """Count or alarm when objects cross a virtual line (direction-aware)."""

    LOITERING = "loitering"
    """Alarm when an object remains inside the zone longer than a duration threshold."""

    UNAUTHORIZED_OBJECT = "unauthorized_object"
    """Alarm when a forbidden object type appears inside the zone."""


class TargetRole(str, enum.Enum):
    """Role of a detection target within the plan logic."""
    TRIGGER = "trigger"
    """Object whose presence/absence directly triggers the rule (e.g. person, car)."""

    SUBJECT = "subject"
    """Primary entity being evaluated (e.g. person in PPE check)."""

    REQUIRED_EQUIPMENT = "required_equipment"
    """Equipment that MUST accompany the subject (e.g. helmet, vest)."""

    FORBIDDEN = "forbidden"
    """Object type that must NOT be present in the zone."""

    COUNTER = "counter"
    """Object being counted (e.g. person count, vehicle count)."""


class AlertLogic(str, enum.Enum):
    """How multiple conditions combine to produce an alarm."""
    ANY_CONDITION_MET = "ANY_CONDITION_MET"
    ALL_CONDITIONS_MET = "ALL_CONDITIONS_MET"


# ---------------------------------------------------------------------------
#  Detection Target
# ---------------------------------------------------------------------------
class DetectionTarget(BaseModel):
    """A single object class that YOLOE should detect."""
    class_name: str = Field(
        ...,
        description="Open-vocabulary class name for YOLOE (e.g. 'person', 'safety helmet', 'car')."
    )
    role: TargetRole = Field(
        ...,
        description="Semantic role of this target in the rule logic."
    )


# ---------------------------------------------------------------------------
#  Condition
# ---------------------------------------------------------------------------
class Condition(BaseModel):
    """A single evaluable condition within the detection plan."""
    type: ConditionType = Field(
        ...,
        description="Type of spatial/logical condition."
    )
    targets: Optional[List[str]] = Field(
        default=None,
        description="Class names this condition applies to (for zone_presence, unauthorized_object, object_count)."
    )
    subject: Optional[str] = Field(
        default=None,
        description="Primary subject class (for zone_absence, loitering)."
    )
    required: Optional[List[str]] = Field(
        default=None,
        description="Equipment classes that must accompany the subject (for zone_absence)."
    )
    logic: str = Field(
        default="ANY",
        description="Intra-condition logic: 'ANY' (any target triggers), 'ALL' (all must be present), 'ANY_MISSING' (alarm if any required is missing)."
    )
    min_confidence: float = Field(
        default=0.30,
        description="Minimum YOLOE confidence to consider a detection valid."
    )
    overlap_iou_threshold: Optional[float] = Field(
        default=None,
        description="For absence checks: minimum IoU between subject and equipment bounding boxes to count as 'wearing'."
    )
    count_threshold: Optional[int] = Field(
        default=None,
        description="For object_count: alarm fires when count exceeds this value."
    )
    count_operator: Optional[str] = Field(
        default=None,
        description="Comparison operator for count: 'gt', 'gte', 'lt', 'lte', 'eq'."
    )
    duration_sec: Optional[float] = Field(
        default=None,
        description="For loitering: seconds an object must remain in zone to trigger alarm."
    )


# ---------------------------------------------------------------------------
#  Detection Plan (top-level compiled output)
# ---------------------------------------------------------------------------
class DetectionPlan(BaseModel):
    """
    The fully compiled, deterministic execution plan derived from a
    natural-language rule by the RuleCompiler.
    """
    plan_version: str = Field(
        default="1.0",
        description="Schema version."
    )
    compiled_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 compilation timestamp."
    )
    source_prompt: str = Field(
        ...,
        description="Original natural-language prompt that was compiled."
    )
    detection_targets: List[DetectionTarget] = Field(
        ...,
        description="All object classes YOLOE/Detector must detect for this rule."
    )
    conditions: List[Condition] = Field(
        ...,
        description="List of conditions to evaluate against detections."
    )
    alert_on: AlertLogic = Field(
        default=AlertLogic.ANY_CONDITION_MET,
        description="How conditions combine to produce a final alarm."
    )
    selected_model: str = Field(
        default="yoloe_detector",
        description="Selected detector: 'safety_detector' | 'coco_detector' | 'yoloe_detector'."
    )
    model_path: Optional[str] = Field(
        default=None,
        description="Model weights path or engine reference."
    )
    model_reason: Optional[str] = Field(
        default=None,
        description="Detailed explanation of why this model was selected."
    )
    triton_model_name: Optional[str] = Field(
        default="yoloe_detector",
        description="NVIDIA Triton Server model name ('safety_detector', 'coco_detector', 'yoloe_detector')."
    )
    expanded_classes: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description="Sub-class decomposition for YOLOE (4-5 synonyms/variants per concept to boost recall)."
    )
    model_classes: Optional[List[str]] = Field(
        default=None,
        description="Final list of class labels configured on the detector."
    )
    yoloe_classes: Optional[List[str]] = Field(
        default=None,
        description="Flat deduplicated list of class names to pass to detector."
    )
    compile_logs: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Step-by-step compilation trace logs for developer inspection."
    )
    compile_latency_ms: Optional[float] = Field(
        default=None,
        description="Latency of compilation in milliseconds."
    )
    status: Optional[str] = Field(
        default="success",
        description="Status: 'success' | 'fallback' | 'error'."
    )
    raw_llm_response: Optional[str] = Field(
        default=None,
        description="Raw LLM response."
    )

    def get_yoloe_classes(self) -> List[str]:
        """Returns a deduplicated, ordered list of class names for detector."""
        if self.model_classes:
            return self.model_classes
        if self.yoloe_classes:
            return self.yoloe_classes
        seen = set()
        classes = []
        for t in self.detection_targets:
            if t.class_name not in seen:
                seen.add(t.class_name)
                classes.append(t.class_name)
        return classes

    @property
    def target_classes(self) -> List[str]:
        """Alias for get_yoloe_classes."""
        return self.get_yoloe_classes()

