"""Real-process crash harness. Requires a running Temporal service and invoice API."""

import argparse
import asyncio
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

import httpx
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from lab.core import BASE
from lab.workflow import InvoiceWorkflow

SCENARIOS = [
    "healthy",
    "crash_before",
    "crash_after",
    "lost_response",
    "transient",
    "invalid",
    "approval_restart",
    "duplicate_start",
]
VARIANTS = ["plain", "temporal", "protected"]


async def snapshot(c, op):
    r = await c.get(f"{BASE}/_test/snapshot/{op}")
    r.raise_for_status()
    return r.json()


async def wait_event(c, op, kind, count=1):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        s = await snapshot(c, op)
        if sum(e["kind"] == kind for e in s["events"]) >= count:
            return
        await asyncio.sleep(0.025)
    raise TimeoutError(f"No {kind} for {op}")


async def spawn(data, queue, directory, restart=0):
    env = {**os.environ, "TASK_QUEUE": queue}
    command = [sys.executable, "-m", "lab.worker"]
    if data["variant"] == "plain":
        command += ["plain", json.dumps(data)]
    log = (directory / f"worker-{restart}.log").open("wb")
    p = await asyncio.create_subprocess_exec(
        *command, env=env, stdin=asyncio.subprocess.PIPE, stdout=log, stderr=log
    )
    log.close()
    return p


async def stop(p, kill=False):
    if p.returncode is None:
        if kill:
            p.kill()
        else:
            p.terminate()
        try:
            await asyncio.wait_for(p.wait(), 5)
        except TimeoutError:
            p.kill()
            await p.wait()


async def one(client, c, root, variant, scenario, repetition, model_mode="fixture"):
    op = uuid.uuid4().hex
    directory = root / op
    directory.mkdir()
    data = {
        "tenant": "synthetic-tenant",
        "operation_id": op,
        "variant": variant,
        "scenario": scenario,
        "model_mode": model_mode,
        "request": {
            "customer": "Example Customer",
            "amount_minor": -1 if scenario == "invalid" else 12500,
            "currency": "USD",
        },
    }
    (directory / "input.json").write_text(json.dumps(data, indent=2))
    (
        await c.post(f"{BASE}/_test/configure", json={"operation_id": op, "scenario": scenario})
    ).raise_for_status()
    queue = f"lab-{op}"
    workflow_id = f"invoice:{data['tenant']}:{op}"
    start = time.monotonic()
    harness = []
    p = await spawn(data, queue, directory)
    handle = None
    killed_at = None

    def record(kind, **detail):
        harness.append(
            {"ts": time.time(), "operation_id": op, "kind": kind, "detail": detail, "source": "harness"}
        )

    async def approve():
        if variant == "plain":
            p.stdin.write(b"approve\n")
            await p.stdin.drain()
        else:
            await handle.signal(InvoiceWorkflow.approve)
        record("approval_sent")

    async def finish():
        if variant != "plain":
            return await asyncio.wait_for(handle.result(), 25)
        await asyncio.wait_for(p.wait(), 25)
        lines = (directory / f"worker-{restart}.log").read_text().splitlines()
        for line in reversed(lines):
            try:
                value = json.loads(line)
                if "status" in value:
                    return value
            except ValueError:
                pass
        raise AssertionError(f"Plain worker failed: {lines[-8:]}")

    restart = 0
    record("worker_started", pid=p.pid)
    try:
        if variant != "plain":
            handle = await client.start_workflow(
                InvoiceWorkflow.run,
                data,
                id=workflow_id,
                task_queue=queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
            )
        if scenario == "invalid":
            result = await finish()
        else:
            await wait_event(c, op, "awaiting_approval")
            if scenario == "approval_restart":
                killed_at = time.monotonic()
                await stop(p, kill=True)
                record("worker_killed", returncode=p.returncode)
                restart = 1
                p = await spawn(data, queue, directory, restart)
                record("worker_restarted", pid=p.pid)
                if variant == "plain":
                    # No silent reapproval after losing the in-memory session.
                    await wait_event(c, op, "awaiting_approval", 2)
                    p.stdin.close()
                    result = await finish()
                else:
                    # Signal survives independently of whether the replacement has polled yet.
                    await approve()
                    result = await finish()
            else:
                await approve()
                if scenario in {"crash_before", "crash_after"}:
                    await wait_event(
                        c,
                        op,
                        "before_submit_barrier" if scenario == "crash_before" else "after_commit_barrier",
                    )
                    killed_at = time.monotonic()
                    await stop(p, kill=True)
                    record("worker_killed", returncode=p.returncode)
                    restart = 1
                    p = await spawn(data, queue, directory, restart)
                    record("worker_restarted", pid=p.pid)
                    if variant == "plain":
                        await wait_event(c, op, "awaiting_approval", 2)
                        # Explicit experiment restart policy: resubmit the approved input.
                        await approve()
                result = await finish()
                if scenario == "duplicate_start":
                    if variant == "plain":
                        restart = 1
                        p = await spawn(data, queue, directory, restart)
                        await wait_event(c, op, "awaiting_approval", 2)
                        await approve()
                        result = await finish()
                    else:
                        try:
                            await client.start_workflow(
                                InvoiceWorkflow.run,
                                data,
                                id=workflow_id,
                                task_queue=queue,
                                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                            )
                            raise AssertionError("Duplicate start accepted")
                        except WorkflowAlreadyStartedError:
                            record("duplicate_start_rejected")
        elapsed = time.monotonic() - start
        recovery = time.monotonic() - killed_at if killed_at else None
        s = await snapshot(c, op)
        counts = defaultdict(int)
        for event in s["events"]:
            counts[event["kind"]] += 1
        expected_invoices = (
            0 if scenario == "invalid" or (scenario == "approval_restart" and variant == "plain") else 1
        )
        if scenario in {"crash_after", "lost_response"} and variant != "protected":
            expected_invoices = 2
        if scenario == "duplicate_start" and variant == "plain":
            expected_invoices = 2
        expected_status = (
            "rejected"
            if scenario == "invalid"
            else (
                "needs_reapproval" if scenario == "approval_restart" and variant == "plain" else "completed"
            )
        )
        assert result["status"] == expected_status, result
        assert len(s["invoice_ids"]) == expected_invoices, s
        # Real provider requests may be retried before a result is persisted.
        if variant != "plain" and model_mode == "fixture":
            assert counts["model_call"] == 1, counts
        if scenario in {"crash_before", "crash_after", "approval_restart"}:
            assert any(e["kind"] == "worker_killed" and e["detail"]["returncode"] == -9 for e in harness)
        row = {
            "run_id": op,
            "workflow_id": workflow_id if handle else None,
            "variant": variant,
            "scenario": scenario,
            "repetition": repetition,
            "status": result["status"],
            "invoice_count": len(s["invoice_ids"]),
            "duplicate_count": max(0, len(s["invoice_ids"]) - 1),
            "model_calls": counts["model_call"],
            "activity_attempts": counts["activity_attempt"],
            "invoice_requests": counts["invoice_request"],
            "elapsed_s": round(elapsed, 4),
            "recovery_s": round(recovery, 4) if recovery is not None else None,
            "assertions_passed": True,
        }
        events = [{**e, "source": "receiver", "detail": json.loads(e["detail"])} for e in s["events"]]
        (directory / "events.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in sorted(events + harness, key=lambda e: e["ts"]))
        )
        (directory / "result.json").write_text(json.dumps(row, indent=2))
        if handle:
            history = await handle.fetch_history()
            (directory / "history.json").write_text(history.to_json())
        return row
    except BaseException as e:
        record("harness_failure", error=repr(e))
        (directory / "failure.json").write_text(json.dumps(harness, indent=2))
        raise
    finally:
        await stop(p)


def report(root):
    rows = [json.loads(p.read_text()) for p in sorted(root.glob("*/result.json"))]
    if not rows:
        raise ValueError("No results")
    (root / "results.json").write_text(json.dumps(rows, indent=2))
    with (root / "results.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Recorded experiment results",
        "",
        f"{len(rows)} completed runs. All expected assertions passed.",
        "",
        "Unsafe controls intentionally demonstrate duplicates and lost pending approval.",
        "",
        "| Variant | Scenario | Runs | Committed invoices | Duplicates | Model calls | Recovery range (s) |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for variant in VARIANTS:
        for scenario in SCENARIOS:
            group = [r for r in rows if r["variant"] == variant and r["scenario"] == scenario]
            if not group:
                continue
            recovery = [r["recovery_s"] for r in group if r["recovery_s"] is not None]
            span = f"{min(recovery):.2f}–{max(recovery):.2f}" if recovery else "—"
            lines.append(
                f"| {variant} | {scenario} | {len(group)} | "
                f"{sum(r['invoice_count'] for r in group)} | {sum(r['duplicate_count'] for r in group)} | "
                f"{sum(r['model_calls'] for r in group)} | {span} |"
            )
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    return rows


async def main(args):
    if args.report:
        report(Path(args.output))
        return
    root = Path(args.output)
    if args.repeat < 1:
        raise ValueError("--repeat must be positive")
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a fresh output directory; never mix experiment campaigns")
    root.mkdir(parents=True, exist_ok=True)
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
    manifest = {
        "started_at": time.time(),
        "python": sys.version,
        "platform": platform.platform(),
        "source_commit": os.environ.get("LAB_SOURCE_COMMIT")
        or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True))
        if Path(".git").exists()
        else None,
        "packages": {
            p: importlib.metadata.version(p) for p in ["temporalio", "fastapi", "httpx", "uvicorn", "openai"]
        },
        "arguments": vars(args),
        "model_mode": args.model_mode,
        "lock_sha256": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    async with httpx.AsyncClient(timeout=5) as c:
        (await c.get(f"{BASE}/health")).raise_for_status()
        for variant in args.variant or VARIANTS:
            for scenario in args.scenario or SCENARIOS:
                for repetition in range(args.repeat):
                    row = await one(client, c, root, variant, scenario, repetition, args.model_mode)
                    print(json.dumps(row), flush=True)
    report(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--variant", choices=VARIANTS, action="append")
    parser.add_argument("--scenario", choices=SCENARIOS, action="append")
    parser.add_argument("--output", default="artifacts/latest")
    parser.add_argument("--model-mode", choices=["fixture", "openai"], default="fixture")
    parser.add_argument("--report", action="store_true")
    asyncio.run(main(parser.parse_args()))
