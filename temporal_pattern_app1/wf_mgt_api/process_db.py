# process_db.py
"""Reusable DB functions for process header, items, and workflow logging."""

import json
from typing import Any, Dict, Optional, List
from datetime import datetime
from psycopg_pool import ConnectionPool
import os
import logging
import uuid

# ------------------------------------------------
# Logging setup
# ------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------
# DB Connection
# ------------------------------------------------
POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING")
if not POSTGRES_CONNECTION_STRING:
    raise ValueError("POSTGRES_CONNECTION_STRING is not set")

pool = ConnectionPool(POSTGRES_CONNECTION_STRING, min_size=1, max_size=3)

# ------------------------------------------------
# Utility functions
# ------------------------------------------------
def to_json(data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Convert dict to JSON string for DB storage."""
    return json.dumps(data) if data else None

def fetch_all(cur) -> List[Dict[str, Any]]:
    """Fetch all rows from cursor as list of dicts."""
    rows = cur.fetchall()
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in rows]

def fetch_one(cur) -> Optional[Dict[str, Any]]:
    """Fetch single row from cursor as dict."""
    row = cur.fetchone()
    if row:
        return dict(zip([d[0] for d in cur.description], row))
    return None

def run_query(query: str, values: tuple = ()):
    """Execute any SELECT query and return results as list of dicts."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(query, values)
                if cur.description:  # SELECT returns rows
                    rows = cur.fetchall()
                    columns = [desc[0] for desc in cur.description]
                    return [dict(zip(columns, row)) for row in rows]
                return []  # No rows returned
            except Exception as e:
                raise RuntimeError(f"Query failed: {e}")
            
# ------------------------------------------------
# Process Header
# ------------------------------------------------
def create_process_header(data: Dict[str, Any]) -> int:
    """Insert new process header and return its ID."""
    query = """
        INSERT INTO automation_process_header (
            reference_id, workflow_type, process_name, process_group,
            declared_data, verification_status, verification_comments, additional_header_data
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """
    values = (
        data.get("reference_id"),
        data.get("workflow_type"),
        data.get("process_name"),
        data.get("process_group"),
        to_json(data.get("declared_data")),
        data.get("verification_status", "PROCESSING"),
        data.get("verification_comments"),
        to_json(data.get("additional_header_data")),
    )
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, values)
        return cur.fetchone()[0]

def get_process_header(header_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve process header by ID."""
    query = "SELECT * FROM automation_process_header WHERE id=%s"
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, (header_id,))
        return fetch_one(cur)

def get_process_header_by_reference(reference_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve latest process header by reference ID."""
    query = """
        SELECT * FROM automation_process_header
        WHERE reference_id=%s
        ORDER BY created_at DESC
        LIMIT 1
    """
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, (reference_id,))
        return fetch_one(cur)

def update_process_header(header_id: int, update_data: Dict[str, Any]):
    """Update process header fields dynamically."""
    fields, values = [], []
    for k, v in update_data.items():
        if k in ("declared_data", "additional_data"):
            v = to_json(v)
        fields.append(f"{k}=%s")
        values.append(v)

    if not fields:
        return

    fields.append("updated_at=NOW()")
    values.append(header_id)

    query = f"UPDATE automation_process_header SET {', '.join(fields)} WHERE id=%s"

    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, values)

# ------------------------------------------------
# Process Items
# ------------------------------------------------
def create_process_item(data: Dict[str, Any]) -> int:
    """Insert new process item and return its ID."""
    query = """
        INSERT INTO automation_process_item (
            header_id, workflow_id, doc_type, document_id, document_url,
            declared_data, verification_status, status, is_active
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
        RETURNING id
    """
    values = (
        data.get("header_id"),
        data.get("workflow_id"),
        data.get("doc_type"),
        data.get("document_id", uuid.uuid4().int >> 64),
        data.get("document_url"),
        to_json(data.get("declared_data")),
        data.get("verification_status", "PROCESSING"),
        data.get("status", "PROCESSING"),
    )
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, values)
        return cur.fetchone()[0]

def get_items_by_header(header_id: int) -> List[Dict[str, Any]]:
    """Retrieve all items linked to a process header."""
    query = "SELECT * FROM automation_process_item WHERE header_id=%s"
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, (header_id,))
        return fetch_all(cur)

def get_latest_ocr_by_item(item_id: int):
    query = """
        SELECT extracted_fields, status
        FROM workflow_ocr_data
        WHERE item_id = %s
        ORDER BY version DESC
        LIMIT 1
    """
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, (item_id,))
        return fetch_one(cur) 
    
def deactivate_existing_item(header_id: int, doc_type: str):
    """Deactivate existing active item for same document type."""
    query = """
        UPDATE automation_process_item
        SET is_active = FALSE, updated_at = NOW()
        WHERE header_id=%s AND doc_type=%s AND is_active=TRUE
    """
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, (header_id, doc_type))

# ------------------------------------------------
# Monitoring / Workflow Queries
# ------------------------------------------------
# -------------------------------
# DB function to list headers
# -------------------------------
def list_process_headers(
    workflow_type: Optional[str] = None,
    process_name: Optional[str] = None,
    verification_status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Fetch all process headers with optional filters"""
    base_query = """
        SELECT id, reference_id, workflow_type, process_name, process_group,
               declared_data, verification_status, verification_comments,
               verification_data, additional_header_data,
               created_at, updated_at
        FROM automation_process_header
        WHERE 1=1
    """
    params = []
    if workflow_type:
        base_query += " AND workflow_type = %s"
        params.append(workflow_type)
    if process_name:
        base_query += " AND process_name = %s"
        params.append(process_name)
    if verification_status:
        base_query += " AND verification_status = %s"
        params.append(verification_status)
    if start_date:
        base_query += " AND created_at >= %s"
        params.append(start_date)
    if end_date:
        base_query += " AND created_at <= %s"
        params.append(end_date)
    base_query += " ORDER BY created_at DESC"

    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(base_query, params)
        return fetch_all(cur)


def list_workflows(status=None, start_date=None, end_date=None):
    """Fetch workflows with optional filters."""
    query = """
        SELECT workflow_id, workflow_type, status, domain, header_id, reference_id,
               start_time, end_time, created_at, updated_at
        FROM workflow_instance
        WHERE 1=1
    """
    params = []

    if status:
        query += " AND status=%s"
        params.append(status)
    if start_date:
        query += " AND start_time >= %s"
        params.append(start_date)
    if end_date:
        query += " AND end_time <= %s"
        params.append(end_date)

    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query, tuple(params))
        return fetch_all(cur)


def list_approval_tasks():
    """Fetch all approval tasks."""
    query = """
        SELECT *
        FROM workflow_approval_task
    """
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(query)
        return fetch_all(cur)


def get_workflow_detail(workflow_id: str):
    """Fetch workflow and its activity log."""
    with pool.connection() as conn, conn.cursor() as cur:

        cur.execute("""
            SELECT workflow_id, workflow_type, status, domain, reference_id, header_id,
                input_data, parent_workflow, workflow_group,
                additional_data, decision, error_message, error_step, triggered_by, source,
                start_time, end_time, created_at, updated_at
            FROM workflow_instance
            WHERE workflow_id = %s
        """, (workflow_id,))
        workflow = fetch_one(cur)

        if not workflow:
            return None

        cur.execute("""
            SELECT activity_id, step_key, task_name, activity_type, activity_group,
                workflow_type, header_id, item_id,
                input_data, output_data, input_context,
                status, start_time, end_time, created_at
            FROM workflow_activity_instance
            WHERE workflow_id = %s
            ORDER BY start_time ASC
        """, (workflow_id,))
        activities = fetch_all(cur)

    return {"workflow": workflow, "activities": activities}

# ------------------------------------------------
# Workflow Logging
# ------------------------------------------------
def log_workflow_signal(workflow_id: str, signal_name: str, signal_input: Dict[str, Any]):
    """Log workflow signal event into approval task table."""
    try:
        query = """
            INSERT INTO workflow_approval_task (
                workflow_id, task_name, task_type, assigned_to, status, decision,
                comments, created_at, completed_at, is_current
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NOW(),FALSE)
        """
        values = (
            workflow_id,
            signal_name,
            "SIGNAL",
            signal_input.get("user_id"),
            "COMPLETED",
            signal_input.get("decision"),
            signal_input.get("comments"),
        )
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(query, values)
    except Exception as e:
        logger.error(f"❌ log_workflow_signal failed: {e}")
        raise

