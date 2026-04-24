#!/usr/bin/env bash
set -euo pipefail

# ==============================
# CONFIG
# ==============================
RESOURCE_GROUP="1-ai-llm-rg"
LOCATION="australiaeast"
VM_NAME="temporal-server-vm"
VM_SIZE="Standard_D2as_v5"
ADMIN_USER="azureuser"
DNS_NAME="temporal-server-demo"

REPO_URL="https://github.com/gohils/temporal1-repo.git"

# ==============================
# CREATE VM (Spot)
# ==============================
echo "🚀 Creating VM..."

az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION"

az vm create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --image Ubuntu2204 \
  --size "$VM_SIZE" \
  --priority Spot \
  --eviction-policy Deallocate \
  --max-price -1 \
  --admin-username "$ADMIN_USER" \
  --ssh-key-values ~/.ssh/id_rsa.pub \
  --public-ip-address-dns-name "$DNS_NAME"

az vm open-port \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --port '*'

FQDN="$DNS_NAME.$LOCATION.cloudapp.azure.com"

echo "✅ VM Created: $FQDN"

# ==============================
# BOOTSTRAP + DEPLOY (ONE SHOT)
# ==============================
echo "🚀 Bootstrapping VM + Deploying stack..."

az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "
    set -eux

    echo '================================='
    echo 'BOOTSTRAP STARTED'
    date
    hostname
    echo '================================='

    # ------------------------------
    # Install base dependencies
    # ------------------------------
    sudo apt update

    sudo apt install -y \
      docker.io \
      docker-compose \
      python3-pip \
      git \
      curl

    # ------------------------------
    # Enable Docker
    # ------------------------------
    sudo systemctl enable docker
    sudo systemctl start docker

    sudo usermod -aG docker $ADMIN_USER

    echo 'Docker version:'
    sudo docker --version

    echo 'Docker Compose version:'
    sudo docker-compose --version

    echo '================================='
    echo 'BOOTSTRAP COMPLETE'
    date
    echo '================================='
"

echo ""
echo "🎯 DONE"
echo "SSH into VM:"
echo "ssh $ADMIN_USER@$FQDN"