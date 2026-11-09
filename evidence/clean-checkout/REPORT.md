# Recorded experiment results

3 completed runs. All expected assertions passed.

Unsafe controls intentionally demonstrate duplicates and lost pending approval.

| Variant | Scenario | Runs | Committed invoices | Duplicates | Model calls | Recovery range (s) |
|---|---|---:|---:|---:|---:|---|
| plain | crash_after | 1 | 2 | 1 | 2 | 1.70–1.70 |
| temporal | crash_after | 1 | 2 | 1 | 1 | 12.86–12.86 |
| protected | crash_after | 1 | 1 | 0 | 1 | 12.77–12.77 |
