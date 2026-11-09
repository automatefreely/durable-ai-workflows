# Validation protocol

The release campaign is 10 repetitions × 8 scenarios × 3 variants, sequentially.
The input is synthetic USD 125.00 for Example Customer; the invalid control is -1.
No real model is called. Separate unit and integration tests cover cases outside the
240-run matrix. Expected failure controls are not silently counted as successful invoices.

For the native isolated-server restart test, start a dedicated container:

```sh
docker run -d --name durable-lab-temporal --user 0 \
  -e NO_PROXY=localhost,127.0.0.1,0.0.0.0 \
  -e no_proxy=localhost,127.0.0.1,0.0.0.0 \
  -p 127.0.0.1:7233:7233 -v durable-lab-temporal:/data \
  temporalio/temporal:1.4.1@sha256:9844298258519ebece82b3253f1ee1fc4eb8d87b7abcc264cfb676be342c74a5 \
  server start-dev --ip 0.0.0.0 --db-filename /data/temporal.db
# Start the native invoice API as in README, then:
LAB_INTEGRATION=1 LAB_RESTART_CONTAINER=durable-lab-temporal \
  uv run pytest tests/test_integration.py::test_pending_approval_survives_temporal_restart -q
```

That test only restarts the specifically named local lab container. Do not run it
against production. The Compose stack's Temporal container uses a different name.

The fixture model creates a model_call event for each execution. Completed Activity
results should replay without incrementing that count. The runner SIGKILL return
code must be -9. Barriers must precede each kill; the after-commit barrier must follow
a receiver commit and an observed HTTP success. Counts are independently taken
from the receiver database, not just inferred from worker status.

Recovery duration is measured from the kill request until result observation. It
includes worker startup, Temporal timeout detection, sticky task-queue scheduling,
and polling overhead. It is not a latency comparison between engines. No clocks
across different hosts are used to compute durations.

Rebuild REPORT.md from the raw results with:

```sh
uv run python -m lab.run --report --output evidence/v1
```

Inspect manifest.json for tested source commit and dirty state. Docker images have
no .git directory: pass LAB_SOURCE_COMMIT from a clean checkout. Its dirty state is
null, so also retain the clean-checkout attestation and image ID in environment.json.
Histories and logs contain synthetic inputs, but production histories would need
sensitive-data controls. CLI output never prints API keys.
