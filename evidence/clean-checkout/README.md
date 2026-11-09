# Clean-checkout reproduction

A fresh local Git clone of commit 4570c22 was built with the README Docker Compose commands.
The decisive crash_after case was run once per variant. All three expected assertions passed:
plain loop: two invoices; Temporal: two; protected: one. This separate 3-run smoke test is
not included in the primary 240-run matrix. Runtime source is unchanged from its tested commit.
