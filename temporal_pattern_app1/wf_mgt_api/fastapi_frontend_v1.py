# main.py
import os
import json
import uuid
import logging
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg_pool import ConnectionPool

# ------------------------------------------------
# Logging
# ------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------
# DB Connection
# ------------------------------------------------
POSTGRES_CONNECTION_STRING = os.getenv("POSTGRES_CONNECTION_STRING")
if not POSTGRES_CONNECTION_STRING:
    raise ValueError("POSTGRES_CONNECTION_STRING not set")

pool = ConnectionPool(POSTGRES_CONNECTION_STRING, min_size=2, max_size=10)

# ------------------------------------------------
# FastAPI App
# ------------------------------------------------
app = FastAPI(title="IBPA API")

# ------------------------------------------------
# Models
# ------------------------------------------------
class DocumentInput(BaseModel):
    doc_type: str = "passport"
    document_url: Optional[str] = "https://example-bucket.s3.amazonaws.com/docs/passport_john_doe.pdf"
    declared_data: Optional[Dict[str, Any]] = {
        "document_number": "P12345678",
        "expiry_date": "2030-12-31",
        "country": "AUS"
    }

class ProcessCreateRequest(BaseModel):
    reference_id: Optional[str] = "CUST-10001"
    workflow_type: str = "Customer Onboarding"
    process_name: str = "KYC"
    process_group: str = "Sales"
    declared_data: Dict[str, Any] = {
        "first_name": "John",
        "last_name": "Doe",
        "dob": "1990-01-01",
        "address": "123 Collins Street, Melbourne VIC 3000",
        "email": "john.doe@example.com",
        "phone": "+61412345678",
        "country": "Australia"
    }
    additional_data: Optional[Dict[str, Any]] = {"source": "web_app", "channel": "self_service_portal"}

class HeaderUpdateRequest(BaseModel):
    workflow_type: Optional[str] = "Customer Onboarding"
    process_name: Optional[str] = "KYC"
    process_group: Optional[str] = "Sales"
    declared_data: Optional[Dict[str, Any]] = {
        "first_name": "John",
        "last_name": "Doe",
        "dob": "1990-01-01",
        "address": "123 Collins Street, Melbourne VIC 3000",
        "email": "john.doe@example.com",
        "phone": "+61412345678",
        "country": "Australia"
    }
    additional_data: Optional[Dict[str, Any]] = {"source": "web_app", "channel": "self_service_portal"}
    verification_status: Optional[str] = "PROCESSING"
    verification_comments: Optional[str] = "Initial metadata update"

# ------------------------------------------------
# Utility
# ------------------------------------------------
def to_json(data):
    return json.dumps(data) if data else None

# ------------------------------------------------
# DB FUNCTIONS
# ------------------------------------------------
def create_process_header(data: Dict[str, Any]) -> int:
    """Insert new process header."""
    try:
        query = """
        INSERT INTO automation_process_header (
            reference_id, workflow_type, process_name, process_group,
            declared_data, verification_status, verification_comments, additional_data
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
            to_json(data.get("additional_data")),
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"❌ create_process_header failed: {e}")
        raise

def create_process_item(data: Dict[str, Any]) -> int:
    """Insert new process item with document_id and document_url."""
    try:
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
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"❌ create_process_item failed: {e}")
        raise

def get_process_header(header_id: int):
    """Fetch header by id."""
    try:
        query = "SELECT * FROM automation_process_header WHERE id=%s"
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (header_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
        return None
    except Exception as e:
        logger.error(f"❌ get_process_header failed: {e}")
        raise

def get_process_header_by_reference(reference_id: str):
    """Fetch latest header by reference_id."""
    try:
        query = """
        SELECT * FROM automation_process_header
        WHERE reference_id=%s
        ORDER BY created_at DESC
        LIMIT 1
        """
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (reference_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
        return None
    except Exception as e:
        logger.error(f"❌ get_process_header_by_reference failed: {e}")
        raise

def get_items_by_header(header_id: int):
    """Fetch items for header."""
    try:
        query = "SELECT * FROM automation_process_item WHERE header_id=%s"
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (header_id,))
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        logger.error(f"❌ get_items_by_header failed: {e}")
        raise

def deactivate_existing_item(header_id: int, doc_type: str):
    """Deactivate active doc for doc_type."""
    try:
        query = """
        UPDATE automation_process_item
        SET is_active = FALSE, updated_at = NOW()
        WHERE header_id=%s AND doc_type=%s AND is_active=TRUE
        """
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (header_id, doc_type))
    except Exception as e:
        logger.error(f"❌ deactivate_existing_item failed: {e}")
        raise

def update_process_header(header_id: int, update_data: Dict[str, Any]):
    """Update header dynamically."""
    try:
        fields, values = [], []
        for k, v in update_data.items():
            if k in ("declared_data", "additional_data"):
                v = to_json(v)
            fields.append(f"{k}=%s")
            values.append(v)

        fields.append("updated_at=NOW()")
        values.append(header_id)

        query = f"""
        UPDATE automation_process_header
        SET {', '.join(fields)}
        WHERE id=%s
        """

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
    except Exception as e:
        logger.error(f"❌ update_process_header failed: {e}")
        raise

# ------------------------------------------------
# API ENDPOINTS
# ------------------------------------------------
@app.post("/process/create")
async def create_process(req: ProcessCreateRequest):
    """Create process with header + items (stores document_id + document_url)."""
    try:
        header_id = create_process_header({
            "reference_id": req.reference_id or f"REF-{uuid.uuid4().hex[:6]}",
            "workflow_type": req.workflow_type,
            "process_name": req.process_name,
            "process_group": req.process_group,
            "declared_data": req.declared_data,
            "verification_status": "PROCESSING",
            "additional_data": req.additional_data or {}
        })

        return {"header_id": header_id, "reference_id": req.reference_id}

    except Exception as e:
        logger.error(f"❌ create_process failed: {e}")
        raise HTTPException(500, "Failed to create process")

@app.post("/process/add_item")
async def add_item(reference_id: str, documents: List[DocumentInput]):
    """
    Add one or more document items to an existing process header.
    For each document type, previous active documents are deactivated. \n
        [
            {
                "doc_type": "passport",
                "document_url": "https://example-bucket.s3.amazonaws.com/docs/passport_john_doe.pdf",
                "declared_data": {
                "document_number": "P12345678",
                "expiry_date": "2030-12-31",
                "country": "AUS"
                }
            },
            {
            "doc_type": "utility_bill",
            "document_url": "https://example-bucket.s3.amazonaws.com/docs/utility_bill_john_doe.pdf",
            "declared_data": {
                "bill_date": "2025-01-01"
            }
            }
        ]
    """
    try:
        # Fetch existing header
        header = get_process_header_by_reference(reference_id)
        if not header:
            raise HTTPException(404, "Case not found")
        header_id = header["id"]

        item_ids = []

        for doc in documents:
            # Deactivate existing active document of this type
            deactivate_existing_item(header_id, doc.doc_type)

            # Insert new document as active
            item_id = create_process_item({
                "header_id": header_id,
                "doc_type": doc.doc_type,
                "document_url": doc.document_url,
                "declared_data": doc.declared_data,
                "status": "PROCESSING"
            })
            item_ids.append(item_id)

        # Optionally update header verification status/comments
        update_process_header(header_id, {
            "verification_status": "PROCESSING",
            "verification_comments": f"{len(documents)} document(s) added"
        })

        return {"header_id": header_id, "item_ids": item_ids}

    except Exception as e:
        logger.error(f"❌ add_item failed: {e}")
        raise HTTPException(500, "Add item failed")
    

# ------------------------------------------------
# Endpoint to update header metadata
# ------------------------------------------------
@app.patch("/process/{header_id}")
async def update_header(header_id: int, req: HeaderUpdateRequest):
    """
    Update header metadata dynamically.
    Only updates fields provided in the request.
    """
    try:
        # Fetch header to ensure it exists
        header = get_process_header(header_id)
        if not header:
            raise HTTPException(404, "Header not found")

        # Build update dictionary with only provided fields
        update_data = {}
        if req.declared_data is not None:
            update_data["declared_data"] = req.declared_data
        if req.additional_data is not None:
            update_data["additional_data"] = req.additional_data
        if req.verification_status is not None:
            update_data["verification_status"] = req.verification_status
        if req.verification_comments is not None:
            update_data["verification_comments"] = req.verification_comments

        if not update_data:
            raise HTTPException(400, "No valid fields provided for update")

        # Update header in DB
        update_process_header(header_id, update_data)

        # Return updated header
        updated_header = get_process_header(header_id)
        return {"header": updated_header}

    except Exception as e:
        logger.error(f"❌ update_header failed: {e}")
        raise HTTPException(500, "Header update failed")
    
@app.get("/process/{header_id}")
async def get_process(header_id: int):
    """Fetch process by header_id."""
    try:
        header = get_process_header(header_id)
        if not header:
            raise HTTPException(404, "Not found")

        items = get_items_by_header(header_id)

        return {"header": header, "items": items}

    except Exception as e:
        logger.error(f"❌ fetch failed: {e}")
        raise HTTPException(500, "Fetch failed")

@app.get("/process/reference/{reference_id}")
async def get_by_reference(reference_id: str):
    """Fetch process by reference_id."""
    try:
        header = get_process_header_by_reference(reference_id)
        if not header:
            raise HTTPException(404, "Not found")

        items = get_items_by_header(header["id"])

        return {"header": header, "items": items}

    except Exception as e:
        logger.error(f"❌ fetch by reference failed: {e}")
        raise HTTPException(500, "Fetch failed")

# -------------------------------
# Run FastAPI app
# -------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)