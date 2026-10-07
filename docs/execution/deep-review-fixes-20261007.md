# Deep review fixes and cost follow-up — 2026-10-07

Work is on codex/deep-review-20261007, preserving the shared stack checkout.
Includes the already reviewed CI baseline cleanup from PR242 (cherry-picked,
not a new main-branch write).

## Source fixes

- Flow completion: keep the legacy short ID for ordinary retries. On a conditional
  failure, consistently read the winner. If its recorded full completionKey differs,
  claim a deterministic full-digest fallback ID. Never overwrite the winner. Preserve
  explicit postpay IDs and fail closed when the winner cannot be read. Legacy rows
  lacking a full key retain their existing dedupe behavior; they are not migrated.
- Derived SEO audits: validate blog existence and fetch page content before the guard.
  Replace permanent mutation claims only for these audit paths with 30-minute fenced
  leases, keyed by actor, page identity and content hash. Release in finally on success
  and failure. Expired leases can be replaced without waiting for DynamoDB TTL deletion.
  A stale worker cannot delete the next worker's claim. Durable financial/admin mutation
  claims retain their original behavior. The source freshness cache remains responsible
  for avoiding repeat model cost; force deliberately invokes the model again.
- Partner caches: tokens and tenant phone mappings refresh after five minutes using a
  monotonic clock. Expired tokens are removed before refetch; removed tenant mappings
  disappear after a successful refresh. Current concrete token consumer is partner
  onboarding; other inbound/outbound consumers described in the helper's docstring are
  not currently wired to it.
- Webhook registry maintenance writes compact JSON into a Standard String SSM parameter,
  enforces the 4096-byte limit, and does not read IAM credentials by default. The old
  owner-only key-consistency operation now requires --verify-aws-keys explicitly.
- braces advisory reporting covers BOTH root and Amplify lockfiles, not only alert61's
  manifest. Root braces3.0.3 is dev-only; Amplify's copy is in its backend tooling tree.
  No fixed upstream release exists in GHSA-vfj7-8cjw-p6xm at this review. Keep the alert
  open; do not call the watch script a vulnerability remediation. --check-upstream exits
  nonzero when GitHub publishes a first patched version. CI prints the offline report.

## Validation

Full Python suite after the baseline CI cleanup: 8363 passed, 6 skipped, 3 xfailed.
Two subsequent additional failure/SSM tests and the final fail-closed initialization
adjustment: 201 focused tests passed, including 80 workspace MCP tests. Syntax and
git diff whitespace checks passed. No frontend application source changed.
Live IAM inspection confirms the SEO role already permits DynamoDB DeleteItem on the
dedup table; no privilege expansion is needed for fenced lease release. Its Lambda
timeout is 120 seconds, below the 1800-second audit lease.

## Production MCP release prepared, not executed

Existing live workspace MCP version10: last modified 2026-10-06T13:43:12Z.
Built the backend already merged in PR241 with exact pinned dependencies and
reproducible ZIP timestamps. ZIP size 16585604 bytes, SHA256
d59e7e6ddd8a687783cefcee38fe8848abc4a22e46e06d3d063b534ae881e7b3.
Uploaded through AWS Core's scoped presigned upload tool; HeadObject verifies size.
The existing CloudFormation template references code parameters only in Function,
Version and Alias. Proposed update uses the previous template and preserves every
other parameter. Previous CodeKey ends in
3e210dcb0d7eb118eb208419e11d02b8734d925a581c5c0d3b9e0033d0899bae.zip;
rollback is previous parameters/version10. No new change set has been created for
this MCP update because automatic approval review rejected the combined request.

## Registry migration prepared, not executed

All 74 Lambda environment maps and repository application sources have no reference
to wecare/config/webhook-registry; the maintenance writer is the sole repository
consumer. External/manual consumers cannot be disproved by a repository search.
The required asm-exec resolver failed to resolve the source. Do not bypass by calling
GetSecretValue directly. AWS-native dynamic references offer a payload-preserving
alternative, recorded in amplify/infra/webhook-registry-migration.json.

Validated and created a change set copy-noncredential-registry in
wecare-registry-migration-20261007. DescribeChangeSet is CREATE_COMPLETE/AVAILABLE
and contains exactly one Add of AWS::SSM::Parameter. It has NOT executed. No new
SSM parameter exists yet, and no additional secret deletion was scheduled.

After explicit approval: execute the reviewed change set; read the resulting
noncredential staging parameter within the AWS script (return no payload); validate
allowed config fields; compact JSON; require <=4096 UTF-8 bytes; put and read back
/wecare/config/webhook-registry as Standard String; compare parsed payload/checksum.
Then schedule the old config secret with a 30-day recovery window and remove the
temporary migration stack/parameter. Intelligent-Tiering might briefly use Advanced
if the old indented payload exceeds 4096 bytes; remove staging so this does not become
a recurring charge. If any validation/readback fails, retain the old secret and stop.
The final storage saving is $0.40/month only after the old secret is marked for deletion.

## Approval limitation

Automatic approval review rejected executing the registry change set and creating
the production MCP update change set. It stated the user had authorized investigation
and code resolution, but not these exact live changes. No alternate execution was
attempted. Obtain explicit approval for this concrete migration and deployment plan.
New source fixes are offered through the feature PR; merging and deploying them are
separate from deploying the already merged PR241 backend.
