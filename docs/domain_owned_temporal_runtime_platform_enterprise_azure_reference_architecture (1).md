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


---

# 19. Azure Infrastructure Architecture — Tier 1, Tier 2, Tier 3 with Failover Design

This section defines the **physical Azure infrastructure layout**, networking boundaries, and **failover implementation mechanics** for each tier in the Domain-Owned Temporal Runtime Platform.

---

# 🟢 Tier 1 — Shared Runtime (Lowest Cost / Shared Risk Model)

## 19.1 Azure Architecture Overview

```mermaid
flowchart TB
    subgraph VNET[Azure VNet - Shared Platform]

        subgraph SubnetA[Shared Subnet]
            LB[Azure Internal Load Balancer]
            TEMP1[Temporal Server VM 1]
            TEMP2[Temporal Server VM 2]
            WORKERS[Worker VM Pool]
        end

        subgraph DataLayer[Data Layer]
            PG[(Azure PostgreSQL Flexible Server - Shared)]
        end

        subgraph Clients[Enterprise Apps]
            APP1[FastAPI on Azure App Service]
            APP2[Internal VM Apps]
        end

    end

    APP1 --> LB
    APP2 --> LB

    LB --> TEMP1
    LB --> TEMP2

    TEMP1 --> PG
    TEMP2 --> PG

    WORKERS --> TEMP1
    WORKERS --> TEMP2
```

---

## 19.2 Failover Model (Tier 1)

### Failover Type: **Soft Failover (VM-based)**

| Component | Strategy |
|----------|----------|
| Temporal VM | Restart / switch active node |
| Workers | Auto-reconnect via task queue |
| DB | Managed HA (Azure PostgreSQL HA mode) |

### Failover Flow

```mermaid
sequenceDiagram
    participant App
    participant LB
    participant VM1
    participant VM2
    participant DB

    App->>LB: Workflow Request
    LB->>VM1: Active Routing
    VM1->>DB: Persist State

    Note over VM1: VM Failure

    LB->>VM2: Failover Routing
    VM2->>DB: Resume Execution
    App->>LB: Retry Request
```

### Characteristics
- Lowest cost
- Shared blast radius
- Suitable for non-critical workflows

---

# 🟡 Tier 2 — Semi-Isolated Business Unit Cells

## 19.3 Azure Architecture Overview

```mermaid
flowchart TB

    subgraph VNET[Azure VNet - Enterprise]

        subgraph FinanceCell[Finance Subnet]
            F_LB[Internal LB]
            F_TEMP1[Temporal VM Active]
            F_TEMP2[Temporal VM Standby]
            F_WORKERS[Finance Workers]
            F_DB[(Finance PostgreSQL)]
        end

        subgraph InsuranceCell[Insurance Subnet]
            I_LB[Internal LB]
            I_TEMP1[Temporal VM Active]
            I_TEMP2[Temporal VM Standby]
            I_WORKERS[Insurance Workers]
            I_DB[(Insurance PostgreSQL)]
        end

        subgraph Apps[Enterprise Apps]
            APP[FastAPI / API Gateway Layer]
        end

    end

    APP --> F_LB
    APP --> I_LB

    F_LB --> F_TEMP1
    F_LB --> F_TEMP2

    I_LB --> I_TEMP1
    I_LB --> I_TEMP2

    F_TEMP1 --> F_DB
    F_TEMP2 --> F_DB

    I_TEMP1 --> I_DB
    I_TEMP2 --> I_DB

    F_WORKERS --> F_LB
    I_WORKERS --> I_LB
```

---

## 19.4 Failover Model (Tier 2)

### Failover Type: **Controlled Domain Failover**

Each business unit has independent failover.

### Flow
```mermaid
sequenceDiagram
    participant Client
    participant LB
    participant ActiveVM
    participant StandbyVM
    participant LeaseDB
    participant PostgreSQL

    Client->>LB: Workflow Request
    LB->>ActiveVM: Route
    ActiveVM->>PostgreSQL: Write State
    ActiveVM->>LeaseDB: Heartbeat

    Note over ActiveVM: Failure Detected

    StandbyVM->>LeaseDB: Acquire Lease
    StandbyVM->>PostgreSQL: Validate State
    LB->>StandbyVM: Redirect Traffic
```

### Characteristics
- Business-unit isolation
- Independent recovery domains
- Medium cost / medium resilience

---

# 🔴 Tier 3 — Fully Isolated Domain-Owned Cells (Enterprise Critical Systems)

## 19.5 Azure Architecture Overview

```mermaid
flowchart TB

    subgraph PaymentsVNET[Payments VNet]
        P_LB[Private LB]
        P_VM1[Temporal VM Active]
        P_VM2[Temporal VM Standby]
        P_WORKERS[Worker Pool]
        P_DB[(Payments PostgreSQL)]
        P_LEASE[(Lease DB Table)]
    end

    subgraph ClaimsVNET[Claims VNet]
        C_LB[Private LB]
        C_VM1[Temporal VM Active]
        C_VM2[Temporal VM Standby]
        C_WORKERS[Worker Pool]
        C_DB[(Claims PostgreSQL)]
        C_LEASE[(Lease DB Table)]
    end

    subgraph EnterpriseApps[Enterprise Apps]
        API[FastAPI on Azure App Service OR Private VM]
    end

    API --> P_LB
    API --> C_LB

    P_LB --> P_VM1
    P_LB --> P_VM2

    C_LB --> C_VM1
    C_LB --> C_VM2

    P_VM1 --> P_DB
    P_VM2 --> P_DB

    C_VM1 --> C_DB
    C_VM2 --> C_DB

    P_WORKERS --> P_LB
    C_WORKERS --> C_LB
```

---

## 19.6 Failover Model (Tier 3)

### Failover Type: **Strict Lease-Based Leadership Election**

### Flow
```mermaid
sequenceDiagram
    participant Client
    participant Gateway
    participant ActiveVM
    participant LeaseTable
    participant StandbyVM
    participant DB

    Client->>Gateway: Request Workflow
    Gateway->>ActiveVM: Route
    ActiveVM->>DB: Persist Event
    ActiveVM->>LeaseTable: Heartbeat

    Note over ActiveVM: Failure

    LeaseTable->>StandbyVM: Lease Expired
    StandbyVM->>DB: Validate State
    StandbyVM->>LeaseTable: Acquire Lease
    Gateway->>StandbyVM: Redirect Traffic
```

---

## 19.7 Tier 3 Key Properties

- Fully isolated domain failure zones
- No shared blast radius
- Independent scaling per domain
- Regulatory compliance friendly (banking / insurance)
- Highest cost, highest resilience

---

# 20. Cross-Tier Azure Networking Model

```mermaid
flowchart LR

    Internet --> AzureFrontDoor[Azure Front Door / WAF]

    AzureFrontDoor --> AppGateway[Application Gateway]

    AppGateway --> VNET1[Tier 1 Shared VNet]
    AppGateway --> VNET2[Tier 2 Business Unit VNet]
    AppGateway --> VNET3[Tier 3 Domain VNet]

    VNET1 --> DB1[(Shared PostgreSQL)]
    VNET2 --> DB2[(BU PostgreSQL)]
    VNET3 --> DB3[(Domain PostgreSQL)]
```

---

# 21. Enterprise Failover Design Summary

| Tier | Failover Style | RPO | RTO | Isolation |
|------|--------------|-----|-----|----------|
| Tier 1 | Soft VM failover | Medium | Medium | Low |
| Tier 2 | BU-level controlled failover | Low | Low | Medium |
| Tier 3 | Lease-based deterministic failover | Near-zero | Fastest | High |

---

# 22. Key Design Insight

Azure is used as:
- Compute substrate (VMs)
- Network isolation boundary (VNet/Subnets)
- Managed state layer (PostgreSQL HA)
- Traffic control plane (App Gateway / Load Balancer)

Temporal is NOT treated as a monolith — it is:
> A distributed domain execution fabric deployed per business isolation requirement.

