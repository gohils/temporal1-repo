"""
start_payment_workflow.py

Starts a PaymentWorkflow in Temporal so you can test the worker.

Run after your worker is already running:

    python start_payment_workflow.py

Optional environment variables:
    TEMPORAL_ADDRESS=localhost:7233
    TEMPORAL_NAMESPACE=payments
    TEMPORAL_TASK_QUEUE=payments-task-queue
"""

import asyncio
import os
import uuid

from temporalio.client import Client


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE = os.getenv(
    "TEMPORAL_TASK_QUEUE",
    "payments-task-queue",
)


# -----------------------------------------------------------------------------
# Main Script
# -----------------------------------------------------------------------------

async def main():
    print(f"Connecting to Temporal at {TEMPORAL_ADDRESS}...")
    
    client = await Client.connect(
        target_host=TEMPORAL_ADDRESS,
        namespace=TEMPORAL_NAMESPACE,
    )

    # Unique workflow ID for every run
    payment_id = str(uuid.uuid4())

    workflow_id = f"payment-{payment_id}"

    print(f"Starting workflow: {workflow_id}")

    # Start the workflow by workflow name string
    # This works even though the workflow class lives inside worker code
    payment_details = {
    "payment_id": payment_id,
    "customer_id": "customer-123",
    "amount": 250.75,
    "currency": "AUD",
    }
    handle = await client.start_workflow(
        "PaymentWorkflow",
        payment_details,
        id=workflow_id,
        task_queue=TEMPORAL_TASK_QUEUE,
    )

    print(f"Workflow started successfully")
    print(f"Workflow ID: {handle.id}")
    print(f"Run ID: {handle.result_run_id}")

    print("\nWaiting for workflow to finish...\n")

    result = await handle.result()

    print("Workflow completed")
    print("Result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())