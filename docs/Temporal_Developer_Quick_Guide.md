# Temporal Developer Quick Guide

## Purpose

This guide provides a reusable template and quick reference for building
new Temporal workers and workflows in Python.

Use this document as:

-   A starter template for new worker implementations
-   A quick reference for Temporal concepts
-   A best-practice guide for production-ready workflow design

------------------------------------------------------------------------

# 1. Core Rules Every Developer Must Follow

## Workflow Code Must Be Deterministic

Workflow code may replay many times. Therefore workflow code must never
do anything non-deterministic.

### Never do this inside a workflow

``` python
import random
from datetime import datetime

value = random.randint(1, 100)
now = datetime.now()
```

### Never do this inside a workflow

-   Call external APIs
-   Read files
-   Write files
-   Access databases
-   Generate UUIDs
-   Use current time directly
-   Use random numbers

### Correct Pattern

All side effects must be placed inside activities.

``` python
result = await workflow.execute_activity(
    some_activity,
    request,
    start_to_close_timeout=timedelta(minutes=1),
)
```

------------------------------------------------------------------------

# 2. Activities

Activities contain all real-world side effects:

-   Database access
-   HTTP calls
-   Sending emails
-   Calling payment providers
-   Reading files
-   Generating IDs

Example:

``` python
@activity.defn
async def send_email_activity(req: SendEmailRequest) -> None:
    await email_service.send(req.email, req.subject, req.body)
```

------------------------------------------------------------------------

# 3. Activities Must Be Idempotent

Activities may run more than once if the worker crashes after the side
effect succeeds but before completion is recorded.

Bad:

``` python
charge_customer()
```

Better:

``` python
charge_customer(idempotency_key=payment_id)
```

Recommended rule:

-   Every external system call should include an idempotency key
-   Or persist a processed flag in a database

------------------------------------------------------------------------

# 4. Request / Response Models

Prefer dataclasses instead of raw dictionaries.

``` python
from dataclasses import dataclass

@dataclass
class PaymentRequest:
    payment_id: str
    customer_id: str
    amount: float
    currency: str = "AUD"
```

Benefits:

-   Easier to understand
-   Safer to evolve
-   Better typing and IDE support

------------------------------------------------------------------------

# 5. Retry Policies

Always add explicit retry policies.

``` python
from temporalio.common import RetryPolicy

retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
)
```

Use when executing an activity:

``` python
await workflow.execute_activity(
    charge_payment_activity,
    request,
    start_to_close_timeout=timedelta(minutes=2),
    schedule_to_close_timeout=timedelta(minutes=5),
    retry_policy=retry_policy,
)
```

------------------------------------------------------------------------

# 6. Activity Timeouts

Recommended activity timeout types:

  Timeout                     Purpose
  --------------------------- ----------------------------------------
  start_to_close_timeout      Max duration of a single attempt
  schedule_to_close_timeout   Max total duration including retries
  heartbeat_timeout           Detect crashed long-running activities

Example:

``` python
await workflow.execute_activity(
    long_running_activity,
    request,
    start_to_close_timeout=timedelta(minutes=10),
    schedule_to_close_timeout=timedelta(minutes=30),
    heartbeat_timeout=timedelta(seconds=30),
)
```

------------------------------------------------------------------------

# 7. Heartbeats

Use heartbeats for long-running activities.

``` python
@activity.defn
async def import_large_file(req: ImportRequest) -> None:
    for item in req.items:
        process(item)
        activity.heartbeat()
```

If the worker crashes, Temporal can quickly retry elsewhere.

------------------------------------------------------------------------

# 8. Signals

Signals allow workflows to receive updates while running.

``` python
@workflow.defn
class PaymentWorkflow:

    def __init__(self):
        self.cancel_requested = False

    @workflow.signal
    async def cancel(self):
        self.cancel_requested = True
```

Use inside workflow:

``` python
if self.cancel_requested:
    return {"status": "CANCELLED"}
```

------------------------------------------------------------------------

# 9. Queries

Queries allow clients to ask for workflow state.

``` python
@workflow.query
def get_status(self) -> str:
    return self.status
```

------------------------------------------------------------------------

# 10. Timers

Use Temporal timers instead of `asyncio.sleep()` inside workflows.

``` python
await workflow.sleep(timedelta(minutes=5))
```

Never use:

``` python
await asyncio.sleep(5)
```

------------------------------------------------------------------------

# 11. Child Workflows

Use child workflows to split large workflows into smaller reusable
units.

``` python
result = await workflow.execute_child_workflow(
    ShippingWorkflow.run,
    shipping_request,
    id=f"ship-{order_id}",
)
```

------------------------------------------------------------------------

# 12. Compensation Pattern

Use compensation when one step succeeds and a later step fails.

Example:

1.  Charge customer
2.  Reserve inventory
3.  Shipping fails
4.  Refund customer

``` python
try:
    charge_result = await workflow.execute_activity(...)
    await workflow.execute_activity(...)
except Exception:
    await workflow.execute_activity(refund_payment_activity, charge_result)
```

------------------------------------------------------------------------

# 13. Graceful Worker Shutdown

``` python
worker = Worker(
    client,
    task_queue="payments-task-queue",
    workflows=[PaymentWorkflow],
    activities=[...],
    graceful_shutdown_timeout=timedelta(seconds=30),
)
```

This lets in-flight work finish before deployment or restart.

------------------------------------------------------------------------

# 14. Recommended Project Structure

``` text
app/
├── workflows/
│   └── payment_workflow.py
├── activities/
│   └── payment_activities.py
├── services/
│   └── payment_service.py
├── models/
│   └── payment_models.py
├── worker.py
└── start_workflow.py
```

------------------------------------------------------------------------

# 15. Developer Checklist

Before creating a new workflow:

``` text
[ ] Workflow contains no side effects
[ ] All external calls are in activities
[ ] Activities are idempotent
[ ] Retry policy added
[ ] Timeouts added
[ ] Long-running activities use heartbeat
[ ] Signals and queries added if needed
[ ] Graceful shutdown configured
```

------------------------------------------------------------------------

# Appendix A - Complete Runnable Worker Script

``` python
"""
single_payment_worker.py
"""

import asyncio
import json
import logging
import os
import sys
import uuid

from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker


# =====================================================================
# Logging
# =====================================================================

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "level": record.levelname,
                "message": record.getMessage(),
            }
        )


logger = logging.getLogger("payment-worker")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(logging.INFO)


# =====================================================================
# Models
# =====================================================================

@dataclass
class PaymentRequest:
    payment_id: str
    customer_id: str
    amount: float
    currency: str = "AUD"


# =====================================================================
# Service Layer
# =====================================================================

class PaymentService:
    async def charge(self, req: PaymentRequest) -> dict:
        await asyncio.sleep(2)

        return {
            "transaction_id": str(uuid.uuid4()),
            "email": f"{req.customer_id}@example.com",
        }


# =====================================================================
# Activities
# =====================================================================

@activity.defn
async def validate_payment_activity(req: PaymentRequest) -> None:
    if req.amount <= 0:
        raise ValueError("Amount must be greater than zero")


@activity.defn
async def charge_payment_activity(req: PaymentRequest) -> dict:
    service = PaymentService()
    return await service.charge(req)


# =====================================================================
# Workflow
# =====================================================================

@workflow.defn
class PaymentWorkflow:

    def __init__(self):
        self.status = "STARTING"
        self.cancel_requested = False

    @workflow.signal
    async def cancel(self):
        self.cancel_requested = True

    @workflow.query
    def get_status(self) -> str:
        return self.status

    @workflow.run
    async def run(self, req: PaymentRequest) -> dict:

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            maximum_attempts=3,
        )

        self.status = "VALIDATING"

        await workflow.execute_activity(
            validate_payment_activity,
            req,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        if self.cancel_requested:
            self.status = "CANCELLED"
            return {"status": "CANCELLED"}

        self.status = "CHARGING"

        result = await workflow.execute_activity(
            charge_payment_activity,
            req,
            start_to_close_timeout=timedelta(minutes=2),
            schedule_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        self.status = "COMPLETED"

        return {
            "status": "SUCCESS",
            "transaction_id": result["transaction_id"],
        }


# =====================================================================
# Worker Startup
# =====================================================================

async def main():
    client = await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "payments"),
    )

    worker = Worker(
        client,
        task_queue=os.getenv(
            "TEMPORAL_TASK_QUEUE",
            "payments-task-queue",
        ),
        workflows=[PaymentWorkflow],
        activities=[
            validate_payment_activity,
            charge_payment_activity,
        ],
        graceful_shutdown_timeout=timedelta(seconds=30),
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
```

------------------------------------------------------------------------

# Appendix B - Start Workflow Script

``` python
"""
start_payment_workflow.py
"""

import asyncio
import uuid

from temporalio.client import Client
from payment_worker import PaymentWorkflow, PaymentRequest


async def main():
    client = await Client.connect(
        "localhost:7233",
        namespace="payments",
    )

    result = await client.execute_workflow(
        PaymentWorkflow.run,
        PaymentRequest(
            payment_id=str(uuid.uuid4()),
            customer_id="customer-123",
            amount=149.99,
        ),
        id=f"payment-{uuid.uuid4()}",
        task_queue="payments-task-queue",
    )

    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```
