"""
single_payment_worker.py

A single-file Temporal worker for testing and local development.

This combines:
- workflow definition
- activities
- service layer
- configuration
- logging
- worker bootstrap

Run:
    python single_payment_worker.py

Required environment variables:
    TEMPORAL_ADDRESS=localhost:7233
    TEMPORAL_NAMESPACE=payments
    TEMPORAL_TASK_QUEUE=payments-task-queue

Install dependencies:
    pip install temporalio
"""

# =============================================================================
# Imports
# =============================================================================

import asyncio
import json
import logging
import os
from random import random
import sys
import uuid
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

# =============================================================================
# Logging Section
# Enterprise-style JSON logging so logs are easy to read in console or Docker
# =============================================================================


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include custom structured fields
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            }:
                payload[key] = value

        return json.dumps(payload)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    logger.addHandler(handler)
    logger.propagate = False

    return logger


logger = get_logger("payment-worker")

# =============================================================================
# Configuration Section
# Reads environment variables or falls back to defaults for local testing
# =============================================================================


@dataclass
class Config:
    temporal_address: str
    temporal_namespace: str
    temporal_task_queue: str


def load_config() -> Config:
    return Config(
        temporal_address=os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
        temporal_namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
        temporal_task_queue=os.getenv(
            "TEMPORAL_TASK_QUEUE", "payments-task-queue"
        ),
    )


# =============================================================================
# Service Layer
# This simulates external APIs such as payment gateway / email service
# =============================================================================


class PaymentService:
    async def charge_payment(
        self,
        payment_id: str,
        customer_id: str,
        amount: float,
        currency: str,
    ) -> dict:
        logger.info(
            "Calling external payment gateway",
            extra={
                "payment_id": payment_id,
                "customer_id": customer_id,
                "amount": amount,
            },
        )

        # Simulate API call delay
        await asyncio.sleep(2)

        return {
            "transaction_id": str(uuid.uuid4()),
            "customer_email": f"{customer_id}@example.com",
            "gateway_status": "APPROVED",
        }

    async def send_receipt_email(
        self,
        email: str,
        payment_id: str,
        amount: float,
        currency: str,
    ) -> None:
        logger.info(
            "Sending receipt email",
            extra={
                "payment_id": payment_id,
                "email": email,
            },
        )

        # Simulate email sending delay
        await asyncio.sleep(1)

        logger.info(
            "Receipt email sent",
            extra={
                "payment_id": payment_id,
                "email": email,
            },
        )


# =============================================================================
# Activity Definitions
# Activities contain real side-effecting code (APIs, DB calls, emails, etc.)
# =============================================================================


@activity.defn
async def validate_payment_activity(payload: dict) -> dict:
    logger.info(
        "Validating payment request",
        extra={
            "payment_id": payload["payment_id"],
            "amount": payload["amount"],
        },
    )

    if payload["amount"] <= 0:
        return {
            "approved": False,
            "reason": "Amount must be greater than zero",
        }

    if payload["amount"] > 10000:
        return {
            "approved": False,
            "reason": "Amount exceeds allowed limit",
        }

    return {
        "approved": True,
        "reason": None,
    }


@activity.defn
async def charge_payment_activity(payload: dict) -> dict:
    service = PaymentService()

    result = await service.charge_payment(
        payment_id=payload["payment_id"],
        customer_id=payload["customer_id"],
        amount=payload["amount"],
        currency=payload["currency"],
    )

    logger.info(
        "Payment successfully charged",
        extra={
            "payment_id": payload["payment_id"],
            "transaction_id": result["transaction_id"],
        },
    )

    return result


@activity.defn
async def send_receipt_activity(payload: dict) -> None:
    service = PaymentService()

    await service.send_receipt_email(
        email=payload["email"],
        payment_id=payload["payment_id"],
        amount=payload["amount"],
        currency=payload["currency"],
    )


# =============================================================================
# Workflow Definition
# Workflow coordinates activities and contains business orchestration logic
# =============================================================================

# Required because activities are imported into workflow-safe context
with workflow.unsafe.imports_passed_through():
    pass


@workflow.defn
class PaymentWorkflow:
    @workflow.run
    async def run(self, payment_details: dict) -> dict:

        payment_id = payment_details["payment_id"]
        customer_id = payment_details["customer_id"]
        amount = payment_details["amount"]
        currency = payment_details.get("currency", "AUD")

        workflow.logger.info(
            "Workflow started",
            extra={
                "payment_id": payment_id,
                "customer_id": customer_id,
                "amount": amount,
            },
        )

        # ---------------------------------------------------------------------
        # Step 1 - Validate payment
        # ---------------------------------------------------------------------
        validation = await workflow.execute_activity(
            validate_payment_activity,
            {
                "payment_id": payment_id,
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
            },
            start_to_close_timeout=timedelta(seconds=30),
        )

        if not validation["approved"]:
            workflow.logger.warning(
                "Payment validation failed",
                extra={
                    "payment_id": payment_id,
                    "reason": validation["reason"],
                },
            )

            return {
                "status": "DECLINED",
                "reason": validation["reason"],
            }

        # ---------------------------------------------------------------------
        # Step 2 - Charge payment
        # ---------------------------------------------------------------------
        charge_result = await workflow.execute_activity(
            charge_payment_activity,
            {
                "payment_id": payment_id,
                "customer_id": customer_id,
                "amount": amount,
                "currency": currency,
            },
            start_to_close_timeout=timedelta(minutes=2),
        )

        # ---------------------------------------------------------------------
        # Step 3 - Send receipt email
        # ---------------------------------------------------------------------
        await workflow.execute_activity(
            send_receipt_activity,
            {
                "payment_id": payment_id,
                "customer_id": customer_id,
                "email": charge_result["customer_email"],
                "amount": amount,
                "currency": currency,
            },
            start_to_close_timeout=timedelta(seconds=30),
        )

        workflow.logger.info(
            "Workflow completed successfully",
            extra={
                "payment_id": payment_id,
                "transaction_id": charge_result["transaction_id"],
            },
        )

        return {
            "status": "SUCCESS",
            "payment_id": payment_id,
            "transaction_id": charge_result["transaction_id"],
        }


# =============================================================================
# Worker Bootstrap Section
# Connects to Temporal and starts polling task queue
# =============================================================================
# -----------------------------
# Main Execution (E2E TEST STYLE)
# -----------------------------
async def main():
    print("🚀 PROGRAM START")

    config = load_config()

    print("🔵 Connecting to Temporal")
    client = await Client.connect(
        target_host=config.temporal_address,
        namespace=config.temporal_namespace,
    )
    print("✅ Temporal connected")

    worker = Worker(
        client,
        task_queue=config.temporal_task_queue,
        workflows=[PaymentWorkflow],
        activities=[
            validate_payment_activity,
            charge_payment_activity,
            send_receipt_activity,
        ],
    )

    print("🚀 Starting worker")

    # Run worker in background so we can also execute test workflow
    async with worker:
        print("✅ Worker is running")

        # -----------------------------
        # E2E TEST WORKFLOW EXECUTION
        # -----------------------------
        print("🚀 Starting test workflow")

        payment_id = str(uuid.uuid4())
        payment_details = {
            "payment_id": payment_id,
            "customer_id": f"customer-{int(random() * 900) + 100}",
            "amount": round((random() * 1000) + (random() * 1000), 2),
            "currency": "AUD",
        }

        handle = await client.start_workflow(
            PaymentWorkflow,
            payment_details,
            id=f"payment-{payment_id}",
            task_queue=config.temporal_task_queue,
        )

        print(f"Workflow started: payment-{payment_id}")

        result = await handle.result()

        print("\n🎉 FINAL RESULT")
        print(result)

# -----------------------------
# Entry Point
# -----------------------------
if __name__ == "__main__":
    asyncio.run(main())