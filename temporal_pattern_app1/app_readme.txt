# build and deploy container with detached mode (up -d option Run in background)
docker-compose -f docker-compose-worker-pattern1.yml up -d

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