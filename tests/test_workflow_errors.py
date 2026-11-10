"""Regression coverage for proposal errors, without network or Temporal services."""

from unittest.mock import AsyncMock, patch

import pytest
from temporalio.exceptions import ActivityError, ApplicationError, TimeoutError, TimeoutType

from lab.workflow import InvoiceWorkflow


@pytest.mark.parametrize(
    "cause,expected",
    [
        (ApplicationError("Bad fields", type="InvalidProposal", non_retryable=True), "rejected"),
        (ApplicationError("Provider unavailable", type="ProviderUnavailable"), "proposal_failed"),
        (
            TimeoutError("Model timed out", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]),
            "proposal_failed",
        ),
    ],
)
async def test_operational_errors_are_not_rejections(cause, expected):
    error = ActivityError(
        "Proposal failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="regression",
        activity_type="propose",
        activity_id="1",
        retry_state=None,
    )
    error.__cause__ = cause
    execute = AsyncMock(side_effect=error)
    with patch("lab.workflow.workflow.execute_activity", execute):
        result = await InvoiceWorkflow().run({"operation_id": "synthetic"})
    assert result == {"status": expected}
    execute.assert_awaited_once()  # Failure exits before approval or invoice submission.
