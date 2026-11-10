# Release status

The companion repository and `v1.0.0` Git tag are public. The article is live:

- Article: https://automatefreely.com/blog/durable-ai-workflows
- Versioned code: https://github.com/automatefreely/durable-ai-workflows/tree/v1.0.0
- Evidence: https://github.com/automatefreely/durable-ai-workflows/blob/v1.0.0/evidence/v1/REPORT.md

The original preparation bundles and versioned release instructions describe their
historical state. The existing tag and recorded evidence remain unchanged.
A separate GitHub Release asset page has not been created.

## Completed verification

- The primary 240-run campaign passed all expected assertions.
- Receiver, adapter, integration and replay tests passed; all 160 Temporal histories replayed.
- A clean-checkout reproduction confirmed the decisive post-commit crash behavior.
- GitHub Actions verification completed successfully after the public push.
- After the article merge, live desktop/mobile browser checks passed at five widths.
- The article is present in the sitemap and has its production canonical URL.
- Social crawlers can fetch the article and its 1200×630 PNG share image.

## Ongoing publication work

Inspect the article in an authorized Google Search Console property and request indexing.
Use the website launch kit for distribution drafts; no social posts or emails have
been sent automatically. Review available search/referral signals after publication.

## Maintenance verification

The updated workflow separates provider failures from rejected proposals. CI covers
receiver tests, model-adapter contract tests, workflow error regression tests, the
24-case real-process smoke campaign, independent event verification, original evidence
checksums, and replay of the generated and all 160 published histories. The server-restart
test remains an explicit local test because it restarts a specifically named container.

For future code changes, retain immutable evidence provenance and rerun applicable
checks. Do not move the existing version tag to incorporate documentation updates.
No paid model calls are included in the recorded campaign; optional adapter tests are offline.
