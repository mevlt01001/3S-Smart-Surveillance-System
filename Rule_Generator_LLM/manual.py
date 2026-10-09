"""
Rules without the language model: builds a detection plan from the choices of the rule form
("what to look for", "when to alert", a number) and says in plain Turkish what any plan does.

The same sentence is shown for plans the language model compiled, so the operator always sees
what the system understood, whichever way the rule was written.
"""

from typing import Any, Dict, List, Optional

from .evaluator import _names
from .schema import DetectionPlan

# What the form offers to look for: label, detector and the classes that stand for it
SUBJECTS: Dict[str, Dict[str, Any]] = {
    "person": {"label": "Kişi", "model": "coco_detector", "classes": ["person"]},
    "vehicle": {"label": "Araç", "model": "coco_detector", "classes": ["car", "truck", "bus", "motorcycle"]},
    "no_hardhat": {"label": "Baretsiz kişi", "model": "safety_detector", "classes": ["NO-Hardhat"]},
    "no_vest": {"label": "Yeleksiz kişi", "model": "safety_detector", "classes": ["NO-Safety Vest"]},
    "forklift": {"label": "Forklift", "model": "yoloe_detector",
                 "classes": ["forklift", "reach truck", "pallet jack", "industrial lifter", "fork truck"]},
    "bag": {"label": "Çanta veya bavul", "model": "coco_detector", "classes": ["backpack", "suitcase", "handbag"]},
}

# When to alert: label, whether a number is needed and what it means
CONDITIONS: Dict[str, Dict[str, Any]] = {
    "presence": {"label": "Bölgede görülünce", "value": None},
    "waiting": {"label": "Bölgede belirli bir süreden uzun kalınca", "value": "seconds"},
    "absence": {"label": "Bölgede belirli bir süre hiç yokken", "value": "seconds"},
    "more_than": {"label": "Bölgedeki sayı bir sınırı geçince", "value": "count"},
    "fewer_than": {"label": "Bölgedeki sayı bir sınırın altına inince", "value": "count"},
}
VALUE_LIMITS = {"seconds": (1, 86400), "count": (0, 500)}


def build_plan(choice: Dict[str, Any]) -> DetectionPlan:
    """The plan for `{"subject", "condition", "value"}`. Raises ValueError (message for the user) for a bad choice."""
    subject = SUBJECTS.get(str(choice.get("subject")))
    condition_key = str(choice.get("condition"))
    condition = CONDITIONS.get(condition_key)
    if not subject or not condition:
        raise ValueError("Kural için neyin aranacağını ve ne zaman haber verileceğini seçin.")
    value = 0.0
    if condition["value"]:
        low, high = VALUE_LIMITS[condition["value"]]
        try:
            value = float(choice.get("value"))
        except (TypeError, ValueError):
            raise ValueError("Süre ya da sayı için bir değer girin.") from None
        if not low <= value <= high:
            raise ValueError(f"Değer {low} ile {high} arasında olmalı.")

    classes: List[str] = subject["classes"]
    base = {"targets": classes, "min_confidence": 0.30}
    if condition_key == "presence":
        rule, role = dict(base, type="zone_presence", logic="ANY"), "forbidden"
    elif condition_key == "waiting":
        rule, role = dict(base, type="loitering", subject=classes[0], duration_sec=value), "subject"
    elif condition_key == "absence":
        rule, role = dict(base, type="zone_absence", subject=classes[0], duration_sec=value), "subject"
    else:
        operator = "gt" if condition_key == "more_than" else "lt"
        rule, role = dict(base, type="object_count", count_threshold=int(value), count_operator=operator), "counter"

    plan = DetectionPlan(
        source_prompt="",
        detection_targets=[{"class_name": name, "role": role} for name in classes],
        conditions=[rule],
        selected_model=subject["model"],
        triton_model_name=subject["model"],
        model_reason="Kural formundan seçildi.",
        expanded_classes={classes[0]: classes} if subject["model"] == "yoloe_detector" else None,
        model_classes=classes,
        yoloe_classes=classes,
        status="success",
    )
    plan.source_prompt = describe_plan(plan.model_dump())
    return plan


def _ablative(number: int) -> str:
    """Turkish "from" suffix of a number as it is read aloud: 3'ten, 5'ten, 6'dan, 10'dan, 20'den."""
    if number == 0:
        return "0'dan"
    for size, words in ((1, ["", "den", "den", "ten", "ten", "ten", "dan", "den", "den", "dan"]),
                        (10, ["", "dan", "den", "dan", "tan", "den", "tan", "ten", "den", "dan"])):
        digit = (number // size) % 10
        if digit:
            return f"{number}'{words[digit]}"
    return f"{number}'den"  # yüz, bin


def _seconds(value: Optional[float]) -> str:
    seconds = float(value or 0)
    if seconds >= 120 and seconds % 60 == 0:
        return f"{int(seconds // 60)} dakika"
    return f"{seconds:g} saniye"


def describe_plan(plan: Optional[Dict[str, Any]]) -> str:
    """What a stored plan does, as one sentence for the operator ('' when there is no plan)."""
    if not plan:
        return ""
    parts = []
    for condition in plan.get("conditions") or []:
        kind = condition.get("type")
        classes = condition.get("targets") or [condition.get("subject") or "person"]
        # An open-vocabulary plan lists several words for one thing: name the thing once
        expanded = plan.get("expanded_classes") or {}
        for parent, variants in expanded.items():
            lowered = {str(variant).lower() for variant in variants}
            if any(str(name).lower() in lowered for name in classes):
                classes = [parent] + [name for name in classes if str(name).lower() not in lowered and name != parent]
        # The classes of a form choice are named the way the form names them ("araç")
        wanted = {str(name).lower() for name in classes}
        choice = next((subject for subject in SUBJECTS.values()
                       if len(subject["classes"]) > 1 and {name.lower() for name in subject["classes"]} == wanted), None)
        who = choice["label"].lower() if choice else _names(classes)
        duration = condition.get("duration_sec")
        if kind in ("zone_presence", "unauthorized_object", "line_crossing"):
            parts.append(f"{who} bölgede görülünce")
        elif kind == "zone_absence" and condition.get("required"):
            parts.append(f"bölgedeki {_names([condition.get('subject') or 'person'])} üzerinde {_names(condition['required'])} yoksa")
        elif kind == "zone_absence":
            parts.append(f"bölgede {_seconds(duration)} boyunca hiç {who} yokken" if duration else f"bölgede hiç {who} yokken")
        elif kind == "loitering":
            parts.append(f"{who} bölgede {_seconds(duration or 30)}den uzun kalınca")
        elif kind == "object_count":
            threshold = int(condition.get("count_threshold") or 0)
            operator = str(condition.get("count_operator") or "gt").lower()
            if operator in ("gt", "gte"):
                parts.append(f"bölgede {_ablative(threshold if operator == 'gt' else max(threshold - 1, 0))} fazla {who} olunca")
            elif operator in ("lt", "lte"):
                parts.append(f"bölgede {_ablative(threshold if operator == 'lt' else threshold + 1)} az {who} olunca")
            else:
                parts.append(f"bölgede tam {threshold} {who} olunca")
    sentence = " veya ".join(dict.fromkeys(parts))
    return sentence[:1].upper() + sentence[1:] if sentence else ""
