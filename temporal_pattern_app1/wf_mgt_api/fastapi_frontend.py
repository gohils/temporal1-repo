# main.py
import os
import json
import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from temporalio.client import Client, WorkflowHandle
import asyncio

# Import DB abstraction layer
import process_db as db

logger = logging.getLogger(__name__)

# ------------------------------------------------
# FastAPI App
# ------------------------------------------------
app = FastAPI(title="IBPA API")

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
DEFAULT_TASK_QUEUE = os.getenv("TASK_QUEUE", "default-task-queue")

"""Lazy singleton Temporal client with retry safety."""
_client: Client | None = None
_lock = asyncio.Lock()

async def get_client() -> Client:
    """Lazy singleton with one retry if connection is stale."""
    global _client

    if _client:
        try:
            # lightweight check (fast)
            await _client.workflow_service.get_system_info()
            return _client
        except Exception:
            logger.warning("⚠️ Temporal client stale. Reconnecting once...")
            _client = None  # force reconnect

    async with _lock:
        if _client:
            return _client

        try:
            logger.info("🔌 Connecting to Temporal...")
            _client = await Client.connect(TEMPORAL_HOST)
            logger.info("✅ Temporal connected")
            return _client
        except Exception as e:
            logger.error(f"❌ Temporal connection failed: {e}")
            raise  # fail THIS request (no infinite retry)

# -------------------------------
# workflow and Signal request model
# -------------------------------
class WorkflowStartRequest(BaseModel):
    workflow_type: str = "HybridEnterpriseSTPWorkflow"
    workflow_prefix: str = "AI_DOC_Workflow"
    domain: str = "ProcessAutomation"
    input_parameters: Dict[str, Any] = {"document_url": "https://zblobarchive.blob.core.windows.net/samples/invoice-iphone1.png"}
    task_queue: str = DEFAULT_TASK_QUEUE

class WorkflowSignalRequest(BaseModel):
    workflow_id: str = "AI_DOC_Workflow-xxxxxxxx"
    signal_name: str = "manual_approval"
    signal_input: Dict[str, Any] = {"decision": "APPROVED", "user_id": "Sid", "comments": "Document verified, ready to onboard"}
    task_queue: str = DEFAULT_TASK_QUEUE

# ------------------------------------------------
# Models
# ------------------------------------------------
class DocumentInput(BaseModel):
    doc_type: str = None
    document_url: Optional[str] = "https://zblobarchive.blob.core.windows.net/samples/aus-passport-sample1.png"
    document_id: Optional[str] = "DOC10001"
    declared_data: Optional[Dict[str, Any]] = None

class ProcessCreateRequest(BaseModel):
    reference_id: Optional[str] 
    workflow_type: str = "HybridEnterpriseSTPWorkflow"
    process_name: str = "KYC"
    process_group: str = "Sales"
    declared_data: Dict[str, Any] = None
    additional_data: Optional[Dict[str, Any]] = None

class HeaderUpdateRequest(BaseModel):
    workflow_type: Optional[str] = "HybridEnterpriseSTPWorkflow"
    process_name: Optional[str] = "KYC"
    process_group: Optional[str] = "Sales"
    declared_data: Optional[Dict[str, Any]] = None
    additional_data: Optional[Dict[str, Any]] = None
    verification_status: Optional[str] = None
    verification_comments: Optional[str] = None

# ------------------------------------------------
# API Endpoints
# ------------------------------------------------
@app.post("/process/create")
async def create_process(req: ProcessCreateRequest):
    """ Create process with header + items (stores document_id + document_url). \n 
    ```json
    {
        "reference_id": "INV901101",
        "workflow_type": "HybridEnterpriseSTPWorkflow",
        "process_name": "INVOICE_PROCESSING",
        "process_group": "FINANCE",
        "declared_data": {
            "first_name": "John",
            "last_name": "Doe",
            "address": "15 Main Street, Melbourne, VIC 3029",
            "email": "john.doe@example.com",
            "country": "Australia"
        },
        "additional_data": {
            "source": "web_app",
            "channel": "self_service_portal"
        }
    }
    """
    try:
        header_id = db.create_process_header({
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
        print(f"❌ create_process failed: {e}")
        raise HTTPException(500, "Failed to create process")

@app.post("/process/add_item")
async def add_item(reference_id: str, documents: List[DocumentInput]):
    """
    Add one or more document items to an existing process header.
    For each document type, previous active documents are deactivated. \n
        [{  
            "doc_type": "Invoice",
            "document_id": "INV901101",
            "document_url": "https://zblobarchive.blob.core.windows.net/samples/invoice-iphone1.png",
            "declared_data": { "invoice_date": "2023-12-25" }
            }
        ]
        
        [
            {
                "doc_type": "passport",
                "document_url": "https://zblobarchive.blob.core.windows.net/samples/aus-passport-sample1.png",
                "declared_data": {
                "document_number": "P12345678",
                "expiry_date": "2030-12-31",
                "country": "AUS"
                }
            },
            {
            "doc_type": "utility_bill",
            "document_url": "https://zblobarchive.blob.core.windows.net/samples/agl_sample1.jpg",
            "declared_data": { "bill_date": "2023-04-23" }
            }
        ]
    """
    header = db.get_process_header_by_reference(reference_id)
    if not header:
        raise HTTPException(404, "Case not found")
    header_id = header["id"]
    item_ids = []
    for doc in documents:
        db.deactivate_existing_item(header_id, doc.doc_type)
        item_id = db.create_process_item({
            "header_id": header_id,
            "doc_type": doc.doc_type,
            "document_id":doc.document_id,
            "document_url": doc.document_url,
            "declared_data": doc.declared_data,
            "status": "PROCESSING"
        })
        item_ids.append(item_id)
    db.update_process_header(header_id, {
        "verification_status": "PROCESSING",
        "verification_comments": f"{len(documents)} document(s) added"
    })
    return {"header_id": header_id, "item_ids": item_ids}

@app.patch("/process/{header_id}")
async def update_header(header_id: int, req: HeaderUpdateRequest):
    """
    Update header metadata dynamically.
    Only updates fields provided in the request.
    """
    header = db.get_process_header(header_id)
    if not header:
        raise HTTPException(404, "Header not found")
    update_data = {k: v for k, v in req.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(400, "No valid fields provided for update")
    db.update_process_header(header_id, update_data)
    return {"header": db.get_process_header(header_id)}

@app.get("/process/{header_id}")
async def get_process(header_id: int):
    """Fetch process by header_id."""
    header = db.get_process_header(header_id)
    if not header:
        raise HTTPException(404, "Not found")
    items = db.get_items_by_header(header_id)
    return {"header": header, "items": items}

@app.get("/process/reference/{reference_id}")
async def get_by_reference(reference_id: str = 'CUST-10001'):
    """Fetch process by reference_id."""
    header = db.get_process_header_by_reference(reference_id)
    if not header:
        raise HTTPException(404, "Not found")
    items = db.get_items_by_header(header["id"])
    return {"header": header, "items": items}

# ------------------------------
# Workflow Monitoring Endpoints
# ------------------------------
@app.get("/monitor/workflows")
def list_workflows(status: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Fetch wokflows with optional filters: /monitor/workflows?status=COMPLETED&start_date=2024-01-01&end_date=2024-12-31"""
    return db.list_workflows(status, start_date, end_date)


@app.get("/monitor/tasks")
def list_approval_tasks():
    """Fetch all approval tasks."""
    return db.list_approval_tasks()


@app.get("/monitor/workflows/{workflow_id}")
def workflow_detail(workflow_id: str):
    """Fetch detailed information about a specific workflow."""
    result = db.get_workflow_detail(workflow_id)
    if not result:
        raise HTTPException(404, "Workflow not found")
    return result

# -------------------------------
# Start workflow (non-blocking)
# -------------------------------
@app.post("/workflow/start/")
async def start_workflow(req: WorkflowStartRequest):
    """Start a workflow asynchronously. Returns immediately with workflow_id and status.
        ```json
        {
        "workflow_type": "HybridEnterpriseSTPWorkflow",
        "workflow_prefix": "AI_DOC_Workflow",
        "domain": "ProcessAutomation",
        "input_parameters": {
            "document_url": "https://zblobarchive.blob.core.windows.net/samples/invoice-iphone1.png"
        },
        "task_queue": "default-task-queue"
        }
    """
    client = await get_client()
    workflow_id = f"{req.workflow_prefix}-{uuid.uuid4()}"
    try:
        await client.start_workflow(
            req.workflow_type,
            args=[req],
            id=workflow_id,
            task_queue=req.task_queue
        )
        return {"workflow_id": workflow_id, "status": "started"}
    except Exception as e:
        raise HTTPException(500, f"Failed to start workflow: {e}")

# -------------------------------
# Start workflow by reference_id (fetch header + items) - non-blocking
# -------------------------------
@app.post("/workflow/start_by_reference/{reference_id}")
async def start_workflow_by_reference(reference_id: str):
    """
    Fetch process by reference_id (header + items) and start a Temporal workflow.
    Returns immediately with workflow_id and status.
    """
    # 1️⃣ Fetch header
    header = db.get_process_header_by_reference(reference_id)
    if not header:
        raise HTTPException(404, "Header not found")

    # 2️⃣ Fetch items
    items = db.get_items_by_header(header["id"])

    # Define only fields needed by workflow
    ALLOWED_ITEM_FIELDS = { "doc_type", "document_url", "document_id", "declared_data"}
    clean_items = []
    for item in items:
        clean_item = {k: v for k, v in item.items() if k in ALLOWED_ITEM_FIELDS}
        clean_items.append(clean_item)

    # 3️⃣ Construct workflow input
    workflow_input = {
        "reference_id": header.get("reference_id"),
        "header_id": header.get("id"),
        "workflow_type": header.get("workflow_type"),
        "process_name": header.get("process_name"),
        "process_group": header.get("process_group"),
        "declared_data": header.get("declared_data"),
        "additional_data": header.get("additional_data"),
        "items": clean_items
    }

    # 4️⃣ Generate a unique workflow ID
    workflow_id = f"{header.get('workflow_type')}-{uuid.uuid4().hex[:8]}"

    # 5️⃣ Start workflow
    print("workflow start input payload - \n ",workflow_input)
    client = await get_client()
    try:
        await client.start_workflow(
            header.get("workflow_type"),
            args=[workflow_input],  # pass dynamic payload
            id=workflow_id,
            task_queue=DEFAULT_TASK_QUEUE
        )
        return {"workflow_id": workflow_id, "status": "started"}
    except Exception as e:
        raise HTTPException(500, f"Failed to start workflow: {e}")
    
# -------------------------------
# Terminate workflow
# -------------------------------
@app.post("/workflow/terminate/{workflow_id}")
async def terminate_workflow(workflow_id: str):
    client = await get_client()
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.terminate(reason="Force terminate due to failure")
        return {"workflow_id": workflow_id, "status": "terminated"}
    except Exception as e:
        raise HTTPException(500, f"Terminate failed: {str(e)}")
    
# -------------------------------
# Endpoint to send signal
# -------------------------------
@app.post("/workflow/signal/")
async def send_signal(req: WorkflowSignalRequest):
    """ Send a signal to a running workflow APPROVED or REJECTED.
    ```json
    {
    "workflow_id": "AI_DOC_Workflow-xxxxxxxx",
    "signal_name": "manual_approval",
    "signal_input": {
        "decision": "APPROVED",
        "user_id": "manager_001",
        "comments": "Document verified, ready to onboard"
    },
    "task_queue": "default-task-queue"
    }    
    """
    client = await get_client()
    try:
        handle: WorkflowHandle = client.get_workflow_handle(req.workflow_id)
        await handle.signal(req.signal_name, req.signal_input)

        return {
            "workflow_id": req.workflow_id,
            "signal": req.signal_name,
            "status": "sent",
            "logged_at": datetime.utcnow().isoformat()
        }

    except Exception as e:
        print(f"❌ send_signal failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send signal: {e}")
    
# ------------------------------------------------
# Run FastAPI
# ------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)