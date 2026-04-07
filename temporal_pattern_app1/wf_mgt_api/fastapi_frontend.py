# main.py
from fastapi.responses import JSONResponse
from fastapi import FastAPI, File, Query, Request, UploadFile, Form, HTTPException
import requests
import os
import json
from pydantic import BaseModel
import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta


from temporalio.client import Client, WorkflowHandle
import asyncio

# Import DB abstraction layer
import process_db as db
from erp_routes import router as erp_router
from crud_router import router as crud_router

from fastapi.middleware.cors import CORSMiddleware




logger = logging.getLogger(__name__)

# ------------------------------------------------
# FastAPI App
# ------------------------------------------------
app = FastAPI(title="IBPA API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] ,  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Include ERP router
app.include_router(erp_router)
app.include_router(crud_router)

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
    input_parameters: Dict[str, Any] 
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
    doc_type: Optional[str] = None
    document_url: Optional[str] = "https://zblobarchive.blob.core.windows.net/samples/aus-passport-sample1.png"
    document_id: Optional[str] = None
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
CLOUD_UPLOAD_API = "https://zdoc-ai-api.azurewebsites.net/azure-image"

# ------------------------------
# Pydantic models
# ------------------------------
class ItemDocument(BaseModel):
    doc_type: str  # declared by user
    file_name: str

# class KycSubmissionRequest(BaseModel):
#     first_name: str
#     last_name: str
#     email: str
#     phone: str
#     address: str
#     documents: List[ItemDocument]

# ------------------------------
# Helper to upload file to cloud
# ------------------------------
def upload_file_to_cloud(file: UploadFile) -> str:
    """
    Upload file to Azure API and return the file URL.
    """
    url = "https://zdoc-ai-api.azurewebsites.net/azure-image"
    files = {"file": (file.filename, file.file, file.content_type)}
    response = requests.post(url, files=files)
    if response.status_code != 200:
        raise HTTPException(500, f"File upload failed: {response.text}")
    data = response.json()
    return data.get("fileUrl")

# ------------------------------
# Process Submission Endpoint
# ------------------------------
@app.post("/kyc/submit")
async def submit_new_kyc_process_details(
    request: Request,
    firstName: str = Form(...),
    lastName: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    documents: List[UploadFile] = File(...),
    declared_doc_types: List[str] = Form(...)
):
    """
    Submit KYC information with multiple documents.
    Generates a business-friendly reference_id, uploads files, stores header + items.
    """
    print("======input form data submit_kyc=====\n", await request.form())
    if not documents or len(documents) != len(declared_doc_types):
        raise HTTPException(400, "Number of documents and declared_doc_types must match")
    
    # 1️⃣ Generate business-friendly reference_id (case ID)
    today = datetime.now().strftime("%Y%m%d")
    short_uuid = str(uuid.uuid4().hex[:6]).upper()
    reference_id = f"KYC-{today}-{short_uuid}"

    # 2️⃣ Prepare declared_data for header
    declared_data = {
        "first_name": firstName,
        "last_name": lastName,
        "email": email,
        "phone": phone,
        "address": address
    }

    # 3️⃣ Create header in DB
    header_id = db.create_process_header({
        "reference_id": reference_id,
        "workflow_type": "CustomerOnboardingWorkflow",
        "process_name": "KYC",
        "process_group": "Sales",
        "declared_data": declared_data,
        "verification_status": "PROCESSING",
        "additional_data": {"submission_source": "customer_portal"}
    })

    # 4️⃣ Upload documents and create items
    item_ids = []
    doc_results = []
    for file, doc_type in zip(documents, declared_doc_types):
        file_url = upload_file_to_cloud(file)
        
        item_id = db.create_process_item({
            "header_id": header_id,
            "doc_type": doc_type,               
            "document_url": file_url,
            "declared_data": {"document_type": doc_type}, # declared by user
            "status": "PROCESSING",
            "is_active": True
        })
        item_ids.append(item_id)
        doc_results.append({"doc_type": doc_type, "document_url": file_url})
    
    # 5️⃣ Return response to UI
    return {
        "reference_id": reference_id,
        "header_id": header_id,
        "documents": doc_results,
        "message": "KYC submitted successfully. Use reference_id to track status."
    }

@app.post("/invoice/submit")
async def submit_invoice(
    request: Request,
    invoiceNumber: str = Form(...),
    invoiceDate: str = Form(...),
    vendorName: str = Form(...),
    amount: str = Form(...),
    description: str = Form(...),
    invoiceFile: UploadFile = File(...),
):
    today = datetime.now().strftime("%Y%m%d")
    short_uuid = str(uuid.uuid4().hex[:6]).upper()
    reference_id = f"INV-{today}-{short_uuid}"

    header_id = db.create_process_header({
        "reference_id": reference_id,
        "workflow_type": "InvoiceProcessingWorkflow",
        "process_name": "Invoice",
        "process_group": "Finance",
        "declared_data": {
            "invoice_number": invoiceNumber,
            "invoice_date": invoiceDate,
            "vendor_name": vendorName,
            "amount": amount,
            "description": description,
        },
        "verification_status": "PROCESSING",
        "additional_data": {"submission_source": "invoice_portal"}
    })

    file_url = upload_file_to_cloud(invoiceFile)
    item_id = db.create_process_item({
        "header_id": header_id,
        "doc_type": "invoice",
        "document_url": file_url,
        "declared_data": {"document_type": "invoice"},
        "status": "PROCESSING",
        "is_active": True
    })

    return {
        "reference_id": reference_id,
        "header_id": header_id,
        "document": {"doc_type": "invoice", "document_url": file_url},
        "message": "Invoice submitted successfully. Use reference_id to track status."
    }

@app.post("/process/create")
async def create_process(req: ProcessCreateRequest):
    """ Create process with header + items (stores document_id + document_url). \n 
    ```json
    {
        "reference_id": "CUST-10001",
        "workflow_type": "CustomerOnboardingWorkflow",
        "process_name": "KYC",
        "process_group": "Sales",
        "declared_data": {
                "customer_id": "CUST-10001",
                "first_name": "Anthony",
                "last_name": "Marcus",
                "email": "anthony.marcus@example.com",
                "phone": "+61-400-000-000",
                "address": "15 Main Street, Melbourne, VIC 3000"
            },
        "additional_data": {
            "channel": "web",
            "source": "self_service_portal"
            }
    }
    {
        "reference_id": "INV901101",
        "workflow_type": "HybridEnterpriseSTPWorkflow",
        "process_name": "INVOICE_PROCESSING",
        "process_group": "FINANCE",
        "declared_data": {
            "purchase_order": "PO101101",
            "country": "Australia"
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
    ```json
    [
        {
            "doc_type": null,
            "document_url": "https://zblobarchive.blob.core.windows.net/samples/driver_license.png",
            "declared_data": {"document_type_hint": "driver_license"}
        },
        {
            "doc_type": null,
            "document_url": "https://zblobarchive.blob.core.windows.net/samples/aus-passport-sample1.png",
            "declared_data": {"document_type_hint": "passport"}
        },
        {
            "doc_type": null,
            "document_url": "https://zblobarchive.blob.core.windows.net/samples/utility_bill.png",
            "declared_data": {"document_type_hint": "utility_bill"}
        }
    ]
    [{  "doc_type": "Invoice",
        "document_id": "INV901101",
        "document_url": "https://zblobarchive.blob.core.windows.net/samples/invoice-iphone1.png",
        "declared_data": { "invoice_date": "2023-12-25" }  }]

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

@app.get("/monitor/headers")
def get_headers(
    workflow_type: Optional[str] = None,
    process_name: Optional[str] = None,
    verification_status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Fetch all process headers with optional filters.
    Example: /monitor/headers?workflow_type=KYC&process_name=Customer%20Onboarding&verification_status=REVIEW
    """
    return db.list_process_headers(workflow_type, process_name, verification_status, start_date, end_date)



@app.get("/process/{header_id}")
async def get_process(header_id: int):
    """Fetch process by header_id."""
    header = db.get_process_header(header_id)
    if not header:
        raise HTTPException(404, "Not found")
    items = db.get_items_by_header(header_id)
    return {"header": header, "items": items}

@app.get("/process/reference/{reference_id}")
async def get_by_reference(reference_id: str):
    """Fetch process by reference_id."""
    header = db.get_process_header_by_reference(reference_id)
    if not header:
        raise HTTPException(404, "Not found")

    items = db.get_items_by_header(header["id"])

    enriched_items = []
    for item in items:
        ocr = db.get_latest_ocr_by_item(item["id"])

        enriched_items.append({
            **item,
            "extractedFields": ocr.get("extracted_fields") if ocr else None,
            "ocr_status": ocr.get("status") if ocr else "PENDING"
        })

    return {
        "header": header,
        "items": enriched_items
    }


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

class SQLQuery(BaseModel):
    sql_query: str = """SELECT id, workflow_type, declared_data FROM automation_process_header LIMIT 5;"""  

@app.post("/api/app_data_retrieval")
def run_any_query(query: SQLQuery):
    raw_sql = query.sql_query.strip()
    sql_lower = raw_sql.lower()

    # ✅ Allow only SELECT queries
    if not sql_lower.startswith("select"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")

    # ❌ Block dangerous keywords
    forbidden = ["insert", "update", "delete", "drop", "alter", "truncate"]
    if any(word in sql_lower for word in forbidden):
        raise HTTPException(status_code=400, detail="Forbidden SQL operation detected")

    # ✅ Enforce LIMIT (basic protection)
    if "limit" not in sql_lower:
        raw_sql += " LIMIT 100"
    try:
        rows = db.run_query(raw_sql)
        return {"data": rows, "meta": {"count": len(rows)}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        {
        "workflow_type": "CustomerOnboardingWorkflow",
        "workflow_prefix": "CustomerOnboarding",
        "domain": "RetailBanking",
        "task_queue": "customer-onboarding",
            "input_parameters": {
            "reference_id": "CUST-10001",
            "documents": [
                {
                "document_url": "https://zblobarchive.blob.core.windows.net/samples/aus_dl_sample1.JPG",
                "declared_data": {"document_type": "driver_license"}
                },
                {
                "document_url": "https://zblobarchive.blob.core.windows.net/samples/aus-passport-sample1.png",
                "declared_data": {"document_type": "passport"}
                },
                {
                "document_url": "https://zblobarchive.blob.core.windows.net/samples/agl_sample1.jpg",
                "declared_data": {"document_type": "utility_bill"}
                }
            ]
            }
            
        }
    """
    client = await get_client()
    workflow_id = f"{req.workflow_prefix}-{uuid.uuid4()}"

    print(f"🚀 Starting workflow {workflow_id} of type {req.workflow_type} with input:\n{json.dumps(req.input_parameters, indent=2)} ")
    try:
        await client.start_workflow(
            req.workflow_type,
            args=[req.dict()],
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
    ALLOWED_ITEM_FIELDS = { "id", "doc_type", "document_url", "document_id", "declared_data"}
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
    workflow_id = f"{header.get('process_name','AI_PROCESS')}-{header.get('reference_id')}-{uuid.uuid4().hex[:8]}"

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