#!/usr/bin/env bash
# ==============================================================================
# Docker & NVIDIA Container Toolkit Kurulum Betiği (Ubuntu / Debian)
# NVIDIA Triton Inference Server'ı GPU desteği ile çalıştırmak için gereklidir.
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}====================================================================${NC}"
echo -e "${BLUE}  Docker & NVIDIA Container Toolkit Otomatik Kurulum Yardımcısı   ${NC}"
echo -e "${BLUE}====================================================================${NC}"

if [ "$EUID" -ne 0 ]; then
  echo -e "${YELLOW}Bilgi: Bu betik sistem düzeyinde paket kurduğu için 'sudo' ile çalıştırılmalıdır.${NC}"
  echo -e "Kullanım: ${GREEN}sudo bash $0${NC}\n"
  exec sudo bash "$0" "$@"
fi

TARGET_USER="${SUDO_USER:-$USER}"

echo -e "\n${GREEN}[Adım 1/4] Temel bağımlılıklar güncelleniyor...${NC}"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg lsb-release

echo -e "\n${GREEN}[Adım 2/4] Resmi Docker CE deposu ekleniyor ve kuruluyor...${NC}"
install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
fi

ARCH=$(dpkg --print-architecture)
CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo -e "\n${GREEN}[Adım 3/4] NVIDIA Container Toolkit kuruluyor...${NC}"
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

apt-get update -qq
apt-get install -y -qq nvidia-container-toolkit

echo -e "\n${GREEN}[Adım 4/4] Docker konfigürasyonu ve servis yeniden başlatma...${NC}"
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

if [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ]; then
    echo -e "Kullanıcı '$TARGET_USER' docker grubuna ekleniyor..."
    usermod -aG docker "$TARGET_USER"
fi

echo -e "\n${BLUE}====================================================================${NC}"
echo -e "${GREEN}✅ Kurulum başarıyla tamamlandı!${NC}"
echo -e "Şimdi Triton sunucusunu başlatmak için şu komutu çalıştırabilirsiniz:"
echo -e "  ${YELLOW}./Object_Detection/start_triton_docker.sh${NC}"
echo -e "${BLUE}====================================================================${NC}"
