import concurrent.futures
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("INVOICE_DB", str(tmp_path / "invoices.db"))
    monkeypatch.setenv("LAB_TEST_MODE", "1")
    import lab.service

    module = importlib.reload(lab.service)
    with TestClient(module.app) as client:
        yield client


def invoice():
    return {
        "tenant": "tenant-a",
        "operation_id": uuid.uuid4().hex,
        "customer": "Synthetic",
        "amount_minor": 100,
        "currency": "USD",
    }


def test_concurrent_deduplication_and_payload_conflict(service):
    body = invoice()
    headers = {"Idempotency-Key": body["operation_id"]}

    def send(_):
        return service.post("/invoices", json=body, headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(send, range(16)))
    assert all(r.status_code == 200 for r in results)
    assert len({r.json()["invoice_id"] for r in results}) == 1
    assert service.post("/invoices", json={**body, "amount_minor": 200}, headers=headers).status_code == 409
    assert (
        len(
            service.get(
                f"/invoices/by-operation/{body['operation_id']}", params={"tenant": "tenant-a"}
            ).json()["invoice_ids"]
        )
        == 1
    )
    assert (
        service.get(f"/invoices/by-operation/{body['operation_id']}", params={"tenant": "tenant-b"}).json()[
            "invoice_ids"
        ]
        == []
    )
    # Key space is explicitly tenant scoped; this API is a mock, not an auth implementation.
    other = service.post("/invoices", json={**body, "tenant": "tenant-b"}, headers=headers)
    assert other.status_code == 200
    assert other.json()["invoice_id"] != results[0].json()["invoice_id"]


@pytest.mark.parametrize("amount", [0, -1, 1.5, "100", True])
def test_invalid_amount_never_commits(service, amount):
    body = {**invoice(), "amount_minor": amount}
    assert service.post("/invoices", json=body).status_code == 422
    assert service.get(f"/_test/snapshot/{body['operation_id']}").json()["invoice_ids"] == []


def test_unprotected_receiver_exposes_duplicate(service):
    body = invoice()
    a = service.post("/invoices", json=body).json()
    b = service.post("/invoices", json=body).json()
    assert a["invoice_id"] != b["invoice_id"]


def test_controls_are_off_by_default(monkeypatch):
    monkeypatch.delenv("LAB_TEST_MODE", raising=False)
    import lab.service

    with TestClient(importlib.reload(lab.service).app) as client:
        assert client.get("/_test/snapshot/anything").status_code == 404
