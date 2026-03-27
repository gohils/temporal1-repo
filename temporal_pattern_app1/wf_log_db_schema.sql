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
    input_data JSONB,
    domain TEXT,
    document_id TEXT,
    parent_workflow TEXT,
    workflow_group TEXT,
    requires_manual_review BOOLEAN DEFAULT FALSE,
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
    execution_order INT,
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
    task_name TEXT NOT NULL,              -- Display name (UI)
    task_type TEXT NOT NULL,              -- Machine classification
    approval_signal_name TEXT,            -- for event-based triggers

    -- Assignment
    assigned_role TEXT,
    assigned_to TEXT,                     -- specific user (optional)
    action_by TEXT,                       -- who completed the task
    -- State
    status TEXT NOT NULL,                 -- PENDING, COMPLETED, REJECTED, etc.
    decision TEXT,                        -- APPROVED / REJECTED / AUTO_APPROVED

    -- Workflow control
    workflow_step INT DEFAULT 1,
    is_current BOOLEAN DEFAULT TRUE,      -- only 1 active task per workflow/step

    -- Business context
    business_key TEXT,                    -- invoice_id / customer_id
    priority TEXT DEFAULT 'MEDIUM',

    -- SLA & escalation
    sla_deadline TIMESTAMP,
    escalated BOOLEAN DEFAULT FALSE,

    -- UI / extensibility
    additional_data JSONB,
    attachments JSONB,

    -- Audit
    comments TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);


-- =========================================================
-- 4. OCR DATA (Document ingestion layer)
-- =========================================================
CREATE TABLE IF NOT EXISTS workflow_ocr_data (
    document_id BIGSERIAL PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    document_url TEXT,
    ocr_raw TEXT,
    ocr_result JSONB,
    extracted_fields JSONB,
    status TEXT DEFAULT 'NEW',
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
    workflow_type TEXT,
    doc_date TEXT,
    owner_name TEXT,
    reference_id TEXT,
    approval_status TEXT DEFAULT 'PENDING',
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
    additional_data JSONB,             

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
    doc_type TEXT,                    -- passport, invoice, direct debit
    document_id TEXT,               -- link to workflow_ocr_data
    document_url TEXT,                -- store S3/Blob URL of uploaded document
    declared_data JSONB,              -- optional per-document declared info
    is_active BOOLEAN DEFAULT TRUE,   -- only 1 active per doc_type

    -- Matching / verification results per document
    matching_result BOOLEAN,          
    matched_result_json JSONB,        
    verification_status TEXT,         -- PROCESSING, VERIFIED, FAILED, REVIEW
    verification_comments TEXT,       -- Human or AI explanation
    verification_details JSONB,       -- LLM + rules reasoning

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