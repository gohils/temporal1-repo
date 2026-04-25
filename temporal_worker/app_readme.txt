# build and deploy container with detached mode (up -d option Run in background)
docker-compose -f docker-compose-worker-pattern1.yml up -d

# Step 1: create .env from terminal
cat > .env <<EOF
POSTGRES_HOST=zdb1.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_USER=sqladmin
POSTGRES_PASSWORD=Zsupabase~1
POSTGRES_DB=temporal
POSTGRES_VISIBILITY_DB=temporal_visibility
EOF

# step 2: run compose with env file
docker-compose --env-file .env -f docker-compose.yml up -d

# Verify containers are running
docker ps

# Check container logs
docker logs -f wf-worker-pattern1
docker logs -f wf-mgt-api

docker-compose -f docker-compose-worker-pattern1.yml down -v

1️⃣ Using docker exec into the container

Run an interactive shell inside the container:
docker exec -it wf-worker1 bash
pip list
pip show httpx

🐳 Temporal App – Docker quick reference guide
1️⃣ Check running containers
# List all running containers
docker ps

# List all containers (running + stopped)
docker ps -a
2️⃣ View container logs
# Follow logs in real-time
docker logs -f wf-worker1
docker logs -f wf-mgt-api

# Show last N lines
docker logs --tail 50 wf-worker1
3️⃣ Stop / terminate containers
# Stop gracefully
docker stop wf-worker1
docker stop wf-mgt-api

# Force stop immediately
docker kill wf-worker1
docker kill wf-mgt-api

# Stop and remove container (for redeploy)
docker rm -f wf-worker1
docker rm -f wf-mgt-api
4️⃣ Start containers (first-time deployment)
# Build Docker images
docker compose -f docker-compose-worker-pattern1.yml build

# Start containers in background (detached mode)
docker compose -f docker-compose-worker-pattern1.yml up -d

# Optional: force recreate (fresh start)
docker compose -f docker-compose-worker-pattern1.yml up -d --force-recreate
5️⃣ Redeploy / update to new version
# Pull latest code from repo
git pull origin main

# Rebuild Docker images with latest code
docker compose -f docker-compose-worker-pattern1.yml build

# Bring up containers (detached)
docker compose -f docker-compose-worker-pattern1.yml up -d

# Force recreate if needed
docker compose -f docker-compose-worker-pattern1.yml up -d --force-recreate
6️⃣ Monitoring & troubleshooting
Worker logs → Shows workflow start/completion & activity execution
FastAPI logs → Shows HTTP requests triggering workflows
Check container status:
docker ps -a | grep wf
Auto-restart containers (from docker-compose.yml) will recover after crash if restart: unless-stopped is set
7️⃣ Stop all containers at once
docker stop $(docker ps -q)         # stop all running containers
docker rm -f $(docker ps -aq)       # stop + remove all containers

✅ Support engineer tips

Always check logs first before stopping a container
Use force recreate only when deploying new code
Ensure FastAPI and worker task queue match environment variables
docker ps + docker logs -f are usually enough to confirm workflow activity

# Run fastapi Locally for POC / Testing
docker run -it --rm -p 8000:8000 \
  -e GIT_REPO=https://github.com/gohils/temporal-worker-repo.git \
  -e BRANCH=main \
  -e APP_MODULE=wf_fastapi.main:app \
  -e TASK_QUEUE=default-task-queue\
  -e TEMPORAL_HOST=temporal-server-demo.australiaeast.cloudapp.azure.com:7233 \
  -e PORT=8000 \
  ghcr.io/gohils/reusable-fastapi-runtime:latest

docker run -it --rm \
  -e GIT_REPO=https://github.com/gohils/temporal-worker-repo.git \
  -e BRANCH=main \
  -e WORKER_FILE=worker-invoice/ai_doc_invoice_worker_v2.py \
  -e TASK_QUEUE=finance-invoice-queue \
  -e TEMPORAL_HOST=temporal-server-demo.australiaeast.cloudapp.azure.com:7233 \
  ghcr.io/gohils/reusable-fastapi-runtime:latest

  docker run -it --rm \
  -e GIT_REPO=https://github.com/gohils/temporal-worker-repo.git \
  -e BRANCH=main \
  -e WORKER_FILE=worker-kyc/ai_doc_kyc_worker_v2.py \
  -e TASK_QUEUE=kyc-onboarding-queue \
  -e TEMPORAL_HOST=temporal-server-demo.australiaeast.cloudapp.azure.com:7233 \
  ghcr.io/gohils/reusable-fastapi-runtime:latest

  https://zreactapp2.z8.web.core.windows.net/