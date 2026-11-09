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
