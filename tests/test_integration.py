"""Against the real local services; no time-skipping environment."""

import asyncio
import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer, Worker

from lab.core import BASE
from lab.run import wait_event
from lab.workflow import InvoiceWorkflow, awaiting, create, propose

pytestmark = pytest.mark.skipif(os.environ.get("LAB_INTEGRATION") != "1", reason="Needs running lab services")


@pytest.mark.parametrize("scenario", ["cancel", "duplicate_approval", "exhausted"])
async def test_workflow_boundaries(scenario):
    op = uuid.uuid4().hex
    data = {
        "tenant": "test",
        "operation_id": op,
        "variant": "protected",
        "scenario": scenario,
        "request": {"customer": "Test", "amount_minor": 100, "currency": "USD"},
    }
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
    async with httpx.AsyncClient(timeout=5) as c:
        (
            await c.post(f"{BASE}/_test/configure", json={"operation_id": op, "scenario": scenario})
        ).raise_for_status()
        async with Worker(
            client, task_queue=op, workflows=[InvoiceWorkflow], activities=[propose, create, awaiting]
        ):
            handle = await client.start_workflow(InvoiceWorkflow.run, data, id=op, task_queue=op)
            await wait_event(c, op, "awaiting_approval")
            if scenario == "cancel":
                await handle.cancel()
                from temporalio.client import WorkflowFailureError

                with pytest.raises(WorkflowFailureError):
                    await asyncio.wait_for(handle.result(), 10)
                expected = 0
            else:
                await handle.signal(InvoiceWorkflow.approve)
                if scenario == "duplicate_approval":
                    await handle.signal(InvoiceWorkflow.approve)
                result = await asyncio.wait_for(handle.result(), 20)
                assert result["status"] == (
                    "needs_reconciliation" if scenario == "exhausted" else "completed"
                )
                expected = 0 if scenario == "exhausted" else 1
            state = (await c.get(f"{BASE}/_test/snapshot/{op}")).json()
            assert len(state["invoice_ids"]) == expected
            if scenario == "exhausted":
                assert sum(e["kind"] == "invoice_request" for e in state["events"]) == 3
                result = (await c.get(f"{BASE}/invoices/by-operation/{op}", params={"tenant": "test"})).json()
                assert result["invoice_ids"] == []


async def test_replay_recorded_histories():
    root = Path(os.environ.get("LAB_EVIDENCE", "artifacts/matrix"))
    paths = list(root.glob("*/history.json"))
    if not paths:
        pytest.skip("Run the matrix before replay testing")
    replayer = Replayer(workflows=[InvoiceWorkflow])
    for path in paths:
        result = json.loads((path.parent / "result.json").read_text())
        history = WorkflowHistory.from_json(result["workflow_id"], path.read_text())
        await replayer.replay_workflow(history)


async def test_pending_approval_survives_temporal_restart():
    # Opt-in: restart only this lab's isolated Docker container, never an arbitrary service.
    if os.environ.get("LAB_RESTART_CONTAINER") != "durable-lab-temporal":
        pytest.skip("Enable isolated Temporal container restart test explicitly")
    import subprocess

    op = uuid.uuid4().hex
    data = {
        "tenant": "test",
        "operation_id": op,
        "variant": "protected",
        "scenario": "server_restart",
        "request": {"customer": "Test", "amount_minor": 100, "currency": "USD"},
    }
    client = await Client.connect("127.0.0.1:7233")
    async with httpx.AsyncClient(timeout=5) as c:
        async with Worker(
            client, task_queue=op, workflows=[InvoiceWorkflow], activities=[propose, create, awaiting]
        ):
            h = await client.start_workflow(InvoiceWorkflow.run, data, id=op, task_queue=op)
            await wait_event(c, op, "awaiting_approval")
        subprocess.run(["docker", "restart", "durable-lab-temporal"], check=True, capture_output=True)
        for _ in range(100):
            try:
                client = await Client.connect("127.0.0.1:7233")
                await client.service_client.workflow_service.get_system_info(
                    __import__(
                        "temporalio.api.workflowservice.v1", fromlist=["GetSystemInfoRequest"]
                    ).GetSystemInfoRequest()
                )
                break
            except (RuntimeError, __import__("temporalio.service", fromlist=["RPCError"]).RPCError):
                await asyncio.sleep(0.1)
        else:
            raise AssertionError("Temporal did not restart")
        async with Worker(
            client, task_queue=op, workflows=[InvoiceWorkflow], activities=[propose, create, awaiting]
        ):
            h = client.get_workflow_handle(op)
            await h.signal(InvoiceWorkflow.approve)
            assert (await asyncio.wait_for(h.result(), 15))["status"] == "completed"
        events = (await c.get(f"{BASE}/_test/snapshot/{op}")).json()["events"]
        assert sum(e["kind"] == "model_call" for e in events) == 1
