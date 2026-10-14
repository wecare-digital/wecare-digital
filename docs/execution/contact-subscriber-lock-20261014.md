# Subscriber identity + contact retention: audit and release checklist

## Audit (2026-10-14)

- Contact rows have an internal `id`/`contactId`, sometimes phone- or Cognito-derived.
- The public `customerUuid` is already a distinct UUIDv4 for invoices. It must not be replaced.
- WhatsApp `WD-SUB` references are submission numbers, not stable contact identifiers.
- CRM, inbound/outbound WhatsApp, website profile, blog, AI and subscription flow can all create contacts.
- Existing contacts are not automatically locked. Existing `locked` fields are respected by the Contacts API.
- AI cleanup paths have separate destructive operations and require further authorization hardening.
- Existing API inventory lacks POST /contacts/{contactId}/lock and /unlock.
- Workspace has no tenant registry. `WORKSPACE_ID` is therefore a trusted deployment slug, not a verified multi-tenant security boundary.

## Implemented in this branch

- `subscriberId = WD-<workspaceId>-<random UUIDv4>`; `workspaceId` defaults to `wecare-digital`.
- New contact rows are locked at creation, with reason `created`.
- Contact identity and lock fields are server-controlled; generic updates cannot change them.
- Unlock requires Admin role and the existing Admin MFA enrollment check.
- Contact UI displays subscriber identity, workspace and lock state; locked archive is disabled.
- Provisioning script is dry-run-first; it reuses the existing Contacts API integration.
- Legacy backfill is dry-run-first, conditional, and leaves existing subscriber IDs intact.

## Critical limitations / release gates

1. **Do not merge or deploy without running all Python and frontend tests.** The branch was prepared through GitHub file APIs, without a checked-out build environment.
2. **Audit remaining direct writers and cleanup APIs** before claiming global enforcement. In particular, AI agent data-clear functions and other message/media deletion paths must share the retention gate.
3. **Review historical IDs:** backfill does not rewrite `customerUuid`, `contactId` or `WD-SUB` flow references. A deliberate mapping strategy is needed for historical subscription references.
4. **Workspace isolation:** a static `WORKSPACE_ID` does not implement true tenant isolation. Do not treat it as authorization; a tenant registry and per-request ownership checks are required for multi-workspace support.
5. **Concurrent hard delete:** this branch disables hard deletion with `HARD_DELETE_DISABLED` until a transactional delete lease can protect messages/media from concurrent retention locks. Existing tests expecting hard deletion must be updated intentionally after policy review.
6. **No production backfill by default.** Review the dry-run summary and retention policy with the owner before `--apply`.
7. **Deployment:** create API routes only after backend release is verified; Lambda `live` alias must be advanced deliberately. No production action is performed by this branch.

## Suggested verification

```sh
python -m compileall -q amplify/functions tests scripts
pytest -q tests/test_subscriber_id_lock.py tests/test_crm_api.py tests/test_contact_lock.py tests/test_contact_soft_delete_guard.py tests/test_blog_subscribe_handler.py
npm ci --no-audit --no-fund
npm run build
python scripts/provision_contact_lock_routes.py
python scripts/backfill_contact_subscriber_ids.py
```
