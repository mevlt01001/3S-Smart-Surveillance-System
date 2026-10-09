"""
RuleCompiler — LLM-backed Natural Language → DetectionPlan Compiler

Takes operator-written security rules in Turkish natural language and
compiles them into structured, deterministic DetectionPlan JSON using
the Evren VLM/LLM API (qwen3-vl-30b).

The LLM acts as a compiler, NOT a chatbot: its output is machine-readable
JSON validated against the DetectionPlan Pydantic schema.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from . import llm_config, schedule as rule_schedule
from .prompts import COMPILER_SYSTEM_PROMPT, COMPILER_USER_TEMPLATE
from .schema import (
    AlertLogic,
    Condition,
    ConditionType,
    DetectionPlan,
    DetectionTarget,
    TargetRole,
)

logger = logging.getLogger("rule_compiler")


# Model definitions and predefined class catalogs
SAFETY_CLASSES = [
    "Hardhat", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety Vest",
    "Person", "Safety Cone", "Safety Vest", "machinery", "vehicle"
]
SAFETY_CLASSES_MAP = {c.lower(): c for c in SAFETY_CLASSES}

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake",
    "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop",
    "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]
COCO_CLASSES_SET = set(COCO_CLASSES)

YOLOE_EXPANSION_DICTIONARY: Dict[str, List[str]] = {
    "forklift": ["forklift", "reach truck", "pallet jack", "industrial lifter", "fork truck"],
    "lifter": ["forklift", "reach truck", "pallet jack", "industrial lifter", "fork truck"],
    "reach truck": ["forklift", "reach truck", "pallet jack", "industrial lifter", "fork truck"],
    "pallet jack": ["forklift", "reach truck", "pallet jack", "industrial lifter", "fork truck"],
    "pallet": ["wooden pallet", "plastic pallet", "cargo pallet", "pallet stack", "industrial skid"],
    "box": ["cardboard box", "cargo package", "shipping box", "storage carton", "wooden crate"],
    "koli": ["cardboard box", "cargo package", "shipping box", "storage carton", "wooden crate"],
    "barrel": ["oil drum", "steel barrel", "chemical drum", "plastic container", "storage barrel"],
    "varil": ["oil drum", "steel barrel", "chemical drum", "plastic container", "storage barrel"],
    "gun": ["handgun", "pistol", "revolver", "firearm", "weapon"],
    "silah": ["handgun", "pistol", "revolver", "firearm", "weapon"],
    "knife": ["kitchen knife", "hunting knife", "pocket knife", "dagger", "utility knife"],
    "bicak": ["kitchen knife", "hunting knife", "pocket knife", "dagger", "utility knife"],
    "fire": ["flame", "fire", "bonfire", "burning smoke", "blaze"],
    "yangin": ["flame", "fire", "bonfire", "burning smoke", "blaze"],
    "smoke": ["dense smoke", "fire smoke", "exhaust smoke", "gray smoke", "black smoke"],
    "duman": ["dense smoke", "fire smoke", "exhaust smoke", "gray smoke", "black smoke"],
    "ladder": ["step ladder", "extension ladder", "industrial ladder", "aluminum ladder", "scaffolding"],
    "merdiven": ["step ladder", "extension ladder", "industrial ladder", "aluminum ladder", "scaffolding"],
}


class RuleCompiler:
    """
    Compiles natural-language surveillance rules into DetectionPlan objects.

    Usage:
        compiler = RuleCompiler()
        plan = compiler.compile("Bu bölgeye yetkisiz kişi girdiğinde alarm üret.")
        print(plan.selected_model)        # 'coco_detector' or 'safety_detector'
        print(plan.get_yoloe_classes())   # ['person']
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: float = 0.05,
        max_retries: int = 2,
    ):
        self.model_name = model_name or llm_config.MODEL
        self.temperature = temperature
        self.max_retries = max_retries
        self.base_url = base_url or llm_config.BASE_URL
        self.api_key = api_key or llm_config.API_KEY

        if not self.base_url or not self.api_key:
            raise RuntimeError(
                "RuleCompiler: API key veya Base URL eksik. "
                "EVREN_API_KEY ve EVREN_BASE_URL env değişkenlerini ayarlayın."
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=120,
        )

    def compile_with_logs(
        self,
        prompt: str,
        zone_name: Optional[str] = None,
        zone_points: Optional[List[Dict[str, float]]] = None,
    ) -> Dict[str, Any]:
        """
        Compiles a natural-language rule into a DetectionPlan while capturing
        an audit trail of compilation steps for developer inspection.
        """
        logs = []
        now_str = lambda: time.strftime("%H:%M:%S")

        clean_prompt = prompt.strip() if prompt else "Bölge izleme"

        logs.append({
            "timestamp": now_str(),
            "step": "GİRDİ",
            "level": "info",
            "message": f"Doğal dil kural yönergesi alındı: \"{clean_prompt}\"",
            "details": {"prompt": clean_prompt}
        })

        pts_count = len(zone_points) if zone_points else 0
        logs.append({
            "timestamp": now_str(),
            "step": "BÖLGE",
            "level": "info",
            "message": f"Tanımlı bölge: '{zone_name or 'Bölge'}' ({pts_count} köşe poligon koordinatı)",
            "details": {"zone_name": zone_name, "points_count": pts_count}
        })

        zone_context = ""
        if zone_name:
            zone_context += f"\nBölge Adı: {zone_name}"
        if zone_points and len(zone_points) >= 3:
            zone_context += f"\nBölge Poligon Noktaları: {len(zone_points)} köşe noktası tanımlı."

        user_message = COMPILER_USER_TEMPLATE.format(
            prompt=clean_prompt,
            zone_context=zone_context,
        )

        logs.append({
            "timestamp": now_str(),
            "step": "LLM_İSTEK",
            "level": "info",
            "message": f"SSB EVREN LLM API'ye istek iletiliyor (Model: {self.model_name})",
            "details": {"model": self.model_name, "endpoint": self.base_url}
        })

        last_error = None
        plan = None
        raw_json = None
        elapsed_sec = 0.0

        for attempt in range(1, self.max_retries + 1):
            try:
                raw_json, elapsed_sec = self._call_llm(user_message)
                logs.append({
                    "timestamp": now_str(),
                    "step": "LLM_YANIT",
                    "level": "success",
                    "message": f"LLM yanıtı başarıyla alındı ({elapsed_sec*1000:.0f} ms, {len(raw_json)} bayt)",
                    "details": {"latency_ms": round(elapsed_sec * 1000, 1), "bytes": len(raw_json)}
                })

                logs.append({
                    "timestamp": now_str(),
                    "step": "ŞEMA",
                    "level": "info",
                    "message": "JSON bloğu ayıklanıyor, model yönlendirmesi doğrulanıyor...",
                })

                plan = self._parse_and_validate(raw_json, source_prompt=clean_prompt)
                plan.compile_latency_ms = round(elapsed_sec * 1000, 1)
                plan.status = "success"
                plan.raw_llm_response = raw_json

                # 1. Log Model Selection
                logs.append({
                    "timestamp": now_str(),
                    "step": "MODEL_SEÇİMİ",
                    "level": "success",
                    "message": f"🎯 Çıkarım Modeli: {plan.selected_model} (Triton: {plan.triton_model_name}) | Gerekçe: {plan.model_reason}",
                    "details": {
                        "selected_model": plan.selected_model,
                        "triton_model_name": plan.triton_model_name,
                        "model_path": plan.model_path,
                        "model_reason": plan.model_reason,
                    }
                })

                # 2. Log YOLOE Sub-class Decomposition if applicable
                if plan.selected_model == "yoloe_detector" and plan.expanded_classes:
                    for parent, subcls in plan.expanded_classes.items():
                        logs.append({
                            "timestamp": now_str(),
                            "step": "ALT_SINIF_GENİŞLETME",
                            "level": "info",
                            "message": f"🔀 YOLOE 4-5 Alt Sınıf Ayrıştırması: '{parent}' -> {subcls} (Doğruluk ve recall artışı)",
                            "details": {"parent_concept": parent, "sub_classes": subcls}
                        })

                # 3. Log Detection Targets
                target_names = [f"{t.class_name} ({t.role.value})" for t in plan.detection_targets]
                logs.append({
                    "timestamp": now_str(),
                    "step": "DETEKSİYON",
                    "level": "success",
                    "message": f"Tespit Planı sınıfları ({len(plan.detection_targets)} hedef): {', '.join(target_names)}",
                    "details": {"targets": [t.dict() for t in plan.detection_targets]}
                })

                # 4. Log Conditions & Logic
                cond_desc = [f"{c.type.value} (mantık={c.logic})" for c in plan.conditions]
                logs.append({
                    "timestamp": now_str(),
                    "step": "MANTIK",
                    "level": "info",
                    "message": f"Koşullar: {', '.join(cond_desc)} | Tetikleme: {plan.alert_on.value}",
                    "details": {"conditions": [c.dict() for c in plan.conditions], "alert_on": plan.alert_on.value}
                })

                # 5. Log Triton Target
                logs.append({
                    "timestamp": now_str(),
                    "step": "TRITON_HEDEF",
                    "level": "info",
                    "message": f"⚡ NVIDIA Triton Server Hedefi: '{plan.triton_model_name}:1' (GPU Çıkarım Hazır)",
                    "details": {"endpoint": f"http://localhost:8000/v2/models/{plan.triton_model_name}"}
                })

                logs.append({
                    "timestamp": now_str(),
                    "step": "DURUM",
                    "level": "success",
                    "message": f"✅ Kural deterministik plan ve optimize model ile başarıyla derlendi.",
                })

                plan.compile_logs = logs
                return {
                    "success": True,
                    "plan": plan,
                    "logs": logs,
                    "raw_llm_response": raw_json,
                    "latency_ms": round(elapsed_sec * 1000, 1),
                    "status": "success",
                    "model": self.model_name
                }

            except UnsupportedRule:
                raise  # not a failure of the model: asking again or falling back would hide its answer
            except Exception as e:
                last_error = e
                logs.append({
                    "timestamp": now_str(),
                    "step": "HATA",
                    "level": "warning",
                    "message": f"Derleme hatası (deneme {attempt}/{self.max_retries}): {e}",
                })
                if attempt < self.max_retries:
                    time.sleep(0.5)

        # Fallback
        logs.append({
            "timestamp": now_str(),
            "step": "FALLBACK",
            "level": "warning",
            "message": f"Tüm LLM denemeleri başarısız ({last_error}). Güvenli varsayılan plana geçiliyor.",
        })

        plan = self._build_fallback_plan(clean_prompt)
        plan.compile_latency_ms = round(elapsed_sec * 1000, 1)
        plan.status = "fallback"
        plan.raw_llm_response = raw_json or str(last_error)

        logs.append({
            "timestamp": now_str(),
            "step": "DURUM",
            "level": "warning",
            "message": f"⚠️ Fallback planı aktif: {plan.yoloe_classes}",
        })
        plan.compile_logs = logs

        return {
            "success": False,
            "plan": plan,
            "logs": logs,
            "raw_llm_response": raw_json or str(last_error),
            "latency_ms": round(elapsed_sec * 1000, 1),
            "status": "fallback",
            "model": self.model_name
        }

    def compile(
        self,
        prompt: str,
        zone_name: Optional[str] = None,
        zone_points: Optional[List[Dict[str, float]]] = None,
    ) -> DetectionPlan:
        """
        Compiles a natural-language rule into a DetectionPlan.
        """
        result = self.compile_with_logs(prompt, zone_name=zone_name, zone_points=zone_points)
        return result["plan"]

    def compile_batch(
        self,
        zones: List[Dict[str, Any]],
    ) -> List[DetectionPlan]:
        """
        Compiles multiple zone descriptions from a single rule into
        individual DetectionPlans.
        """
        plans = []
        for zone in zones:
            description = zone.get("description", "").strip()
            if not description:
                plan = self._build_fallback_plan(
                    f"Bölge '{zone.get('name', 'Bölge')}' içinde hareket ve nesne tespiti"
                )
                plan.compile_logs = [{
                    "timestamp": time.strftime("%H:%M:%S"),
                    "step": "VARSAYILAN",
                    "level": "info",
                    "message": f"Açıklama belirtilmedi. Varsayılan nesne tespiti uygulandı."
                }]
                plan.status = "success"
            else:
                res = self.compile_with_logs(
                    prompt=description,
                    zone_name=zone.get("name"),
                    zone_points=zone.get("points"),
                )
                plan = res["plan"]
            plans.append(plan)
        return plans

    # ------------------------------------------------------------------
    #  Internal Methods
    # ------------------------------------------------------------------

    def _call_llm(self, user_message: str) -> Tuple[str, float]:
        """Calls the LLM API and extracts the JSON response text with latency."""
        messages = [
            {"role": "system", "content": COMPILER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        t0 = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
        )
        elapsed = time.perf_counter() - t0

        text = response.choices[0].message.content or ""
        logger.debug(f"[RuleCompiler] LLM yanıt ({elapsed:.2f}s): {text[:300]}...")

        # Strip thinking tags if present (qwen3 models)
        text = self._strip_thinking_tags(text)
        return text, elapsed

    @staticmethod
    def _strip_thinking_tags(text: str) -> str:
        """Removes <think>...</think> blocks from qwen3 responses."""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text.strip()

    def _parse_and_validate(self, raw_text: str, source_prompt: str) -> DetectionPlan:
        """
        Parses LLM output text into a validated DetectionPlan.
        Handles JSON extraction from potential markdown fences.
        """
        json_str = self._extract_json(raw_text)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise CompilationError(
                f"LLM çıktısı geçerli JSON değil: {e}\nÇıktı: {raw_text[:500]}"
            )

        # What the model said about its own limits: a request it cannot serve at all is not
        # turned into some plan anyway, and a note only accompanies a plan that is partial
        feasibility = str(data.get("feasibility") or "full").strip().lower()
        note = str(data.get("user_note") or "").strip() or None
        if feasibility == "none":
            raise UnsupportedRule(note or "Bu istek kameradan anlaşılabilecek bir duruma çevrilemedi.")
        data["feasibility"] = "partial" if feasibility == "partial" and note else "full"
        data["user_note"] = note if data["feasibility"] == "partial" else None

        data["schedule"] = rule_schedule.normalize(data.get("schedule"), source="text")
        if not rule_schedule.has_window(data["schedule"]):
            data["schedule"] = None

        data["source_prompt"] = source_prompt
        data = self._normalize_plan_data(data, source_prompt=source_prompt)

        try:
            plan = DetectionPlan(**data)
        except Exception as e:
            raise CompilationError(
                f"DetectionPlan şema doğrulaması başarısız: {e}\nVeri: {json.dumps(data, ensure_ascii=False)[:500]}"
            )

        if not plan.detection_targets:
            raise CompilationError("DetectionPlan'da en az 1 detection_target olmalı.")
        if not plan.conditions:
            raise CompilationError("DetectionPlan'da en az 1 condition olmalı.")

        plan.yoloe_classes = plan.get_yoloe_classes()
        return plan

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extracts JSON from raw LLM output, handling markdown fences."""
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if fence_match:
            return fence_match.group(1).strip()

        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            return text[brace_start : brace_end + 1]

        return text.strip()

    @staticmethod
    def _normalize_plan_data(data: dict, source_prompt: str = "") -> dict:
        """
        Normalizes and fixes common LLM output issues:
        - Detects / validates appropriate model (safety_detector, coco_detector, yoloe_detector)
        - Decomposes open-vocabulary YOLOE classes into 4-5 sub-classes/synonyms
        - Maps target classes, roles, and conditions
        """
        prompt_lower = (source_prompt or data.get("source_prompt", "")).lower()

        # 1. Raw targets inspection
        raw_targets = data.get("detection_targets", [])
        extracted_classes = []
        for t in raw_targets:
            if isinstance(t, str):
                extracted_classes.append(t.strip().lower())
            elif isinstance(t, dict):
                extracted_classes.append(t.get("class_name", "").strip().lower())

        # Determine Model Selection
        selected_model = str(data.get("selected_model", "")).strip().lower()

        # Indicators for safety / construction
        safety_keywords = [
            "baret", "kask", "yelek", "maske", "isg", "şantiye", "insaat", "inşaat",
            "baretsiz", "yeleksiz", "maskesiz", "hardhat", "safety vest", "safety cone",
            "koni", "trafik koni", "iş makine", "kepçe", "ekskavatör", "vinç", "dozer", "mikser"
        ]
        has_safety_keyword = any(kw in prompt_lower for kw in safety_keywords)
        has_safety_target = any(
            c in SAFETY_CLASSES_MAP or "hardhat" in c or "vest" in c or "cone" in c or "machinery" in c
            for c in extracted_classes
        )

        if has_safety_keyword or has_safety_target or selected_model in ("safety_detector", "safety"):
            selected_model = "safety_detector"
            triton_model = "safety_detector"
            model_path = "Object_Detection/yolo26m_safety_insaat_object_detection.pt"
            reason = data.get("model_reason") or (
                "İnşaat sahası ve İSG kuralları (Hardhat, NO-Hardhat, Safety Vest vb.) içerdiği için "
                "özel eğitilmiş safety_detector (10 sınıf) modeli seçildi."
            )
        else:
            # Check if all targets are in COCO 80 classes
            all_in_coco = len(extracted_classes) > 0 and all(c in COCO_CLASSES_SET for c in extracted_classes)
            coco_keywords = ["araba", "araç", "car", "person", "insan", "kişi", "çanta", "backpack", "valiz", "suitcase", "kedi", "köpek", "bisiklet", "motor"]
            if all_in_coco or (selected_model in ("coco_detector", "coco") and not any(kw in prompt_lower for kw in ("forklift", "palet", "varil", "koli"))):
                selected_model = "coco_detector"
                triton_model = "coco_detector"
                model_path = "Object_Detection/yolo26m.pt"
                reason = data.get("model_reason") or "Standart nesneler (COCO 80 sınıfı) içerdiği için optimize coco_detector modeli seçildi."
            else:
                selected_model = "yoloe_detector"
                triton_model = "yoloe_detector"
                model_path = "yoloe-26l-seg_decoupled_sim.onnx"
                reason = data.get("model_reason") or (
                    "Özel ve açık kelime dağarcığı gerektiren nesneler için YOLOE açık sözlüklü model seçildi "
                    "ve tespit başarımını artırmak üzere 4-5 alt sınıfa ayrıştırıldı."
                )

        data["selected_model"] = selected_model
        data["triton_model_name"] = triton_model
        data["model_path"] = model_path
        data["model_reason"] = reason

        # Handle YOLOE Sub-class Expansion (4-5 terms)
        expanded_classes = data.get("expanded_classes") or {}
        if selected_model == "yoloe_detector":
            # If LLM didn't provide expanded_classes, or provided only 1 term, populate 4-5 terms
            if not expanded_classes or all(len(v) < 4 for v in expanded_classes.values()):
                # Look for known concepts in prompt or targets
                concept_found = False
                for kw, sub_list in YOLOE_EXPANSION_DICTIONARY.items():
                    if kw in prompt_lower or any(kw in c for c in extracted_classes):
                        expanded_classes[kw] = sub_list
                        concept_found = True
                        break

                if not concept_found and extracted_classes:
                    base_term = extracted_classes[0]
                    expanded_classes[base_term] = [
                        base_term,
                        f"industrial {base_term}",
                        f"small {base_term}",
                        f"heavy {base_term}",
                        f"{base_term} equipment",
                    ]

        data["expanded_classes"] = expanded_classes if expanded_classes else None

        # Build normalized detection_targets
        normalized_targets = []
        seen_classes = set()

        if selected_model == "safety_detector":
            # Map classes to exact safety detector casing
            for t in raw_targets:
                if isinstance(t, str):
                    t = {"class_name": t, "role": "trigger"}
                cn = t.get("class_name", "").strip().lower()
                mapped_cn = SAFETY_CLASSES_MAP.get(cn, cn)
                # Map common Turkish/general terms to safety classes
                if "baretsiz" in cn or "no-helmet" in cn or "no-hardhat" in cn:
                    mapped_cn = "NO-Hardhat"
                elif "yeleksiz" in cn or "no-vest" in cn or "no-safety vest" in cn:
                    mapped_cn = "NO-Safety Vest"
                elif "maskesiz" in cn or "no-mask" in cn:
                    mapped_cn = "NO-Mask"
                elif "baret" in cn or "helmet" in cn or "hardhat" in cn:
                    mapped_cn = "Hardhat"
                elif "yelek" in cn or "vest" in cn:
                    mapped_cn = "Safety Vest"
                elif "koni" in cn or "cone" in cn:
                    mapped_cn = "Safety Cone"
                elif "makine" in cn or "machine" in cn:
                    mapped_cn = "machinery"
                elif cn in ("car", "truck", "bus", "araba", "araç"):
                    mapped_cn = "vehicle"
                elif cn in ("person", "insan", "kişi"):
                    mapped_cn = "Person"

                if mapped_cn not in seen_classes:
                    seen_classes.add(mapped_cn)
                    normalized_targets.append({
                        "class_name": mapped_cn,
                        "role": t.get("role", "forbidden" if "NO-" in mapped_cn else "trigger")
                    })

        elif selected_model == "yoloe_detector" and expanded_classes:
            # Flatten all expanded classes into targets
            for parent, sub_list in expanded_classes.items():
                for sub in sub_list:
                    sub_clean = sub.strip()
                    if sub_clean.lower() not in seen_classes:
                        seen_classes.add(sub_clean.lower())
                        normalized_targets.append({
                            "class_name": sub_clean,
                            "role": "forbidden" if ("olmasın" in prompt_lower or "yasak" in prompt_lower) else "trigger"
                        })
            # Also keep existing if any
            for t in raw_targets:
                cn = t.get("class_name", "").strip() if isinstance(t, dict) else str(t).strip()
                if cn.lower() not in seen_classes and cn:
                    seen_classes.add(cn.lower())
                    normalized_targets.append({"class_name": cn, "role": "trigger"})

        else:  # coco_detector
            for t in raw_targets:
                if isinstance(t, str):
                    t = {"class_name": t, "role": "trigger"}
                cn = t.get("class_name", "").strip().lower()
                if cn and cn not in seen_classes:
                    seen_classes.add(cn)
                    normalized_targets.append({
                        "class_name": cn,
                        "role": t.get("role", "trigger")
                    })

        if not normalized_targets:
            # Default to person
            normalized_targets.append({"class_name": "person" if selected_model != "safety_detector" else "Person", "role": "trigger"})

        data["detection_targets"] = normalized_targets

        # Normalize conditions
        conditions = data.get("conditions", [])
        normalized_conditions = []

        all_target_class_names = [t["class_name"] for t in normalized_targets]

        valid_types = {ct.value for ct in ConditionType}
        for c in conditions:
            ctype = c.get("type", "zone_presence").lower().strip()
            if ctype not in valid_types:
                ctype = "zone_presence"

            # Semantik Doğrulama: 'zone_absence' ile 'loitering' arasındaki ayrım
            # Eğer required equipment yoksa ve prompt 'durma/bekleme/kalma süresi' ifade ediyorsa,
            # bu bir yokluk (absence) değil bekleme süresi aşımıdır (loitering).
            if ctype == "zone_absence" and not c.get("required"):
                loiter_terms = ["durma", "durmasın", "durmamalı", "bekleme", "beklemesin", "beklememeli", "kalmasın", "meşgul", "oyalanma", "loiter"]
                absence_terms = ["ayrıl", "terk", "yoksa", "bulunmazsa", "kalmazsa", "boş", "kaybol"]
                has_loiter = any(term in prompt_lower for term in loiter_terms)
                has_absence = any(term in prompt_lower for term in absence_terms)
                if has_loiter and not has_absence:
                    ctype = "loitering"
                    if not c.get("subject") and c.get("targets"):
                        c["subject"] = c["targets"][0]

            c["type"] = ctype

            logic = c.get("logic", "ANY").upper().strip()
            if logic not in ("ANY", "ALL", "ANY_MISSING"):
                logic = "ANY"
            c["logic"] = logic

            if "min_confidence" not in c or c["min_confidence"] is None:
                c["min_confidence"] = 0.30

            # If targets is empty, populate with all targets
            cond_targets = c.get("targets") or all_target_class_names
            if selected_model == "safety_detector":
                # Ensure safety case
                cond_targets = [SAFETY_CLASSES_MAP.get(t.lower(), t) for t in cond_targets]
            elif selected_model == "yoloe_detector" and expanded_classes:
                # Ensure all expanded classes are represented in condition targets
                exp_set = set(all_target_class_names)
                cond_targets = list(exp_set)

            c["targets"] = cond_targets
            normalized_conditions.append(c)

        if not normalized_conditions:
            normalized_conditions.append({
                "type": "zone_presence",
                "targets": all_target_class_names,
                "logic": "ANY",
                "min_confidence": 0.30
            })

        data["conditions"] = normalized_conditions

        # Normalize alert_on
        alert_on = data.get("alert_on", "ANY_CONDITION_MET").upper().strip()
        if alert_on not in (al.value for al in AlertLogic):
            alert_on = "ANY_CONDITION_MET"
        data["alert_on"] = alert_on

        # Set model_classes
        data["model_classes"] = all_target_class_names

        return data

    @staticmethod
    def _build_fallback_plan(prompt: str) -> DetectionPlan:
        """
        Builds a safe fallback DetectionPlan when LLM compilation fails.
        """
        prompt_lower = prompt.lower()
        if any(w in prompt_lower for w in ("baret", "yelek", "isg", "şantiye", "insaat")):
            return DetectionPlan(
                source_prompt=prompt,
                selected_model="safety_detector",
                triton_model_name="safety_detector",
                model_reason="İSG kuralı için fallback safety_detector modeli.",
                detection_targets=[
                    DetectionTarget(class_name="NO-Hardhat", role=TargetRole.FORBIDDEN),
                    DetectionTarget(class_name="NO-Safety Vest", role=TargetRole.FORBIDDEN),
                    DetectionTarget(class_name="Person", role=TargetRole.TRIGGER),
                ],
                conditions=[
                    Condition(
                        type=ConditionType.ZONE_PRESENCE,
                        targets=["NO-Hardhat", "NO-Safety Vest"],
                        logic="ANY",
                        min_confidence=0.35,
                    ),
                ],
                alert_on=AlertLogic.ANY_CONDITION_MET,
                model_classes=["NO-Hardhat", "NO-Safety Vest", "Person"],
                yoloe_classes=["NO-Hardhat", "NO-Safety Vest", "Person"],
            )

        if "forklift" in prompt_lower:
            forklift_subs = ["forklift", "reach truck", "pallet jack", "industrial lifter", "fork truck"]
            return DetectionPlan(
                source_prompt=prompt,
                selected_model="yoloe_detector",
                triton_model_name="yoloe_detector",
                model_reason="Forklift tespiti için 5 alt sınıfa ayrıştırılmış YOLOE modeli.",
                expanded_classes={"forklift": forklift_subs},
                detection_targets=[
                    DetectionTarget(class_name=s, role=TargetRole.FORBIDDEN) for s in forklift_subs
                ],
                conditions=[
                    Condition(
                        type=ConditionType.ZONE_PRESENCE,
                        targets=forklift_subs,
                        logic="ANY",
                        min_confidence=0.25,
                    ),
                ],
                alert_on=AlertLogic.ANY_CONDITION_MET,
                model_classes=forklift_subs,
                yoloe_classes=forklift_subs,
            )

        return DetectionPlan(
            source_prompt=prompt,
            selected_model="coco_detector",
            triton_model_name="coco_detector",
            model_reason="Genel nesne tespiti fallback planı.",
            detection_targets=[
                DetectionTarget(class_name="person", role=TargetRole.TRIGGER),
                DetectionTarget(class_name="car", role=TargetRole.TRIGGER),
                DetectionTarget(class_name="truck", role=TargetRole.TRIGGER),
            ],
            conditions=[
                Condition(
                    type=ConditionType.ZONE_PRESENCE,
                    targets=["person", "car", "truck"],
                    logic="ANY",
                    min_confidence=0.30,
                ),
            ],
            alert_on=AlertLogic.ANY_CONDITION_MET,
            model_classes=["person", "car", "truck"],
            yoloe_classes=["person", "car", "truck"],
        )


class CompilationError(Exception):
    """Raised when the LLM output cannot be parsed into a valid DetectionPlan."""
    pass


class UnsupportedRule(CompilationError):
    """
    The request needs something the system cannot observe (sound, identity, ...) and has no
    useful approximation. The message is the model's explanation, written for the operator.
    """

