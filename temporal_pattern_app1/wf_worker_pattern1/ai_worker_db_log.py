# log_wf_db_pool.py
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
    document_id: Optional[str] = None,
    requires_manual_review: Optional[bool] = False,
    end_time: Optional[datetime] = None,
    domain: Optional[str] = None,
    parent_workflow: Optional[str] = None,
    workflow_group: Optional[str] = None
):
    """Insert or update a workflow instance record with input_data and document_id"""
    if end_time is None and status in ("COMPLETED", "FAILED"):
        end_time = datetime.utcnow()    

    try:
        query = """
        INSERT INTO workflow_instance(
            workflow_id, workflow_type, status,
            input_data, document_id,
            requires_manual_review, end_time, domain, parent_workflow, workflow_group
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (workflow_id) DO UPDATE
        SET status = EXCLUDED.status,
            input_data = EXCLUDED.input_data,
            document_id = EXCLUDED.document_id,
            requires_manual_review = EXCLUDED.requires_manual_review,
            end_time = EXCLUDED.end_time,
            domain = EXCLUDED.domain,
            parent_workflow = EXCLUDED.parent_workflow,
            workflow_group = EXCLUDED.workflow_group,
            updated_at = NOW()
        """
        values = (
            workflow_id,
            workflow_type,
            status,
            json.dumps(input_data) if input_data else None,
            document_id,
            requires_manual_review,
            end_time,
            domain,
            parent_workflow,
            workflow_group
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
    except Exception as e:
        print("❌ Workflow instance logging failed:", e)

# ------------------------------------------------
# Upsert activity Instance
# ------------------------------------------------
def upsert_activity_event(log: Dict[str, Any]):
    try:
        query = """
        INSERT INTO workflow_activity_instance(
            activity_id,
            workflow_id, execution_order, workflow_type, task_name, activity_type, status,
            input_data, output_data, input_context, start_time, end_time, activity_group
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (activity_id) DO UPDATE
        SET status = EXCLUDED.status,
            output_data = EXCLUDED.output_data,
            end_time = EXCLUDED.end_time
        """
        values = (
            log.get("activity_id"),
            log.get("workflow_id"),
            log.get("execution_order"),
            log.get("workflow_type"),
            log.get("task_name"),
            log.get("activity_type"),
            log.get("status"),
            json.dumps(to_serializable(log.get("input_data"))) if log.get("input_data") else None,
            json.dumps(to_serializable(log.get("output_data"))) if log.get("output_data") else None,
            json.dumps(to_serializable(log.get("input_context"))) if log.get("input_context") else None,
            log.get("start_time"),
            log.get("end_time"),
            log.get("activity_group")
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
    except Exception as e:
        print("❌ DB logging failed:", e)

# ------------------------------------------------
# Decorator: log_activity
# ------------------------------------------------
def log_activity(task_name: str, activity_type: str = "SystemIntegration", activity_group: Optional[str] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):

            input_obj = args[0] if args else None
            workflow_id = getattr(input_obj, "context", {}).get("workflow_id", "UNKNOWN")
            workflow_type = getattr(input_obj, "context", {}).get("workflow_type", "UNKNOWN")
            execution_order = getattr(input_obj, "payload", {}).get("execution_order")
            activity_id = str(uuid.uuid4())   # 🔥 UNIQUE PER EXECUTION
            start_time = datetime.utcnow()

            # START → INSERT
            upsert_activity_event({
                "activity_id": activity_id,
                "workflow_id": workflow_id,
                "execution_order": execution_order,
                "workflow_type": workflow_type,
                "task_name": task_name,
                "activity_type": activity_type,
                "status": "STARTED",
                "input_data": getattr(input_obj, "payload", None),
                "input_context": getattr(input_obj, "context", None),
                "start_time": start_time,
                "activity_group": activity_group
            })

            try:
                result = await func(*args, **kwargs)

                # COMPLETE → UPDATE
                upsert_activity_event({
                    "activity_id": activity_id,
                    "workflow_id": workflow_id,
                    "execution_order": execution_order,
                    "workflow_type": workflow_type,
                    "task_name": task_name,
                    "activity_type": activity_type,
                    "status": "COMPLETED",
                    "output_data": getattr(result, "response", None),
                    "end_time": datetime.utcnow()
                })

                return result

            except Exception as e:
                # FAIL → UPDATE
                upsert_activity_event({
                    "activity_id": activity_id,
                    "workflow_id": workflow_id,
                    "execution_order": execution_order,
                    "workflow_type": workflow_type,
                    "task_name": task_name,
                    "activity_type": activity_type,
                    "status": "FAILED",
                    "output_data": {"error": str(e)},
                    "end_time": datetime.utcnow()
                })
                raise

        return wrapper
    return decorator

# ------------------------------------------------
# Append Approval Signal (Immutable Log)
# ------------------------------------------------
VALID_STATUS = {
    "PENDING", "IN_PROGRESS", "COMPLETED",
    "REJECTED", "CANCELLED", "EXPIRED"
}

VALID_DECISION = {
    "APPROVED", "REJECTED",
    "AUTO_APPROVED", "MANUAL_APPROVED", "MANUAL_REJECTED",
    None
}

def log_approval_signal(
    workflow_id, workflow_type, task_name, task_type, approval_signal_name=None,
    assigned_role=None, action_by=None,
    status="PENDING", decision=None,
    comments=None, business_key=None, priority="MEDIUM",
    workflow_step=1, sla_deadline=None, escalated=False,
    additional_data=None, attachments=None, completed_at=None
):
    if status not in {"PENDING","IN_PROGRESS","COMPLETED","REJECTED","CANCELLED","EXPIRED"}:
        raise ValueError("Invalid status")
    if decision not in {"APPROVED","REJECTED","AUTO_APPROVED","MANUAL_APPROVED","MANUAL_REJECTED",None}:
        raise ValueError("Invalid decision")

    now = datetime.now(timezone.utc)
    if not completed_at and status in ("COMPLETED","REJECTED"):
        completed_at = now

    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE workflow_approval_task SET is_current=FALSE "
                "WHERE workflow_id=%s AND workflow_step=%s AND is_current=TRUE",
                (workflow_id, workflow_step)
            )

            cur.execute("""
                INSERT INTO workflow_approval_task(
                    workflow_id, workflow_type, task_name, task_type, approval_signal_name,
                    assigned_role, action_by,
                    status, decision, comments,
                    business_key, priority,
                    workflow_step, sla_deadline, escalated,
                    additional_data, attachments,
                    created_at, completed_at, is_current
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
            """, (
                workflow_id, workflow_type, task_name, task_type, approval_signal_name,
                assigned_role, action_by,
                status, decision, comments,
                business_key, priority,
                workflow_step, sla_deadline, escalated,
                json.dumps(additional_data) if additional_data else None,
                json.dumps(attachments) if attachments else None,
                now, completed_at
            ))
            conn.commit()
    except Exception as e:
        print("❌ Approval log failed:", e)
        raise

# ------------------------------------------------
# Append OCR Result - New function to store OCR results in a separate table
# ------------------------------------------------
def store_ocr_result(
    workflow_id: str,
    document_url: str,
    ocr_raw: Optional[str] = None,
    ocr_result: Optional[dict] = None,
    extracted_fields: Optional[dict] = None,
    status: str = "NEW"
) -> int:
    """
    Store OCR output into PostgreSQL (raw text and/or structured JSON)
    and return document_id.
    """
    try:
        query = """
        INSERT INTO workflow_ocr_data (
            workflow_id, document_url, ocr_raw, ocr_result, extracted_fields, status
        ) VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING document_id
        """
        values = (
            workflow_id,
            document_url,
            ocr_raw,
            json.dumps(to_serializable(ocr_result)) if ocr_result else None,
            json.dumps(to_serializable(extracted_fields)) if extracted_fields else None,
            status
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                document_id = cur.fetchone()[0]
        return document_id
    except Exception as e:
        print("❌ OCR storage failed:", e)
        raise

# ------------------------------------------------
# Retrieve OCR Result
# ------------------------------------------------
def get_ocr_result(
    document_id: Optional[int] = None,
    document_url: Optional[str] = None,
    workflow_id: Optional[str] = None
) -> Optional[dict]:
    """
    Fetch OCR result from workflow_ocr_data table.
    Can search by document_id, document_url, or workflow_id.
    Returns structured OCR JSON if found, otherwise None.
    """
    if not (document_id or document_url or workflow_id):
        raise ValueError("At least one of document_id, document_url, or workflow_id must be provided")

    query = "SELECT ocr_result FROM workflow_ocr_data WHERE "
    conditions = []
    values = []

    if document_id:
        conditions.append("document_id = %s")
        values.append(document_id)
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
    reference_id: Optional[str] = None
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
            doc_id, doc_type, workflow_id, doc_date, owner_name,
            reference_id, approval_status, approved_by, header_data, line_items
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            workflow_id,
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