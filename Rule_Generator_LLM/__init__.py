"""
Rule_Generator_LLM Package
Transforms natural-language surveillance rules into deterministic
object-detection execution plans (DetectionPlan).

Components:
    - RuleCompiler:       LLM-backed compiler that parses operator prompts
                          into structured DetectionPlan JSON.
    - ConditionEvaluator: Runtime evaluator that takes YOLOE detections
                          + zone polygons + plan conditions → boolean verdict.
    - DetectionPlan:      Pydantic schema for compiled plans.
"""

from .schema import (
    DetectionPlan,
    DetectionTarget,
    Condition,
    ConditionType,
    TargetRole,
    AlertLogic,
)
from .compiler import RuleCompiler
from .evaluator import ConditionEvaluator, EvaluationResult

__all__ = [
    "RuleCompiler",
    "ConditionEvaluator",
    "EvaluationResult",
    "DetectionPlan",
    "DetectionTarget",
    "Condition",
    "ConditionType",
    "TargetRole",
    "AlertLogic",
]
