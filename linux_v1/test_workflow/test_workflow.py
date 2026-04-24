import asyncio
import uuid
from datetime import timedelta
from random import random

from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.worker import Worker

# TEMPORAL_HOST =  "localhost:7233"
TEMPORAL_HOST =  "temporal-server-demo.australiaeast.cloudapp.azure.com:7233"  # Update if Temporal server is running on a different host/port

# -----------------------------
# Activities
# -----------------------------
@activity.defn
async def validate(payload: dict) -> dict:
    print(f"[ACTIVITY] validate -> payload: {payload}")

    if payload["amount"] <= 0:
        print("[ACTIVITY] validate -> FAILED")
        return {"approved": False, "reason": "Invalid amount"}

    print("[ACTIVITY] validate -> APPROVED")
    return {"approved": True}


@activity.defn
async def charge(payload: dict) -> dict:
    print(f"[ACTIVITY] charge -> payload: {payload}")

    await asyncio.sleep(1)

    result = {
        "transaction_id": str(uuid.uuid4()),
        "email": f"{payload['customer_id']}@test.com",
    }

    print(f"[ACTIVITY] charge -> success: {result}")
    return result


@activity.defn
async def send_receipt(payload: dict):
    print(f"[ACTIVITY] send_receipt -> payload: {payload}")

    await asyncio.sleep(0.5)

    print("[ACTIVITY] send_receipt -> email sent")


# -----------------------------
# Workflow
# -----------------------------
@workflow.defn
class PaymentWorkflow:
    @workflow.run
    async def run(self, data: dict):

        print(f"[WORKFLOW] START -> {data}")

        # Step 1: Validate
        print("[WORKFLOW] Step 1 -> validate")
        res = await workflow.execute_activity(
            validate,
            data,
            start_to_close_timeout=timedelta(seconds=10),
        )

        print(f"[WORKFLOW] validate result -> {res}")

        if not res["approved"]:
            print("[WORKFLOW] DECLINED")
            return {"status": "DECLINED"}

        # Step 2: Charge
        print("[WORKFLOW] Step 2 -> charge")

        charge_res = await workflow.execute_activity(
            charge,
            data,
            start_to_close_timeout=timedelta(seconds=30),
        )

        print(f"[WORKFLOW] charge result -> {charge_res}")

        # Step 3: Receipt
        print("[WORKFLOW] Step 3 -> send receipt")

        await workflow.execute_activity(
            send_receipt,
            {**data, "email": charge_res["email"]},
            start_to_close_timeout=timedelta(seconds=10),
        )

        print("[WORKFLOW] SUCCESS COMPLETE")

        return {
            "status": "SUCCESS",
            "tx": charge_res["transaction_id"],
        }


# -----------------------------
# Main
# -----------------------------
async def main():
    print("🚀 STARTING WORKER")

    client = await Client.connect(TEMPORAL_HOST)
    print("✅ Connected to Temporal")

    worker = Worker(
        client,
        task_queue="payments",
        workflows=[PaymentWorkflow],
        activities=[validate, charge, send_receipt],
    )

    async with worker:
        print("🟢 Worker running")

        payload = {
            "payment_id": str(uuid.uuid4()),
            "customer_id": f"cust-{int(random()*1000)}",
            "amount": round(random() * 1000, 2),
        }

        print(f"🚀 Starting workflow -> {payload}")

        handle = await client.start_workflow(
            PaymentWorkflow,
            payload,
            id=f"payment-{payload['payment_id']}",
            task_queue="payments",
        )

        result = await handle.result()

        print("\n🎉 FINAL RESULT")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())