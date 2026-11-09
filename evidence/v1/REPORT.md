# Recorded experiment results

240 completed runs. All expected assertions passed.

Unsafe controls intentionally demonstrate duplicates and lost pending approval.

| Variant | Scenario | Runs | Committed invoices | Duplicates | Model calls | Recovery range (s) |
|---|---|---:|---:|---:|---:|---|
| plain | healthy | 10 | 10 | 0 | 10 | — |
| plain | crash_before | 10 | 10 | 0 | 20 | 1.14–1.68 |
| plain | crash_after | 10 | 20 | 10 | 20 | 1.10–1.31 |
| plain | lost_response | 10 | 20 | 10 | 10 | — |
| plain | transient | 10 | 10 | 0 | 10 | — |
| plain | invalid | 10 | 0 | 0 | 10 | — |
| plain | approval_restart | 10 | 0 | 0 | 20 | 0.80–1.08 |
| plain | duplicate_start | 10 | 20 | 10 | 20 | — |
| temporal | healthy | 10 | 10 | 0 | 10 | — |
| temporal | crash_before | 10 | 10 | 0 | 10 | 13.00–13.09 |
| temporal | crash_after | 10 | 20 | 10 | 10 | 12.71–13.06 |
| temporal | lost_response | 10 | 20 | 10 | 10 | — |
| temporal | transient | 10 | 10 | 0 | 10 | — |
| temporal | invalid | 10 | 0 | 0 | 10 | — |
| temporal | approval_restart | 10 | 10 | 0 | 10 | 10.28–10.40 |
| temporal | duplicate_start | 10 | 10 | 0 | 10 | — |
| protected | healthy | 10 | 10 | 0 | 10 | — |
| protected | crash_before | 10 | 10 | 0 | 10 | 12.92–13.08 |
| protected | crash_after | 10 | 10 | 0 | 10 | 12.84–12.96 |
| protected | lost_response | 10 | 10 | 0 | 10 | — |
| protected | transient | 10 | 10 | 0 | 10 | — |
| protected | invalid | 10 | 0 | 0 | 10 | — |
| protected | approval_restart | 10 | 10 | 0 | 10 | 10.28–10.45 |
| protected | duplicate_start | 10 | 10 | 0 | 10 | — |
