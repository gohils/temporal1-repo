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
CREATE TABLE IF NOT EXISTS workflow_activity_log (
    activity_log_id BIGSERIAL PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    task_name TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    activity_group TEXT,
    status TEXT NOT NULL,
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
    task_name TEXT NOT NULL,              -- Display name (UI)
    task_type TEXT NOT NULL,              -- Machine classification

    -- Assignment
    assigned_role TEXT,
    assigned_to TEXT,                     -- specific user (optional)

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
    form_data JSONB,
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
    document_url TEXT NOT NULL,
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
drop table workflow_instance cascade;
drop table workflow_activity_log cascade;
drop table workflow_approval_task cascade;
drop table workflow_ocr_data;
drop table erp_crm_documents;
