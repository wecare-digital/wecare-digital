# Meta catalog workspace retirement and IAM hardening — 2026-11-02

## Workspace change

The retired Meta Commerce tab and operator controls have been removed from the rendered staff product catalog. Normal product saves no longer submit the retired `metaEnabled` publication flag. The native product list, variant prices, website publishing, checkout and WhatsApp messages remain in place.

**Important:** Other Meta-specific helpers, bulk migration routines, and API clients remain in the source tree but are no longer reachable from the rendered catalog navigation. They must be removed in a separate tested source refactor; simply deleting them would risk the legacy product-promotion workflows.

## AWS root account

On 2026-11-02 the live IAM account summary showed MFA enabled. `ListAccessKeys` returned one **Inactive** root key; it was deleted after verifying it was the only listed key, and a follow-up `ListAccessKeys` returned zero keys. No active key was changed.

The AWS connector `sts:GetCallerIdentity` still returned the account root ARN. That value **does not prove** which underlying credential or delegated authorization path the connector uses. Validate the installed connector setup and ensure production deployments use IAM Identity Center or scoped OIDC roles, not root credentials.

## Shared execution role

`wecare-digital-lambda-role` is used by 54 functions and currently has 16 inline policies and six managed policies. A prior read-only review found wildcard resource statements across social messaging, language/voice, CloudWatch metrics and other service actions. Some AWS actions cannot be resource-scoped. **No role policies were removed or expanded.**

Before least-privilege rollout:
1. Group the 54 Lambdas by payments/auth, WhatsApp, commerce, content and support.
2. Identify SDK calls from each domain's source; use `uvx iam-policy-autopilot@latest generate-policies` with the repository's actual source paths and documented CLI arguments. Compare with CloudTrail Access Analyzer evidence.
3. Create separate roles with required scoped resources and trust policy, then canary-deploy one low-risk function, verify aliases and logs, and expand only after tests.
4. Keep the existing role as rollback until every function has moved safely.

## Acceptance

- Confirm native product editing and checkout work independently of Meta catalog sync.
- Verify the Meta catalog UI tab cannot be reopened and the backend Meta-sync Lambda remains throttled with reserved concurrency zero.
- Confirm TypeScript and release guard CI success, then merge only the tested workspace change.
- Continue the dedicated backend Meta source and endpoint retirement when consumers are proven absent.
