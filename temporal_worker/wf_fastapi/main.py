# fastapi_temporal_generic.py temporalio==1.6.0
import os, uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional, Mapping

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from temporalio.client import Client, WorkflowHandle


TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal-server-demo.australiaeast.cloudapp.azure.com:7233")
DEFAULT_TASK_QUEUE = os.getenv("TASK_QUEUE", "default-task-queue")

# -------------------------------
# FastAPI app
# -------------------------------
app = FastAPI(title="Generic Temporal Workflow API")

# -------------------------------
# Pydantic models
# -------------------------------
class WorkflowStartRequest(BaseModel):
    workflow_type: str = "HybridEnterpriseSTPWorkflow"
    workflow_prefix: str = "AI_DOC_Workflow"
    input: Dict[str, Any] = {"document_url": "https://zblobarchive.blob.core.windows.net/samples/invoice-iphone1.png"}
    task_queue: str = DEFAULT_TASK_QUEUE

class WorkflowSignalRequest(BaseModel):
    workflow_id: str = "AI_DOC_Workflow-xxxxxxxx"
    signal_name: str = "manual_approval"
    signal_input: Dict[str, Any] = {"decision": "APPROVED", "user_id": "manager_001", "comments": "Document verified, ready to onboard"}
    task_queue: str = DEFAULT_TASK_QUEUE


# -------------------------------
# Helper to connect Temporal
# -------------------------------
async def get_client() -> Client:
    return await Client.connect(TEMPORAL_HOST)

# -------------------------------
# Start workflow (non-blocking)
# -------------------------------
@app.post("/workflow/start/")
async def start_workflow(req: WorkflowStartRequest):
    """Start a Temporal workflow with flexible input.
    ```json
    {
        "workflow_type": "PaymentWorkflow",
        "workflow_prefix": "payment_workflow",
        "input": {
            "payment_id": "pay-001",
            "customer_id": "cust-123",
            "amount": 1200,
            "currency": "AUD"
        },
        "task_queue": "payments-task-queue"
        }
    ```
    """
    client = await get_client()
    workflow_id = f"{req.workflow_prefix}-{uuid.uuid4()}"
    try:
        await client.start_workflow(
            req.workflow_type,
            args=[req.input],
            id=workflow_id,
            task_queue=req.task_queue
        )
        return {"workflow_id": workflow_id, "status": "started"}
    except Exception as e:
        raise HTTPException(500, f"Failed to start workflow: {e}")

# -------------------------------
# Send signal to running workflow
# -------------------------------
@app.post("/workflow/signal/")
async def send_signal(req: WorkflowSignalRequest):
    client = await get_client()
    try:
        handle: WorkflowHandle = client.get_workflow_handle(req.workflow_id)
        await handle.signal(req.signal_name, req.signal_input)
        return {"workflow_id": req.workflow_id, "signal": req.signal_name, "status": "sent"}
    except Exception as e:
        raise HTTPException(500, f"Failed to send signal: {e}")

# -------------------------------
# Workflow progress monitoring
# -------------------------------
@app.get("/workflow/progress/{workflow_id}")
async def workflow_progress(workflow_id: str):
    client = await get_client()

    try:
        handle = client.get_workflow_handle(workflow_id)

        desc = await handle.describe()

        # Safer history extraction
        history = await handle.fetch_history()

        steps = []

        for event in history.events:
            if hasattr(event, "activity_task_scheduled_event_attributes") and event.activity_task_scheduled_event_attributes:
                steps.append(
                    event.activity_task_scheduled_event_attributes.activity_type.name
                )

        return {
            "workflow_id": workflow_id,
            "workflow_type": getattr(desc, "workflow_type", "UNKNOWN"),
            "status": desc.status.name,
            "steps": steps
        }

    except Exception as e:
        print(f"[ERROR] workflow_progress failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------------
# Get workflow result (blocking)
#--------------------------------
@app.get("/workflow/list/all")
async def list_all_workflows(page_size: int = 100):
    """
    List ALL workflows from Temporal (no filtering).
    Useful for debugging, demos, and full visibility.
    """

    client = await get_client()

    try:
        print("[DEBUG] Fetching ALL workflows from Temporal")

        results = []

        # IMPORTANT: no query = returns everything visible in namespace
        async for wf in client.list_workflows(page_size=page_size):

            results.append({
                "workflow_id": wf.id,
                "run_id": wf.run_id,
                "workflow_type": wf.workflow_type,
                "status": wf.status.name,
                "start_time": str(wf.start_time),
                "close_time": str(wf.close_time) if wf.close_time else None,
                "task_queue": wf.task_queue,
            })

        print(f"[DEBUG] Total workflows fetched: {len(results)}")

        return {
            "count": len(results),
            "workflows": results
        }

    except Exception as e:
        print(f"[ERROR] Failed to list workflows: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
# -------------------------------
# List workflows (filter by workflow_type)
# -------------------------------
@app.get("/workflow/list/")
async def list_workflows(
    workflow_type: str | None = None,
    status: str | None = None,
    page_size: int = 100
):
    """List workflows using Temporal visibility query."""
    client = await get_client()
    try:
        # Build query dynamically
        filters = []
        if workflow_type:
            filters.append(f"WorkflowType='{workflow_type}'")
        if status:
            filters.append(f"ExecutionStatus='{status.upper()}'")

        query = " AND ".join(filters) if filters else None

        # IMPORTANT: must iterate async iterator
        results = []
        async for wf in client.list_workflows(query=query, page_size=page_size):
            results.append({
                "workflow_id": wf.id,
                "run_id": wf.run_id,
                "workflow_type": wf.workflow_type,
                "status": wf.status.name,
                "start_time": str(wf.start_time),
                "close_time": str(wf.close_time) if wf.close_time else None,
                "task_queue": wf.task_queue
            })

        return {"count": len(results), "workflows": results}

    except Exception as e:
        raise HTTPException(500, f"Failed to list workflows: {str(e)}")
    
# -------------------------------
# Cancel workflow
# -------------------------------
@app.post("/workflow/cancel/{workflow_id}")
async def cancel_workflow(workflow_id: str):
    client = await get_client()
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.cancel()
        return {"workflow_id": workflow_id, "status": "cancellation requested"}
    except Exception as e:
        raise HTTPException(500, f"Failed to cancel workflow: {str(e)}")

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
# Run FastAPI app
# -------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)