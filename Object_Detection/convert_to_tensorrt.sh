#!/usr/bin/env bash
# ==============================================================================
# 3S - ONNX → TensorRT Engine Dönüşüm Scripti
# Container: triton_yoloe_server | TRT: 8.6.1 | GPU: GTX 1650 Ti (4 GB)
# ==============================================================================
# Çalıştırma: ./Object_Detection/convert_to_tensorrt.sh
# Süre tahmini: ~25-45 dakika (4 GB VRAM - GTX 1650 Ti)
# ==============================================================================

set -e

CONTAINER="triton_yoloe_server"
TRTEXEC="/usr/src/tensorrt/bin/trtexec"
MODEL_BASE="/models"

# Renk kodları
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}=================================================================${NC}"
echo -e "${CYAN}  3S — ONNX → TensorRT Engine Dönüşümü${NC}"
echo -e "${CYAN}  Container: ${CONTAINER} | TRT v8.6.1 | GPU: GTX 1650 Ti${NC}"
echo -e "${CYAN}=================================================================${NC}"
echo ""

# Container kontrolü
if ! docker ps --filter "name=${CONTAINER}" --format "{{.Names}}" | grep -q "^${CONTAINER}$"; then
    echo -e "${RED}HATA: '${CONTAINER}' container'ı çalışmıyor.${NC}"
    echo -e "${YELLOW}Önce Triton'u başlatın: Object_Detection/start_triton_docker.sh${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Container hazır: ${CONTAINER}${NC}"
echo ""

# GPU durumu
echo -e "${BLUE}--- GPU Durumu ---${NC}"
docker exec "${CONTAINER}" nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
echo ""

# ==============================================================================
# Yardımcı fonksiyon
# ==============================================================================
convert_model() {
    local MODEL_NAME="$1"
    local ONNX_PATH="${MODEL_BASE}/${MODEL_NAME}/1/model.onnx"
    local ENGINE_PATH="${MODEL_BASE}/${MODEL_NAME}/1/model.plan"
    shift 2
    local EXTRA_ARGS="$@"

    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  [$(date '+%H:%M:%S')] Dönüştürülüyor: ${MODEL_NAME}${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "  ONNX  : ${ONNX_PATH}"
    echo -e "  Engine: ${ENGINE_PATH}"
    echo -e "  Args  : ${EXTRA_ARGS}"
    echo ""

    local CMD="${TRTEXEC} \
        --onnx=${ONNX_PATH} \
        --saveEngine=${ENGINE_PATH} \
        --fp16 \
        --workspace=2048 \
        ${EXTRA_ARGS} \
        2>&1 | tail -20"

    if docker exec "${CONTAINER}" bash -c "${TRTEXEC} \
        --onnx=${ONNX_PATH} \
        --saveEngine=${ENGINE_PATH} \
        --fp16 \
        --workspace=2048 \
        ${EXTRA_ARGS}" 2>&1 | tee /tmp/trt_${MODEL_NAME}.log | tail -25; then
        echo ""
        local ENGINE_SIZE=$(docker exec "${CONTAINER}" du -h "${ENGINE_PATH}" 2>/dev/null | cut -f1)
        echo -e "${GREEN}  ✅ ${MODEL_NAME} engine hazır! (${ENGINE_SIZE})${NC}"
        echo -e "${GREEN}  Kayıt: ${ENGINE_PATH}${NC}"
    else
        echo -e "${RED}  ❌ ${MODEL_NAME} dönüşümü BAŞARISIZ! Log: /tmp/trt_${MODEL_NAME}.log${NC}"
        cat /tmp/trt_${MODEL_NAME}.log | tail -30
        return 1
    fi
    echo ""
}

# ==============================================================================
# 1. coco_detector — YOLO11 COCO 80 sınıf
#    Input : [batch, 3, height, width]  — tüm boyutlar dinamik
#    Output: [batch, 84, anchors]
#    Profile: 640x640 fixed spatial, batch 1-8
# ==============================================================================
convert_model "coco_detector" "" \
    "--minShapes=images:1x3x640x640" \
    "--optShapes=images:4x3x640x640" \
    "--maxShapes=images:8x3x640x640"

# ==============================================================================
# 2. safety_detector — YOLO11 PPE/İSG (14 sınıf)
#    Input : [batch, 3, height, width]  — tüm boyutlar dinamik
#    Output: [batch, 14, anchors]
#    Profile: 640x640 fixed spatial, batch 1-8
# ==============================================================================
convert_model "safety_detector" "" \
    "--minShapes=images:1x3x640x640" \
    "--optShapes=images:4x3x640x640" \
    "--maxShapes=images:8x3x640x640"

# ==============================================================================
# 3. anomaly_detector — 3D Conv Video Anomali Skoru
#    Input : [batch, 3, 16, 224, 224]  — spatial/temporal sabit, batch dinamik
#    Output: [batch, 1]
#    Profile: batch 1-16
# ==============================================================================
convert_model "anomaly_detector" "" \
    "--minShapes=video_segment:1x3x16x224x224" \
    "--optShapes=video_segment:4x3x16x224x224" \
    "--maxShapes=video_segment:16x3x16x224x224"

# ==============================================================================
# 4. yoloe_detector — Decoupled Open-Vocabulary YOLOE
#    Input 1: [batch, 3, 640, 640]         — batch dinamik, spatial sabit
#    Input 2: [batch, num_classes, 512]    — batch + num_classes dinamik
#    Output : [batch, 4+num_classes, 8400]
#    Profile: text_feats num_classes 1-16
# ==============================================================================
convert_model "yoloe_detector" "" \
    "--minShapes=images:1x3x640x640,text_feats:1x1x512" \
    "--optShapes=images:1x3x640x640,text_feats:1x4x512" \
    "--maxShapes=images:8x3x640x640,text_feats:8x16x512"

# ==============================================================================
# Sonuç özeti
# ==============================================================================
echo ""
echo -e "${CYAN}=================================================================${NC}"
echo -e "${CYAN}  Dönüşüm Tamamlandı — Engine Dosya Boyutları${NC}"
echo -e "${CYAN}=================================================================${NC}"
for model in coco_detector safety_detector anomaly_detector yoloe_detector; do
    PLAN="${MODEL_BASE}/${model}/1/model.plan"
    if docker exec "${CONTAINER}" test -f "${PLAN}" 2>/dev/null; then
        SIZE=$(docker exec "${CONTAINER}" du -h "${PLAN}" 2>/dev/null | cut -f1)
        echo -e "  ${GREEN}✅ ${model}${NC}: ${SIZE}"
    else
        echo -e "  ${RED}❌ ${model}${NC}: model.plan bulunamadı"
    fi
done

echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  SONRAKİ ADIM: config.pbtxt güncelleme ve Triton restart${NC}"
echo -e "${YELLOW}  Komut: Object_Detection/apply_tensorrt_configs.sh${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
