import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from test_workflow import CustomerOnboardingWorkflow, validate_customer, create_crm, create_erp

TEMPORAL_HOST =  "localhost:7233"
TEMPORAL_HOST =  "4.197.33.155:7233"  # Update if Temporal server is running on a different host/port
async def main():
    client = await Client.connect(TEMPORAL_HOST)

    worker = Worker(
        client,
        task_queue="customer-onboarding-task-queue",
        workflows=[CustomerOnboardingWorkflow],
        activities=[validate_customer, create_crm, create_erp],
    )

    print("Worker started...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())