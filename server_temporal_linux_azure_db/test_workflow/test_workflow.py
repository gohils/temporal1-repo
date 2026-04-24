# 1httpx_wf_deco.py
import asyncio
from dataclasses import dataclass
from datetime import timedelta
import random
from temporalio import workflow, activity
from temporalio.client import Client
from temporalio.worker import Worker

TEMPORAL_HOST = "temporal-server-demo.australiaeast.cloudapp.azure.com:7233"
TEMPORAL_HOST = "localhost:7233"

# -----------------------------
# Data Classes
# -----------------------------
@dataclass
class Customer:
    customer_id: str
    name: str
    email: str

@dataclass
class ValidateCustomerInput:
    customer: Customer
    workflow_id: str

@dataclass
class CreateCRMInput:
    customer: Customer
    workflow_id: str

@dataclass
class CreateERPInput:
    customer: Customer
    workflow_id: str

# -----------------------------
# Activities
# -----------------------------
@activity.defn
async def validate_customer(input: ValidateCustomerInput):
    import httpx
    print("🟡 Activity START: validate_customer")
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://jsonplaceholder.typicode.com/posts/1", timeout=10)
        return resp.json()


@activity.defn
async def create_crm(input: CreateCRMInput):
    import httpx
    print("🟡 Activity START: create_crm")
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://jsonplaceholder.typicode.com/posts", json=input.customer.__dict__, timeout=10)
        return resp.json()


@activity.defn
async def create_erp(input: CreateERPInput):
    import httpx
    print("🟡 Activity START: create_erp")
    payload = {"customer_id": input.customer.customer_id, "billing_profile": "STANDARD"}
    async with httpx.AsyncClient() as client:
        resp = await client.post("https://jsonplaceholder.typicode.com/posts", json=payload, timeout=10)
        return resp.json()

# -----------------------------
# Workflow
# -----------------------------
@workflow.defn
class CustomerOnboardingWorkflow:
    @workflow.run
    async def run(self, customer: Customer):
        workflow_id = f"onboarding-{customer.customer_id}"
        print("🔷 WORKFLOW START")

        validation_result = await workflow.execute_activity(
            validate_customer,
            ValidateCustomerInput(customer, workflow_id),
            start_to_close_timeout=timedelta(seconds=30)
        )

        crm_result = await workflow.execute_activity(
            create_crm,
            CreateCRMInput(customer, workflow_id),
            start_to_close_timeout=timedelta(seconds=30)
        )

        erp_result = await workflow.execute_activity(
            create_erp,
            CreateERPInput(customer, workflow_id),
            start_to_close_timeout=timedelta(seconds=30)
        )

        return {
            "validation": validation_result,
            "crm": crm_result,
            "erp": erp_result
        }

# -----------------------------
# Main Execution
# -----------------------------
async def main():
    print("🚀 PROGRAM START")

    client = await Client.connect(TEMPORAL_HOST)
    print("✅ Connected")

    worker = Worker(
        client,
        task_queue="customer-onboarding-task-queue",
        workflows=[CustomerOnboardingWorkflow],
        activities=[validate_customer, create_crm, create_erp],
    )

    # START worker FIRST
    worker_task = asyncio.create_task(worker.run())

    print("👷 Worker started")

    # small delay to ensure polling is active
    await asyncio.sleep(2)

    customer = Customer(
        customer_id=f"CUST-{random.randint(100, 999)}",
        name="Alice",
        email="alice@example.com"
    )

    handle = await client.start_workflow(
        CustomerOnboardingWorkflow.run,
        customer,
        id=f"onboarding-{customer.customer_id}",
        task_queue="customer-onboarding-task-queue",
    )

    result = await handle.result()
    print("\n🎉 FINAL RESULT")
    print(result)

    worker_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())