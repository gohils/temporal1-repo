# -----------------------------
# customer_onboarding_workflow_refactored_v2.py
# -----------------------------

import asyncio, json, uuid, os
from dataclasses import dataclass
from datetime import timedelta, datetime
from typing import Dict, Any, List

from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from temporalio.worker import Worker
from temporalio.client import Client

# Safe imports for HTTP requests and DB/ERP logging
with workflow.unsafe.imports_passed_through():
    import httpx
    from ai_worker_db_log import (
        log_activity,
        upsert_workflow_instance,
        store_ocr_result,
        store_erp_document,
        log_approval_signal
    )

# -----------------------------
# Constants
# -----------------------------
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
            "doc_type": doc.get("declared_data", {}).get("document_type_hint"),
            "document_url": doc.get("document_url")
        }
        for doc in documents
    ]

    upsert_workflow_instance(
        workflow_id=input.context["workflow_id"],
        workflow_type=input.context["workflow_type"],
        status="STARTED",
        input_data=params
    )

    print(f"📝 Pre-processed {len(normalized_docs)} documents")
    return ActivityOutput(
        {"normalized_documents": normalized_docs},
        {**input.context, "reference_id": reference_id}
    )


@activity.defn
@log_activity("ai_classify_document")
async def ai_classify_document(input: ActivityInput) -> ActivityOutput:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{AI_API_URL}/classify_document/default",
            params={"input_doc_url": input.payload["document_url"]}
        )
        resp.raise_for_status()
        result = resp.json()

    print(f"🧠 Classified doc {input.payload.get('doc_id')}: {result.get('doc_type')}")
    return ActivityOutput(
        {**input.payload, "doc_type": result.get("doc_type"), "confidence": result.get("confidence_pct", 0)},
        {**input.context, "last_classification": result}
    )


@activity.defn
@log_activity("ai_process_doc")
async def ai_process_doc(input: ActivityInput) -> ActivityOutput:
    """
    Process a single document through the appropriate AI model.
    Works for driver_license, passport, and utility_bill.
    """

    print(f"🔍 ai_process_doc input payload: {json.dumps(input.payload)}")

    doc_url = input.payload.get("document_url")
    doc_type = input.payload.get("doc_type", "generic_document").lower()

    # Map document type to AI endpoint (use 'default' to avoid {full_path} issues)
    model_map = {
        "driver_license": "analyse_licence/default",
        "passport": "analyse_passport/default",
        "electricity_bill": "analyse_electricity/default"
    }
    model_name = model_map.get(doc_type, "analyse_document/default")

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                f"{AI_API_URL}/{model_name}",
                params={"input_doc_url": doc_url},
                headers={"accept": "application/json"}
            )
            resp.raise_for_status()
            ocr_data = resp.json()
        except httpx.HTTPStatusError as e:
            # Catch 4xx/5xx and return as FAILED payload
            print(f"⚠️ OCR failed for doc {input.payload.get('doc_id')}: {e}")
            return ActivityOutput(
                {**input.payload, "status": "FAILED", "error": str(e)},
                input.context
            )

    # Store OCR result
    document_id = store_ocr_result(
        workflow_id=input.context.get("workflow_id"),
        document_url=doc_url,
        ocr_raw=json.dumps(ocr_data),
        ocr_result=ocr_data,
        extracted_fields=ocr_data,
        status="OCR_COMPLETE"
    )

    print(f"🔍 OCR completed for doc {input.payload.get('doc_id')}, document_id={document_id}")

    return ActivityOutput(
        {**input.payload, "document_id": document_id, "ocr_data": ocr_data, "status": "SUCCESS"},
        {**input.context, "last_ocr": {"document_id": document_id}}
    )


@activity.defn
@log_activity("validate_document")
async def validate_document(input: ActivityInput) -> ActivityOutput:
    status = "VALID" if input.payload.get("ocr_data") else "INVALID"
    print(f"✅ Validation for doc {input.payload.get('doc_id')}: {status}")
    return ActivityOutput(
        {**input.payload, "validation_status": status},
        {**input.context, "last_validation": status}
    )


@activity.defn
@log_activity("cross_document_verification")
async def cross_document_verification(input: ActivityInput) -> ActivityOutput:
    print(f"🔎 Cross-document verification for {len(input.payload)} docs")
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
    print(f"📤 Posted to ERP: {erp_id}")
    return ActivityOutput({"erp_id": erp_id}, input.context)


@activity.defn
@log_activity("store_audit")
async def store_audit(input: ActivityInput) -> ActivityOutput:
    print(f"🗂️ AUDIT: {json.dumps(input.payload, indent=2)}")
    return ActivityOutput({"status": "stored"}, input.context)


# -----------------------------
# Workflow
# -----------------------------
@workflow.defn
class CustomerOnboardingWorkflow:
    @workflow.run
    async def run(self, initial_payload: Dict) -> Dict[str, Any]:
        wf_id = workflow.info().workflow_id
        workflow_type = initial_payload.get("workflow_type")
        context = {"workflow_id": wf_id, "workflow_type": workflow_type}

        # 1️⃣ Pre-processing
        pre_result: ActivityOutput = await workflow.execute_activity(
            pre_process_documents,
            ActivityInput(initial_payload, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )
        context = pre_result.context

        # 2️⃣ Fan-out: process each document in parallel with labels
        # -----------------------------
        # Fan-out: process each document in parallel with proper activity_id labeling
        # -----------------------------
        async def document_pipeline(doc: Dict[str, Any], index: int):
            suffix = f"_doc{index}"
            try:
                classify_result: ActivityOutput = await workflow.execute_activity(
                    ai_classify_document,
                    ActivityInput(doc, context),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    activity_id=f"ai_classify_document{suffix}"
                )

                ocr_result: ActivityOutput = await workflow.execute_activity(
                    ai_process_doc,
                    ActivityInput(classify_result.response, context),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    activity_id=f"ai_process_doc{suffix}"
                )

                validate_result: ActivityOutput = await workflow.execute_activity(
                    validate_document,
                    ActivityInput(ocr_result.response, context),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    activity_id=f"validate_document{suffix}"
                )

                return validate_result.response

            except Exception as e:
                print(f"⚠️ Document pipeline {suffix} failed: {e}")
                return {**doc, "status": "FAILED", "error": str(e)}

        # Launch all documents in parallel with proper suffixes
        doc_results: List[Dict[str, Any]] = await asyncio.gather(
            *[document_pipeline(d, i) for i, d in enumerate(pre_result.response["normalized_documents"], start=1)]
        )

        # 3️⃣ Fan-in: cross-document verification
        verification_result: ActivityOutput = await workflow.execute_activity(
            cross_document_verification,
            ActivityInput(doc_results, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        # 4️⃣ Post results to ERP
        erp_result: ActivityOutput = await workflow.execute_activity(
            post_to_erp,
            ActivityInput(verification_result.response, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        # 5️⃣ Store audit
        await workflow.execute_activity(
            store_audit,
            ActivityInput({"workflow_id": wf_id, "erp_id": erp_result.response, "documents": doc_results}, context),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        return {
            "workflow_id": wf_id,
            "erp_id": erp_result.response,
            "documents": doc_results,
            "cross_verification": verification_result.response,
        }


# -----------------------------
# Worker
# -----------------------------
async def main():
    client = await Client.connect(TEMPORAL_HOST)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[CustomerOnboardingWorkflow],
        activities=[
            pre_process_documents,
            ai_classify_document,
            ai_process_doc,
            validate_document,
            cross_document_verification,
            post_to_erp,
            store_audit
        ],
        max_concurrent_activities=50,
        max_concurrent_workflow_tasks=20
    )
    async with worker:
        print("🚀 Hybrid Worker running...")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())