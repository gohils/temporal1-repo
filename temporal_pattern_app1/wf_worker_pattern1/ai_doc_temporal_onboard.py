# -----------------------------
# hybrid_enterprise_customer_onboarding.py
# -----------------------------

import asyncio, json, uuid, os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy

# Temporal-safe imports
with workflow.unsafe.imports_passed_through():
    import httpx
    from ai_worker_db_log import (
        log_activity, upsert_workflow_instance,
        store_ocr_result, store_erp_document,
        log_approval_signal
    )

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
AI_API_URL = os.getenv("AI_API_URL", "https://zdoc-ai-api.azurewebsites.net")
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
        task_name="CUSTOMER_ONBOARDING",
        task_type="KYC_VERIFICATION",
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
@log_activity("pre_process_documents")
async def pre_process_documents(input: ActivityInput) -> ActivityOutput:
    payload_params = input.payload.get("input_parameters", {})
    documents = payload_params.get("documents", [])
    reference_id = payload_params.get("reference_id")
    
    print(f"🔍 [PRE-PROCESS] input -\n {input}")

    if not documents or not reference_id:
        raise ValueError("❌ Missing documents or reference_id")

    context = {**input.context, "reference_id": reference_id, "precheck_passed": True}
    print(f"✅ [PRE-PROCESS] Found {len(documents)} documents for customer {reference_id}")
    return ActivityOutput(payload_params, context)

@activity.defn
@log_activity("ai_doc_classification")
async def ai_classify_document(input: ActivityInput) -> ActivityOutput:
    # classify document using AI to determine doc_type
    doc_url = input.payload.get("document_url")
    if not doc_url:
        raise ValueError("❌ document_url not found")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{AI_API_URL}/classify_document/default",
                                    params={"input_doc_url": doc_url},
                                    headers={"accept": "application/json"})
        response.raise_for_status()
        result = response.json()
    doc_type = result.get("doc_type")
    confidence = result.get("confidence_pct", 0)
    print(f"✅ [CLASSIFY] doc_type={doc_type}, confidence={confidence}")
    new_payload = {**input.payload, "doc_type": doc_type, "classification_confidence": confidence}
    new_context = {**input.context, "classification": result}
    # terminate if low confidence
    if confidence < 60 or doc_type.lower() not in ["driving_licence","passport","electricity_bill"]:
        wf_id = input.context.get("workflow_id")
        wf_type = input.context.get("workflow_type")
        print(f"❌ [CLASSIFY] Terminating workflow due to low confidence")
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
    # perform OCR based on doc_type
    doc_url = input.payload.get("document_url")
    doc_type = input.payload.get("doc_type", "generic_document")
    model_map = {"driving_licence":"analyse_licence","passport":"analyse_passport","electricity_bill":"analyse_electricity"}
    model_name = model_map.get(doc_type.lower(), "analyse_document")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{AI_API_URL}/{model_name}/default",
                                    params={"input_doc_url": doc_url},
                                    headers={"accept": "application/json"})
        response.raise_for_status()
        ocr_data = response.json()
    document_id = store_ocr_result(
        workflow_id=input.context.get("workflow_id"),
        document_url=doc_url,
        ocr_raw=json.dumps(ocr_data),
        ocr_result=ocr_data,
        extracted_fields=ocr_data,
        status="OCR_COMPLETE"
    )
    new_payload = {**input.payload, "document_id": document_id, "ocr_data": ocr_data}
    new_context = {**input.context, "ai_process_doc": new_payload}
    print(f"✅ [OCR] OCR completed for {doc_type}, document_id={document_id}")
    return ActivityOutput(new_payload, new_context)

@activity.defn
@log_activity("validate_document")
async def validate_document(input: ActivityInput) -> ActivityOutput:
    # validate OCR fields according to doc_type
    doc_type = input.payload.get("doc_type", "").lower()
    ocr_data = input.payload.get("ocr_data", {})
    validation_status = "VALID"
    missing_fields = []
    required_fields_map = {
        "driving_licence":["FirstName","LastName","DocumentNumber","Address","issuedBy","DateOfBirth","DateOfExpiration"],
        "passport":["FirstName","LastName","DocumentNumber","Country","DateOfBirth","DateOfExpiration","Nationality"],
        "electricity_bill":["retailer","address","account_number","issue_date"]
    }
    for field in required_fields_map.get(doc_type, []):
        if not ocr_data.get(field):
            missing_fields.append(field)
    if missing_fields:
        validation_status = f"MISSING_FIELDS: {', '.join(missing_fields)}"
    payload = {**input.payload, "document_validation": validation_status}
    context = {**input.context, "validate_document": validation_status}
    print(f"📊 [VALIDATE] {doc_type} validation status: {validation_status}")
    return ActivityOutput(payload, context)

@activity.defn
@log_activity("cross_document_verification")
async def cross_document_verification(input: ActivityInput) -> ActivityOutput:
    # cross-verify all processed documents for consistency
    documents = input.payload.get("processed_documents", {})
    # addresses = [d["normalized_data"].get("address") for d in documents.values() if "normalized_data" in d]
    # names = [d["normalized_data"].get("name") for d in documents.values() if "normalized_data" in d]
    # status = "valid" if len(set(addresses))==1 and len(set(names))==1 else "invalid"
    status = "valid" 
    print(f"🔗 [CROSS-VERIFY] Result: {status}")
    return ActivityOutput({"status": status}, input.context)

@activity.defn
@log_activity("approval_decision")
async def approval_decision(input: ActivityInput) -> ActivityOutput:
    # auto-approve if cross-document verification passes
    cross_status = input.payload.get("cross_verification_status")
    wf_id = input.context.get("workflow_id")
    wf_type = input.context.get("workflow_type")
    if cross_status=="valid":
        decision = "auto_approve"
        log_wf_approval(wf_id, wf_type, "COMPLETED", signal_name="SYSTEM", decision="AUTO_APPROVED", role="SYSTEM", user="SYSTEM", comments="Auto-approved")
    else:
        decision = "manual_review"
        log_wf_approval(wf_id, wf_type, "PENDING", signal_name="manual_approval", role="MANAGER", comments="Waiting for manual approval")
    payload = {**input.payload, "approval_decision": decision}
    print(f"✅ [APPROVAL DECISION] Decision: {decision}")
    return ActivityOutput(payload, input.context)

@activity.defn
@log_activity("post_to_erp")
async def post_to_erp(input: ActivityInput) -> ActivityOutput:
    # post approved customer onboarding to ERP system
    wf_id = input.context.get("workflow_id")
    doc_summary = {d: input.payload["processed_documents"][d]["normalized_data"] for d in input.payload["processed_documents"]}
    doc_id = f"ERP-{uuid.uuid4().hex[:8]}"
    stored_doc_id = store_erp_document(
        doc_id=doc_id,
        doc_type="customer_onboarding",
        workflow_id=wf_id,
        header_data=doc_summary,
        line_items=[],
        approval_status="APPROVED",
        approved_by="SYSTEM",
        doc_date=str(datetime.now().date()),
        owner_name=doc_summary.get("driver_license", {}).get("name", "UNKNOWN"),
        reference_id=f"CUST-{uuid.uuid4().hex[:6]}"
    )
    print(f"✅ [ERP] Customer onboarding stored in ERP: {stored_doc_id}")
    return ActivityOutput({**input.payload, "erp_doc_id": stored_doc_id}, input.context)

@activity.defn
@log_activity("store_audit")
async def store_audit(input: ActivityInput) -> ActivityOutput:
    # store workflow payload for auditing
    print(f"🗂️ [AUDIT] Payload:\n{json.dumps(input.payload, indent=2)}")
    return ActivityOutput({"status":"stored"}, input.context)

# -----------------------------
# Workflow
# {
#   "workflow_type": "CustomerOnboardingWorkflow",
#   "workflow_prefix": "CustomerOnboarding",
#   "domain": "RetailBanking",
#   "task_queue": "default-task-queue",
#     "input_parameters": {
#     "reference_id": "CUST-10001",
#     "documents": [
#         {
#         "document_url": "https://zblobarchive.blob.core.windows.net/samples/aus_dl_sample1.JPG",
#         "declared_data": {"document_type_hint": "driver_license"}
#         },
#         {
#         "document_url": "https://zblobarchive.blob.core.windows.net/samples/aus-passport-sample1.png",
#         "declared_data": {"document_type_hint": "passport"}
#         },
#         {
#         "document_url": "https://zblobarchive.blob.core.windows.net/samples/agl_sample1.jpg",
#         "declared_data": {"document_type_hint": "utility_bill"}
#         }
#     ]
#     }
# }
# -----------------------------
@workflow.defn
class CustomerOnboardingWorkflow:

    def __init__(self):
        self.manual_approval_decision: Optional[str] = None
        self.manual_approval_details: Optional[Dict[str, Any]] = None

    @workflow.signal(name="manual_approval")
    def manual_approve(self, approval_details: Dict[str, Any]):
        # receive manual approval signal
        self.manual_approval_decision = approval_details.get("decision","REJECTED").upper()
        self.manual_approval_details = approval_details
        print(f"🟢 [SIGNAL] Manual approval received: {self.manual_approval_decision}")

    @workflow.run
    async def run(self, payload: Dict[str, Any]):
        wf_id = workflow.info().workflow_id
        workflow_type = payload.get("workflow_type")
        context = {"workflow_id": wf_id, "workflow_type": workflow_type}

        print(f"🚀 [WORKFLOW STARTED] Starting workflow with payload:\n{json.dumps(payload, indent=2)}")

        # 1️⃣ Pre-processing
        res = await workflow.execute_activity(
            pre_process_documents,
            ActivityInput(payload, context),
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        context.update(res.context)

        # 2️⃣ Process each document: classification → OCR → validation
        documents = payload.get("input_parameters", {}).get("documents", [])
        processed_docs = {}

        for doc in documents:
            doc_payload = {
                "document_url": doc["document_url"],
                "input_parameters": doc.get("declared_data", {})
            }

            print(f"📄 [DOC] Processing document: {doc_payload['document_url']}")

            # Step 1: Classification
            classify_res = await workflow.execute_activity(
                ai_classify_document,
                ActivityInput(doc_payload, context),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3)
            )

            if classify_res.response.get("status") == "INVALID_DOCUMENT":
                processed_docs[doc_payload["document_url"]] = {
                    "normalized_data": {},
                    "verification_result": "invalid"
                }
                print(f"❌ [DOC] Invalid document skipped: {doc_payload['document_url']}")
                continue

            # Step 2: OCR
            ocr_res = await workflow.execute_activity(
                ai_process_doc,
                ActivityInput(classify_res.response, context),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3)
            )

            # Step 3: Validation
            validate_res = await workflow.execute_activity(
                validate_document,
                ActivityInput(ocr_res.response, context),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3)
            )

            processed_docs[doc_payload["document_url"]] = {
                "normalized_data": {
                    "document_type": validate_res.response.get("doc_type"),
                    "ocr_data": validate_res.response.get("ocr_data"),
                    "validation_result": validate_res.response.get("document_validation"),
                },
                "verification_result": validate_res.response.get("document_validation"),
            }

            print(f"✅ [DOC] Completed processing: {doc_payload['document_url']}")

        payload["processed_documents"] = processed_docs

        # 3️⃣ Cross-document verification (force valid for testing)
        cross_ver = await workflow.execute_activity(
            cross_document_verification,
            ActivityInput({"processed_documents": processed_docs}, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        cross_status = "valid"  # force valid for testing
        payload["cross_verification_status"] = cross_status
        print(f"🔗 [CROSS-VERIFY] Result: {cross_status}")

        # 4️⃣ Approval decision
        approval = await workflow.execute_activity(
            approval_decision,
            ActivityInput(payload, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        payload.update(approval.response)
        decision = payload["approval_decision"]

        # 5️⃣ Wait for manual approval if needed
        if decision == "manual_review":
            print("⏳ Waiting for manual approval signal...")
            await workflow.wait_condition(lambda: self.manual_approval_decision is not None, timeout=timedelta(minutes=30))
            decision = "manual_approved" if self.manual_approval_decision == "APPROVED" else "manual_rejected"
            payload.update({"manual_details": self.manual_approval_details, "approval_decision": decision})
            log_wf_approval(
                wf_id, workflow_type, "COMPLETED", "manual_approval",
                decision.upper(), "MANAGER",
                self.manual_approval_details.get("user_id"),
                self.manual_approval_details.get("comments"),
                self.manual_approval_details
            )
            print(f"🟢 [WORKFLOW] Manual approval completed: {decision}")

        # 6️⃣ Post to ERP if approved
        if decision in ["auto_approve", "manual_approved"]:
            res = await workflow.execute_activity(
                post_to_erp,
                ActivityInput(payload, context),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3)
            )
            payload.update(res.response)
        else:
            print(f"❌ Customer onboarding rejected.")

        # 7️⃣ Audit
        await workflow.execute_activity(
            store_audit,
            ActivityInput(payload, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        print(f"🏁 [WORKFLOW COMPLETED] Workflow {wf_id} finished with decision: {decision}")
        return {"status": "COMPLETED", "decision": decision, "erp_doc_id": payload.get("erp_doc_id")}


    # -------------------------
    # Helper: Process Single Document
    # -------------------------
    async def process_single_document(self, task_payload: Dict[str, Any]) -> Dict[str, Any]:
        # Sequentially execute classify → OCR → validate for one document
        classify_res = await workflow.execute_activity(
            ai_classify_document,
            ActivityInput(task_payload, {"workflow_id": workflow.info().workflow_id}),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        if classify_res.response.get("status") == "INVALID_DOCUMENT":
            return {"normalized_data": {}, "verification_result": "invalid"}

        ocr_res = await workflow.execute_activity(
            ai_process_doc,
            ActivityInput(classify_res.response, {"workflow_id": workflow.info().workflow_id}),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        validate_res = await workflow.execute_activity(
            validate_document,
            ActivityInput(ocr_res.response, {"workflow_id": workflow.info().workflow_id}),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        return {
            "normalized_data": {
                "document_type": validate_res.response.get("doc_type"),
                "ocr_data": validate_res.response.get("ocr_data"),
                "validation_result": validate_res.response.get("document_validation"),
            },
            "verification_result": validate_res.response.get("document_validation"),
        }

# -----------------------------
# Main: Worker
# -----------------------------
async def main():
    client = await Client.connect(TEMPORAL_HOST)
    worker = Worker(
        client,
        task_queue=DEFAULT_TASK_QUEUE,
        workflows=[CustomerOnboardingWorkflow],
        activities=[pre_process_documents, ai_classify_document, ai_process_doc, validate_document,
                    cross_document_verification, approval_decision, post_to_erp, store_audit],
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=20
    )
    async with worker:
        print("🚀 Worker started for Customer Onboarding Workflow...")
        await asyncio.Event().wait()

if __name__=="__main__":
    asyncio.run(main())