# Domain-Owned Temporal Runtime Platform
## Ephemeral Compute + Shared Durable State Architecture on Azure

---

# 1. Executive Summary

This platform defines a domain-owned workflow execution architecture built on Temporal and Azure PostgreSQL Flexible Server, designed for large enterprises that require:

- Strong domain isolation
- Independent ownership of workflow runtimes
- Predictable failover behavior
- Controlled infrastructure duplication
- Clear cost vs resilience trade-offs
- Secure private networking between all runtime components

The design intentionally avoids a single global Temporal cluster.

Instead, each business domain becomes an independent execution cell with:

- Its own Temporal runtime
- Its own worker pool
- Its own Azure PostgreSQL state store (or shared business-unit DB)
- Its own failover procedure and SLA

Core principle:

> Compute is disposable. State is durable. Failure is a domain-level concern.

---

# 2. Enterprise Placement Model

In a real enterprise deployment there are four logical layers:

1. Enterprise Applications
2. Workflow Integration Layer
3. Domain Runtime Cells
4. Shared Durable State Layer

```mermaid
flowchart TB
    subgraph Apps[Enterprise Applications]
        PORTAL[Customer Portal]
        ERP[ERP / SAP]
        CRM[CRM]
        MOBILE[Mobile App]
    end

    subgraph Integration[Workflow Integration Layer]
        API[FastAPI Workflow API\nAzure Web App or Integration VM]
    end

    subgraph Domains[Domain Runtime Cells]
        PAY[Payments Domain Cell]
        CLAIMS[Claims Domain Cell]
        LOANS[Loans Domain Cell]
    end

    PORTAL --> API
    ERP --> API
    CRM --> API
    MOBILE --> API

    API --> PAY
    API --> CLAIMS
    API --> LOANS
```

The FastAPI layer is the canonical enterprise integration boundary.

It is responsible for:

- Submitting workflows
- Monitoring workflow status
- Sending workflow signals
- Returning business-friendly status responses
- Hiding internal Temporal details from business applications

---

# 3. Recommended Azure Deployment Topology

Each domain cell is deployed using:

- One Azure Linux VM for active Temporal server container
- One Azure Linux VM for standby Temporal server container
- One or more Azure Linux VMs for workers
- Azure PostgreSQL Flexible Server
- Internal Load Balancer or Nginx gateway
- Private DNS + private subnet

```mermaid
flowchart LR
    APP[FastAPI Workflow API]

    subgraph DomainCell[Payments Domain Cell]
        GW[temporal.payments.internal]

        subgraph Runtime[Private Runtime Subnet]
            VM1[Temporal VM Active]
            VM2[Temporal VM Standby]
            W1[Worker VM 1]
            W2[Worker VM 2]
        end

        PG[(Azure PostgreSQL Flexible Server)]
        LEASE[(domain_runtime_leases)]
    end

    APP --> GW

    GW --> VM1
    GW -. failover .-> VM2

    W1 --> GW
    W2 --> GW

    VM1 --> PG
    VM2 --> PG

    VM1 --> LEASE
    VM2 --> LEASE
```

---

# 4. Networking and Private Connectivity

Recommended network layout:

- VNet: 10.10.0.0/16
- Integration subnet: 10.10.1.0/24
- Temporal subnet: 10.10.2.0/24
- Worker subnet: 10.10.3.0/24
- PostgreSQL delegated subnet: 10.10.4.0/24

```mermaid
flowchart TB
    VNET[Azure VNet 10.10.0.0/16]

    VNET --> API_SUBNET[10.10.1.0/24\nFastAPI Web App / VM]
    VNET --> TEMP_SUBNET[10.10.2.0/24\nTemporal VMs]
    VNET --> WORKER_SUBNET[10.10.3.0/24\nWorker VMs]
    VNET --> DB_SUBNET[10.10.4.0/24\nAzure PostgreSQL]
```

Internal DNS examples:

- temporal.payments.internal.company.local
- temporal.claims.internal.company.local
- temporal-ui.payments.internal.company.local
- postgres.payments.internal.company.local

---

# 5. Domain Runtime Cell Internal Architecture

```mermaid
flowchart TB
    subgraph Integration[Workflow Integration Layer]
        API[FastAPI Workflow API]
    end

    subgraph Gateway[Domain Gateway]
        LB[Internal Load Balancer / Nginx]
    end

    subgraph ActiveRuntime[Active Runtime]
        T1[Temporal Server Container\nVM1]
    end

    subgraph StandbyRuntime[Standby Runtime]
        T2[Temporal Server Container\nVM2]
    end

    subgraph Workers[Worker Pool]
        W1[Worker Container VM1]
        W2[Worker Container VM2]
    end

    PG[(Azure PostgreSQL)]
    LEASE[(domain_runtime_leases)]

    API --> LB

    LB --> T1
    LB -. failover .-> T2

    W1 --> LB
    W2 --> LB

    T1 --> PG
    T2 --> PG

    T1 --> LEASE
    T2 --> LEASE
```

---

# 6. Worker Container and Workflow Script Communication

Each worker VM runs one or more worker containers.

Inside each worker container:

- Temporal client connects to the domain gateway
- Polls the assigned task queue
- Executes workflow code
- Executes activity code
- Returns results back to Temporal

```mermaid
flowchart LR
    subgraph WorkerVM[Worker VM]
        subgraph Container[Worker Container]
            CLIENT[Temporal Client]
            POLL[Task Queue Poller]
            WF[workflow.py]
            ACT[activities.py]
        end
    end

    TEMP[temporal.payments.internal:7233]

    CLIENT --> POLL
    POLL --> WF
    POLL --> ACT

    POLL --> TEMP
    TEMP --> POLL
```

---

# 7. Workflow Submission Flow

Business applications do not connect directly to Temporal.

They submit workflows through the FastAPI integration layer.

```mermaid
sequenceDiagram
    participant User as Portal / ERP / CRM
    participant API as FastAPI Workflow API
    participant DB as Business Process DB
    participant Temporal as Temporal Domain Gateway
    participant Worker as Worker VM

    User->>API: POST /workflow_start_by_reference/{reference_id}

    API->>DB: Fetch process header + items
    DB-->>API: Business payload

    API->>Temporal: start_workflow(...)
    Temporal-->>API: workflow_id

    API-->>User: workflow_id + started status

    Worker->>Temporal: Poll task queue
    Temporal-->>Worker: Deliver workflow task
```

Example FastAPI connection setting:

```python
TEMPORAL_HOST = "temporal.payments.internal.company.local:7233"
```

Recommended deployment for FastAPI:

- Azure Web App with VNet Integration
- OR dedicated Integration VM in private subnet

---

# 8. Workflow Monitoring Model

Business users should receive business-friendly status.

They should not need to understand Temporal internals.

```mermaid
sequenceDiagram
    participant User as Business User
    participant API as FastAPI Monitor API
    participant DB as Process DB
    participant Temporal as Temporal Server

    User->>API: GET /process/reference/KYC-20260421-ABC123

    API->>DB: Read process status
    DB-->>API: PROCESSING / APPROVED / FAILED

    API->>Temporal: Optional workflow query
    Temporal-->>API: RUNNING / COMPLETED

    API-->>User: Combined business response
```

Recommended business statuses:

- SUBMITTED
- PROCESSING
- WAITING_FOR_APPROVAL
- COMPLETED
- FAILED
- REJECTED

---

# 9. Real-Time Status Updates

For richer user experience:

- Frontend starts workflow
- Receives workflow_id or reference_id
- Opens WebSocket or SignalR channel
- FastAPI pushes updates whenever DB or workflow state changes

```mermaid
flowchart LR
    UI[Portal UI]
    API[FastAPI + WebSocket / SignalR]
    DB[(Process DB)]
    TEMP[Temporal]

    TEMP --> DB
    DB --> API
    API --> UI
```

---

# 10. Temporal UI Access Model

Temporal Web UI is for operations and support teams only.

It should never be exposed publicly.

```mermaid
flowchart LR
    OPS[Operations Team]
    VPN[VPN / Bastion / Corporate Network]
    UI[Temporal Web UI\nPrivate Internal URL]
    TEMP[Temporal Server]

    OPS --> VPN --> UI --> TEMP
```

Example internal URL:

- http://temporal-ui.payments.internal.company.local:8080

Recommended deployment:

- Same VM as Temporal server
- Or separate admin VM
- Protected by VPN + SSO

---

# 11. Tiered Enterprise Deployment Model

## Tier 1 — Shared Runtime

```mermaid
flowchart TB
    subgraph SharedCluster[Shared Runtime Cluster]
        TEMP[Shared Temporal Runtime]
        WORKERS[Shared Worker Pool]
        DB[(Shared PostgreSQL)]
    end

    PAY[Payments]
    CLAIMS[Claims]
    LOANS[Loans]

    PAY --> TEMP
    CLAIMS --> TEMP
    LOANS --> TEMP

    TEMP --> DB
    WORKERS --> TEMP
```

Characteristics:

- Lowest cost
- Shared infrastructure
- Logical isolation only

## Tier 2 — Semi-Isolated Business Unit Cells

```mermaid
flowchart LR
    subgraph Finance[Finance Cell]
        FT[Finance Temporal]
        FW[Finance Workers]
        FDB[(Finance PostgreSQL)]
    end

    subgraph Insurance[Insurance Cell]
        IT[Insurance Temporal]
        IW[Insurance Workers]
        IDB[(Insurance PostgreSQL)]
    end

    FT --> FDB
    FW --> FT

    IT --> IDB
    IW --> IT
```

Characteristics:

- Isolation by business unit
- Separate databases per unit
- Balanced resilience and cost

## Tier 3 — Fully Isolated Domain Cells

```mermaid
flowchart TB
    subgraph Payments[Payments Cell]
        PT[Payments Temporal]
        PW[Payments Workers]
        PDB[(Payments PostgreSQL)]
    end

    subgraph Claims[Claims Cell]
        CT[Claims Temporal]
        CW[Claims Workers]
        CDB[(Claims PostgreSQL)]
    end

    PT --> PDB
    PW --> PT

    CT --> CDB
    CW --> CT
```

Characteristics:

- Highest isolation
- Dedicated SLA and failover per domain
- Highest infrastructure duplication

---

# 12. Failover Sequence

```mermaid
sequenceDiagram
    participant Gateway
    participant Active as Active Temporal VM
    participant Lease as Lease Table
    participant Standby as Standby Temporal VM
    participant DB as Azure PostgreSQL
    participant Worker

    Active->>Lease: Heartbeat ACTIVE lease

    Note over Active: Failure Occurs

    Lease-->>Standby: Lease expired
    Standby->>Lease: Acquire ACTIVE lease
    Standby->>DB: Validate DB connectivity

    Gateway->>Standby: Route traffic

    Worker->>Gateway: Reconnect automatically
    Gateway-->>Worker: Continue polling
```

---

# 13. Lease Control Table

```sql
CREATE TABLE domain_runtime_leases (
    domain_id TEXT PRIMARY KEY,
    active_node_id TEXT NOT NULL,
    lease_status TEXT NOT NULL,
    lease_expiry TIMESTAMP,
    heartbeat_ts TIMESTAMP
);
```

Purpose:

- Prevent split-brain
- Ensure only one active Temporal server per domain
- Coordinate deterministic failover

---

# 14. Operational Separation

```mermaid
flowchart TB
    USER[Business User]
    OPS[Operations Team]

    API[FastAPI Monitoring API]
    UI[Temporal UI]

    DB[(Business Process DB)]
    TEMP[Temporal Runtime]

    USER --> API
    OPS --> UI

    API --> DB
    UI --> TEMP
```

Business users consume:

- Reference IDs
- Document status
- Approval status
- Business outcome

Operations team consumes:

- Workflow history
- Activity retries
- Task queue backlog
- Failed workflow diagnostics

---

# 15. Final Enterprise Positioning

This platform enables enterprises to evolve from:

> Centralized, tightly coupled workflow infrastructure

into:

> Domain-owned, failure-isolated execution cells with predictable recovery, private connectivity, and tunable infrastructure duplication.

The architecture deliberately trades global HA complexity for:

- Stronger domain ownership
- Easier operational reasoning
- Lower blast radius
- More explicit cost control
- Better alignment with enterprise business structures

