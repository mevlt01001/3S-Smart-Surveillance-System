#!/usr/bin/env bash
# NVIDIA Triton Inference Server Başlatma Betiği

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
MODEL_REPO="$DIR/model_repository"

echo "=========================================================="
echo "  NVIDIA Triton Inference Server (YOLOE Decoupled Modeli) "
echo "=========================================================="
echo "Model Deposu: $MODEL_REPO"

# Docker kontrolü
if ! command -v docker &> /dev/null; then
    echo "HATA: 'docker' komutu bulunamadı."
    echo "Docker ve NVIDIA Container Toolkit'i otomatik kurmak için şu komutu çalıştırabilirsiniz:"
    echo "  sudo bash $DIR/install_docker_prerequisites.sh"
    exit 1
fi

# Docker soket yetki kontrolü (Oturum yenilenmediyse otomatik sg docker ile çalıştır)
if ! docker info &> /dev/null; then
    if sg docker -c "docker info" &> /dev/null; then
        echo "Bilgi: Docker grup yetkisi mevcut oturum için aktif ediliyor..."
        exec sg docker -c "$0 $*"
    else
        echo "Bilgi: Docker erişimi için sudo kullanılıyor..."
        exec sudo "$0" "$@"
    fi
fi

echo "Triton Docker container başlatılıyor (GPU ile)..."
docker run --gpus all --rm -it \
    --name triton_yoloe_server \
    --shm-size=1g \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    -p 8000:8000 \
    -p 8001:8001 \
    -p 8002:8002 \
    -v "$MODEL_REPO":/models \
    nvcr.io/nvidia/tritonserver:24.01-py3 \
    tritonserver --model-repository=/models --log-verbose=0
