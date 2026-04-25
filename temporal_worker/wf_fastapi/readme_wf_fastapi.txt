# Run fastapi Locally for POC / Testing
docker run -it --rm -p 8000:8000 \
  -e GIT_REPO=https://github.com/gohils/fastapi-repo \
  -e BRANCH=main \
  -e APP_MODULE=app1.main:app \
  -e PORT=8000 \
  ghcr.io/gohils/reusable-fastapi-runtime:latest


docker run -it --rm -p 8000:8000 \
  -e GIT_REPO=https://github.com/gohils/temporal1-repo \
  -e BRANCH=main \
  -e APP_MODULE=temporal_worker.wf_fastapi.main:app \
  -e PORT=8000 \
  -e TASK_QUEUE=payments-task-queue \
  -e TEMPORAL_HOST=temporal-server-demo.australiaeast.cloudapp.azure.com:7233 \
  ghcr.io/gohils/reusable-fastapi-runtime:latest

Step — Run worker Locally for POC / Testing
docker run -it --rm \
  -e GIT_REPO=https://github.com/gohils/temporal-worker-repo.git \
  -e BRANCH=main \
  -e WORKER_FILE=run_payment_worker.py \
  -e TASK_QUEUE=payments-task-queue \
  -e TEMPORAL_HOST=temporal-server-demo.australiaeast.cloudapp.azure.com:7233 \
  ghcr.io/gohils/reusable-fastapi-runtime:latest