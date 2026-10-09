"""Rule endpoints: rules with their zones, and the state of their compilation."""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException

from .. import rule_compilation
from ..camera_service import camera_service
from ..change_detector import change_detector
from ..rules_service import rules_service
from .schemas import CreateRuleRequest, UpdateRuleRequest

router = APIRouter(prefix="/api/rules", tags=["rules"])

SYSTEM_SCOPE_NAME = "Tüm kameralar"


def _require_rule(rule_id: str) -> dict:
    rule = rules_service.get_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Kural bulunamadı.")
    return rule


@router.get("")
async def list_rules(camera_id: Optional[str] = None, full: bool = False):
    """All rules, optionally of one camera. `full` includes the compiled plans."""
    rules = [rule_compilation.rule_view(rule, slim=not full) for rule in rules_service.get_all(camera_id=camera_id)]
    return {
        "success": True,
        "count": len(rules),
        "compiler_available": rule_compilation.is_available(),
        "rules": rules,
    }


@router.post("")
async def create_rule(req: CreateRuleRequest):
    """Stores a rule; the descriptions of its zones are compiled in the background."""
    if not req.title.strip():
        raise HTTPException(status_code=422, detail="Kural başlığı boş olamaz.")
    if req.scope != "system" and not (req.camera_id and camera_service.get_by_id(req.camera_id)):
        raise HTTPException(status_code=422, detail="Kuralın uygulanacağı kamera bulunamadı.")

    rule = rules_service.create_rule(
        title=req.title,
        scope=req.scope,
        camera_id=req.camera_id,
        camera_name=req.camera_name,
        severity=req.severity,
        description=req.description,
        zones=[zone for zone in (req.zones or []) if isinstance(zone, dict)],
        actions=req.actions,
    )
    rule_compilation.start(rule["id"])
    return {"success": True, "rule": rule_compilation.rule_view(rule, slim=True)}


@router.get("/{rule_id}")
async def get_rule(rule_id: str):
    return {"success": True, "rule": rule_compilation.rule_view(_require_rule(rule_id))}


@router.put("/{rule_id}")
async def update_rule(rule_id: str, req: UpdateRuleRequest):
    """Changes the given fields of a rule (switching it on / off, zones, camera…)."""
    existing = _require_rule(rule_id)
    updates = {key: value for key, value in req.model_dump().items() if value is not None}
    if "title" in updates and not updates["title"].strip():
        raise HTTPException(status_code=422, detail="Kural başlığı boş olamaz.")

    if updates.get("scope", existing.get("scope")) == "system":
        updates.update(scope="system", camera_id=None, camera_name=SYSTEM_SCOPE_NAME)
    elif "scope" in updates or "camera_id" in updates:
        camera_id = updates.get("camera_id") or existing.get("camera_id")
        camera = camera_service.get_by_id(camera_id) if camera_id else None
        if not camera:
            raise HTTPException(status_code=422, detail="Kuralın uygulanacağı kamera bulunamadı.")
        updates.update(
            scope="camera",
            camera_id=camera_id,
            camera_name=updates.get("camera_name") or camera.get("name") or camera.get("ip"),
        )

    if "zones" in updates:
        updates["zones"] = rule_compilation.keep_unchanged_plans(existing.get("zones", []), updates["zones"])

    updated = rules_service.update_rule(rule_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Kural bulunamadı.")
    if "zones" in updates:
        # Only zones whose description is new or changed are compiled
        rule_compilation.start(rule_id)
    return {"success": True, "rule": rule_compilation.rule_view(updated, slim=True)}


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str):
    rule = _require_rule(rule_id)
    rules_service.delete_rule(rule_id)
    rule_compilation.forget(rule_id)
    # Reference pictures of this rule's obstacle / change zones are useless now
    if rule.get("camera_id"):
        for zone in rule.get("zones", []):
            if zone.get("zone_type") == "change_detection" and zone.get("id"):
                change_detector.delete_reference(rule["camera_id"], zone["id"])
    return {"success": True}


@router.get("/{rule_id}/plan")
async def rule_plans(rule_id: str):
    """Diagnostics: the compiled plan, compile log and raw model answer of every zone."""
    rule = _require_rule(rule_id)
    plans = []
    for zone in rule.get("zones", []):
        plan = zone.get("detection_plan")
        if not plan:
            continue
        plans.append({
            "zone_id": zone.get("id"),
            "zone_name": zone.get("name"),
            "detection_plan": plan,
            "compile_logs": zone.get("compile_logs") or plan.get("compile_logs") or [],
            "compile_meta": zone.get("compile_meta") or {
                "latency_ms": plan.get("compile_latency_ms", 0.0),
                "status": plan.get("status", "success"),
                "compiled_at": plan.get("compiled_at"),
            },
            "raw_llm_response": zone.get("raw_llm_response") or plan.get("raw_llm_response"),
        })
    return {
        "success": True,
        "rule_id": rule_id,
        "compiler_available": rule_compilation.is_available(),
        "compile_status": rule_compilation.status_of(rule),
        "compile_error": rule_compilation.error_of(rule_id),
        "plans_count": len(plans),
        "plans": plans,
    }


@router.post("/{rule_id}/compile")
async def recompile_rule(rule_id: str):
    """Compiles every zone of the rule again and waits for the result."""
    if not rule_compilation.is_available():
        raise HTTPException(status_code=503, detail="Kural hazırlama servisine ulaşılamıyor.")
    rule = _require_rule(rule_id)
    zones = [dict(zone) for zone in rule.get("zones", [])]
    if not any(rule_compilation.zone_needs_plan(zone) for zone in zones):
        return {"success": True, "plans_count": 0}

    version = rule.get("updated_at")
    # Language-model round trips take seconds: keep them off the event loop
    compiled_zones, plans = await asyncio.to_thread(rule_compilation.recompile, zones)

    current = _require_rule(rule_id)
    if current.get("updated_at") != version:
        raise HTTPException(status_code=409, detail="Kural hazırlanırken değiştirildi. Lütfen yeniden deneyin.")
    rules_service.update_rule(rule_id, {"zones": compiled_zones})
    return {"success": True, "plans_count": len(plans)}
