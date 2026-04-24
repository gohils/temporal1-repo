# -----------------------------
# hybrid_enterprise_human_in_loop_workflow.py
# -----------------------------

import asyncio, json, uuid, os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy

# Temporal-safe imports
with workflow.unsafe.imports_passed_through():
    import httpx
    from ai_worker_db_log import (
        log_activity,upsert_workflow_instance,
        store_ocr_result,
        store_erp_document,
        log_approval_signal
    )

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "20.213.111.57:7233")
TEMPORAL_HOST = "localhost:7233"
# TEMPORAL_HOST = "temporal-server-demo.australiaeast.cloudapp.azure.com:7233"

AI_API_URL = os.getenv("AI_API_URL","https://zdoc-ai-api.azurewebsites.net")
DEFAULT_TASK_QUEUE = os.getenv("TASK_QUEUE", "default-task-queue")
# -----------------------------
# Data Classes
# -----------------------------
@dataclass
class ActivityInput:
    payload: Dict[str, Any]
    context: Dict[str, Any]

@dataclass
class ActivityOutput:
    response: Dict[str, Any]
    context: Dict[str, Any]

# -----------------------------
# Approval logging helper
# -----------------------------
def log_wf_approval(wf_id, wf_type, status, signal_name=None, decision=None, role=None, user=None, comments=None,additional_data=None):
    log_approval_signal(
        workflow_id=wf_id,
        workflow_type=wf_type,
        task_name="INVOICE_APPROVAL",
        task_type="INVOICE_APPROVAL_L1",
        approval_signal_name=signal_name,
        assigned_role=role,
        action_by=user,
        status=status,
        decision=decision,
        comments=comments,
        additional_data=additional_data
    )
    print(f"📝 [APPROVAL LOGGED] status={status}, decision={decision}, role={role}, user={user}")

# -----------------------------
# Activities
# -----------------------------
@activity.defn
@log_activity("ai_process_doc")
async def ai_process_doc(input: ActivityInput) -> ActivityOutput:
    doc_url = input.payload.get("input_parameters", {}).get("document_url")

    # Try old payload first
    doc_url = input.payload.get("input_parameters", {}).get("document_url")

    # Fallback to first item in "items" if doc_url is not found
    if not doc_url:
        items = input.payload.get("items", [])
        if items:
            doc_url = items[0].get("document_url")

    print("======ai_process_doc===== doc_url ========\n",doc_url )

    wf_id = input.context.get("workflow_id")
    simulate = input.payload.get("simulate_ocr")
    print(f"➡️ [OCR] Starting OCR for document_url={doc_url}")

    if simulate:
        ocr_data = simulate
    else:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{AI_API_URL}/ai_doc_llm/analyze-document-prebuilt-model",
                json={"document_url": doc_url, "model_name": "prebuilt-invoice", "response_format": "structured"}
            )
            response.raise_for_status()
            ocr_data = response.json()  # now this works because 'response' is awaited

    document_id = store_ocr_result(
        workflow_id=wf_id,
        document_url=doc_url,
        ocr_raw="".join([d.get("raw_text","") for d in ocr_data.get("documents",[])]),
        ocr_result=ocr_data.get("documents", []),
        extracted_fields={},
        status="OCR_COMPLETE"
    )

    print(f"✅ [OCR] OCR completed, document_id={document_id}")
    new_payload = {**input.payload, "document_id": document_id, "ocr_data": ocr_data}
    new_context = {**input.context, "ai_process_doc": new_payload}
    return ActivityOutput(new_payload, new_context)

@activity.defn
@log_activity("normalize_document")
async def normalize_document(input: ActivityInput) -> ActivityOutput:
    ocr = input.payload.get("ocr_data", {})
    header = ocr.get("documents", [{}])[0].get("header", {})
    invoice = {
        "invoice_id": header.get("InvoiceId") or "UNKNOWN",
        "vendor_name": header.get("VendorName") or "UNKNOWN",
        "invoice_total": float(str(header.get("InvoiceTotal","0")).replace("$","").replace(",","")),
        "invoice_date": header.get("InvoiceDate")
    }
    print(f"📝 [NORMALIZE] Invoice extracted: {invoice['invoice_id']} for vendor {invoice['vendor_name']}")
    payload = {**input.payload, "invoice_data": invoice}
    context = {**input.context, "normalize_document": invoice}
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("validate_document")
async def validate_document(input: ActivityInput) -> ActivityOutput:
    invoice = input.payload.get("invoice_data")
    classification = "HIGH_VALUE" if invoice.get("invoice_total",0) > 1000 else "NORMAL"
    print(f"📊 [VALIDATE] Invoice {invoice.get('invoice_id')} classified as {classification}")
    payload = {**input.payload, "invoice_valuation": classification}
    context = {**input.context, "validate_document": classification}
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("approval_decision")
async def approval_decision(input: ActivityInput) -> ActivityOutput:
    invoice = input.payload.get("invoice_data")
    wf_id = input.context.get("workflow_id")
    wf_type = input.context.get("workflow_type")
    total = invoice.get("invoice_total", 0)

    if total <= 2000:
        decision = "auto_approve"
        log_wf_approval(wf_id=wf_id, wf_type=wf_type, status="COMPLETED", signal_name="SYSTEM", decision="AUTO_APPROVED", role="SYSTEM", user="SYSTEM", comments="Auto-approved")
        print(f"✅ [APPROVAL DECISION] Invoice {invoice.get('invoice_id')} auto-approved")
    else:
        decision = "manual_review"
        log_wf_approval(wf_id=wf_id, wf_type=wf_type, status="PENDING", signal_name="manual_approval", decision=None, role="MANAGER", user=None, comments="Waiting for manual approval")
        print(f"⏳ [APPROVAL DECISION] Invoice {invoice.get('invoice_id')} requires manual review")

    payload = {**input.payload, "approval_decision": decision}
    context = {**input.context, "approval_decision": decision}
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("post_to_erp")
async def post_to_erp(input: ActivityInput) -> ActivityOutput:
    wf_id = input.context.get("workflow_id")
    ocr = input.payload.get("ocr_data", {}).get("documents", [{}])[0]
    invoice = input.payload.get("invoice_data", {})
    decision = input.payload.get("approval_decision", "PENDING")
    manual = input.payload.get("manual_details", {})

    header = ocr.get("header", {})
    line_items = ocr.get("items", [])

    doc_id = f"ERP-{uuid.uuid4().hex[:8]}"
    stored_doc_id = store_erp_document(
        doc_id=doc_id,
        doc_type="invoice",
        workflow_id=wf_id,
        header_data=header,
        line_items=line_items,
        approval_status=decision,
        approved_by=manual.get("reviewer_id", "SYSTEM"),
        doc_date=header.get("InvoiceDate") or "1970-01-01",
        owner_name=header.get("VendorName") or "Unknown Owner",
        reference_id=str(header.get("InvoiceId") or f"REF-{uuid.uuid4().hex[:6]}")
    )

    print(f"✅ [ERP] Document {stored_doc_id} stored successfully for invoice {invoice.get('invoice_id')}")
    payload = {**input.payload, "erp_doc_id": stored_doc_id}
    context = {**input.context, "post_to_erp": {"doc_id": stored_doc_id, "header": header, "line_items": line_items}}
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("send_rejection_notification")
async def send_rejection_notification(input: ActivityInput) -> ActivityOutput:
    wf_id = input.context.get("workflow_id")
    invoice = input.payload.get("invoice_data")
    await asyncio.sleep(0.5)
    notification = {"status":"sent","invoice_id":invoice.get("invoice_id")}
    print(f"📩 [NOTIFY] Rejection notification sent for invoice {invoice.get('invoice_id')}")
    payload = {**input.payload, "notification": notification}
    context = {**input.context, "send_rejection_notification": notification}
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("store_audit")
async def store_audit(input: ActivityInput) -> ActivityOutput:
    print(f"🗂️ [AUDIT] Storing audit log:\n{json.dumps(input.payload, indent=2)}")
    return ActivityOutput({"status":"stored"}, input.context)

# -----------------------------
# Workflow
# -----------------------------
@workflow.defn
class HybridEnterpriseSTPWorkflow:

    def __init__(self):
        self.manual_approval_decision: Optional[str] = None
        self.manual_approval_details: Optional[Dict[str, Any]] = None
        self.execution_counter = 0

    @workflow.signal(name="manual_approval")
    def manual_approve(self, approval_details: Dict[str, Any]):
        self.manual_approval_decision = approval_details.get("decision","REJECTED").upper()
        self.manual_approval_details = approval_details
        print(f"🟢 [SIGNAL] Manual approval received: {self.manual_approval_decision}")

    @workflow.run
    async def run(self, initial_payload: Dict):
        # 🔹 initial_payload is exactly what you passed from FastAPI
        print("📥 workflow input payload received:", initial_payload)

        def next_step():
            self.execution_counter += 1
            return self.execution_counter

        wf_id = workflow.info().workflow_id
        workflow_type = initial_payload.get("workflow_type")
        domain=initial_payload.get("domain")
        context = {"workflow_id": wf_id,"workflow_type": workflow_type}
        payload = initial_payload.copy()
        audit = []
        retry = RetryPolicy(maximum_attempts=3)

        def log(step,data): audit.append({"step":step,"time":workflow.now().isoformat(),"payload":data})

        print(f"🚀 [WORKFLOW START] Workflow ID: {wf_id}, starting processing...")
        # Extract document_id if already present in payload
        document_id = payload.get("input_parameters", {}).get("document_url")

        # Log workflow start with input_data and document_id
        upsert_workflow_instance(
            workflow_id=wf_id,
            workflow_type=workflow_type,
            status="STARTED",
            input_data=initial_payload,
            document_id=document_id,
            domain=domain,
            parent_workflow=None,
            workflow_group=None,
            requires_manual_review=False
        )

        # 1️⃣ OCR
        res = await workflow.execute_activity(ai_process_doc, ActivityInput( {**payload, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=120), retry_policy=retry)
        payload.update(res.response); context.update(res.context); log("ai_process_doc", res.response)

        # 2️⃣ Normalize
        res = await workflow.execute_activity(normalize_document, ActivityInput( {**payload, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=30), retry_policy=retry)
        payload.update(res.response); context.update(res.context); log("normalize_document", res.response)

        # 3️⃣ Classify
        res = await workflow.execute_activity(validate_document, ActivityInput( {**payload, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=30), retry_policy=retry)
        payload.update(res.response); context.update(res.context); log("validate_document", res.response)

        # 4️⃣ Approval Decision
        res = await workflow.execute_activity(approval_decision, ActivityInput( {**payload, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=30), retry_policy=retry)
        payload.update(res.response); context.update(res.context); log("approval_decision", res.response)

        decision = payload.get("approval_decision")

        # 5️⃣ Manual approval
        if decision=="manual_review":
            print("⏳ Waiting for manual approval signal...")
            await workflow.wait_condition(lambda: self.manual_approval_decision is not None, timeout=timedelta(minutes=30))
            decision = "manual_approved" if self.manual_approval_decision=="APPROVED" else "manual_rejected"
            payload.update({"manual_details": self.manual_approval_details,"approval_decision":decision})
            log_wf_approval(wf_id=wf_id, wf_type=workflow_type, status="COMPLETED", signal_name="manual_approval", decision=decision.upper(), role="MANAGER", user=self.manual_approval_details.get("user_id"), comments=self.manual_approval_details.get("comments"),additional_data=self.manual_approval_details)
            log("manual_decision", self.manual_approval_details)
            print(f"🟢 [WORKFLOW] Manual approval completed: {decision}")

        # 6️⃣ Route
        if decision in ["auto_approve","manual_approved"]:
            res = await workflow.execute_activity(post_to_erp, ActivityInput( {**payload, "execution_order": next_step()}, context),
                start_to_close_timeout=timedelta(seconds=60), retry_policy=retry)
            payload.update(res.response); context.update(res.context); log("post_to_erp", res.response)
        else:
            res = await workflow.execute_activity(send_rejection_notification, ActivityInput( {**payload, "execution_order": next_step()}, context),
                start_to_close_timeout=timedelta(seconds=30), retry_policy=retry)
            payload.update(res.response); context.update(res.context); log("send_rejection_notification", res.response)

        # 7️⃣ Audit
        await workflow.execute_activity(store_audit, ActivityInput({"audit":audit, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=30), retry_policy=retry)

        print(f"🏁 [WORKFLOW COMPLETED] Workflow {wf_id} finished with decision: {decision}")
        # Mark workflow as completed
        upsert_workflow_instance(
            workflow_id=wf_id,
            workflow_type=workflow_type,
            status="COMPLETED",
            input_data=initial_payload,
            document_id=document_id,
            domain=domain,
            requires_manual_review=(decision == "manual_review")
        )
        return {"status":"COMPLETED","decision":decision,"erp_doc_id":payload.get("erp_doc_id"),"audit":audit}

# -----------------------------
# Main
# -----------------------------
async def main():
    client = await Client.connect(TEMPORAL_HOST)
    worker = Worker(
        client,
        task_queue=f"{DEFAULT_TASK_QUEUE}",
        workflows=[HybridEnterpriseSTPWorkflow],
        activities=[ai_process_doc,normalize_document,validate_document,approval_decision,
                    post_to_erp,send_rejection_notification,store_audit],
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=20
    )
    async with worker:
        print("🚀 Worker started for Hybrid Enterprise STP...")
        await asyncio.Event().wait()

if __name__=="__main__":
    asyncio.run(main())