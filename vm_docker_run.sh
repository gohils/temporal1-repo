#!/usr/bin/env bash
set -euo pipefail

RESOURCE_GROUP="1-ai-llm-rg"
VM_NAME="temporal-server-vm"

REPO_URL="https://github.com/gohils/temporal1-repo.git"

PAYMENTS_WORKERS=3
CLAIMS_WORKERS=2
KYC_WORKERS=1

echo "🚀 Deploying Temporal stack..."

az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "
    set -eux

    export DOCKER_COMPOSE_CMD='sudo docker-compose'

    APP_DIR=/opt/temporal-demo
    mkdir -p \$APP_DIR
    cd \$APP_DIR

    if [ ! -d temporal1-repo ]; then
      git clone $REPO_URL
    fi

    cd temporal1-repo/linux_v1

    \$DOCKER_COMPOSE_CMD -f docker-compose-image-postgres.yml up -d

    echo '⏳ Waiting for Temporal...'
    sleep 20

    cd /opt/temporal-demo/temporal1-repo

    WORKER_DIR=\$(find . -name 'docker-compose-worker-pattern1.yml' | head -n 1 | xargs dirname)

    cd \$WORKER_DIR

    \$DOCKER_COMPOSE_CMD up -d \
      --scale kyc-worker=$KYC_WORKERS

    echo '📦 Containers:'
    sudo docker ps
"

echo "✅ Deployment complete"