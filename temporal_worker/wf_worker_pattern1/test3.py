import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Import your DB log function and pool
from ai_worker_db_log import log_approval_signal


def test_approval_logging():
    """
    Test logging of workflow approval tasks (AUTO_APPROVED, MANUAL_APPROVED, MANUAL_REJECTED)
    """
    wf_id = "TEST-WF-001"
    context = {
        "workflow_type": "InvoiceProcessingWorkflow",
        "reference_id": "INV-REF-001",
        "header_id": 1
    }
    inv = {"item_id": 101}
    inv_payload = {
        "invoice_data": {"invoice_total": 2500.0, "vendor_name": "Acme Corp"},
        "classification": "HIGH_VALUE"
    }

    test_cases = [
        {
            "decision": "auto_approve",
            "expected_decision": "AUTO_APPROVED",
            "approval_signal_name": "SYSTEM",
            "summary": {
                "invoice_total": inv_payload["invoice_data"]["invoice_total"],
                "vendor_name": inv_payload["invoice_data"]["vendor_name"],
                "approval_decision": "auto_approve"
            },
            "additional_data": {"validation_class": inv_payload.get("classification")},
            "status": "COMPLETED",
            "assigned_role": "FINANCE_APPROVER",
            "label": "SYSTEM / AUTO_APPROVED"
        },
        {
            "decision": "rejected",
            "expected_decision": "MANUAL_REJECTED",
            "approval_signal_name": "manual_approval",
            "summary": {"final_decision": "rejected"},
            "additional_data": None,
            "status": "COMPLETED",
            "assigned_role": "FINANCE_APPROVER",
            "label": "MANUAL_REJECTED"
        },
        {
            "decision": "approved",
            "expected_decision": "MANUAL_APPROVED",
            "approval_signal_name": "manual_approval",
            "summary": {"final_decision": "approved"},
            "additional_data": None,
            "status": "COMPLETED",
            "assigned_role": "FINANCE_APPROVER",
            "label": "MANUAL_APPROVED"
        }
    ]

    for case in test_cases:
        try:
            log_approval_signal(
                workflow_id=wf_id,
                workflow_type=context.get("workflow_type"),
                reference_id=context.get("reference_id"),
                header_id=context.get("header_id"),
                item_id=inv["item_id"],
                task_name="DOCUMENT_APPROVAL",
                task_type="DOCUMENT_APPROVAL_L1",
                approval_signal_name=case["approval_signal_name"],
                assigned_role=case["assigned_role"],
                status=case["status"],
                decision=case["expected_decision"],
                task_approval_summary=case["summary"],
                additional_data=case["additional_data"]
            )
            print(f"✅ {case['label']} log successful")
        except Exception as e:
            print(f"❌ {case['label']} log failed:", e)


if __name__ == "__main__":
    test_approval_logging()