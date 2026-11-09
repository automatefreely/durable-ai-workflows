"""Independent receiver: invoice and idempotency receipt commit in one transaction."""
import asyncio
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

DB = Path(os.environ.get("INVOICE_DB", "state/invoices.db"))
TEST_MODE = os.environ.get("LAB_TEST_MODE") == "1"
app = FastAPI(title="Mock invoices — local demonstration only")


@contextmanager
def database():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.executescript('''
    CREATE TABLE IF NOT EXISTS invoices (
      id TEXT PRIMARY KEY, tenant TEXT NOT NULL, operation_id TEXT NOT NULL, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS receipts (
      tenant TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL, invoice_id TEXT NOT NULL,
      PRIMARY KEY(tenant, key));
    CREATE TABLE IF NOT EXISTS controls (
      operation_id TEXT PRIMARY KEY, scenario TEXT NOT NULL, fault_consumed INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, operation_id TEXT NOT NULL,
      kind TEXT NOT NULL, detail TEXT NOT NULL);
    ''')
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def event(c, operation, kind, detail=None):
    c.execute("INSERT INTO events(ts,operation_id,kind,detail) VALUES(?,?,?,?)",
              (time.time(), operation, kind, json.dumps(detail or {})))


class Invoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    customer: str = Field(min_length=1)
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern="^[A-Z]{3}$")


@app.get("/health")
def health():
    with database():
        return {"ok": True, "test_mode": TEST_MODE}


@app.post("/invoices")
async def create_invoice(body: Invoice, idempotency_key: str | None = Header(default=None)):
    payload = json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    transient = lost_response = False
    with database() as c:
        c.execute("BEGIN IMMEDIATE")
        event(c, body.operation_id, "invoice_request", {"key": idempotency_key})
        control = c.execute("SELECT * FROM controls WHERE operation_id=?", (body.operation_id,)).fetchone()
        if TEST_MODE and control and not control["fault_consumed"]:
            if control["scenario"] in {"transient", "lost_response", "exhausted"}:
                transient = control["scenario"] in {"transient", "exhausted"}
                lost_response = control["scenario"] == "lost_response"
                c.execute("UPDATE controls SET fault_consumed=1 WHERE operation_id=?", (body.operation_id,))
        if TEST_MODE and control and control["scenario"] == "exhausted":
            transient = True
        if transient:
            event(c, body.operation_id, "transient_failure")
        else:
            receipt = c.execute("SELECT * FROM receipts WHERE tenant=? AND key=?",
                                (body.tenant, idempotency_key)).fetchone() if idempotency_key else None
            if receipt:
                if receipt["digest"] != digest:
                    raise HTTPException(409, "Idempotency key reused with different payload")
                invoice_id = receipt["invoice_id"]
                event(c, body.operation_id, "invoice_reused", {"invoice_id": invoice_id})
            else:
                invoice_id = str(uuid.uuid4())
                c.execute("INSERT INTO invoices VALUES(?,?,?,?)",
                          (invoice_id, body.tenant, body.operation_id, payload))
                if idempotency_key:
                    c.execute("INSERT INTO receipts VALUES(?,?,?,?)",
                              (body.tenant, idempotency_key, digest, invoice_id))
                event(c, body.operation_id, "invoice_committed", {"invoice_id": invoice_id})
    if transient:
        raise HTTPException(503, "Injected temporary outage")
    if lost_response:
        # Commit has happened; caller times out before seeing this response.
        await asyncio.sleep(3)
    return {"invoice_id": invoice_id}


@app.get("/invoices/by-operation/{operation_id}")
def lookup(operation_id: str, tenant: str):
    with database() as c:
        rows = c.execute("SELECT id FROM invoices WHERE operation_id=? AND tenant=?",
                         (operation_id, tenant)).fetchall()
    return {"invoice_ids": [r["id"] for r in rows]}


if TEST_MODE:
    class Control(BaseModel):
        operation_id: str
        scenario: str

    @app.post("/_test/configure")
    def configure(body: Control):
        with database() as c:
            c.execute("INSERT INTO controls(operation_id,scenario) VALUES(?,?)",
                      (body.operation_id, body.scenario))
        return {"ok": True}

    @app.post("/_test/event/{operation_id}/{kind}")
    def write_event(operation_id: str, kind: str):
        with database() as c:
            event(c, operation_id, kind)
        return {"ok": True}

    @app.post("/_test/consume/{operation_id}")
    def consume(operation_id: str):
        with database() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT fault_consumed FROM controls WHERE operation_id=?", (operation_id,)).fetchone()
            consumed = bool(row and row["fault_consumed"])
            c.execute("UPDATE controls SET fault_consumed=1 WHERE operation_id=?", (operation_id,))
        return {"first": not consumed}

    @app.get("/_test/snapshot/{operation_id}")
    def snapshot(operation_id: str):
        with database() as c:
            rows = c.execute("SELECT * FROM events WHERE operation_id=? ORDER BY seq", (operation_id,)).fetchall()
            invoices = c.execute("SELECT id FROM invoices WHERE operation_id=?", (operation_id,)).fetchall()
        return {"events": [dict(r) for r in rows], "invoice_ids": [r["id"] for r in invoices]}
