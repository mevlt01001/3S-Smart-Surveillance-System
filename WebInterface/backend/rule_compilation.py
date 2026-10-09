"""
Rule compilation: turns the plain-language description of a rule zone into a
deterministic detection plan with the help of the language model, in the background.

The HTTP layer only asks this module to start a compilation and what state a rule is in.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from Rule_Generator_LLM import manual as manual_rules, schedule as rule_schedule

from .camera_service import camera_service
from .rules_service import rules_service

logger = logging.getLogger("aegis.rules")

try:
    from Rule_Generator_LLM.compiler import RuleCompiler, UnsupportedRule

    # Address, key and model come from the EVREN_* environment variables
    _compiler: Optional[Any] = RuleCompiler(temperature=0.05)
    logger.info("Rule compiler is ready.")
except Exception as exc:  # missing package, key or network configuration
    _compiler = None

    class UnsupportedRule(Exception):  # type: ignore[no-redef]  # never raised without a compiler
        pass
    logger.warning("Rule compiler is unavailable; rules that need a plan will not run: %s", exc)

# rule_id -> {"token", "status": "compiling" | "error" | "unsupported", "started_at", "error"}
# "unsupported": the model explained that the request cannot be observed by a camera; `error` is
# that explanation, meant for the operator
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()

_PLAN_FIELDS = ("detection_plan", "compile_logs", "compile_meta", "raw_llm_response")
_BULKY_FIELDS = ("detection_plan", "compile_logs", "raw_llm_response")


def is_available() -> bool:
    return _compiler is not None


def zone_needs_plan(zone: Dict[str, Any]) -> bool:
    """Change-detection zones are pure image comparison and never need a compiled plan."""
    return zone.get("zone_type", "detection") != "change_detection"


def apply_manual_plans(zones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Gives every zone that was defined by form choices (`manual`) its plan, here and now: no
    language model is involved. The sentence that says what the plan does becomes the zone's
    description. Raises ValueError (a message for the user) for an impossible choice.
    """
    result = []
    for zone in zones:
        if zone_needs_plan(zone) and isinstance(zone.get("manual"), dict):
            plan = manual_rules.build_plan(zone["manual"])
            zone = dict(zone, description=plan.source_prompt, detection_plan=plan.model_dump(),
                        compile_meta={"status": "manual", "compiled_at": plan.compiled_at})
            zone.pop("compile_logs", None)
            zone.pop("raw_llm_response", None)
        result.append(zone)
    return result


def compiled_changes(rule: Dict[str, Any], zones: List[Dict[str, Any]], plans: Dict[str, Any]) -> Dict[str, Any]:
    """
    What to store after a compilation: the zones and, unless the user set the working hours
    in the form, the hours the model read from the sentences (none read = always).
    """
    changes: Dict[str, Any] = {"zones": zones}
    if (rule.get("schedule") or {}).get("source") != "user":
        changes["schedule"] = next((plan.schedule for plan in plans.values() if plan.schedule), None)
    return changes


def _with_plan(zone: Dict[str, Any], plan: Any) -> Dict[str, Any]:
    compiled = dict(zone)
    compiled["detection_plan"] = plan.model_dump()
    compiled["compile_logs"] = plan.compile_logs
    compiled["compile_meta"] = {
        "latency_ms": plan.compile_latency_ms,
        "status": plan.status,
        "model": _compiler.model_name,
        "compiled_at": plan.compiled_at,
    }
    compiled["raw_llm_response"] = plan.raw_llm_response
    return compiled


def _compile_zones(zones: List[Dict[str, Any]], force: bool) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Compiles the zones described by a sentence that lack a plan (all of them when `force`).
    Blocking (language-model round trips): never call from the event loop.
    Returns (zones, plans by zone id).
    """
    targets = [z for z in zones
               if zone_needs_plan(z) and not z.get("manual") and (force or not z.get("detection_plan"))]
    if not targets:
        return zones, {}
    plans = _compiler.compile_batch(targets)
    compiled = {id(zone): _with_plan(zone, plan) for zone, plan in zip(targets, plans)}
    return [compiled.get(id(zone), zone) for zone in zones], {z.get("id"): p for z, p in zip(targets, plans)}


def keep_unchanged_plans(old_zones: List[Dict[str, Any]], new_zones: List[Any]) -> List[Dict[str, Any]]:
    """
    Carries the compiled plan over to zones whose description did not change, so renaming a
    rule or moving a polygon neither interrupts detection nor triggers another compilation.
    """
    old_by_id = {z.get("id"): z for z in (old_zones or []) if z.get("id")}
    merged = []
    for zone in new_zones or []:
        if not isinstance(zone, dict):
            continue
        zone = dict(zone)
        old = old_by_id.get(zone.get("id"))
        unchanged = (
            old
            and zone_needs_plan(zone)
            and old.get("detection_plan")
            and not zone.get("detection_plan")
            and not zone.get("manual") and not old.get("manual")
            and (old.get("description") or "").strip() == (zone.get("description") or "").strip()
            and old.get("zone_type", "detection") == zone.get("zone_type", "detection")
        )
        if unchanged:
            zone.update({key: old[key] for key in _PLAN_FIELDS if key in old})
        merged.append(zone)
    return merged


def start(rule_id: str) -> bool:
    """Compiles the missing plans of a rule in a background thread. Returns True if a job was started."""
    rule = rules_service.get_by_id(rule_id)
    if not (is_available() and rule):
        return False
    zones = [dict(zone) for zone in rule.get("zones", [])]
    if not any(zone_needs_plan(zone) and not zone.get("detection_plan") for zone in zones):
        return False

    version = rule.get("updated_at")
    token = f"{rule_id}:{time.time()}"
    with _jobs_lock:
        _jobs[rule_id] = {"token": token, "status": "compiling", "started_at": time.time()}

    def work():
        try:
            compiled, plans = _compile_zones(zones, force=False)
            current = rules_service.get_by_id(rule_id)
            # Discard the result if the rule was edited or deleted while the model was working
            if current and current.get("updated_at") == version:
                rules_service.update_rule(rule_id, compiled_changes(current, compiled, plans))
                logger.info("Rule '%s' compiled (%d zones).", rule.get("title", ""), len(plans))
            with _jobs_lock:
                if _jobs.get(rule_id, {}).get("token") == token:
                    _jobs.pop(rule_id, None)
        except Exception as exc:
            status = "unsupported" if isinstance(exc, UnsupportedRule) else "error"
            logger.warning("Rule '%s' could not be compiled (%s): %s", rule.get("title", ""), status, exc)
            with _jobs_lock:
                if _jobs.get(rule_id, {}).get("token") == token:
                    _jobs[rule_id] = {"token": token, "status": status, "error": str(exc), "started_at": time.time()}

    threading.Thread(target=work, daemon=True, name=f"RuleCompile_{rule_id}").start()
    return True


def recompile(zones: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Compiles every detection zone again. Blocking: run in a worker thread."""
    return _compile_zones(zones, force=True)


def forget(rule_id: str) -> None:
    """Drops the job state of a deleted rule."""
    with _jobs_lock:
        _jobs.pop(rule_id, None)


def error_of(rule_id: str) -> Optional[str]:
    return (_jobs.get(rule_id) or {}).get("error")


def status_of(rule: Dict[str, Any]) -> str:
    """compiling | error | unsupported | not_required | compiled | fallback | pending | unavailable"""
    job = _jobs.get(rule.get("id", ""))
    if job:
        return job["status"]
    detection_zones = [zone for zone in rule.get("zones", []) if zone_needs_plan(zone)]
    if not detection_zones:
        return "not_required"
    if all(zone.get("detection_plan") for zone in detection_zones):
        statuses = {
            (zone.get("compile_meta") or {}).get("status") or (zone.get("detection_plan") or {}).get("status")
            for zone in detection_zones
        }
        return "fallback" if "fallback" in statuses else "compiled"
    return "pending" if is_available() else "unavailable"


def rule_view(rule: Dict[str, Any], slim: bool = False) -> Dict[str, Any]:
    """API representation of a rule. `slim` replaces the bulky plan data by a short summary (list views)."""
    view = dict(rule)
    view["compile_status"] = status_of(rule)
    view["schedule_text"] = rule_schedule.describe(rule.get("schedule"))
    # False while the rule is switched on but outside its working hours
    view["active_now"] = bool(rule.get("enabled", True)) and rule_schedule.is_active(rule.get("schedule"))
    # Why the request cannot be turned into a rule, in words for the operator
    view["compile_note"] = error_of(rule.get("id", "")) if view["compile_status"] == "unsupported" else None
    view["camera_missing"] = bool(
        rule.get("scope") != "system" and rule.get("camera_id") and not camera_service.get_by_id(rule["camera_id"])
    )
    if not slim:
        return view

    zones = []
    for zone in rule.get("zones", []):
        light = {key: value for key, value in zone.items() if key not in _BULKY_FIELDS}
        plan = zone.get("detection_plan")
        if plan:
            light["plan_summary"] = {
                "model": plan.get("triton_model_name") or plan.get("selected_model"),
                "classes": plan.get("model_classes") or plan.get("yoloe_classes") or [],
                "conditions": [condition.get("type") for condition in plan.get("conditions", [])],
                "status": (zone.get("compile_meta") or {}).get("status") or plan.get("status"),
                # What the plan does, in one sentence for the operator
                "text": manual_rules.describe_plan(plan),
                # Set when the rule is only the closest thing to what was asked
                "note": plan.get("user_note"),
            }
        zones.append(light)
    view["zones"] = zones
    return view
