#!/bin/bash
set -e

# -----------------------------
# CONFIG
# -----------------------------
RG="1-ai-llm-rg"
VM_NAME="temporal-server-vm"
IMAGE="Ubuntu2204"
SIZE="Standard_D2as_v5"
DNS_NAME="temporal-server-demo"

# -----------------------------
# 1. CREATE VM (Spot)
# -----------------------------
echo "🚀 Creating Azure Spot VM..."

az vm create \
  --resource-group "$RG" \
  --name "$VM_NAME" \
  --image "$IMAGE" \
  --size "$SIZE" \
  --priority Spot \
  --eviction-policy Deallocate \
  --max-price -1 \
  --admin-username azureuser \
  --ssh-key-values ~/.ssh/id_rsa.pub \
  --public-ip-address-dns-name "$DNS_NAME"

# -----------------------------
# 2. OPEN PORTS (ALL for demo)
# -----------------------------
echo "🔓 Opening ports..."

az vm open-port \
  --resource-group "$RG" \
  --name "$VM_NAME" \
  --port "*"

# -----------------------------
# 3. INSTALL + RUN DOCKER ON VM
# -----------------------------
echo "⚙️ Installing Docker + running Temporal stack..."

az vm run-command invoke \
  --resource-group "$RG" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts @- <<'EOF'

set -e

echo "Updating system..."
apt update -y

echo "Installing Docker, Compose, Git, Python..."
apt install -y docker.io docker-compose git python3-pip

echo "Enabling Docker..."
systemctl enable docker
systemctl start docker

echo "Cloning repo..."
rm -rf temporal1-repo
git clone https://github.com/gohils/temporal1-repo.git

cd temporal1-repo/linux_v1

echo "Starting Temporal + Postgres via Docker Compose..."
docker-compose -f docker-compose-image-postgres.yml up -d

echo "Deployment complete"
EOF


echo "🎉 VM and Temporal server deployment completed!"
echo "🌐 Access via: temporal-server-demo.<region>.cloudapp.azure.com:7233 (or your configured ports)"