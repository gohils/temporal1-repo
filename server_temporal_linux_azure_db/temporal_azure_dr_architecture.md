# Temporal Server Disaster Recovery Architecture on Azure

## Overview
This document describes a production-grade Disaster Recovery (DR) architecture for Temporal deployed on Azure using:
- Azure Linux VMs (same VNet / private subnet)
- Azure PostgreSQL Flexible Server
- Stateless Temporal Server containers
- Stateless Worker services

---

## 1. High-Level Architecture

Azure PostgreSQL (Single Source of Truth)
- Stores all workflow state
- Stores history, visibility, task queues
- Enabled with HA + PITR

Temporal Server Layer (Stateless)
- Frontend Service
- History Service
- Matching Service
- Runs on multiple Azure Linux VMs

Worker Layer (Stateless)
- Executes activities
- Horizontally scalable
- Auto-recovery via task re-assignment

Internal Load Balancer
- Routes gRPC traffic (port 7233) to Temporal servers
```text
                    ┌──────────────────────────────┐
                    │   Azure PostgreSQL (HA)      │
                    │  - temporal DB               │
                    │  - visibility DB             │
                    │  - PITR enabled              │
                    └─────────────┬────────────────┘
                                  │
                  Private VNet (same subnet)
                                  │
     ┌────────────────────────────┴────────────────────────────┐

     ┌──────────────────────┐        ┌──────────────────────┐
     │ Temporal Server VM-1 │        │ Temporal Server VM-2 │
     │ (Primary)            │        │ (Standby / Failover) │
     └──────────┬───────────┘        └──────────┬───────────┘
                │                                │
                └───────────┬────────────────────┘
                            │
                  Internal Load Balancer
                      (TCP :7233)
                            │
     ┌──────────────────────┴──────────────────────┐
     │                                              │
┌───────────────┐                         ┌───────────────┐
│ Worker VM-1   │                         │ Worker VM-2   │
│ (stateless)   │                         │ (stateless)   │
└───────────────┘                         └───────────────┘

```
---

## 2. Key Design Principles

### Database is Source of Truth
All workflow execution state is persisted in Azure PostgreSQL.

### Stateless Compute Layer
Temporal servers and workers are replaceable and do not hold durable state.

### Horizontal Scalability
- Multiple Temporal server VMs
- Multiple worker VMs
- Load-balanced gRPC traffic

---

## 3. Azure Infrastructure Requirements

### Networking
- Azure VNet (single subnet recommended)
- NSG rules:
  - 7233 (Temporal)
  - 5432 (PostgreSQL private endpoint)

### PostgreSQL
Enable:
- High Availability (Zone redundant)
- Automated backups
- Point-in-time restore (PITR)
- Optional geo-redundant backup

---

## 4. Disaster Recovery Scenarios

### Temporal VM Failure
- No workflow loss
- Restart VM or deploy new VM
- Reconnect to PostgreSQL
- Workers continue processing

### Full Temporal Cluster Loss
Steps:
1. Provision new VMs
2. Deploy Docker Compose
3. Point to same PostgreSQL
4. System resumes automatically

### PostgreSQL Failure
- Restore from Azure PITR backup
- Reconnect Temporal cluster
- Full workflow recovery guaranteed

# ⚙️ 4. Temporal Server Layer (DR Design)

## ✔ Deployment model

Run 2 VMs minimum:

### VM-1 (Primary)
- Temporal frontend
- history service
- matching service

### VM-2 (Hot standby)
- Same services installed
- Passive until failover

---

## ✔ Docker Compose (same on both VMs)

```yaml
services:
  temporal:
    image: temporalio/server:1.28

    environment:
      CLUSTER_NAME: temporal-cluster

      DB: postgres12
      DBNAME: temporal
      VISIBILITY_DBNAME: temporal_visibility

      POSTGRES_SEEDS: <azure-postgres-host>
      POSTGRES_USER: <user>
      POSTGRES_PWD: <password>

      SQL_TLS_ENABLED: "true"
      SQL_HOST_VERIFICATION: "true"
      SQL_HOST_NAME: <azure-postgres-host>

      DYNAMIC_CONFIG_FILE_PATH: /etc/temporal/config/dynamicconfig/development.yaml

    ports:
      - "7233:7233"

    restart: unless-stopped
```

---

# 🔁 5. Worker Layer (DR Design)

Workers are:

## ✔ Stateless services

They:
- poll task queues
- execute activities
- report back to Temporal

---

## Worker scaling model

```
Worker VM-1  → queue A
Worker VM-2  → queue A
Worker VM-3  → queue B (optional scaling)
```

---

## Worker failure behavior

If a worker dies:
- Task becomes unacknowledged
- Temporal retries automatically
- Another worker picks it up

✔ No data loss

---

# 🔄 6. Disaster Recovery Scenarios

## 💥 Scenario A — Temporal VM failure

### Impact:
- No orchestration temporarily

### Recovery:
- Start VM-2 or new VM
- Point to same PostgreSQL
- Rejoin cluster

✔ Zero workflow loss

---

## 💥 Scenario B — Entire Temporal cluster lost

### Steps:
- Provision new VMs
- Deploy same docker-compose
- Point to same Azure PostgreSQL
- Start services

✔ Temporal reconstructs all state automatically

---

## 💥 Scenario C — PostgreSQL failure

### Impact:
- Critical failure (system of record lost)

### Recovery:
- Restore from Azure PITR backup
- Reconnect Temporal servers

✔ Full workflow recovery

---

# 🧠 7. Failover Strategy (Production Grade)

## ✔ Option 1 — Active-Passive (Recommended)

- VM-1 active
- VM-2 standby
- Manual or scripted failover

---

## ✔ Option 2 — Active-Active

- Both VMs serve traffic
- Load balancer distributes gRPC calls

⚠ Requires strict config consistency

---

# 🔐 8. Reliability Guarantees

Temporal provides:

- ✔ Exactly-once workflow logic (logical)
- ✔ At-least-once activity execution
- ✔ Durable execution state in PostgreSQL
- ✔ Automatic retry after failure

---

# 📦 9. Backup Strategy (CRITICAL)

## Only backup needed:
👉 Azure PostgreSQL

### Enable:
- PITR (Point-in-time restore)
- Geo-backup (optional)
- Automated backups (default)

---

# 🚀 10. RPO / RTO Targets

| Component       | RPO   | RTO              |
|----------------|-------|------------------|
| Temporal server | 0     | < 5 min          |
| Workers         | 0     | < 1 min          |
| PostgreSQL      | 0–5m  | depends on restore |

---

# 🧠 11. Key Production Insights

- ✔ Temporal servers are disposable
- ✔ Workers are replaceable
- ✔ PostgreSQL is critical dependency
- ✔ No workflow state lives in compute layer

---

# ⚡ Final Mental Model

> Temporal is a stateful system built on a stateless compute layer + durable database
---

## 5. Worker Failure Behavior
- Workers are stateless
- Tasks are retried automatically
- Another worker picks up execution

---

## 6. Backup Strategy

ONLY required backup:
- Azure PostgreSQL database

Recommended:
- PITR enabled
- Geo-redundant backups

No need to backup:
- Temporal servers
- Worker VMs
- Docker containers

---

## 7. RPO / RTO Targets

| Component | RPO | RTO |
|----------|-----|-----|
| Temporal Server | 0 | <5 min |
| Workers | 0 | <1 min |
| PostgreSQL | 0–5 min | depends on restore |

---

## 8. Key Takeaway

Temporal is a stateful system built on:
- Stateless compute layer (servers/workers)
- Stateful persistence layer (PostgreSQL)
