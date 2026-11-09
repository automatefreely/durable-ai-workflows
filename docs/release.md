# Release gate: prepared locally, not published

The public repository is intentionally not created by this preparation step.
The website article remains `published: false`. Publishing the companion source,
creating its public release, and deploying the article are later release actions.

After reviewing the code, evidence and article:

1. Check repository-name availability for `automatefreely/durable-ai-workflows` again.
   Do not silently change a repository name that is embedded in article links.
2. Create the public repository without generating a README/license on GitHub.
3. Add its origin URL to this prepared repository and push the reviewed history/tag.
4. Publish a v1.0.0 release with the source archive, SHA256 sums, and evidence replay.
5. Clone the public tag into an empty directory and execute the README quickstart.
6. Verify evidence/v1/manifest.json, environment.json, REPORT.md and SHA256SUMS.
7. Set the website article's actual date and `published: true`, review the publication
   diff, deploy, and run the launch checklist in the website article PR.

No tag name or checksum makes a release trustworthy by itself; inspect the source,
retain provenance, and compare the receiver events with the generated summary.

The optional OpenAI integration has offline adapter contract tests. No paid model
calls are included in the recorded release campaign. CI configuration is supplied;
do not call it a remotely passing CI run until the workflow actually runs on GitHub.
