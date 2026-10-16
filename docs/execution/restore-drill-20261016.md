# Restore drill — 2026-10-16

First recorded restore drill for the backup/DR plan
(`docs/migrations/backup-and-dr-plan.md` §5). A backup is a hypothesis until it
has been restored; this is the evidence it works.

## DynamoDB point-in-time recovery

| Field | Value |
|-------|-------|
| Source table | `stack-wecare-digital-SiteLanguageCache` |
| Restore target | `stack-wecare-digital-SiteLanguageCache-restore-test` |
| Method | `restore-table-to-point-in-time --use-latest-restorable-time` |
| Source item count (COUNT scan) | 253 |
| Restored item count (COUNT scan) | 253 |
| Result | **MATCH — faithful restore** |
| Restore duration | ~4–5 min from CREATING to ACTIVE |
| Cleanup | test table deleted immediately after comparison (confirmed `ResourceNotFoundException`) |

Procedure used (repeatable):

```bash
SRC=stack-wecare-digital-SiteLanguageCache
DST=$SRC-restore-test
aws dynamodb restore-table-to-point-in-time \
  --source-table-name "$SRC" --target-table-name "$DST" \
  --use-latest-restorable-time --region us-east-1
# wait for ACTIVE, then:
aws dynamodb scan --table-name "$SRC" --select COUNT --region us-east-1 --query Count
aws dynamodb scan --table-name "$DST" --select COUNT --region us-east-1 --query Count
# counts match -> delete the test table
aws dynamodb delete-table --table-name "$DST" --region us-east-1
```

Note: item counts were taken with a live `COUNT` scan, not the table's
`ItemCount` property, which DynamoDB only refreshes about every 6 hours and would
have been stale on a freshly restored table.

## What this proves and does not

- **Proves:** PITR is enabled, a restore completes, and the restored data is
  complete (every item present). The runbook in `recovery-kit/README.md` step 3 is
  executable, not aspirational.
- **Does not prove:** a full-account rebuild, an S3 object-version restore, or a
  secrets restore. Those are separate drills (§5) still to be run.

## Next drills to schedule (quarterly)

- S3: delete an object, recover it from a prior version and from the (future) replica.
- Secrets: a real `secrets_backup.py restore` read confirming field names intact
  (the integrity half is already automated by `verify_backup_artifact.py`).
- Cognito: confirm `export_cognito_users.py` output parses and the user count matches.
