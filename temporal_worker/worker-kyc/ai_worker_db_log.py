# ai_worker_db_log.py
import uuid
import os
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from psycopg_pool import ConnectionPool
from functools import wraps

import logging
# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
# ------------------------------------------------
# PostgreSQL connection pool
# ------------------------------------------------
POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING","postgresql://postgres.sceeibvfwcdhooljytsq:Zsupabase~1@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres")
if not POSTGRES_CONNECTION_STRING:
    raise ValueError("POSTGRES_CONNECTION_STRING is not set")

logger.info(f"Connecting to DB: {POSTGRES_CONNECTION_STRING}")

try:
    pool = ConnectionPool(
        POSTGRES_CONNECTION_STRING,
        min_size=2,
        max_size=10,
        timeout=30
    )

    # Test connection immediately
    with pool.connection() as conn:
        logger.info("✅ Database connection successful")

except Exception as e:
    logger.error(f"❌ Failed to connect DB: {e}")
    raise

# ------------------------------------------------
# Utility: Convert objects to JSON-safe dict
# ------------------------------------------------
def to_serializable(obj):
    if is_dataclass(obj):
        return asdict(obj)
    elif isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_serializable(i) for i in obj]
    else:
        return obj

# ------------------------------------------------
# Upsert Workflow Instance
# ------------------------------------------------
def upsert_workflow_instance(
    workflow_id: str,
    workflow_type: str,
    status: str,
    input_data: Optional[dict] = None,
    reference_id: Optional[str] = None,
    header_id: Optional[int] = None,
    end_time: Optional[datetime] = None,
    domain: Optional[str] = None,
    parent_workflow: Optional[str] = None,
    workflow_group: Optional[str] = None
):
    """Insert or update workflow instance with proper start/end time handling"""
    try:
        query = """
        INSERT INTO workflow_instance(
            workflow_id,
            workflow_type,
            status,
            input_data,
            domain,
            parent_workflow,
            workflow_group,
            reference_id,
            header_id,
            start_time,
            end_time
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)
        ON CONFLICT (workflow_id) DO UPDATE
        SET status = EXCLUDED.status,
            input_data = EXCLUDED.input_data,
            domain = EXCLUDED.domain,
            parent_workflow = EXCLUDED.parent_workflow,
            workflow_group = EXCLUDED.workflow_group,
            reference_id = EXCLUDED.reference_id,
            header_id = EXCLUDED.header_id,
            end_time = COALESCE(EXCLUDED.end_time, workflow_instance.end_time),
            updated_at = NOW()
        """
        values = (
            workflow_id,
            workflow_type,
            status,
            json.dumps(input_data) if input_data else None,
            domain,
            parent_workflow,
            workflow_group,
            reference_id,
            header_id,
            end_time
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
            conn.commit()
    except Exception as e:
        print("❌ Workflow instance logging failed:", e)

# ------------------------------------------------
# Upsert activity Instance
# ------------------------------------------------
def build_activity_values(log):
    return (
        log.get("activity_id"),
        log.get("workflow_id"),
        log.get("execution_run_id"),
        log.get("node_instance_id"),
        log.get("parent_activity_id"),
        log.get("execution_path_id"),
        log.get("child_workflow_id"),
        log.get("header_id"),
        log.get("item_id"),
        log.get("step_key"),
        log.get("display_name"),
        log.get("node_id"),
        log.get("prev_node_id"),
        log.get("branch_id"),
        log.get("attempt", 1),
        log.get("workflow_type"),
        log.get("task_name"),
        log.get("activity_type"),
        log.get("activity_group"),
        log.get("status"),
        log.get("status_reason"),   # ✅ FIX ADDED
        json.dumps(to_serializable(log.get("input_data"))),
        json.dumps(to_serializable(log.get("output_data"))),
        json.dumps(to_serializable(log.get("input_context"))),
        log.get("start_time"),
        log.get("end_time"),
        log.get("duration_ms"),
    )

def upsert_activity_event(log: Dict[str, Any]):

    record_values = build_activity_values(log)

    try:
        query = """
        INSERT INTO workflow_activity_instance(
            activity_id, workflow_id, execution_run_id,
            node_instance_id, parent_activity_id, execution_path_id,
            child_workflow_id, header_id, item_id,
            step_key, display_name,
            node_id, prev_node_id, branch_id,
            attempt,
            workflow_type, task_name, activity_type, activity_group,
            status, status_reason,
            input_data, output_data, input_context,
            start_time, end_time, duration_ms
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (activity_id) DO UPDATE
        SET status=EXCLUDED.status, status_reason=EXCLUDED.status_reason,
            output_data=EXCLUDED.output_data, input_context=EXCLUDED.input_context,
            end_time=EXCLUDED.end_time, duration_ms=EXCLUDED.duration_ms
        """

        # print(f"====== VALUES COUNT: {len(record_values)}", record_values)
        # print("======== QUERY PLACEHOLDERS:", query.count("%s"))

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, record_values)
            conn.commit()

    except Exception as e:
        print("❌ DB logging failed:", e)
        
# ------------------------------------------------
# Decorator: log_activity
# ------------------------------------------------
def log_activity(display_name: str,  activity_type: str = "SystemIntegration", activity_group: Optional[str] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):

            input_obj = args[0] if args else None
            ctx = getattr(input_obj, "context", {}) or {}
            payload = getattr(input_obj, "payload", {}) or {}

            wf_id = ctx.get("workflow_id", "UNKNOWN")
            wf_type = ctx.get("workflow_type", "UNKNOWN")

            run_id = ctx.get("execution_run_id") or wf_id

            start_time = datetime.utcnow()

            # -----------------------------
            # GRAPH STATE (already prepared by workflow engine)
            # -----------------------------
            node_id = ctx.get("current_node_id") or display_name
            prev_node_id = ctx.get("prev_node_id")
            branch_id = ctx.get("branch_id", "MAIN")
            execution_path_id = ctx.get("execution_path_id") or branch_id

            activity_id = str(uuid.uuid4())
            node_instance_id = str(uuid.uuid4())

            base_event = {
                "activity_id": activity_id,
                "workflow_id": wf_id,
                "execution_run_id": run_id,

                "node_instance_id": node_instance_id,
                "parent_activity_id": ctx.get("parent_activity_id"),

                "execution_path_id": execution_path_id,

                "child_workflow_id": ctx.get("child_workflow_id"),
                "header_id": ctx.get("header_id"),
                "item_id": ctx.get("item_id"),

                "step_key": display_name,
                "display_name": display_name,

                # ✅ CRITICAL FOR REACTFLOW EDGE LIGHTING
                "node_id": node_id,
                "prev_node_id": prev_node_id,
                "branch_id": branch_id,

                "attempt": 1,

                "workflow_type": wf_type,
                "task_name": func.__name__,
                "activity_type": activity_type,
                "activity_group": activity_group,

                "input_context": ctx,
                "start_time": start_time
            }

            # -----------------------------
            # START EVENT
            # -----------------------------
            upsert_activity_event({
                **base_event,
                "status": "STARTED",
                "input_data": payload
            })

            try:
                result = await func(*args, **kwargs)
                end_time = datetime.utcnow()

                # -----------------------------
                # SUCCESS EVENT
                # -----------------------------
                upsert_activity_event({
                    **base_event,
                    "status": "COMPLETED",
                    "output_data": getattr(result, "response", None),
                    "end_time": end_time,
                    "duration_ms": int((end_time - start_time).total_seconds() * 1000)
                })

                return result

            except Exception as e:
                end_time = datetime.utcnow()

                # -----------------------------
                # FAILURE EVENT
                # -----------------------------
                upsert_activity_event({
                    **base_event,
                    "status": "FAILED",
                    "status_reason": str(e),
                    "output_data": {
                        "error": str(e),
                        "failed_node": node_id,
                        "prev_node": prev_node_id,
                        "payload_snapshot": payload
                    },
                    "end_time": end_time,
                    "duration_ms": int((end_time - start_time).total_seconds() * 1000)
                })

                raise

        return wrapper
    return decorator

# ------------------------------------------------
# Upsert Approval Signal (Immutable Log)
# ------------------------------------------------
def log_approval_signal(
workflow_id, workflow_type, task_name,task_type=None,approval_signal_name=None,
assigned_role=None, assigned_to=None, action_by=None, status="PENDING", status_reason=None,
decision=None, comments=None, reference_id=None, priority="MEDIUM",
sla_deadline=None, sla_breached=False,  additional_data=None,
task_approval_summary=None, signal_payload=None,
signal_received_at=None, completed_at=None, header_id=None, item_id=None
):
    """
    Upsert human-in-the-loop approval task for Temporal workflows.
    Supports automated and manual approval signals, SLA, and task summary.
    Updates existing record if present, otherwise inserts a new one.
    """
    now = datetime.now(timezone.utc)
    if not completed_at and status in ("COMPLETED", "REJECTED"):
        completed_at = now

    try:
        with pool.connection() as conn, conn.cursor() as cur:
            # UPSERT logic
            cur.execute("""
                INSERT INTO workflow_approval_task(
                    workflow_id, workflow_type, header_id, item_id, reference_id,
                    task_name, task_type, approval_signal_name, assigned_role, assigned_to, action_by,
                    status, decision, status_reason, comments, priority,
                    sla_deadline, sla_breached, additional_data,
                    task_approval_summary, signal_payload, signal_received_at,
                    completed_at, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (workflow_id, item_id, task_name) 
                DO UPDATE SET
                    workflow_type = EXCLUDED.workflow_type,
                    header_id = EXCLUDED.header_id,
                    reference_id = EXCLUDED.reference_id,
                    approval_signal_name = EXCLUDED.approval_signal_name,
                    assigned_role = EXCLUDED.assigned_role,
                    assigned_to = EXCLUDED.assigned_to,
                    action_by = EXCLUDED.action_by,
                    status = EXCLUDED.status,
                    decision = EXCLUDED.decision,
                    status_reason = EXCLUDED.status_reason,
                    comments = EXCLUDED.comments,
                    priority = EXCLUDED.priority,
                    sla_deadline = EXCLUDED.sla_deadline,
                    sla_breached = EXCLUDED.sla_breached,
                    task_approval_summary = EXCLUDED.task_approval_summary,
                    additional_data = EXCLUDED.additional_data,
                    signal_payload = EXCLUDED.signal_payload,
                    signal_received_at = EXCLUDED.signal_received_at,
                    completed_at = EXCLUDED.completed_at,
                    updated_at = NOW()
            """, (
                workflow_id, workflow_type, header_id, item_id, reference_id,
                task_name, task_type, approval_signal_name, assigned_role, assigned_to, action_by,
                status, decision, status_reason, comments, priority,
                sla_deadline, sla_breached, 
                json.dumps(additional_data) if additional_data else None,
                json.dumps(task_approval_summary) if task_approval_summary else None,
                json.dumps(signal_payload) if signal_payload else None,
                signal_received_at,
                completed_at, now
            ))
            conn.commit()
    except Exception as e:
        print("❌ Approval upsert failed:", e)
        raise
# ------------------------------------------------
# Append OCR Result - New function to store OCR results in a separate table
# ------------------------------------------------
def store_ocr_result(
    workflow_id: str,
    document_url: str,
    header_id: Optional[int] = None,
    item_id: Optional[int] = None,
    doc_type: Optional[str] = None,
    ocr_raw: Optional[str] = None,
    ocr_result: Optional[dict] = None,
    extracted_fields: Optional[dict] = None,
    status: str = "NEW"
) -> int:
    """
    Store OCR output into PostgreSQL and return ocr_document_id.
    
    Automatically extracts workflow_id, header_id, and item_id from input_obj if not provided.
    """
    try:

        query = """
        INSERT INTO workflow_ocr_data (
            workflow_id,
            header_id,
            item_id,
            doc_type,
            document_url,
            ocr_raw,
            ocr_result,
            extracted_fields,
            status
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING ocr_document_id
        """

        values = (
            workflow_id,
            header_id,
            item_id,
            doc_type,
            document_url,
            ocr_raw,
            json.dumps(to_serializable(ocr_result)) if ocr_result else None,
            json.dumps(to_serializable(extracted_fields)) if extracted_fields else None,
            status
        )

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                ocr_document_id = cur.fetchone()[0]
            conn.commit()

        logger.info(f"✅ OCR stored successfully (id={ocr_document_id})")
        return ocr_document_id

    except Exception as e:
        logger.error(f"❌ OCR storage failed: {e}", exc_info=True)
        raise
    
def get_ocr_result(
    ocr_document_id: Optional[int] = None,
    document_url: Optional[str] = None,
    workflow_id: Optional[str] = None
) -> Optional[dict]:
    """
    Fetch OCR result from workflow_ocr_data table.
    Can search by ocr_document_id, document_url, or workflow_id.
    Returns structured OCR JSON if found, otherwise None.
    """
    if not (ocr_document_id or document_url or workflow_id):
        raise ValueError("At least one of ocr_document_id, document_url, or workflow_id must be provided")

    query = "SELECT ocr_result FROM workflow_ocr_data WHERE "
    conditions = []
    values = []

    if ocr_document_id:
        conditions.append("ocr_document_id = %s")
        values.append(ocr_document_id)
    if document_url:
        conditions.append("document_url = %s")
        values.append(document_url)
    if workflow_id:
        conditions.append("workflow_id = %s")
        values.append(workflow_id)

    query += " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT 1"

    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                row = cur.fetchone()
                if row and row[0]:
                    return row[0]
                else:
                    return None
    except Exception as e:
        print(f"❌ Failed to fetch OCR result: {e}")
        raise
    
# ------------------------------------------------
# Store Document into Generic ERP Table
# ------------------------------------------------
def store_erp_document(
    doc_id: str,
    doc_type: str,
    workflow_id: str,
    header_data: dict,
    line_items: Optional[list] = None,
    approval_status: str = "PENDING",
    approved_by: Optional[str] = None,
    doc_date: Optional[Any] = None,
    owner_name: Optional[str] = None,
    reference_id: Optional[str] = None,
    child_workflow_id: Optional[str] = None,
    header_id: Optional[int] = None,
    item_id: Optional[int] = None
) -> str:
    """
    Store any document (invoice, passport, receipt, etc.) into ERP PostgreSQL table.
    All fields are safely converted to strings where needed to prevent workflow failures.
    Returns the document ID.
    """
    try:
        # Ensure doc_date is always string
        doc_date_str = str(doc_date) if doc_date is not None else "1970-01-01"

        # Ensure owner_name and reference_id are strings
        owner_name_str = str(owner_name) if owner_name is not None else "Unknown Owner"
        reference_id_str = str(reference_id) if reference_id is not None else f"REF-{uuid.uuid4().hex[:6]}"
        approved_by_str = str(approved_by) if approved_by is not None else "SYSTEM"

        query = """
        INSERT INTO erp_crm_documents (
            doc_id, doc_type, workflow_id, child_workflow_id, header_id, item_id, doc_date, owner_name,
            reference_id, approval_status, approved_by, header_data, line_items
        ) VALUES (%s, %s, %s,%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (doc_id) DO UPDATE
        SET header_data = EXCLUDED.header_data,
            line_items = EXCLUDED.line_items,
            approval_status = EXCLUDED.approval_status,
            approved_by = EXCLUDED.approved_by
        RETURNING doc_id
        """

        values = (
            doc_id,
            doc_type,
            workflow_id, child_workflow_id, header_id, item_id,
            doc_date_str,
            owner_name_str,
            reference_id_str,
            approval_status,
            approved_by_str,
            json.dumps(header_data),
            json.dumps(line_items) if line_items else None
        )

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                returned_id = cur.fetchone()[0]
                conn.commit()

        print(f"✅ [ERP] Document stored successfully: {returned_id}")
        return returned_id

    except Exception as e:
        print(f"❌ ERP storage failed for {doc_id}:", e)
        raise