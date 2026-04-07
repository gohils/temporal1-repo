import json, os, uuid, logging
from typing import Any, Dict, Optional, List
from psycopg_pool import ConnectionPool

# ------------------------------------------------
# Logging setup
# ------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------
# DB Pool
# ------------------------------------------------
POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING")
if not POSTGRES_CONNECTION_STRING:
    raise ValueError("POSTGRES_CONNECTION_STRING is not set")

pool = ConnectionPool(POSTGRES_CONNECTION_STRING, min_size=1, max_size=3)  # Connection pool to avoid exhaustion

# ------------------------------------------------
# Helpers
# ------------------------------------------------
def to_json(data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Convert dict to JSON string."""
    return json.dumps(data) if data else None

def execute_query(query: str, values: tuple = (), fetch: str = "all"):
    """Execute SQL query with optional fetch type ('all', 'one', or None)."""
    with pool.connection() as conn, conn.cursor() as cur:
        try:
            cur.execute(query, values)
            if fetch == "one" and cur.description:
                return dict(zip([d[0] for d in cur.description], cur.fetchone()))
            elif fetch == "all" and cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            else:
                conn.commit()
                return cur.rowcount
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Query failed: {e}")

# ------------------------------------------------
# Process Header
# ------------------------------------------------
def create_process_header(data: Dict[str, Any]) -> int:
    """Insert new process header and return its ID."""
    query = """INSERT INTO automation_process_header
               (reference_id, workflow_type, process_name, process_group,
                declared_data, verification_status, verification_comments, additional_header_data)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id"""
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
    return execute_query(query, values, fetch="one")["id"]

def get_process_header(header_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve process header by ID."""
    return execute_query("SELECT * FROM automation_process_header WHERE id=%s", (header_id,), fetch="one")

def get_process_header_by_reference(reference_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve latest process header by reference ID."""
    return execute_query(
        "SELECT * FROM automation_process_header WHERE reference_id=%s ORDER BY created_at DESC LIMIT 1",
        (reference_id,), fetch="one"
    )

def update_process_header(header_id: int, update_data: Dict[str, Any]):
    """Update process header fields dynamically."""
    if not update_data: return
    fields, values = [], []
    for k, v in update_data.items():
        fields.append(f"{k}=%s")
        values.append(to_json(v) if k in ("declared_data","additional_data") else v)
    fields.append("updated_at=NOW()")
    values.append(header_id)
    execute_query(f"UPDATE automation_process_header SET {', '.join(fields)} WHERE id=%s", tuple(values))

# ------------------------------------------------
# Process Items
# ------------------------------------------------
def create_process_item(data: Dict[str, Any]) -> int:
    """Insert new process item and return its ID."""
    query = """INSERT INTO automation_process_item
               (header_id, workflow_id, doc_type, document_id, document_url,
                declared_data, verification_status, status, is_active)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING id"""
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
    return execute_query(query, values, fetch="one")["id"]

def get_items_by_header(header_id: int) -> List[Dict[str, Any]]:
    """Retrieve all items linked to a process header."""
    return execute_query("SELECT * FROM automation_process_item WHERE header_id=%s", (header_id,), fetch="all")

def deactivate_existing_item(header_id: int, doc_type: str):
    """Deactivate existing active item for same document type."""
    execute_query("UPDATE automation_process_item SET is_active=FALSE, updated_at=NOW() WHERE header_id=%s AND doc_type=%s AND is_active=TRUE", (header_id, doc_type))

# ------------------------------------------------
# Workflow & Monitoring
# ------------------------------------------------
def list_workflows(status=None, start_date=None, end_date=None):
    """Fetch workflows with optional filters."""
    query = "SELECT workflow_id, workflow_type, status, domain, document_id, requires_manual_review, start_time, end_time FROM workflow_instance WHERE 1=1"
    params = []
    if status: params.extend([status]); query += " AND status=%s"
    if start_date: params.extend([start_date]); query += " AND start_time >= %s"
    if end_date: params.extend([end_date]); query += " AND end_time <= %s"
    return execute_query(query, tuple(params), fetch="all")

def list_approval_tasks():
    """Fetch all approval tasks."""
    return execute_query("SELECT * FROM workflow_approval_task", fetch="all")

def get_workflow_detail(workflow_id: str):
    """Fetch workflow and its activity log."""
    workflow = execute_query("SELECT * FROM workflow_instance WHERE workflow_id=%s", (workflow_id,), fetch="one")
    if not workflow: return None
    activities = execute_query("SELECT * FROM workflow_activity_instance WHERE workflow_id=%s ORDER BY start_time ASC", (workflow_id,), fetch="all")
    return {"workflow": workflow, "activities": activities}

def log_workflow_signal(workflow_id: str, signal_name: str, signal_input: Dict[str, Any]):
    """Log workflow signal event into approval task table."""
    query = """INSERT INTO workflow_approval_task
               (workflow_id, task_name, task_type, assigned_to, status, decision, comments, created_at, completed_at, is_current)
               VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NOW(),FALSE)"""
    values = (
        workflow_id,
        signal_name,
        "SIGNAL",
        signal_input.get("user_id"),
        "COMPLETED",
        signal_input.get("decision"),
        signal_input.get("comments"),
    )
    execute_query(query, values)