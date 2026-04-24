# Temporal on Azure — Two-VM Private Subnet Architecture with Azure PostgreSQL

## Objective

Refactor the local Docker Compose deployment into an Azure deployment where:

- Azure PostgreSQL Flexible Server is the durable shared state layer
- Temporal server container runs on Azure Linux VM #1
- Worker container(s) run on Azure Linux VM #2
- Both VMs reside in a private subnet
- Communication occurs only over private IPs
- Optional bastion / jump host or VPN is used for administration

---

# 1. Target Azure Architecture

```mermaid
flowchart TB
    USER[Internal App / SDK / VPN User]

    subgraph VNET[Azure Virtual Network]

        subgraph SUBNET1[Private Subnet - Temporal Runtime]
            VM1[Azure Linux VM #1\nTemporal Server Container]
        end

        subgraph SUBNET2[Private Subnet - Worker Runtime]
            VM2[Azure Linux VM #2\nWorker Container]
        end

        subgraph DBSUBNET[Delegated DB Subnet]
            PG[(Azure PostgreSQL Flexible Server)]
        end

        subgraph MGMT[Optional Management Access]
            BASTION[Azure Bastion / VPN / Jumpbox]
        end
    end

    USER --> BASTION
    BASTION --> VM1
    BASTION --> VM2

    VM1 -->|5432| PG
    VM2 -->|7233| VM1
```

---

# 2. Runtime Communication Model

```mermaid
flowchart LR
    CLIENT[Application / SDK Client]

    subgraph VM1[Azure VM 1 - Temporal Server]
        TEMP[Temporal Container\nPort 7233]
    end

    subgraph VM2[Azure VM 2 - Worker]
        WORKER[Worker Container\npython worker.py]
    end

    PG[(Azure PostgreSQL Flexible Server)]

    CLIENT -->|gRPC 7233| TEMP
    WORKER -->|Poll Task Queues| TEMP
    TEMP -->|Dispatch Workflow + Activity Tasks| WORKER

    TEMP -->|Workflow State / History| PG
```

---

# 3. Azure Networking Layout

Recommended VNet:

- VNet: 10.10.0.0/16
- Subnet-temporal: 10.10.1.0/24
- Subnet-worker: 10.10.2.0/24
- Subnet-postgres: 10.10.3.0/24

```mermaid
flowchart TB
    VNET[10.10.0.0/16]

    VNET --> S1[10.10.1.0/24\nTemporal VM Subnet]
    VNET --> S2[10.10.2.0/24\nWorker VM Subnet]
    VNET --> S3[10.10.3.0/24\nAzure PostgreSQL Delegated Subnet]

    S1 --> VM1[10.10.1.4\nTemporal VM]
    S2 --> VM2[10.10.2.4\nWorker VM]
    S3 --> PG[10.10.3.4\nAzure PostgreSQL]
```

---

# 4. NSG Rules

## VM1 (Temporal Server VM)

Allow:
- TCP 7233 from worker subnet and client subnet
- SSH only from Bastion / VPN
- TCP 5432 outbound to Azure PostgreSQL

## VM2 (Worker VM)

Allow:
- Outbound TCP 7233 to Temporal VM
- SSH only from Bastion / VPN

## PostgreSQL Flexible Server

Allow:
- TCP 5432 inbound only from VM1 subnet

```mermaid
flowchart LR
    VM2[Worker VM]
    VM1[Temporal VM]
    PG[(Azure PostgreSQL)]

    VM2 -->|TCP 7233| VM1
    VM1 -->|TCP 5432| PG

    VM2 -. no direct DB access .-> PG
```

---

# 5. VM1 Container Layout

Azure Linux VM #1 hosts only Temporal server-related containers.

```mermaid
flowchart TB
    subgraph VM1[Azure Linux VM #1]
        TEMP[temporal container]
        ADMIN[temporal-admin-tools]
        NS[create-namespace container]
    end

    PG[(Azure PostgreSQL Flexible Server)]

    ADMIN -->|Create Schema| PG
    TEMP -->|Read/Write Workflow State| PG
    NS -->|Register Namespace| TEMP
```

Example docker-compose.yml on VM1:

```yaml
services:
  temporal-admin-tools:
    image: temporalio/admin-tools:latest
    environment:
      DB: postgres12
      DB_PORT: 5432
      POSTGRES_USER: temporal
      POSTGRES_PWD: ${POSTGRES_PASSWORD}
      POSTGRES_SEEDS: mypg.postgres.database.azure.com
    volumes:
      - ./scripts:/scripts
    entrypoint: ["/bin/sh"]
    command: /scripts/setup-postgres.sh

  temporal:
    image: temporalio/server:latest
    ports:
      - "7233:7233"
    environment:
      DB: postgres12
      DB_PORT: 5432
      POSTGRES_USER: temporal
      POSTGRES_PWD: ${POSTGRES_PASSWORD}
      POSTGRES_SEEDS: mypg.postgres.database.azure.com
      BIND_ON_IP: 0.0.0.0
      DYNAMIC_CONFIG_FILE_PATH: config/dynamicconfig/development-sql.yaml
    depends_on:
      - temporal-admin-tools

  temporal-create-namespace:
    image: temporalio/admin-tools:latest
    environment:
      TEMPORAL_ADDRESS: localhost:7233
      DEFAULT_NAMESPACE: default
    depends_on:
      - temporal
```

---

# 6. VM2 Worker Container Layout

VM2 only hosts worker containers.

```mermaid
flowchart TB
    subgraph VM2[Azure Linux VM #2]
        WORKER[worker container]

        subgraph INSIDE[Inside Worker Container]
            CLIENT[Temporal Client]
            WF[workflow.py]
            ACT[activities.py]
        end
    end

    TEMP[Temporal Server VM1]

    WORKER --> TEMP
    CLIENT --> WF
    CLIENT --> ACT
```

Example docker-compose.yml on VM2:

```yaml
services:
  payment-worker:
    build: ./worker
    container_name: payment-worker
    restart: always
    environment:
      TEMPORAL_SERVER: 10.10.1.4:7233
      TASK_QUEUE: payments
    ports: []
```

---

# 7. Workflow Execution Across Two VMs

```mermaid
sequenceDiagram
    participant Client
    participant VM1 as Temporal Container on VM1
    participant PG as Azure PostgreSQL
    participant VM2 as Worker Container on VM2
    participant WF as Workflow Script
    participant ACT as Activity Script

    Client->>VM1: StartWorkflow()
    VM1->>PG: Persist workflow started

    VM2->>VM1: Poll workflow task queue
    VM1-->>VM2: Deliver workflow task

    VM2->>WF: Execute workflow code
    WF->>VM1: Schedule activity

    VM1->>PG: Persist activity scheduled

    VM2->>VM1: Poll activity queue
    VM1-->>VM2: Deliver activity task

    VM2->>ACT: Execute activity.py
    ACT-->>VM2: Result

    VM2->>VM1: Complete activity
    VM1->>PG: Persist completion

    VM1-->>Client: Workflow complete
```

---

# 8. Optional HA Version with Second Temporal VM

If later you want failover:

```mermaid
flowchart LR
    CLIENT[Client]

    LB[Internal Load Balancer\ntemporal.internal]

    VM1[Temporal VM #1 Active]
    VM3[Temporal VM #2 Standby]

    VM2[Worker VM]

    PG[(Azure PostgreSQL)]

    CLIENT --> LB
    LB --> VM1
    LB -. failover .-> VM3

    VM2 --> LB

    VM1 --> PG
    VM3 --> PG
```

---

# 9. Recommended Azure Resources

| Resource | Purpose |
|---|---|
| Azure VNet | Private network for all components |
| Azure Linux VM #1 | Runs Temporal server containers |
| Azure Linux VM #2 | Runs worker containers |
| Azure PostgreSQL Flexible Server | Durable workflow state store |
| Azure Bastion | Secure admin access without public SSH |
| Network Security Groups | Restrict east-west traffic |
| Private DNS Zone | Resolve postgres and temporal internal names |
| Azure Key Vault | Store DB password and TLS secrets |

---

# 10. Recommended Internal DNS Names

| Component | Internal Name |
|---|---|
| Temporal Server | temporal.internal.company.local |
| PostgreSQL | postgres.internal.company.local |
| Worker VM | worker01.internal.company.local |

Then the worker container can use:

```yaml
TEMPORAL_SERVER: temporal.internal.company.local:7233
```

instead of a hardcoded IP.

---

# 11. Recommended Future Improvements

- Add second Temporal VM for failover
- Add second Worker VM for horizontal scale
- Use Azure Private Endpoint for PostgreSQL
- Store secrets in Azure Key Vault
- Use Docker systemd service for automatic startup
- Replace raw VMs with VM Scale Sets later if desired

