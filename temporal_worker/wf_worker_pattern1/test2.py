# -----------------------------
# customer_onboarding_hybrid.py (refactored)
# -----------------------------

import asyncio, json, uuid, os
from dataclasses import dataclass
from datetime import timedelta, datetime
from typing import Dict, Any, Optional, List

from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy

# Safe imports
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
TASK_QUEUE = "customer-onboarding"
AI_API_URL = os.getenv("AI_API_URL", "https://zdoc-ai-api.azurewebsites.net")


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
# Shared Execution Helper
# -----------------------------
async def execute_step(activity_fn, payload, context, timeout=30):
    """Execute activity and merge payload/context safely."""
    result: ActivityOutput = await workflow.execute_activity(
        activity_fn,
        ActivityInput(payload, context),
        start_to_close_timeout=timedelta(seconds=timeout),
        retry_policy=RetryPolicy(maximum_attempts=3)
    )
    merged_payload = {**payload, **result.response}
    merged_context = {**context, **result.context}
    return merged_payload, merged_context


# -----------------------------
# Activities
# -----------------------------
@activity.defn
@log_activity("pre_process_documents")
async def pre_process_documents(input: ActivityInput) -> ActivityOutput:
    params = input.payload.get("input_parameters", {})
    documents = params.get("documents", [])
    reference_id = params.get("reference_id")
    if not documents or not reference_id:
        raise ValueError("Missing documents or reference_id")

    normalized_docs = [
        {
            "doc_id": str(uuid.uuid4())[:8],
            "declared_doc_type": doc.get("declared_data", {}).get("document_type_hint"),
            "document_url": doc.get("document_url")
        }
        for doc in documents
    ]

    execution_plan = [{**d, "status": "PLANNED"} for d in normalized_docs]

    upsert_workflow_instance(
        workflow_id=input.context["workflow_id"],
        workflow_type=input.context["workflow_type"],
        status="STARTED",
        input_data=params
    )

    return ActivityOutput(
        {"normalized_documents": normalized_docs},
        {**input.context, "reference_id": reference_id, "execution_plan": execution_plan}
    )


@activity.defn
@log_activity("ai_classify_document")
async def ai_classify_document(input: ActivityInput) -> ActivityOutput:
    async with httpx.AsyncClient(timeout=30) as client:
        result = (await client.get(
            f"{AI_API_URL}/classify_document/default",
            params={"input_doc_url": input.payload["document_url"]}
        )).json()

    return ActivityOutput(
        {**input.payload, "doc_type": result.get("doc_type"), "confidence": result.get("confidence_pct", 0)},
        {**input.context, "last_classification": result}
    )


@activity.defn
@log_activity("ai_process_doc")
async def ai_process_doc(input: ActivityInput) -> ActivityOutput:
    """Perform OCR and store results."""
    doc_url = input.payload.get("document_url")
    doc_type = input.payload.get("doc_type", "generic_document")
    model_map = {"driving_licence": "analyse_licence",
                 "passport": "analyse_passport",
                 "electricity_bill": "analyse_electricity"}
    model_name = model_map.get(doc_type.lower(), "analyse_document")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{AI_API_URL}/{model_name}/default",
                                params={"input_doc_url": doc_url},
                                headers={"accept": "application/json"})
        resp.raise_for_status()
        ocr_data = resp.json()

    document_id = store_ocr_result(
        workflow_id=input.context.get("workflow_id"),
        document_url=doc_url,
        ocr_raw=json.dumps(ocr_data),
        ocr_result=ocr_data,
        extracted_fields=ocr_data,
        status="OCR_COMPLETE"
    )

    print(f"✅ [OCR] Completed {doc_type}, document_id={document_id}")
    return ActivityOutput(
        {**input.payload, "document_id": document_id, "ocr_data": ocr_data},
        {**input.context, "last_ocr": {"document_id": document_id}}
    )


@activity.defn
@log_activity("validate_document")
async def validate_document(input: ActivityInput) -> ActivityOutput:
    status = "VALID" if input.payload.get("ocr_data") else "INVALID"
    return ActivityOutput({**input.payload, "validation_status": status}, {**input.context, "last_validation": status})


@activity.defn
@log_activity("cross_document_verification")
async def cross_document_verification(input: ActivityInput) -> ActivityOutput:
    # minimal verification example
    print(f"🔍 Cross-doc verification: \n{json.dumps(input.payload, indent=2)}")
    return ActivityOutput({"status": "valid"}, input.context)


@activity.defn
@log_activity("post_to_erp")
async def post_to_erp(input: ActivityInput) -> ActivityOutput:
    erp_id = f"ERP-{uuid.uuid4().hex[:8]}"
    store_erp_document(
        doc_id=erp_id,
        doc_type="customer_onboarding",
        workflow_id=input.context["workflow_id"],
        header_data=input.payload,
        line_items=[],
        approval_status="APPROVED",
        approved_by="SYSTEM",
        doc_date=str(datetime.utcnow().date()),
        owner_name="SYSTEM",
        reference_id=f"CUST-{uuid.uuid4().hex[:6]}"
    )
    return ActivityOutput({"erp_id": erp_id}, input.context)


@activity.defn
@log_activity("store_audit")
async def store_audit(input: ActivityInput) -> ActivityOutput:
    print(f"🗂️ AUDIT:\n{json.dumps(input.payload, indent=2)}")
    return ActivityOutput({"status": "stored"}, input.context)


# -----------------------------
# Child Workflow (Document Processing)
# -----------------------------
@workflow.defn
class DocumentWorkflow:
    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = payload.get("data", {})
        context = payload.get("context", {})
        doc_id = data.get("doc_id", "unknown")

        result = {
            "doc_id": doc_id,
            "doc_type": "UNKNOWN",
            "ocr_data": None,
            "validation": "FAILED",
            "status": "FAILED",
            "errors": []
        }

        print(f"📄 Starting child workflow for document_id={doc_id}")

        # Step 1️⃣ AI classify document
        try:
            data, context = await execute_step(ai_classify_document, data, context)
            result["doc_type"] = data.get("doc_type", "UNKNOWN")
            print(f"🧠 Classified document {doc_id}: doc_type={result['doc_type']}")
        except Exception as e:
            error_msg = f"Classification failed: {e}"
            result["errors"].append(error_msg)
            print(f"⚠️ {error_msg}")

        # Step 2️⃣ AI OCR / process document
        try:
            data, context = await execute_step(ai_process_doc, data, context)
            result["ocr_data"] = data.get("ocr_data", None)
            print(f"🔍 OCR completed for document {doc_id}")
        except Exception as e:
            error_msg = f"OCR failed: {e}"
            result["errors"].append(error_msg)
            print(f"⚠️ {error_msg}")

        # Step 3️⃣ Validate document
        try:
            data, context = await execute_step(validate_document, data, context)
            result["validation"] = data.get("validation_status", "FAILED")
            print(f"✅ Validation status for document {doc_id}: {result['validation']}")
        except Exception as e:
            error_msg = f"Validation failed: {e}"
            result["errors"].append(error_msg)
            print(f"⚠️ {error_msg}")

        # Determine overall status
        if not result["errors"]:
            result["status"] = "COMPLETED"
        else:
            result["status"] = "FAILED"

        return result


# -----------------------------
# Parent Workflow
# -----------------------------
@workflow.defn
class CustomerOnboardingWorkflow:
    def __init__(self):
        self.manual_decision: Optional[str] = None

    @workflow.signal
    def manual_approval(self, decision: str):
        self.manual_decision = decision
        print(f"🟢 Manual approval received: {decision}")

    @workflow.run
    async def run(self, payload: Dict[str, Any]):
        wf_id = workflow.info().workflow_id
        context = {"workflow_id": wf_id, "workflow_type": payload.get("workflow_type", "CustomerOnboarding")}
        print(f"🚀 Starting workflow: {wf_id}")

        # Step 1: Pre-process documents
        pre_payload, context = await execute_step(pre_process_documents, payload, context)
        docs = pre_payload.get("normalized_documents", [])
        print(f"📄 Pre-processed {len(docs)} documents")

        # Step 2: Fan-out child workflows correctly
        def sanitize(value: str) -> str:
            return value.lower().replace(" ", "_") if value else "unknown"
        child_handles = [
            workflow.execute_child_workflow(
                DocumentWorkflow.run,
                {"data": doc, "context": {"workflow_id": wf_id,"doc_type": doc.get("declared_doc_type")}},
                id=f"{wf_id}_{sanitize(doc.get('declared_doc_type'))}_{i}",
                task_queue=TASK_QUEUE,
                execution_timeout=timedelta(minutes=5)
            )
            for i, doc in enumerate(docs)
        ]

        # Step 2a: Collect child results
        results = []
        for handle in child_handles:
            try:
                res = await handle  # execute_child_workflow returns the result directly
            except Exception as e:
                res = {"status": "FAILED", "error": str(e)}
            results.append(res)
            print(f"✅ Child workflow completed: doc_type={res.get('doc_type')}, validation={res.get('validation')}, status={res.get('status')}")

        # Step 3: Cross-document verification
        cross_payload, context = await execute_step(
            cross_document_verification,
            {"documents": results},
            context
        )
        print(f"🔍 Cross-document verification status: {cross_payload.get('status')}")

        # Step 4: Determine approval decision
        if cross_payload.get("status") == "valid":
            decision = "AUTO_APPROVED"
        else:
            decision = await self._wait_manual_decision()
        print(f"📝 Workflow decision: {decision}")

        # Step 5: ERP posting
        erp_id = None
        if decision in ["AUTO_APPROVED", "APPROVED"]:
            erp_payload, context = await execute_step(post_to_erp, {"documents": results}, context)
            erp_id = erp_payload.get("erp_id")
            print(f"📦 Posted to ERP, erp_id={erp_id}")

        # Step 6: Audit
        await execute_step(
            store_audit,
            {"workflow_id": wf_id, "documents": results, "decision": decision, "erp_id": erp_id},
            context
        )
        print(f"🗂️ Audit stored for workflow {wf_id}")

        return {"status": "COMPLETED", "decision": decision, "erp_id": erp_id}

    async def _wait_manual_decision(self) -> str:
        print("⏳ Waiting for manual decision (30 min timeout)...")
        await workflow.wait_condition(lambda: self.manual_decision is not None, timeout=timedelta(minutes=30))
        print(f"🟢 Manual decision received: {self.manual_decision}")
        return self.manual_decision
       
# -----------------------------
# Worker
# -----------------------------
async def main():
    client = await Client.connect(TEMPORAL_HOST)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CustomerOnboardingWorkflow, DocumentWorkflow],
        activities=[pre_process_documents, ai_classify_document, ai_process_doc, validate_document,
                    cross_document_verification, post_to_erp, store_audit],
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=20
    )
    async with worker:
        print("🚀 Hybrid Worker running...")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())