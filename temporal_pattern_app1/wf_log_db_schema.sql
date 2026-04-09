-- =========================================================
-- Worker Schema v1
-- Domain: Intelligent Document Processing (STP)
-- =========================================================

-- =========================================================
-- 1. WORKFLOW INSTANCE (Top-level tracking)
-- =========================================================
CREATE TABLE IF NOT EXISTS workflow_instance (
    workflow_id TEXT PRIMARY KEY,
    workflow_type TEXT NOT NULL,
    status TEXT,
    error_message TEXT,
    error_step TEXT,
    decision TEXT,               -- AUTO_APPROVED / REJECTED / MANUAL_REVIEW
    current_step TEXT,          -- "OCR", "VALIDATION", "APPROVAL"    
    input_data JSONB,
    domain TEXT,
    reference_id TEXT,
    -- Link to header / case
    header_id BIGINT ,

    parent_workflow TEXT,
    workflow_group TEXT,

    -- UI / extensibility
    additional_data JSONB,
    triggered_by TEXT,      -- user / system
    source TEXT,             -- API / UI / batch
    start_time TIMESTAMP DEFAULT NOW(),
    end_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);


-- =========================================================
-- 2. ACTIVITY LOG (High-volume logging)
-- =========================================================
CREATE TABLE IF NOT EXISTS workflow_activity_instance (
    activity_id  TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    child_workflow_id TEXT, -- for sub-workflows (optional)
    header_id TEXT,         -- <-- added for header linkage
    item_id TEXT,           -- <-- added for item/document linkage
    step_key TEXT,          -- 01_PREPROCESSING, 02_OCR, 03_VALIDATION, 04_APPROVAL, etc.
    display_name TEXT,
    workflow_type TEXT,
    task_name TEXT,
    activity_type TEXT,
    activity_group TEXT,
    status TEXT,
    input_data JSONB,
    output_data JSONB,
    input_context JSONB,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);


-- =========================================================
-- 3. APPROVAL TASK (Human-in-the-loop)
-- =========================================================
CREATE TABLE IF NOT EXISTS workflow_approval_task (
    approval_task_id BIGSERIAL PRIMARY KEY,

    -- Core workflow linkage
    workflow_id TEXT NOT NULL,
    workflow_type TEXT,
    header_id BIGINT,                    -- Link to automation_process_header
    item_id BIGINT,                    -- Link to automation_process_header_item (optional, for document-level tasks)
    -- Business context
    reference_id TEXT,                    -- invoice_id / customer_id
    priority TEXT DEFAULT 'MEDIUM',
    
    -- Task identity
    task_name TEXT NOT NULL,              -- e.g., "Invoice Approval", "KYC Review"
    task_type TEXT ,              -- Display name (UI)
    approval_signal_name TEXT,            -- for event-based triggers
    task_approval_summary JSONB,          -- brief context for approver (e.g., invoice total, customer name)

    -- Assignment
    assigned_role TEXT,
    assigned_to TEXT,                     -- specific user (optional)
    action_by TEXT,                       -- who completed the task
    -- State
    status TEXT NOT NULL,                 -- PENDING, COMPLETED, REJECTED, etc.
    decision TEXT,                        -- APPROVED / REJECTED / AUTO_APPROVED
    status_reason TEXT,

    is_current BOOLEAN DEFAULT TRUE,      -- only 1 active 

    -- SLA & escalation
    sla_deadline TIMESTAMP,
    sla_breached BOOLEAN DEFAULT FALSE,

    -- Temporal signal tracking
    signal_payload JSONB,
    signal_received_at TIMESTAMP,
    additional_data JSONB,              -- for extensibility (e.g., escalation history, reminder count)
    -- Audit
    comments TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Unique for UPSERT
    CONSTRAINT workflow_task_unique UNIQUE(workflow_id, item_id, task_name)
);

-- =========================================================
-- 4. OCR DATA (Document ingestion layer)
-- =========================================================
CREATE TABLE IF NOT EXISTS workflow_ocr_data (
    ocr_document_id BIGSERIAL PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    header_id BIGINT,
    item_id BIGINT,
    doc_type TEXT,
    document_url TEXT,
    ocr_raw TEXT,
    ocr_result JSONB,
    extracted_fields JSONB,
    status TEXT DEFAULT 'NEW',
    version INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =========================================================
-- 5. ERP / CRM DOCUMENT STORE (Final output layer)
-- =========================================================
CREATE TABLE IF NOT EXISTS erp_crm_documents (
    doc_id TEXT PRIMARY KEY,
    doc_type TEXT NOT NULL,
    workflow_id TEXT,
    child_workflow_id  TEXT , -- for sub-workflows (optional)
    header_id BIGINT,
    item_id BIGINT,
    workflow_type TEXT,
    doc_date TEXT,
    owner_name TEXT,
    reference_id TEXT,
    approval_status TEXT ,
    approved_by TEXT,
    header_data JSONB NOT NULL,
    line_items JSONB,
    comments TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =========================================================
-- 6. -- automation_process_header (Workflow / Case Header)
CREATE TABLE IF NOT EXISTS automation_process_header (
    id BIGSERIAL PRIMARY KEY,
    reference_id TEXT,               -- customer_id, invoice number, employee_id, etc.
    -- Domain-driven workflow-level metadata
    workflow_type TEXT,          -- e.g., Customer Onboarding, Invoice Processing, 
    process_name TEXT,                     -- e.g., KYC, Billing, Payroll
    process_group TEXT,              -- e.g., Sales, Finance, HR

    -- User-declared / structured data (source of truth for entire case)
    declared_data JSONB,             

    -- Aggregate / case-level verification (optional, derived from items)
    verification_status TEXT,        -- VERIFIED / FAILED / REVIEW
    verification_comments TEXT,      -- optional summary / human explanation
    verification_data JSONB,             
    additional_header_data JSONB,             

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =========================================================
-- 7. -- automation_process_item (Documents / Line Items)
CREATE TABLE IF NOT EXISTS automation_process_item (
    id BIGSERIAL PRIMARY KEY,
    
    -- Link to header / case
    header_id BIGINT NOT NULL,
    
    -- Workflow instance per document
    workflow_id TEXT,

    -- Document / line item details
    document_id TEXT,                    -- document number, employee ID, etc.
    declared_doc_type TEXT,                    -- passport, invoice, direct debit
    doc_type TEXT,                    -- passport, invoice, direct debit
    latest_ocr_document_id BIGINT,               -- link to workflow_ocr_data
    document_url TEXT,                -- store S3/Blob URL of uploaded document
    declared_data JSONB,              -- optional per-document declared info
    is_active BOOLEAN DEFAULT TRUE,   -- only 1 active per doc_type

    -- Matching / verification results per document
    matching_result BOOLEAN,          
    matched_result_json JSONB,        
    verification_status TEXT,         -- PROCESSING, VERIFIED, FAILED, REVIEW
    verification_comments TEXT,       -- Human or AI explanation
    verification_details JSONB,       -- LLM + rules reasoning
    additional_item_data JSONB,             

    -- Processing status (tracking per document)
    status TEXT DEFAULT 'PROCESSING', -- PROCESSING, VERIFIED, FAILED, REVIEW

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =========================================================
drop table workflow_instance cascade;
drop table workflow_activity_instance cascade;
drop table workflow_approval_task cascade;
drop table workflow_ocr_data;
drop table erp_crm_documents;
drop table automation_process_header;
drop table automation_process_item;