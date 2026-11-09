from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    import httpx
    from pydantic import ValidationError

    from lab.core import mark, proposal, submit

RETRY = RetryPolicy(
    initial_interval=timedelta(milliseconds=100),
    backoff_coefficient=2,
    maximum_interval=timedelta(seconds=1),
    maximum_attempts=3,
)


@activity.defn
async def propose(data: dict) -> dict:
    try:
        return await proposal(data)
    except (ValidationError, ValueError) as e:
        raise ApplicationError(str(e), type="InvalidProposal", non_retryable=True) from e


@activity.defn
async def create(data: dict, invoice: dict) -> dict:
    try:
        return await submit(data, invoice)
    except httpx.HTTPStatusError as e:
        if 400 <= e.response.status_code < 500:
            raise ApplicationError(str(e), non_retryable=True, type="PermanentHTTPError") from e
        raise


@activity.defn
async def awaiting(operation: str) -> None:
    await mark(operation, "awaiting_approval")


@workflow.defn
class InvoiceWorkflow:
    def __init__(self):
        self.approved = False

    @workflow.signal
    def approve(self):
        self.approved = True

    @workflow.run
    async def run(self, data: dict) -> dict:
        try:
            invoice = await workflow.execute_activity(
                propose, data, start_to_close_timeout=timedelta(seconds=15), retry_policy=RETRY
            )
        except ActivityError:
            return {"status": "rejected"}
        await workflow.execute_activity(
            awaiting, data["operation_id"], start_to_close_timeout=timedelta(seconds=2), retry_policy=RETRY
        )
        await workflow.wait_condition(lambda: self.approved)
        try:
            result = await workflow.execute_activity(
                create, args=[data, invoice], start_to_close_timeout=timedelta(seconds=2), retry_policy=RETRY
            )
            return {"status": "completed", **result}
        except ActivityError:
            # Could have committed externally: operator must reconcile by operation ID.
            return {"status": "needs_reconciliation"}
