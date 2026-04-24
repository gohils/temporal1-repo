# Temporal Server with Azure PostgreSQL (Docker Compose) --- Step-by-Step Guide

## 🧭 Architecture

-   Azure PostgreSQL Flexible Server in the Austrlia East (Compute size
Standard_B2s (2 vCores, 4 GiB memory, 1280 max iops))
-   Docker VM (Windows/Linux)
-   Temporal Server (gRPC 7233)
-   Temporal UI (8080)
-   Admin Tools (tctl)

------------------------------------------------------------------------

## 🪜 Step 1 --- Azure PostgreSQL Setup
### provision azure postgreSQL and activate following extensions
Add extensions btree_gin, pg_trgm, btree_gist on Azure postgreSQL
PostgreSQL → Server Parameters
Check: azure.extensions
Add: btree_gin, pg_trgm, btree_gist

``` bash
az postgres flexible-server parameter set \
  --resource-group 1-a-databases\
  --server-name zdb1\
  --name azure.extensions \
  --value "btree_gin,pg_trgm,btree_gist"
```
### Create databases

``` sql
CREATE DATABASE temporal;
CREATE DATABASE temporal_visibility;
```

### Run this python script to creat these two database
``` bash
python server_temporal_linux_azure_db\scripts\create_temporal_databases.py 
```

Add extensions on Azure postgreSQL
PostgreSQL → Server Parameters
Check: azure.extensions
Add: btree_gin, pg_trgm, btree_gist

### Network

-   Allow VM IP on port 5432
-   SSL required (Azure PostgreSQL)

------------------------------------------------------------------------

## 🪜 Step 2 --- VM Setup

Install Docker Desktop or Docker Engine.

Verify:

``` bash
docker version
docker compose version
```

------------------------------------------------------------------------

## 🪜 Step 3 --- Folder Structure

    temporal/
     ├── docker-compose.yml
     ├── .env
     ├── config/
     │   └── dynamicconfig/
     │       └── development.yaml

------------------------------------------------------------------------

## 🪜 Step 4 --- .env
``` bash
cat > .env <<EOF
POSTGRES_HOST=zdb1.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_USER=sqladmin
POSTGRES_PASSWORD=Zsupabase~1
POSTGRES_DB=temporal
POSTGRES_VISIBILITY_DB=temporal_visibility
EOF
```
------------------------------------------------------------------------

## 🪜 Step 5 --- Dynamic Config

config/dynamicconfig/development.yaml

``` yaml
system.enableVisibilitySampling:
  - value: true
    constraints: {}
```

------------------------------------------------------------------------
## 🪜 Step 6 --- One-time DB initialization (only first deployment or upgrade)
Run this docker compose only once
``` bash
docker-compose -f docker-compose-temporal-db-init.yml up -d
``` 
#### the following are manually steps of docker-compose-temporal-db-init.yml

Run for: - temporal DB 
``` bash
MSYS_NO_PATHCONV=1 docker run --rm -it \
  --env-file .env \
  -v "$(pwd -W)/scripts:/scripts" \
  --entrypoint /bin/sh \
  temporalio/admin-tools:1.29 \
  -x /scripts/setup-postgres.sh
```
------------------------------------------------------------------------

## 🪜 Step 7 --- Docker Compose Temporal server

``` bash
docker-compose -f docker-compose-temporal-azure.yml up -d 
```
------------------------------------------------------------------------
## 🪜 Step 8 --- One-time Namespace creation on temporal server (only once after deployment)

Run for: - create namespace
``` bash
MSYS_NO_PATHCONV=1 docker run --rm -it \
  --env-file .env \
  --network temporal-network \
  -v "$(pwd -W)/scripts:/scripts" \
  --entrypoint /bin/sh \
  temporalio/admin-tools:1.29 \
  -x /scripts/create-namespace.sh
```

## 🪜 Step 9 --- Verify

``` bash
docker ps
docker logs temporal
```

Expected: - Frontend started - History started - Matching started

------------------------------------------------------------------------

## 🪜 Step 10 --- UI

http://localhost:8080

------------------------------------------------------------------------

## 🪜 Step 11 --- Namespace

``` bash
tctl namespace register default
```

------------------------------------------------------------------------

## 🧠 Key Fixes Learned

-   DB must be `postgres12`
-   Azure requires SSL enabled
-   Dynamic config must be mounted correctly
-   Schema must be initialized before server start
