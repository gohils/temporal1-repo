# -----------------------------
# hybrid_enterprise_customer_onboarding_workflow.py
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
        log_activity,
        upsert_workflow_instance,
        store_ocr_result,
        store_erp_document,
        log_approval_signal
    )

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
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
def log_wf_approval(wf_id, wf_type, status, signal_name=None, decision=None, role=None, user=None, comments=None, additional_data=None):
    log_approval_signal(
        workflow_id=wf_id,
        workflow_type=wf_type,
        task_name="DOCUMENT_APPROVAL",
        task_type="DOCUMENT_APPROVAL_L1",
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
@log_activity("ai_doc_classification")
async def ai_classify_document(input: ActivityInput) -> ActivityOutput:
    doc_url = input.payload.get("input_parameters", {}).get("document_url")
    if not doc_url and input.payload.get("items"):
        doc_url = input.payload["items"][0].get("document_url")
    if not doc_url:
        raise ValueError("❌ document_url not found in payload")

    print(f"➡️ [CLASSIFY] Calling classification API for: {doc_url}")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{AI_API_URL}/classify_document/default",
            params={"input_doc_url": doc_url},
            headers={"accept": "application/json"}
        )
        response.raise_for_status()
        result = response.json()

    doc_type = result.get("doc_type")
    confidence = result.get("confidence_pct", 0)

    print(f"✅ [CLASSIFY] doc_type={doc_type}, confidence={confidence}")

    new_payload = {**input.payload, "doc_type": doc_type, "classification_confidence": confidence}
    new_context = {**input.context, "classification": result}

    # Terminate early if low confidence
    if confidence < 60 or doc_type.lower() not in ["driving_licence", "passport", "electricity_bill", "direct_debit", "invoice", "receipt"]:
        wf_id = input.context.get("workflow_id")
        wf_type = input.context.get("workflow_type")

        print(f"❌ [CLASSIFY] Terminating workflow: doc_type={doc_type}, confidence={confidence}")

        upsert_workflow_instance(
            workflow_id=wf_id,
            workflow_type=wf_type,
            status="FAILED",
            requires_manual_review=True,
            input_data=new_payload
        )

        return ActivityOutput({"status": "INVALID_DOCUMENT", "confidence": confidence}, new_context)

    return ActivityOutput(new_payload, new_context)

@activity.defn
@log_activity("ai_process_doc")
async def ai_process_doc(input: ActivityInput) -> ActivityOutput:
    doc_url = input.payload.get("input_parameters", {}).get("document_url")
    if not doc_url and input.payload.get("items"):
        doc_url = input.payload["items"][0].get("document_url")

    wf_id = input.context.get("workflow_id")
    doc_type = input.payload.get("doc_type", "generic_document")

    # Map document type → prebuilt OCR model driving_licence, passport, electricity_bill
    model_map = {
        "driving_licence": "analyse_licence",
        "passport": "analyse_passport",
        "electricity_bill": "analyse_electricity",
        "direct_debit": "analyse_directdebit",
        "invoice": "process_invoice",
        "receipt": "process_receipt"
    }
    model_name = model_map.get(doc_type.lower(), "analyse_document")

    print(f"➡️ [OCR] Starting OCR for document_url={doc_url} using model {model_name}")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{AI_API_URL}/{model_name}/default",
            params={"input_doc_url": doc_url},
            headers={"accept": "application/json"}
        )
        response.raise_for_status()
        ocr_data = response.json()

    # Store OCR results
    document_id = store_ocr_result(
        workflow_id=wf_id,
        document_url=doc_url,
        ocr_raw=json.dumps(ocr_data),
        ocr_result=ocr_data,
        extracted_fields=ocr_data,  # already normalized
        status="OCR_COMPLETE"
    )

    print(f"✅ [OCR] OCR completed, document_id={document_id}")
    new_payload = {**input.payload, "document_id": document_id, "ocr_data": ocr_data}
    new_context = {**input.context, "ai_process_doc": new_payload}
    return ActivityOutput(new_payload, new_context)

@activity.defn
@log_activity("validate_document")
async def validate_document(input: ActivityInput) -> ActivityOutput:
    doc_type = input.payload.get("doc_type", "").lower()
    ocr_data = input.payload.get("ocr_data", {})

    validation_status = "VALID"
    missing_fields = []

    if doc_type == "driving_licence":
        required_fields = ["FirstName", "LastName", "DocumentNumber", "Address","issuedBy","DateOfBirth","DateOfExpiration"]
        for field in required_fields:
            if not ocr_data.get(field):
                missing_fields.append(field)
        if missing_fields:
            validation_status = f"MISSING_FIELDS: {', '.join(missing_fields)}"

    elif doc_type == "passport":
        required_fields = ["FirstName", "LastName", "DocumentNumber", "Country","DateOfBirth","DateOfExpiration","Nationality"]
        for field in required_fields:
            if not ocr_data.get(field):
                missing_fields.append(field)
        if missing_fields:
            validation_status = f"MISSING_FIELDS: {', '.join(missing_fields)}"

    elif doc_type == "electricity_bill":
        required_fields = ["retailer", "address", "account_number","issue_date"]
        for field in required_fields:
            if not ocr_data.get(field):
                missing_fields.append(field)
        if missing_fields:
            validation_status = f"MISSING_FIELDS: {', '.join(missing_fields)}"

    print(f"📊 [VALIDATE] Document type={doc_type}, validation={validation_status}")

    payload = {**input.payload, "document_validation": validation_status}
    context = {**input.context, "validate_document": validation_status}
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("approval_decision")
async def approval_decision(input: ActivityInput) -> ActivityOutput:
    wf_id = input.context.get("workflow_id")
    wf_type = input.context.get("workflow_type")
    doc_validation = input.payload.get("document_validation")

    if doc_validation == "VALID":
        decision = "auto_approve"
        log_wf_approval(wf_id=wf_id, wf_type=wf_type, status="COMPLETED",
                        signal_name="SYSTEM", decision="AUTO_APPROVED", role="SYSTEM", user="SYSTEM",
                        comments="Auto-approved")
        print(f"✅ [APPROVAL DECISION] Document auto-approved")
    else:
        decision = "manual_review"
        log_wf_approval(wf_id=wf_id, wf_type=wf_type, status="PENDING",
                        signal_name="manual_approval", decision=None, role="MANAGER",
                        user=None, comments="Requires manual review")
        print(f"⏳ [APPROVAL DECISION] Document requires manual review")

    payload = {**input.payload, "approval_decision": decision}
    context = {**input.context, "approval_decision": decision}
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("post_to_erp")
async def post_to_erp(input: ActivityInput) -> ActivityOutput:
    wf_id = input.context.get("workflow_id")
    doc_type = input.payload.get("doc_type")
    ocr_data = input.payload.get("ocr_data", {})
    decision = input.payload.get("approval_decision", "PENDING")
    manual = input.payload.get("manual_details", {})

    doc_id = f"ERP-{uuid.uuid4().hex[:8]}"
    stored_doc_id = store_erp_document(
        doc_id=doc_id,
        doc_type=doc_type,
        workflow_id=wf_id,
        header_data=ocr_data,
        line_items=[],  # not applicable for ID / utility bill
        approval_status=decision,
        approved_by=manual.get("reviewer_id", "SYSTEM"),
        doc_date=ocr_data.get("DateOfExpiration") or ocr_data.get("issue_date") or datetime.now().isoformat(),
        owner_name=f"{ocr_data.get('FirstName','')} {ocr_data.get('LastName','')}".strip() or "Unknown Owner",
        reference_id=str(ocr_data.get("DocumentNumber") or f"REF-{uuid.uuid4().hex[:6]}")
    )

    print(f"✅ [ERP] Document {stored_doc_id} stored successfully")
    payload = {**input.payload, "erp_doc_id": stored_doc_id}
    context = {**input.context, "post_to_erp": {"doc_id": stored_doc_id, "ocr_data": ocr_data}}
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("send_rejection_notification")
async def send_rejection_notification(input: ActivityInput) -> ActivityOutput:
    wf_id = input.context.get("workflow_id")
    doc_type = input.payload.get("doc_type")
    await asyncio.sleep(0.5)
    notification = {"status":"sent","document_type":doc_type}
    print(f"📩 [NOTIFY] Rejection notification sent for document type {doc_type}")
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
class AIDocumentProcessingWorkflow:

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
        print("📥 workflow input payload received:", initial_payload)

        def next_step():
            self.execution_counter += 1
            return self.execution_counter

        wf_id = workflow.info().workflow_id
        workflow_type = initial_payload.get("workflow_type")
        domain = initial_payload.get("domain")
        context = {"workflow_id": wf_id, "workflow_type": workflow_type}
        payload = initial_payload.copy()
        audit = []
        retry = RetryPolicy(maximum_attempts=3)

        # Log workflow start
        document_url = payload.get("input_parameters", {}).get("document_url")
        upsert_workflow_instance(
            workflow_id=wf_id,
            workflow_type=workflow_type,
            status="STARTED",
            input_data=initial_payload,
            document_id=document_url,
            domain=domain,
            parent_workflow=None,
            workflow_group=None,
            requires_manual_review=False
        )

        # Step 1: Document Classification
        classification_output = await workflow.execute_activity(
            ai_classify_document,
            ActivityInput({**payload, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=60)
        )
        payload.update(classification_output.response)
        context.update(classification_output.context)
        audit.append({"step": "ai_classify_document", "time": workflow.now().isoformat(), "payload": classification_output.response})

        if classification_output.response.get("status") == "INVALID_DOCUMENT":
            upsert_workflow_instance(
                workflow_id=wf_id,
                workflow_type=workflow_type,
                status="FAILED",
                input_data=payload,
                requires_manual_review=True,
                domain=domain
            )
            return {"status": "FAILED", "reason": "LOW_CONFIDENCE_DOCUMENT", "payload": payload, "audit": audit}

        # Step 2: OCR & Normalization
        res = await workflow.execute_activity(
            ai_process_doc,
            ActivityInput({**payload, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=retry
        )
        payload.update(res.response)
        context.update(res.context)
        audit.append({"step": "ai_process_doc", "time": workflow.now().isoformat(), "payload": res.response})

        # Step 3: Validate Document
        res = await workflow.execute_activity(
            validate_document,
            ActivityInput({**payload, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry
        )
        payload.update(res.response)
        context.update(res.context)
        audit.append({"step": "validate_document", "time": workflow.now().isoformat(), "payload": res.response})

        # Step 4: Approval Decision
        res = await workflow.execute_activity(
            approval_decision,
            ActivityInput({**payload, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry
        )
        payload.update(res.response)
        context.update(res.context)
        audit.append({"step": "approval_decision", "time": workflow.now().isoformat(), "payload": res.response})

        decision = payload.get("approval_decision")

        # Step 5: Manual approval if needed
        if decision == "manual_review":
            print("⏳ Waiting for manual approval signal...")
            await workflow.wait_condition(lambda: self.manual_approval_decision is not None, timeout=timedelta(minutes=30))
            decision = "manual_approved" if self.manual_approval_decision == "APPROVED" else "manual_rejected"
            payload.update({"manual_details": self.manual_approval_details, "approval_decision": decision})
            log_wf_approval(
                wf_id=wf_id, wf_type=workflow_type, status="COMPLETED",
                signal_name="manual_approval", decision=decision.upper(),
                role="MANAGER", user=self.manual_approval_details.get("user_id"),
                comments=self.manual_approval_details.get("comments"),
                additional_data=self.manual_approval_details
            )
            print(f"🟢 [WORKFLOW] Manual approval completed: {decision}")

        # Step 6: Route to ERP or send rejection
        if decision in ["auto_approve", "manual_approved"]:
            res = await workflow.execute_activity(
                post_to_erp,
                ActivityInput({**payload, "execution_order": next_step()}, context),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=retry
            )
            payload.update(res.response)
            context.update(res.context)
            audit.append({"step": "post_to_erp", "time": workflow.now().isoformat(), "payload": res.response})
        else:
            res = await workflow.execute_activity(
                send_rejection_notification,
                ActivityInput({**payload, "execution_order": next_step()}, context),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry
            )
            payload.update(res.response)
            context.update(res.context)
            audit.append({"step": "send_rejection_notification", "time": workflow.now().isoformat(), "payload": res.response})

        # Step 7: Audit
        await workflow.execute_activity(
            store_audit,
            ActivityInput({"audit": audit, "execution_order": next_step()}, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry
        )

        # Mark workflow completed
        upsert_workflow_instance(
            workflow_id=wf_id,
            workflow_type=workflow_type,
            status="COMPLETED",
            input_data=initial_payload,
            document_id=document_url,
            domain=domain,
            requires_manual_review=(decision == "manual_review")
        )

        print(f"🏁 [WORKFLOW COMPLETED] Workflow {wf_id} finished with decision: {decision}")
        return {"status":"COMPLETED", "decision": decision, "erp_doc_id": payload.get("erp_doc_id"), "audit": audit}

# -----------------------------
# Main
# -----------------------------
async def main():
    client = await Client.connect(TEMPORAL_HOST)
    worker = Worker(
        client,
        task_queue=DEFAULT_TASK_QUEUE,
        workflows=[AIDocumentProcessingWorkflow],
        activities=[ai_classify_document, ai_process_doc, validate_document, approval_decision,
                    post_to_erp, send_rejection_notification, store_audit],
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=20
    )
    async with worker:
        print("🚀 Worker started for Customer Onboarding Workflow...")
        await asyncio.Event().wait()

if __name__=="__main__":
    asyncio.run(main())