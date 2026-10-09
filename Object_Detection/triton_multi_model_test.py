#!/usr/bin/env python3
"""
Triton Multi-Model & Rule Compiler Integration Test

Tests:
1. Triton Server Status: Checks that anomaly_detector, coco_detector, safety_detector, yoloe_detector are all READY.
2. Direct Triton Inferences:
   - safety_detector: detects PPE & construction violations (Hardhat, NO-Hardhat, Safety Vest, NO-Safety Vest, Person).
   - coco_detector: detects standard COCO objects (bus, person, car, backpack).
   - yoloe_detector: open-vocabulary detection with 4-5 decomposed sub-classes (forklift, reach truck, pallet jack, industrial lifter, fork truck).
3. RuleCompiler Dynamic Model Routing & Expansion:
   - Safety rule -> routes to safety_detector
   - COCO rule -> routes to coco_detector
   - Open-vocab rule -> routes to yoloe_detector with 4-5 decomposed sub-classes
4. End-to-End detection via YOLODetector.detect_with_plan.
"""

import sys
import os
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from Object_Detection import YOLODetector
from Object_Detection.triton_backend import TritonBackend
from Rule_Generator_LLM.compiler import RuleCompiler


def main():
    print("=" * 70)
    print("🚀 SMART SURVEILLANCE SYSTEM - TRITON MULTI-MODEL INTEGRATION TEST")
    print("=" * 70)

    # 1. Triton Server Health & Ready Models
    print("\n[ADIM 1] Triton Sunucu ve Model Durumu Denetleniyor...")
    triton = TritonBackend(url="localhost:8000")
    if not triton.is_alive():
        print("❌ HATA: NVIDIA Triton Sunucusu çevrimdışı!")
        sys.exit(1)

    ready_models = triton.get_ready_models()
    print(f"✅ Triton Çevrimiçi. Hazır Modeller: {ready_models}")
    expected_models = ["anomaly_detector", "coco_detector", "safety_detector", "yoloe_detector"]
    for em in expected_models:
        is_ready = triton.is_model_ready(em)
        status_mark = "✅" if is_ready else "❌"
        print(f"   {status_mark} Model '{em}': {'READY' if is_ready else 'NOT READY'}")
        if not is_ready:
            print(f"❌ HATA: '{em}' modeli Triton'da hazır değil!")
            sys.exit(1)

    # Initialize YOLODetector
    detector = YOLODetector(backend="triton")

    # 2. Test safety_detector
    print("\n[ADIM 2] 'safety_detector' (İSG & Şantiye Modeli) Test Ediliyor...")
    res_safety = detector.detect("bus.jpg", model_name="safety_detector")
    print(f"✅ safety_detector tespit sayısı: {len(res_safety.boxes)}")
    for b in res_safety.boxes:
        print(f"   🛡️ [{b.cls_name}] Güven: {b.conf:.2f} BBox: {b.xyxy}")

    # 3. Test coco_detector
    print("\n[ADIM 3] 'coco_detector' (Genel COCO 80 Modeli) Test Ediliyor...")
    res_coco = detector.detect("bus.jpg", model_name="coco_detector")
    print(f"✅ coco_detector tespit sayısı: {len(res_coco.boxes)}")
    for b in res_coco.boxes:
        print(f"   📦 [{b.cls_name}] Güven: {b.conf:.2f} BBox: {b.xyxy}")

    # 4. Test yoloe_detector (Open-Vocabulary with 5 Sub-classes)
    print("\n[ADIM 4] 'yoloe_detector' (Açık Sözlüklü 4-5 Alt Sınıf Ayrıştırması) Test Ediliyor...")
    forklift_subs = ["forklift", "reach truck", "pallet jack", "industrial lifter", "fork truck"]
    warehouse_img = "warehouse2.png" if os.path.exists("warehouse2.png") else "warehouse.png"
    if os.path.exists(warehouse_img):
        res_yoloe = detector.detect(warehouse_img, model_name="yoloe_detector", classes=forklift_subs)
        print(f"✅ yoloe_detector ({warehouse_img}) tespit sayısı: {len(res_yoloe.boxes)}")
        for b in res_yoloe.boxes:
            print(f"   👁️ [{b.cls_name}] Güven: {b.conf:.2f} BBox: {b.xyxy}")
    else:
        print(f"ℹ️ {warehouse_img} bulunamadı, bus.jpg üzerinde test ediliyor...")
        res_yoloe = detector.detect("bus.jpg", model_name="yoloe_detector", classes=forklift_subs)
        print(f"✅ yoloe_detector tespit sayısı: {len(res_yoloe.boxes)}")

    # 5. Test RuleCompiler Dynamic Model Routing & Sub-class Expansion
    print("\n[ADIM 5] Rule_Generator_LLM Doğal Dil Derleyicisi Test Ediliyor...")
    compiler = RuleCompiler()

    test_rules = [
        ("Bu alanda baretsiz veya yeleksiz personel bulunmasın.", "safety_detector"),
        ("Bu bekleme salonuna sırt çantası veya valiz bırakılmasın.", "coco_detector"),
        ("Bu yükleme peronunda forklift ve transpalet bulunmasın.", "yoloe_detector"),
    ]

    for prompt, expected_model in test_rules:
        print(f"\n--- KURAL: \"{prompt}\" ---")
        res = compiler.compile_with_logs(prompt)
        plan = res["plan"]
        print(f"   🎯 Seçilen Model: {plan.selected_model} (Beklenen: {expected_model})")
        print(f"   ⚡ Triton Hedefi: {plan.triton_model_name}:1")
        print(f"   📝 Gerekçe: {plan.model_reason}")
        if plan.expanded_classes:
            print(f"   🔀 Alt Sınıf Genişletmesi: {plan.expanded_classes}")
        print(f"   🎯 Model Hedef Sınıfları: {plan.get_yoloe_classes()}")
        print(f"   ⏱️ Derleme Gecikmesi: {res['latency_ms']} ms")

        # Verify model selection
        assert plan.selected_model == expected_model, f"Hata: {plan.selected_model} != {expected_model}"

        # End-to-end plan inference
        if expected_model == "safety_detector":
            plan_res = detector.detect_with_plan("bus.jpg", plan)
            print(f"   ✅ Plan Çıkarımı Yapıldı: {len(plan_res.boxes)} ihlal/nesne tespit edildi.")
            for b in plan_res.boxes:
                print(f"      🚨 [{b.cls_name}] {b.conf:.2f} {b.xyxy}")

    print("\n" + "=" * 70)
    print("🎉 TÜM MODEL YÖNLENDİRME, YOLOE AYRIŞTIRMA VE TRITON TESTLERİ BAŞARIYLA TAMAMLANDI!")
    print("=" * 70)


if __name__ == "__main__":
    main()
