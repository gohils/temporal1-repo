# worker.py
import os

from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.worker import Worker
from datetime import timedelta
import asyncio
import uuid


TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "temporal-server-demo.australiaeast.cloudapp.azure.com:7233")
TASK_QUEUE = "payments-task-queue"
# =====================================================
# WORKFLOW
# =====================================================
@workflow.defn
class PaymentWorkflow:

    @workflow.run
    async def run(self, payload: dict):

        print("\n================ WORKFLOW START ================\n")
        print(f"[WORKFLOW] Raw Input Payload:\n{payload}\n")

        # Normalize flexible input
        payment_id = payload.get("payment_id", "payment-001")
        customer_id = payload.get("customer_id", "unknown")
        amount = payload.get("amount", 0)
        currency = payload.get("currency", "AUD")

        print(f"[WORKFLOW] Normalized Input:")
        print(f"  payment_id = {payment_id}")
        print(f"  customer_id = {customer_id}")
        print(f"  amount = {amount}")
        print(f"  currency = {currency}\n")

        # =================================================
        # STEP 1 - VALIDATE
        # =================================================
        print("▶ STEP 1: VALIDATE")

        res = await workflow.execute_activity(
            validate,
            {
                "payment_id": payment_id,
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
            },
            start_to_close_timeout=timedelta(seconds=10),
        )

        print(f"[WORKFLOW] Validation Result: {res}\n")

        if not res.get("approved"):
            print("❌ PAYMENT DECLINED\n")
            return {
                "status": "DECLINED",
                "reason": res.get("reason", "validation failed"),
            }

        # =================================================
        # STEP 2 - CHARGE
        # =================================================
        print("▶ STEP 2: CHARGE")

        charge_res = await workflow.execute_activity(
            charge,
            {
                "payment_id": payment_id,
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
            },
            start_to_close_timeout=timedelta(seconds=30),
        )

        print(f"[WORKFLOW] Charge Result: {charge_res}\n")

        # =================================================
        # STEP 3 - RECEIPT
        # =================================================
        print("▶ STEP 3: SEND RECEIPT")

        receipt_payload = {
            "payment_id": payment_id,
            "customer_id": customer_id,
            "email": charge_res["email"],
            "amount": amount,
            "currency": currency,
        }

        print(f"[WORKFLOW] Receipt Payload: {receipt_payload}\n")

        await workflow.execute_activity(
            send_receipt,
            receipt_payload,
            start_to_close_timeout=timedelta(seconds=10),
        )

        print("✅ WORKFLOW SUCCESS COMPLETE\n")

        return {
            "status": "SUCCESS",
            "payment_id": payment_id,
            "transaction_id": charge_res["transaction_id"],
        }


# =====================================================
# ACTIVITIES
# =====================================================
@activity.defn
async def validate(payload: dict) -> dict:
    print("\n[ACTIVITY] VALIDATE")
    print(f"[ACTIVITY INPUT] {payload}")

    if payload["amount"] <= 0:
        print("[ACTIVITY] Validation FAILED\n")
        return {"approved": False, "reason": "invalid amount"}

    print("[ACTIVITY] Validation APPROVED\n")
    return {"approved": True}


@activity.defn
async def charge(payload: dict) -> dict:
    print("\n[ACTIVITY] CHARGE")
    print(f"[ACTIVITY INPUT] {payload}")

    result = {
        "transaction_id": str(uuid.uuid4()),
        "email": f"{payload['customer_id']}@test.com",
    }

    print(f"[ACTIVITY OUTPUT] {result}\n")
    return result


@activity.defn
async def send_receipt(payload: dict):
    print("\n[ACTIVITY] SEND RECEIPT")
    print(f"[ACTIVITY INPUT] {payload}")
    print("[ACTIVITY] Email sent successfully\n")


# =====================================================
# WORKER BOOTSTRAP
# =====================================================
async def main():

    print("\n🚀 STARTING TEMPORAL WORKER")
    print(f"Connecting to: {TEMPORAL_HOST}\n")

    client = await Client.connect(TEMPORAL_HOST)

    print("✅ Connected to Temporal\n")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[PaymentWorkflow],
        activities=[validate, charge, send_receipt],
    )

    print("🟢 Worker is running and waiting for tasks...\n")

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())