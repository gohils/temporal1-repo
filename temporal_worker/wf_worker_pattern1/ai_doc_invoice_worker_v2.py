# -----------------------------
# Invoice_processing_human_in_loop_workflow_KYC_style.py
# -----------------------------

import asyncio, json, uuid, os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy

# Temporal-safe imports for HTTP and DB logging
with workflow.unsafe.imports_passed_through():
    import httpx
    from ai_worker_db_log import (
        log_activity, upsert_workflow_instance,
        store_ocr_result, store_erp_document,
        log_approval_signal
    )

# -----------------------------
# Environment and Task Queue
# -----------------------------
# TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_HOST =  "4.197.33.155:7233"  # Update if Temporal server is running on a different host/port

# AI_API_URL = os.getenv("AI_API_URL", "https://zdoc-ai-api.azurewebsites.net")
AI_API_URL = "http://localhost:8000"  # Local testing override
AI_API_URL = "https://zdoc-ai-api.azurewebsites.net"  # Production override
DEFAULT_TASK_QUEUE = "finance-invoice-queue"

# -----------------------------
# Data Contracts
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
# Context Management (STANDARDIZED)
# -----------------------------
def build_base_context(payload, wf_id):
    # Build initial workflow context
    return {
        "workflow_id": wf_id,
        "workflow_type": payload.get("workflow_type"),
        "reference_id": payload.get("reference_id"),
        "header_id": payload.get("header_id"),
    }

def merge_context(parent, child):
    # Merge parent and child context with item fallback
    return {
        **parent,
        **child,
        "workflow_id": parent.get("workflow_id"),
        "workflow_type": parent.get("workflow_type"),
        "reference_id": parent.get("reference_id"),
        "header_id": parent.get("header_id"),
        "item_id": child.get("item_id") or parent.get("item_id"),
        "doc_type": child.get("doc_type") or parent.get("doc_type"),
    # IMPORTANT CHANGE (implicit fix):
    # prev_node_id / current_node_id are NOT allowed to be overwritten by child
    }

# -----------------------------
# Execution Wrapper
# -----------------------------
async def execute_step(activity_fn, payload, context, step, timeout=30):

    # -----------------------------
    # GRAPH STATE (ONLY PLACE WHERE IT IS UPDATED)
    # -----------------------------
    prev_node = context.get("current_node_id")

    context = {
        **context,
        "prev_node_id": prev_node,
        "current_node_id": step,
        "branch_id": context.get("branch_id", "MAIN")
    }

    result: ActivityOutput = await workflow.execute_activity(
        activity_fn,
        ActivityInput(payload, context),
        start_to_close_timeout=timedelta(seconds=timeout),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )

    payload = {**payload, **result.response}

    # -----------------------------
    # SAFE MERGE (DO NOT OVERWRITE GRAPH STATE)
    # -----------------------------
    business_context = merge_context(context, result.context)

    # preserve graph fields explicitly
    business_context["prev_node_id"] = context["prev_node_id"]
    business_context["current_node_id"] = context["current_node_id"]
    business_context["branch_id"] = context["branch_id"]

    return payload, business_context

# -----------------------------
# Activities
# -----------------------------
@activity.defn
@log_activity(display_name="01_PREPROCESS_INVOICE")
async def pre_process_invoices(input: ActivityInput) -> ActivityOutput:
    # Normalize invoice items and ensure document_url exists
    print("📄 [PREPROCESS] Starting invoice preprocessing", input.payload, input.context)
    input_data = input.payload or {}  # incoming request payload
    invoices = input.payload.get("items", [])
    if not invoices:
        raise ValueError("No invoice items found")

    normalized = []
    for inv in invoices:
        # Prefer top-level document_url, fallback to input_parameters.document_url
        doc_url = inv.get("document_url") or inv.get("input_parameters", {}).get("document_url")
        normalized.append({
            "item_id": str(inv.get("id") or inv.get("item_id") or uuid.uuid4()),
            "document_url": doc_url,
            "doc_type": inv.get("doc_type") or "invoice",
        })

    # Persist workflow start
    upsert_workflow_instance(
        workflow_id=input.context["workflow_id"],
        workflow_type=input.context["workflow_type"],
        status="STARTED",
        input_data=input_data,
        header_id=input.context.get("header_id"),
        reference_id=input.context.get("reference_id"),
    )

    return ActivityOutput(
        {**input.payload, "normalized_invoices": normalized},
        {"preprocess": {"count": len(normalized)}}
    )

@activity.defn
@log_activity(display_name="02_OCR")
async def ai_process_doc(input: ActivityInput) -> ActivityOutput:
    # Call AI OCR and store results
    print("📄 [OCR] Starting document processing", input.payload, input.context)
    doc_url = input.payload.get("document_url")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{AI_API_URL}/ai_doc_llm/analyze-document-prebuilt-model",
            json={"document_url": doc_url, "ai_model_name": "prebuilt-invoice", "response_format": "structured"}
        )
        resp.raise_for_status()
        ocr_data = resp.json()

    print("📄 ====== [OCR] OCR processing complete:", json.dumps(ocr_data, indent=2))
    ocr_docs = ocr_data.get("documents", [{}])
    doc = ocr_docs[0] if ocr_docs else {}

    header_fields = doc.get("header", {})
    items_fields = doc.get("items", [])
    extracted_fields = {
    "header": header_fields,
    "items": items_fields
    }
    document_id = store_ocr_result(
        workflow_id=input.context.get("workflow_id"),
        header_id=input.context.get("header_id"),
        item_id=input.context.get("item_id"),
        document_url=doc_url,
        doc_type=input.context.get("doc_type", "invoice"),
        ocr_raw=json.dumps(ocr_data),
        ocr_result=ocr_data,
        extracted_fields=extracted_fields,
        status="OCR_COMPLETE",
    )
    return ActivityOutput(
        {"document_id": document_id, "ocr_data": ocr_data},
        {"ocr": {"document_id": document_id}}
    )

@activity.defn
@log_activity(display_name="03_NORMALIZE")
async def normalize_document(input: ActivityInput) -> ActivityOutput:
    # Normalize OCR data into structured invoice fields
    print("📄 [NORMALIZE] Starting invoice normalization", input.payload, input.context)
    ocr = input.payload.get("ocr_data", {})
    header = ocr.get("documents", [{}])[0].get("header", {})
    invoice = {
        "invoice_id": header.get("InvoiceId") or "UNKNOWN",
        "vendor_name": header.get("VendorName") or "UNKNOWN",
        "invoice_total": float(str(header.get("InvoiceTotal","0")).replace("$","").replace(",","")),
        "invoice_date": header.get("InvoiceDate")
    }
    print(f"📝 [NORMALIZE] Invoice extracted: {invoice['invoice_id']} for vendor {invoice['vendor_name']}")
    return ActivityOutput(
        {**input.payload, "invoice_data": invoice},
        {"normalize": {"fields": len(invoice)}}
    )

@activity.defn
@log_activity(display_name="04_VALIDATE")
async def validate_document(input: ActivityInput) -> ActivityOutput:
    # Simple validation and classification
    invoice = input.payload.get("invoice_data")
    classification = "HIGH_VALUE" if invoice.get("invoice_total",0) > 1000 else "NORMAL"
    print(f"📊 [VALIDATE] Invoice {invoice.get('invoice_id')} classified as {classification}")
    return ActivityOutput(
        {**input.payload, "classification": classification},
        {"validate": {"type": classification}}
    )

@activity.defn
@log_activity(display_name="05_DECISION")
async def approval_decision(input: ActivityInput) -> ActivityOutput:
    # Decide if invoice is auto-approved or requires manual review
    total = input.payload.get("invoice_data", {}).get("invoice_total", 0)
    decision = "auto_approve" if total <= 2000 else "manual_review"
    return ActivityOutput(
        {**input.payload, "approval_decision": decision},
        {"decision": {"type": decision}}
    )

@activity.defn
@log_activity(display_name="06_ERP")
async def post_to_erp(input: ActivityInput) -> ActivityOutput:
    # Post approved invoice to ERP system
    erp_id = f"ERP-{uuid.uuid4().hex[:8]}"
    store_erp_document(
        doc_id=erp_id,
        doc_type="invoice",
        workflow_id=input.context.get("workflow_id"),
        child_workflow_id=None,
        header_id=input.context.get("header_id"),
        item_id=input.context.get("item_id"),
        header_data=input.payload,
        line_items=[],
        approval_status="APPROVED",
        approved_by="SYSTEM",
        doc_date=str(datetime.utcnow().date()),
        owner_name="SYSTEM",
        reference_id=input.context.get("reference_id"),
    )
    return ActivityOutput(
        {**input.payload, "erp_id": erp_id},
        {"erp": {"id": erp_id}}
    )

@activity.defn
@log_activity(display_name="07_NOTIFY")
async def send_rejection_notification(input: ActivityInput) -> ActivityOutput:
    # Notify relevant parties on rejection
    return ActivityOutput(
        {**input.payload, "notification": "sent"},
        {"notify": {"status": "sent"}}
    )

@activity.defn
@log_activity(display_name="08_AUDIT")
async def store_audit(input: ActivityInput) -> ActivityOutput:
    # Log final results for audit
    print(json.dumps(input.payload, indent=2))
    return ActivityOutput({**input.payload, "status": "stored"}, {})

# -----------------------------
# Workflow Definition
# -----------------------------
@workflow.defn
class InvoiceProcessingWorkflow:
    def __init__(self):
        self.manual_approval_decision: Optional[str] = None
        self.manual_approval_details: Optional[Dict[str, Any]] = None

    @workflow.signal(name="manual_approval")
    def manual_approve(self, approval_details: Dict[str, Any]):
        # Signal to accept manual approval decision
        self.manual_approval_decision = approval_details.get("decision","REJECTED").upper()
        self.manual_approval_details = approval_details
        print(f"🟢 [SIGNAL] Manual approval received: {self.manual_approval_decision}")

    @workflow.run
    async def run(self, initial_payload: Dict):
        # Main workflow run method
        print("📥 workflow input payload received:", initial_payload)
        wf_id = workflow.info().workflow_id
        context = build_base_context(initial_payload, wf_id)
        payload = initial_payload.copy()

        # Step 1: Preprocess invoice documents
        payload, context = await execute_step(pre_process_invoices, payload, context, "01_PREPROCESS")

        results = []

        # Step 2: Process each invoice individually
        inv = payload.get("normalized_invoices", [])[0]  # For simplicity, process first invoice; can be extended to loop over all
        inv_payload = {**payload, **inv}  # merge root payload for full state
        inv_context = merge_context(context, {"item_id": inv["item_id"], "doc_type": inv.get("doc_type")})

        # OCR extraction
        inv_payload, inv_context = await execute_step(ai_process_doc, inv_payload, inv_context, "02_OCR", 120)

        # Normalize document fields
        inv_payload, inv_context = await execute_step(normalize_document, inv_payload, inv_context, "03_NORMALIZE")

        # Validate invoice data
        inv_payload, inv_context = await execute_step(validate_document, inv_payload, inv_context, "04_VALIDATE")

        # Make approval decision
        inv_payload, inv_context = await execute_step(approval_decision, inv_payload, inv_context, "05_DECISION")
        decision = inv_payload.get("approval_decision")

        # Log task summary for approver (auto or pending manual)
        log_approval_signal(
            workflow_id=wf_id,
            workflow_type=context.get("workflow_type"),
            reference_id=context.get("reference_id"),
            header_id=context.get("header_id"),
            item_id=inv["item_id"],
            task_name="DOCUMENT_APPROVAL",
            task_type="DOCUMENT_APPROVAL_L1",
            approval_signal_name="SYSTEM" if decision.startswith("auto") else "manual_approval",
            assigned_role="FINANCE_APPROVER",
            status="PENDING" if decision == "manual_review" else "COMPLETED",
            decision="AUTO_APPROVED" if decision.startswith("auto") else None,
            task_approval_summary={
                "invoice_total": inv_payload.get("invoice_data", {}).get("invoice_total"),
                "vendor_name": inv_payload.get("invoice_data", {}).get("vendor_name"),
                "approval_decision": decision
            },
            additional_data={"validation_class": inv_payload.get("classification")},
            signal_payload={"source": "SYSTEM"}  # mark system-generated signal
        )

        # Wait for manual approval if required
        if decision == "manual_review":
            # Wait for manual signal from workflow
            await workflow.wait_condition(
                lambda: self.manual_approval_decision is not None,
                timeout=timedelta(minutes=30)
            )

            # Extract manual approval details
            manual_details = self.manual_approval_details or {}
            final_decision = (
                "approved" if manual_details.get("decision", "").upper() == "APPROVED"
                else "rejected"
            )
            inv_payload["approval_decision"] = final_decision

            # Log full manual approval into workflow task table
            log_approval_signal(
                workflow_id=wf_id,
                workflow_type=context.get("workflow_type"),
                reference_id=context.get("reference_id"),
                header_id=context.get("header_id"),
                item_id=inv["item_id"],
                task_name="DOCUMENT_APPROVAL",
                task_type="DOCUMENT_APPROVAL_L1",
                approval_signal_name="manual_approval",
                assigned_role="FINANCE_APPROVER",
                assigned_to=manual_details.get("user_id"),          # log approver
                status="COMPLETED",
                decision="MANUAL_APPROVED" if final_decision=="approved" else "MANUAL_REJECTED",
                task_approval_summary={
                    "final_decision": final_decision,
                    "invoice_total": inv_payload.get("invoice_data", {}).get("invoice_total"),
                    "vendor_name": inv_payload.get("invoice_data", {}).get("vendor_name")
                },
                signal_payload=manual_details,                      # full JSON from signal
                comments=manual_details.get("comments"),           # log human comments
                additional_data={"validation_class": inv_payload.get("classification")}
            )

        # Route invoice based on decision
        decision = inv_payload.get("approval_decision")
        inv_context["branch_id"] = decision.upper()  # tag context with decision branch
        if decision in ["auto_approve", "approved"]:
            inv_payload, inv_context = await execute_step(post_to_erp, inv_payload, inv_context, "06_ERP")
        else:
            inv_payload, inv_context = await execute_step(send_rejection_notification, inv_payload, inv_context, "07_NOTIFY")


        results.append({**inv_payload, "context": inv_context})  # preserve full context

        # Audit final results
        await execute_step(store_audit, {"results": results}, inv_context, "08_AUDIT")

        # Step : mark workflow completed
        end_time = workflow.now()
        upsert_workflow_instance(
            workflow_id=wf_id,
            workflow_type=payload.get("workflow_type"),
            status="COMPLETED",
            input_data=payload,
            header_id=payload.get("header_id"),
            reference_id=payload.get("reference_id"),
            end_time=end_time   # explicitly mark workflow end
        )

        return {"status": "COMPLETED", "results": results}

# -----------------------------
# Worker Entry Point
# -----------------------------
async def main():
    # Start Temporal worker
    client = await Client.connect(TEMPORAL_HOST)
    worker = Worker(
        client,
        task_queue=DEFAULT_TASK_QUEUE,
        workflows=[InvoiceProcessingWorkflow],
        activities=[
            pre_process_invoices,
            ai_process_doc,
            normalize_document,
            validate_document,
            approval_decision,
            post_to_erp,
            send_rejection_notification,
            store_audit,
        ],
    )
    async with worker:
        print("🚀 Worker running...")
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())