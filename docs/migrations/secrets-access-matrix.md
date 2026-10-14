# Secrets access matrix

Region us-east-1 · 22 active secrets · 13 scheduled for deletion (NOT counted as
future savings — AWS stopped billing them when deletion was scheduled).
No secret VALUES were read to build this. Last-access + KMS are live metadata
(2026-10-14). Consumer mapping is derived from `config/lambda-env-manifest.json`
and code references, not from reading values.

KMS: a `None` KMS id means the AWS-managed key `aws/secretsmanager` (no CMK
charge). Four secrets use a customer CMK (`9b5b8734-…`): `bing/api`,
`google/ads`, `google/cloud`, `plivo/api`.

Rotation: `None` (RotationEnabled) on every secret → no managed rotation
configured anywhere today.

| Secret | Security domain | Last access | KMS | Candidate action | Rationale |
|---|---|---|---|---|---|
| `wecare/razorpay/api` | payments | 2026-10-14 | managed | KEEP_ISOLATED | payment acquiring creds; never group |
| `wecare/razorpay-webhook` | payments | 2026-10-10 | managed | KEEP_ISOLATED | webhook signature secret; isolate |
| `wecare/meta/payments` | payments | 2026-10-06 | managed | KEEP_ISOLATED | Meta payments config |
| `wecare/meta-system-user-token` | integrations/meta | 2026-10-14 | managed | KEEP_ISOLATED | Graph token+app_secret; appsecret_proof |
| `wecare/flow-private-key` | security | 2026-10-08 | managed | KEEP_ISOLATED | RSA key for Flow decryption |
| `wecare/otp/pepper` | security | 2026-10-06 | managed | KEEP_ISOLATED | OTP hashing pepper |
| `wecare/backup/recovery-passphrase` | security | 2026-10-06 | managed | KEEP_ISOLATED | DR passphrase |
| `wecare/aws/iam-access-keys` | security | 2026-10-06 | managed | NEEDS_OWNER_REVIEW | prefer runtime IAM roles over stored long-lived keys |
| `wecare/github-pat` | security | 2026-10-13 | managed | NEEDS_OWNER_REVIEW | flagged exposed/over-privileged — see secrets-consolidation.md §PAT |
| `wecare/plivo/api` | communications | 2026-10-13 | CMK | KEEP_ISOLATED | voice provider |
| `wecare/plivo-answer` | communications | 2026-10-06 | managed | KEEP_ISOLATED | answer-url token |
| `wecare/sinch/rcs` | communications | 2026-10-14 | managed | KEEP_ISOLATED | India RCS |
| `wecare/truecaller` | communications | 2026-10-06 | managed | KEEP_ISOLATED | auth callback |
| `wecare/agent-connector-token` | integrations | 2026-10-06 | managed | NEEDS_OWNER_REVIEW | identify consumer before action |
| `wecare/seo/google-oauth` | seo | 2026-10-07 | managed | KEEP_ISOLATED | OAuth client (reused by comms plan) |
| `wecare/google/ads` | integrations | 2026-10-07 | CMK | KEEP_ISOLATED | blocked on developer_token (comms plan) |
| `wecare/google/cloud` | integrations | 2026-10-12 | CMK | KEEP_ISOLATED | GCP SA |
| `wecare/bing/api` | seo | 2026-10-06 | CMK | NEEDS_OWNER_REVIEW | confirm active consumer |
| `wecare/config/webhook-registry` | integrations | 2026-10-06 | managed | MOVE_TO_PARAMETER_STORE (non-secret parts only) | split: non-secret config → SSM Standard; keep any secret field in SM |
| `wecare/wix/headless-api-key` | integrations/wix | 2026-10-14 | managed | RETIRE_AFTER_CUTOVER | blog+store admin key; live until Workstream A acceptance |
| `wecare/wix/catalog-webhook` | integrations/wix | 2026-10-13 | managed | RETIRE_AFTER_CUTOVER | webhook verify key |
| `wecare/wix/app-oauth` | integrations/wix | 2026-10-06 | managed | ROTATE + RETIRE_AFTER_CUTOVER | **exposed 2026-10-02** per secret description |

## Wix-secret consumers & IAM (for Phase 7)

Roles to inspect (task B7): `wecare-checkout-role`,
`wecare-meta-catalog-sync-role`, `wecare-wix-catalog-webhook-role`,
`wecare-digital-lambda-role`. Known grant: GetSecretValue on
`wecare/wix/headless-api-key`. Remove via IaC only after Phase-6 cutover proves
no app needs it. Never touch the shared role's non-Wix grants; never
delete/disable the shared execution role.

## Consolidation stance (B4)

- **No mega-secret.** One access helper + naming standard only.
- Group only within a security domain where every consuming role needs every
  field AND rotation lifecycles match. On this inventory, no two secrets meet
  that bar strongly enough to justify grouping over the ~$0.40/mo each — security
  isolation wins over marginal savings.
- Parameter Store Standard (free) only for confirmed NON-secret config (the
  non-secret portion of `wecare/config/webhook-registry`, provider IDs). Never
  move an actual secret to plaintext SSM.
- Net: the honest directly-controllable secret saving is retiring the **3 Wix
  secrets** (~$1.20/mo, POTENTIAL until deletion windows close) plus a small SSM
  move. See `aws-cost-optimization.md`.
