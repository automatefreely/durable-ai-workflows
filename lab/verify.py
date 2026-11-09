"""Cross-check summary counts against receiver events, not just harness assertions."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from lab.run import SCENARIOS, VARIANTS, report


def verify(root: Path, repeats: int):
    paths = sorted(root.glob("*/result.json"))
    assert len(paths) == len(SCENARIOS) * len(VARIANTS) * repeats, "Incomplete matrix"
    assert not list(root.glob("*/failure.json")), "Campaign contains harness failures"
    groups = Counter()
    for path in paths:
        row = json.loads(path.read_text())
        data = json.loads((path.parent / "input.json").read_text())
        events = [json.loads(line) for line in (path.parent / "events.jsonl").read_text().splitlines()]
        counts = Counter(e["kind"] for e in events)
        groups[(row["variant"], row["scenario"])] += 1
        assert row["run_id"] == data["operation_id"] == path.parent.name
        assert all(e["operation_id"] == row["run_id"] for e in events)
        assert row["invoice_count"] == counts["invoice_committed"]
        assert row["invoice_requests"] == counts["invoice_request"]
        assert row["model_calls"] == counts["model_call"]
        assert row["activity_attempts"] == counts["activity_attempt"]
        if row["variant"] != "plain":
            assert row["model_calls"] == 1
            assert (path.parent / "history.json").is_file()
        if row["scenario"] in {"crash_before", "crash_after", "approval_restart"}:
            kills = [i for i, e in enumerate(events) if e["kind"] == "worker_killed"]
            assert len(kills) == 1 and events[kills[0]]["detail"]["returncode"] == -9
            assert any(e["kind"] == "worker_restarted" for e in events[kills[0] + 1 :])
            if row["scenario"] == "crash_after":
                before = events[: kills[0]]
                assert any(e["kind"] == "invoice_committed" for e in before)
                assert any(e["kind"] == "response_received" for e in before)
                assert any(e["kind"] == "after_commit_barrier" for e in before)
        if row["variant"] == "protected" and row["scenario"] in {"crash_after", "lost_response"}:
            ids = {e["detail"]["invoice_id"] for e in events if e["kind"] == "invoice_committed"}
            reused = [e["detail"]["invoice_id"] for e in events if e["kind"] == "invoice_reused"]
            assert len(ids) == 1 and reused and all(value in ids for value in reused)
        assert row["assertions_passed"] is True
    assert groups == Counter({(v, s): repeats for v in VARIANTS for s in SCENARIOS})
    report(root)
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (root / "SHA256SUMS").write_text(
        "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root)}\n" for p in files)
    )
    print(f"Verified {len(paths)} runs against raw events; integrity hashes written.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--repeat", type=int, default=10)
    args = parser.parse_args()
    verify(args.output, args.repeat)
