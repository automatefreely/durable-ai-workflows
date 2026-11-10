"""Adapter contract tests: no network or paid model calls."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from lab import core


def data():
    return {
        "tenant": "synthetic",
        "operation_id": "model-contract",
        "model_mode": "openai",
        "request": {"customer": "Example", "amount_minor": 12500, "currency": "USD"},
    }


@pytest.mark.parametrize("invalid", [False, True])
async def test_real_adapter_contract_without_provider(invalid, monkeypatch):
    observed = {}

    async def mark(operation, kind):
        observed["event"] = (operation, kind)

    class FakeClient:
        def __init__(self, **options):
            observed["options"] = options
            self.responses = SimpleNamespace(create=self.create)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def create(self, **kwargs):
            observed["model"] = kwargs["model"]
            fields = json.loads(kwargs["input"])
            if invalid:
                fields["amount_minor"] = -1
            return SimpleNamespace(output_text=json.dumps(fields))

    monkeypatch.setattr(core, "mark", mark)
    monkeypatch.setenv("OPENAI_MODEL", "synthetic-test-model")
    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    if invalid:
        with pytest.raises(ValidationError):
            await core.proposal(data())
    else:
        result = await core.proposal(data())
        assert result["amount_minor"] == 12500
        assert result["tenant"] == "synthetic"
    assert observed["options"]["max_retries"] == 0
    assert observed["model"] == "synthetic-test-model"
    assert observed["event"] == ("model-contract", "model_call")


@pytest.mark.parametrize(
    "output",
    [
        "[]",
        "null",
        "not JSON",
        '{"customer":"Example","amount_minor":100,"currency":"USD","tenant":"other"}',
    ],
)
async def test_malformed_proposals_are_permanent_rejections(output, monkeypatch):
    from unittest.mock import AsyncMock

    from temporalio.exceptions import ApplicationError

    from lab.workflow import propose

    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(output_text=output))
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(core, "mark", AsyncMock())
    monkeypatch.setenv("OPENAI_MODEL", "synthetic-test-model")
    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    with pytest.raises(ApplicationError) as failure:
        await propose(data())
    assert failure.value.type == "InvalidProposal"
    assert failure.value.non_retryable is True
