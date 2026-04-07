# Intelligent Business Process Automation (IBPA) System – Design Document
**Stack:** ReactJS (Frontend) ↔ FastAPI (Backend) ↔ Temporal (Workflow Engine) ↔ PostgreSQL/Blob Storage (DB & Documents)

---

## 1. Overview

This system enables enterprises to automate **complex, human-supervised workflows** such as KYC, invoice processing, or HR onboarding. It integrates:

- **ReactJS**: User interface for customers and managers.
- **FastAPI**: REST API backend handling CRUD operations, workflow triggers, signals, and reporting.
- **Temporal**: Workflow orchestration engine for reliable, asynchronous, human-in-the-loop process automation.
- **Database**: PostgreSQL for structured workflow, task, and document metadata. Blob storage for document images/PDFs.

**Goals:**

- Support human + AI hybrid workflows.
- Capture and validate documents with structured metadata.
- Enable real-time task monitoring and approval.
- Maintain fully auditable process logs.

---

## 2. High-Level Architecture

```
[ReactJS Frontend]
        |
        v
[FastAPI Backend]  -----> [Temporal Workflow Engine]
        |                        |
        |                        v
        |                  [Workflow Activity Workers]
        |                        |
        v                        v
[PostgreSQL DB] <-----> [Blob/S3 Storage for Documents]
```

**Description:**

1. **ReactJS Frontend**
   - Customer portal: Submit forms, upload documents.
   - Manager portal: Review tasks, approve/reject workflows.
   - Workflow monitoring dashboard: Track status, pending tasks.

2. **FastAPI Backend**
   - Provides **REST endpoints** for CRUD, workflow control, monitoring, and ad-hoc queries.
   - Integrates with **Temporal** to start workflows asynchronously, send signals, and track execution.

3. **Temporal Workflow Engine**
   - Orchestrates asynchronous business workflows.
   - Executes child activities: document validation, OCR processing, AI-assisted verification, notifications.
   - Supports human-in-the-loop tasks via signals.
   - Guarantees retries, durability, and audit logging.

4. **Database (PostgreSQL)**
   - Stores workflow metadata, document records, approvals, and audit logs.
   - Tables: `automation_process_header`, `automation_process_item`, `workflow_approval_task`, `workflow_instance`, `workflow_activity_instance`, `workflow_ocr_data`, `erp_crm_documents`.

5. **Blob/S3 Storage**
   - Stores actual document files (PDFs, images).
   - URLs referenced in DB (`document_url`).

---

## 3. Data Flow

### 3.1 Customer Workflow

1. User submits KYC form on ReactJS frontend.
2. ReactJS POSTs `/process/create` → creates a **header** in DB.
3. User uploads documents → POST `/process/add_item` → creates **items** linked to header.
4. Backend triggers Temporal workflow → async processing starts: OCR extraction, AI verification, assign human tasks.
5. Temporal logs every activity in `workflow_activity_instance`.
6. ReactJS monitors workflow via `/monitor/workflows` and `/process/reference/{reference_id}`.

### 3.2 Manager Approval Workflow

1. Manager views pending tasks on ReactJS `/monitor/tasks`.
2. Manager selects task → loads header + documents (`/process/{header_id}`).
3. Manager approves/rejects → POST `/workflow/signal/`.
4. Temporal updates workflow state.
5. Backend updates `workflow_approval_task` and `automation_process_item`.
6. ReactJS reflects updated status in near real-time.

### 3.3 Admin / Reporting Flow

1. Admin submits SELECT queries via `/api/app_data_retrieval`.
2. Backend executes safe queries on DB and returns results.
3. ReactJS visualizes results in dashboards.

---

## 4. ReactJS Page Structure

| Page Name | Key API Endpoints | Description |
|-----------|-----------------|-------------|
| CustomerOnboardingPage | `/process/create`, `/process/add_item`, `/workflow/start_by_reference/{reference_id}` | Form submission, document upload, trigger workflow |
| WorkflowStatusPage | `/process/reference/{reference_id}` | Show header + document + workflow status |
| TaskGridPage | `/monitor/tasks` | Manager view of pending approval tasks |
| DocumentReviewItem | `/process/{header_id}`, `/workflow/signal/` | Review document, approve/reject |
| WorkflowMonitorPage | `/monitor/workflows`, `/monitor/workflows/{workflow_id}` | Detailed workflow execution logs |
| AdminQueryPage | `/api/app_data_retrieval` | Ad-hoc data queries for admins |

---

## 5. FastAPI Endpoints Overview

| Endpoint | Method | Function |
|----------|--------|---------|
| `/process/create` | POST | Create header/case |
| `/process/add_item` | POST | Add documents/line items |
| `/process/{header_id}` | PATCH/GET | Update/fetch header |
| `/process/reference/{reference_id}` | GET | Fetch header + items by reference |
| `/monitor/workflows` | GET | List workflows |
| `/monitor/workflows/{workflow_id}` | GET | Workflow details |
| `/monitor/tasks` | GET | List approval tasks |
| `/workflow/start/` | POST | Start workflow asynchronously |
| `/workflow/start_by_reference/{reference_id}` | POST | Start workflow for existing process |
| `/workflow/terminate/{workflow_id}` | POST | Terminate workflow |
| `/workflow/signal/` | POST | Send approval/reject signals |
| `/api/app_data_retrieval` | POST | Execute safe SELECT queries |

---

## 6. Database Design

**Key Relationships:**

- `automation_process_header` 1 → N `automation_process_item`
- `workflow_instance` 1 → N `workflow_activity_instance`
- `workflow_instance` 1 → N `workflow_approval_task`

**Important Fields:**

- **Header:** reference_id, workflow_type, declared_data, verification_status
- **Item:** document_id, doc_type, document_url, declared_data, status
- **Approval Task:** assigned_role, status, decision, comments
- **Workflow Instance:** workflow_id, status, input_data, domain
- **Activity Instance:** task_name, activity_type, status, input/output data

---

## 7. Temporal Workflow Design

- **Workflow Type:** `HybridEnterpriseSTPWorkflow`
- **Activities:**
  1. Preprocessing: validate input, deactivate old items
  2. OCR extraction → store in `workflow_ocr_data`
  3. AI verification → update `automation_process_item`
  4. Assign approval tasks → insert into `workflow_approval_task`
  5. Send notifications / escalate if SLA breached
  6. Complete workflow → update `workflow_instance`

- **Signals:**
  - `manual_approval` → updates task and workflow status

- **Parallelism:**
  - Fan-out for document-level activities
  - Fan-in for task aggregation

---

## 8. Security & Access

- **Authentication**: JWT or OAuth2 (recommended for production)
- **Authorization**: Role-based (Customer / Manager / Admin)
- **SQL Safety**: `/api/app_data_retrieval` restricts to SELECT queries with keyword filtering
- **Document Storage**: Private S3/Blob with signed URLs for frontend access

---

## 9. Future Enhancements

1. **WebSocket/Event Streaming** for real-time workflow status
2. **Multi-file Upload Endpoint** (multipart/form-data)
3. **Audit Logging** for all user actions (frontend + signals)
4. **Batch Workflow Start** for multiple headers
5. **Advanced Reporting** with query builder in frontend

---

## 10. Summary

This system design supports:

- **End-to-end workflow automation** from document upload → AI verification → manager approval → ERP integration.
- **ReactJS frontend** interacts seamlessly with **FastAPI**, which orchestrates **Temporal workflows** and persists metadata in **PostgreSQL**.
- Fully **extensible**, with auditability, asynchronous task mana