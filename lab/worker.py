import asyncio
import json
import os
import sys

import httpx
from temporalio.client import Client
from temporalio.worker import Worker

from lab.core import mark, proposal, submit
from lab.workflow import InvoiceWorkflow, awaiting, create, propose


async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "plain":
        data = json.loads(sys.argv[2])
        try:
            invoice = await proposal(data)
        except ValueError:
            print(json.dumps({"status": "rejected"}), flush=True)
            return
        await mark(data["operation_id"], "awaiting_approval")
        if (await asyncio.to_thread(sys.stdin.readline)).strip() != "approve":
            print(json.dumps({"status": "needs_reapproval"}), flush=True)
            return
        await mark(data["operation_id"], "approval_observed")
        for attempt in range(3):
            try:
                result = await submit(data, invoice)
                print(json.dumps({"status": "completed", **result}), flush=True)
                return
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                    break
                await asyncio.sleep(0.1 * 2**attempt)
        print(json.dumps({"status": "needs_reconciliation"}), flush=True)
    else:
        client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
        async with Worker(
            client,
            task_queue=os.environ.get("TASK_QUEUE", "invoice-lab"),
            workflows=[InvoiceWorkflow],
            activities=[propose, create, awaiting],
        ):
            print("WORKER_READY", flush=True)
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
