# Vault-only S3 upload and paid download (2026-11-01)

**Scope: Vault only.** This change does not alter the customer-facing Drop Docs upload service.

## Exact storage contract

Staff Vault uploads use the operator-specified S3 location, preserving the spelling:

```
s3://wecare-digital-get/secure/d/public/valut/
```

One uploaded object has a generated opaque key such as
`secure/d/public/valut/wecare-digital-<opaque-file-id>.pdf`.
The corresponding `SecureFilesTable` row owns `fileId`, `s3Key`, bound customer
Cognito subject, owner phone, stored MIME and size, status, and audit actor.
No public S3 key is returned by the Vault listing.

**This prefix is nested in the CDN's usually public delivery subtree.**
S3 Block Public Access does *not* protect reads through CloudFront's authorized
origin-access-control principal. The Lambda@Edge origin-response handler must deny
`secure/d/public/valut/` (including percent-encoded variants), remove object bytes
from redirected responses, and be deployed as a **published numbered version**
on CloudFront distribution `E2GP22R4BIFGQ3`. Matching private-prefix entries must
also exist in the Python and TypeScript media path contracts.

For defense in depth, consider an explicit bucket-policy **Deny** of
`s3:GetObject` for CloudFront's service principal, scoped **only** to
`arn:aws:s3:::wecare-digital-get/secure/d/public/valut/*`, with its distribution
SourceArn. Do not deny the staff Lambda's signed direct-S3 operations.

## Separate journeys

```text
STAFF WORKSPACE: /workspace/payments/?view=vault
  -> authenticated Operator
  -> choose a customer + file
  -> POST /secure-files/upload-init
     -> create owner-bound SecureFilesTable row (pending)
     -> signed PUT for secure/d/public/valut/<opaque-name>
  -> browser PUT to S3
  -> POST /secure-files/{fileId}/confirm
     -> S3 HEAD + actual file type/size checks
     -> mark the exact row active, deliverable=link
  -> select the now-active Vault file
  -> staff-initiated native WhatsApp Review & Pay, if unpaid
  -> Razorpay captured/verified by the existing commerce rail
  -> status updates + GST invoice + Access Vault URL template
  -> customer verifies WhatsApp OTP and exact-file entitlement
  -> 24-hour paid access window
  -> GET /secure-files/{fileId}/download
  -> short-lived, direct-S3 presigned GET of stored s3Key

DROP DOCS: separate customer-facing upload product, not used by this staff Vault intake.
```

The Vault Access URL template is a **web link**, not a direct public PDF or WhatsApp
document attachment. The staff preview `GET /secure-files/{fileId}/staff-download`
requires Operator auth, checks active S3 bytes, and returns a 60-second presigned
GET URL. The customer download route still enforces customer ownership and payment.

## Fail-closed rollout order

1. **Do not place customer files under this prefix yet.** The source change by
   itself does not change live CloudFront version 16.
2. Review the changed CDN/private-path code and run
   `python -m unittest discover -s tests -p 'test_vault_private_storage.py'`
   and `python scripts/verify_media_prefixes.py`.
3. Publish and associate the updated numbered Lambda@Edge version with
   CloudFront `E2GP22R4BIFGQ3`. Wait for `Deployed`, invalidate
   `/secure/d/public/valut/*`, and prove a **harmless** existing test object
   returns only a refusal / redirect and **zero bytes** both through the
   `/get/` website rewrite and the distribution URL. Check encoded paths too.
   Confirm a legitimate public WhatsApp template image remains available.
4. Deploy the secure-files Lambda's new version/alias, staff API routes, and
   workspace website. The provisioning code intentionally sets
   `VAULT_DIRECT_UPLOAD_ENABLED=false`. Verify the staff upload endpoint returns
   `VAULT_UPLOAD_NOT_READY` while disabled.
5. Only after the live CDN test passes, set
   `VAULT_DIRECT_UPLOAD_ENABLED=true` in the **new published Lambda version**
   and point the `live` alias to it. Updating `$LATEST` alone is insufficient.
   Make sure later deploys do not silently reset this gate before the intended
   rollout decision.
6. Smoke-test one harmless staff Vault upload and confirmation. Confirm S3 key,
   owner binding, `SecureFilesTable` visibility, staff preview, one payment
   initiation, invoice, and paid customer download. Never send a real payment
   message or charge as part of an infrastructure smoke test.

Existing Vault records retain their original `s3Key`; this change does not copy,
rename, move, delete or re-charge them. The legacy `publish-document` server
route stays for older records but is **not used** for new Vault workspace uploads.

## Launch status

Code changes in a draft PR are **not deployed**. The S3 folder currently contains
only a zero-byte marker. Uploads must remain disabled until the edge restriction is
deployed and independently verified.
