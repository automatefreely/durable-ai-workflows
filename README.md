# Durable AI workflows: crash the worker, inspect the invoice

A local, synthetic experiment accompanying **Beyond the Agent Loop: Build AI Workflows
That Survive Crashes and Retries** by Automate Freely.

We compare a plain in-memory loop, Temporal without receiver idempotency, and Temporal
with an atomic idempotency receipt. The runner sends real SIGKILL signals at explicit
barriers. It does not simulate a crash by raising an exception.

No API key, account, real customer, real invoice, or paid model is required.
This is a reliability experiment, not a model-quality benchmark or production platform.

## Quickstart (Docker)

Requirements: Docker Engine/Desktop with Compose v2, Git, and free ports 7233, 8233, 8000.
Linux containers are required (including Docker Desktop on macOS/Windows).

```sh
git clone https://github.com/automatefreely/durable-ai-workflows.git
cd durable-ai-workflows
git checkout v1.0.0
# Set immutable source provenance for the image's runner.
export LAB_SOURCE_COMMIT="$(git rev-parse HEAD)"
docker compose build
docker compose up -d --wait temporal invoice
# One repeat of all 24 variant/scenario combinations:
docker compose run --rm runner python -m lab.run --repeat 1 --output /artifacts/smoke
# Full published protocol: 3 variants × 8 scenarios × 10 repeats.
docker compose run --rm runner
```

If using the prepared source archive instead of Git, skip clone/checkout and set
`LAB_SOURCE_COMMIT` from its included `SOURCE_COMMIT.txt`. A GitHub-generated archive
without that file needs the release commit SHA supplied explicitly.

Open `artifacts/latest/REPORT.md`. Each run also has input, JSONL events, worker logs,
a result, and (for Temporal variants) execution history. The CLI exits nonzero on an
unexpected result. Unsafe controls are EXPECTED to duplicate invoices in specific
scenarios; an expected failure is a passing experiment assertion.

The runner starts its own disposable workers on unique task queues. Do not start the
interactive worker for the matrix. Re-running generates new operation IDs. Use a fresh
output directory for each campaign; never mix old and new results.

```sh
# Just the decisive scenario, both controls and protected version:
docker compose run --rm runner python -m lab.run --scenario crash_after --repeat 1 --output /artifacts/crash
# Receiver unit tests (isolated temporary databases):
docker compose run --rm runner pytest tests/test_receiver.py -q
# Integration boundaries and replay; assumes artifacts/latest already exists:
docker compose run --rm -e LAB_INTEGRATION=1 -e LAB_EVIDENCE=/artifacts/latest runner pytest tests/test_integration.py -q
# Stop while retaining databases; deletes nothing:
docker compose down
```

The Temporal UI is at http://localhost:8233. The mock API is at http://localhost:8000/docs.
Ports bind localhost. The receiver is deliberately unauthenticated; never expose it.
Named volumes preserve state across restarts. `docker compose down -v` intentionally
deletes the lab databases—use only when a clean reset is wanted.

## Expected observations

| Scenario | Plain loop | Temporal | Temporal + idempotency |
|---|---|---|---|
| Healthy | One invoice | One | One |
| Crash before submit | Restart repeats model, one invoice | Replay, one | Replay, one |
| Crash after commit | Two invoices | Two | One, original ID reused |
| Commit then response timeout | Two invoices | Two | One, original ID reused |
| Transient 503 | Retries, one | Retries, one | Retries, one |
| Invalid proposal | Rejected, none | Rejected, none | Rejected, none |
| Restart awaiting approval | Lost session; needs reapproval | Pending wait resumes | Pending wait resumes |
| Duplicate submission | Two invoices | Second workflow start rejected | Second start rejected |

Plain crash cases explicitly resubmit the previously approved input after restart.
The awaiting-approval case deliberately does not invent approval after losing a session.
The workflow duplicate-start case rejects reuse even after completion. These policies
are visible choices, not universal default behavior of every agent framework.

## Native development

Python 3.12 and uv 0.13.5 are used in the recorded environment.

```sh
uv sync --frozen
docker compose up -d --wait temporal
# In a separate terminal:
LAB_TEST_MODE=1 uv run uvicorn lab.service:app --host 127.0.0.1 --port 8000
# Then:
uv run pytest tests/test_receiver.py -q
uv run python -m lab.run --repeat 1 --output artifacts/native
LAB_INTEGRATION=1 LAB_EVIDENCE=artifacts/native uv run pytest tests/test_integration.py -q
```

Native worker crashes require SIGKILL semantics; use Docker on Windows. To test actual
Temporal server restart, use the specifically named isolated container described in
`docs/validation.md`; that test is skipped unless explicitly enabled.

## Optional real model

The default fixture is deterministic and avoids paid calls. For a separate healthy
smoke test, set OPENAI_API_KEY through your environment, set OPENAI_MODEL to a model
available to your account, and run the native runner with `--model-mode openai
--scenario healthy --variant protected --repeat 1 --output artifacts/real-model`.
The model must support the Responses API and return the requested JSON. Output is
strictly validated before approval; no actual invoices are issued.

Do not mix those results with the fixture campaign. Provider retries are disabled;
a response lost before persistence can still mean another billable call. Never put
credentials in artifacts, command arguments, or committed files. For containers,
pass only `-e OPENAI_API_KEY -e OPENAI_MODEL` to `compose run`; these flags forward
already-set environment variables without putting values in shell history.

## Evidence and limitations

See `evidence/v1/REPORT.md` and `docs/architecture.md`. The report is generated from
per-run artifacts, not handwritten. Timing includes local scheduling and worker
startup. Local success counts are not a production availability estimate. Synthetic
fixtures test orchestration, not model competence. SQLite on a Temporal dev server
and localhost HTTP do not reproduce production storage or network behavior.

A stronger receiver contract is part of the result: without atomic receipt storage,
adequate key retention, authenticated tenant isolation, and provider reconciliation,
the single-effect guarantee does not follow. This mock enforces key scoping, not auth.

## License

MIT. Synthetic example data and original diagrams are included under the same license.
