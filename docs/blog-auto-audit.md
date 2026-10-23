# Blog auto-audit Lambda

`wecare-blog-auto-audit` automates the repeatable part of the protected blog-remediation process.

## Safety model

The worker is intentionally conservative:

1. Recount the live corpus.
2. Require exactly **1,430 posts = 976 Conversations + 454 Gastronomy**.
3. Require every post author to be exactly `Anew by WECARE.DIGITAL`.
4. Require no duplicate slugs or unexpected categories.
5. Apply only exact allow-listed replacements from `rules.py`.
6. Use conditional writes that preserve id, slug, URL, category, author and original publication date.
7. Recount after writes.
8. Log unresolved findings as review items instead of inventing copy.

The Lambda has no delete permission and no S3 permission. It has no public API route and uses no AI/Bedrock model.

## What is automatic

Deterministic corruption and known source-wrapper remnants can be repaired without a human approval batch.

Unknown source/reference language, malformed prose not covered by an exact rule, author failures, corpus-count failures, duplicate slugs, or unexpected categories are **not** automatically rewritten. They are logged for editorial review.

## Schedule

The provisioning script creates an EventBridge Scheduler job at 02:30 UTC daily (08:00 Asia/Kolkata), with auto-apply enabled for exact safe rules.

Manual IAM invocation is also supported:

```json
{"apply": false}
```

for audit-only, or:

```json
{"apply": true, "maxWrites": 50}
```

for an immediate deterministic safe-fix sweep.

## Deploy

```bash
python scripts/provision_blog_auto_audit.py
```
