#!/usr/bin/env bash
# ==============================================================================
# AegisVision — TensorRT config.pbtxt Güncelleme & Triton Yeniden Başlatma
# Dönüşüm tamamlandıktan sonra çalıştırın:
#   Object_Detection/apply_tensorrt_configs.sh
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_REPO="${DIR}/model_repository"
CONTAINER="triton_yoloe_server"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

echo ""
echo -e "${CYAN}=== AegisVision: TensorRT Config Güncelleme ===${NC}"
echo ""

# Tüm engine'ların mevcut olup olmadığını kontrol et
MISSING=0
for model in coco_detector safety_detector anomaly_detector yoloe_detector; do
    if [ ! -f "${MODEL_REPO}/${model}/1/model.plan" ]; then
        echo -e "${RED}❌ EKSIK: ${model}/1/model.plan — Önce convert_to_tensorrt.sh çalıştırın${NC}"
        MISSING=1
    fi
done
[ $MISSING -eq 1 ] && exit 1

echo -e "${GREEN}✅ Tüm model.plan dosyaları mevcut.${NC}"
echo ""

# ------------------------------------------------------------------------------
# 1. coco_detector — YOLO11 COCO, 80 sınıf
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[1/4]${NC} coco_detector config güncelleniyor..."
cat > "${MODEL_REPO}/coco_detector/config.pbtxt" << 'EOF'
name: "coco_detector"
backend: "tensorrt"
max_batch_size: 8

input [
  {
    name: "images"
    data_type: TYPE_FP32
    dims: [ 3, 640, 640 ]
  }
]

output [
  {
    name: "output0"
    data_type: TYPE_FP32
    dims: [ 84, -1 ]
  }
]

dynamic_batching {
  max_queue_delay_microseconds: 5000
}

instance_group [
  {
    count: 1
    kind: KIND_GPU
  }
]
EOF
echo -e "  ${GREEN}✅ coco_detector/config.pbtxt güncellendi${NC}"

# ------------------------------------------------------------------------------
# 2. safety_detector — YOLO11 PPE İSG, 14 sınıf
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[2/4]${NC} safety_detector config güncelleniyor..."
cat > "${MODEL_REPO}/safety_detector/config.pbtxt" << 'EOF'
name: "safety_detector"
backend: "tensorrt"
max_batch_size: 8

input [
  {
    name: "images"
    data_type: TYPE_FP32
    dims: [ 3, 640, 640 ]
  }
]

output [
  {
    name: "output0"
    data_type: TYPE_FP32
    dims: [ 14, -1 ]
  }
]

dynamic_batching {
  max_queue_delay_microseconds: 5000
}

instance_group [
  {
    count: 1
    kind: KIND_GPU
  }
]
EOF
echo -e "  ${GREEN}✅ safety_detector/config.pbtxt güncellendi${NC}"

# ------------------------------------------------------------------------------
# 3. anomaly_detector — 3D Conv Video Anomali Skoru
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[3/4]${NC} anomaly_detector config güncelleniyor..."
cat > "${MODEL_REPO}/anomaly_detector/config.pbtxt" << 'EOF'
name: "anomaly_detector"
backend: "tensorrt"
max_batch_size: 16

input [
  {
    name: "video_segment"
    data_type: TYPE_FP32
    dims: [ 3, 16, 224, 224 ]
  }
]

output [
  {
    name: "logits"
    data_type: TYPE_FP32
    dims: [ 1 ]
  }
]

dynamic_batching {
  max_queue_delay_microseconds: 5000
}

instance_group [
  {
    count: 1
    kind: KIND_GPU
  }
]
EOF
echo -e "  ${GREEN}✅ anomaly_detector/config.pbtxt güncellendi${NC}"

# ------------------------------------------------------------------------------
# 4. yoloe_detector — Decoupled Open-Vocabulary
# ------------------------------------------------------------------------------
echo -e "${YELLOW}[4/4]${NC} yoloe_detector config güncelleniyor..."
cat > "${MODEL_REPO}/yoloe_detector/config.pbtxt" << 'EOF'
name: "yoloe_detector"
backend: "tensorrt"
max_batch_size: 8

input [
  {
    name: "images"
    data_type: TYPE_FP32
    dims: [ 3, 640, 640 ]
  },
  {
    name: "text_feats"
    data_type: TYPE_FP32
    dims: [ -1, 512 ]
  }
]

output [
  {
    name: "outputs"
    data_type: TYPE_FP32
    dims: [ -1, 8400 ]
  }
]

instance_group [
  {
    count: 1
    kind: KIND_GPU
  }
]
EOF
echo -e "  ${GREEN}✅ yoloe_detector/config.pbtxt güncellendi${NC}"

# ------------------------------------------------------------------------------
# Triton'u yeniden başlat
# ------------------------------------------------------------------------------
echo ""
echo -e "${CYAN}--- Triton yeniden başlatılıyor ---${NC}"
docker restart "${CONTAINER}"
echo -e "  Triton yeniden başlatıldı, modellerin yüklenmesi bekleniyor..."
sleep 8

# Sağlık kontrolü
echo ""
echo -e "${CYAN}--- Model Durumu ---${NC}"
if curl -sf http://localhost:8000/v2/health/ready > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Triton HAZIR${NC}"
    for model in coco_detector safety_detector anomaly_detector yoloe_detector; do
        if curl -sf "http://localhost:8000/v2/models/${model}" > /dev/null 2>&1; then
            echo -e "  ${GREEN}✅ ${model}: YÜKLÜ (TensorRT)${NC}"
        else
            echo -e "  ${RED}❌ ${model}: YÜKLENEMEDİ${NC}"
        fi
    done
else
    echo -e "${RED}❌ Triton henüz hazır değil. Logları kontrol edin.${NC}"
fi

echo ""
echo -e "${CYAN}=== Güncelleme Tamamlandı ===${NC}"
echo ""
