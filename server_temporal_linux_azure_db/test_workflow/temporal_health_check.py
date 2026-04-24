import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio import workflow

TEMPORAL_HOST = "localhost:7233"

@workflow.defn
class PingWorkflow:
    @workflow.run
    async def run(self):
        return "OK"

async def main():
    client = await Client.connect(TEMPORAL_HOST)

    worker = Worker(
        client,
        task_queue="test-queue",
        workflows=[PingWorkflow],
    )

    async with worker:
        handle = await client.start_workflow(
            PingWorkflow.run,
            id="ping-1",
            task_queue="test-queue",
        )

        print(await handle.result())

asyncio.run(main())