import asyncio
import json
import os

import httpx

from lab.service import Invoice

BASE = os.environ.get("INVOICE_URL", "http://127.0.0.1:8000")


async def mark(operation, kind):
    async with httpx.AsyncClient(timeout=2) as c:
        (await c.post(f"{BASE}/_test/event/{operation}/{kind}")).raise_for_status()


async def barrier(operation, kind):
    async with httpx.AsyncClient(timeout=2) as c:
        first = (await c.post(f"{BASE}/_test/consume/{operation}")).json()["first"]
    if first:
        await mark(operation, kind)
        await asyncio.Event().wait()  # Harness sends SIGKILL; never reports success.


async def proposal(data):
    await mark(data["operation_id"], "model_call")
    if data.get("model_mode") == "openai":
        from openai import AsyncOpenAI

        model = os.environ["OPENAI_MODEL"]
        # Model retries disabled: orchestration owns retries, and output must validate.
        async with AsyncOpenAI(max_retries=0, timeout=10) as c:
            response = await c.responses.create(
                model=model,
                instructions="Return only JSON with customer, amount_minor (integer), and currency. "
                "Copy the request exactly. Do not add fields.",
                input=json.dumps(data["request"]),
            )
        fields = json.loads(response.output_text)
    else:
        fields = dict(data["request"])
    if not isinstance(fields, dict) or set(fields) != {"customer", "amount_minor", "currency"}:
        raise ValueError("Proposal must contain exactly customer, amount_minor, and currency")
    invoice = Invoice(tenant=data["tenant"], operation_id=data["operation_id"], **fields)
    return invoice.model_dump()


async def submit(data, invoice):
    operation = data["operation_id"]
    await mark(operation, "activity_attempt")
    if data["scenario"] == "crash_before":
        await barrier(operation, "before_submit_barrier")
    headers = {}
    if data["variant"] == "protected":
        headers["Idempotency-Key"] = f"{invoice['tenant']}:{operation}:create-invoice"
    async with httpx.AsyncClient(timeout=0.5) as c:
        r = await c.post(f"{BASE}/invoices", json=invoice, headers=headers)
        r.raise_for_status()
    await mark(operation, "response_received")
    if data["scenario"] == "crash_after":
        await barrier(operation, "after_commit_barrier")
    return r.json()
