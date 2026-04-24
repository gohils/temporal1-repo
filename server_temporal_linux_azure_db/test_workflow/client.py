import asyncio
import random
from temporalio.client import Client
from test_workflow import CustomerOnboardingWorkflow, Customer

TEMPORAL_HOST =  "localhost:7233"
TEMPORAL_HOST =  "4.197.33.155:7233"  # Update if Temporal server is running on a different host/port


async def main():
    client = await Client.connect(TEMPORAL_HOST)

    customer = Customer(
        customer_id=f"CUST-{random.randint(100,999)}",
        name="Alice",
        email="alice@example.com"
    )

    handle = await client.start_workflow(
        CustomerOnboardingWorkflow.run,
        customer,
        id=f"onboarding-{customer.customer_id}",
        task_queue="customer-onboarding-task-queue",
    )

    print("Started:", handle.id)

    result = await handle.result()
    print("DONE:", result)

asyncio.run(main())