# WhatsApp Vault chooser retirement — issue #2133

**State:** source change awaiting independent review and immutable Lambda release.
The product is staff-issued, owner-bound exact-file Vault access through
`https://wecare.digital/vault/?file=<fileId>`. This change intentionally does
**not** deploy, send a customer message, alter templates, touch invoice/payment
records, change prices, or update AWS aliases during code review.

## Inbound entry-point audit

| Signed inbound event | Before | After |
| --- | --- | --- |
| Vault-only catalog `order` item | `catalogService.start` → chooser | `retiredVault` → generic audited notice |
| `vault`, `my vault`, `/vault` keyword | `catalogService.start` → chooser | `retiredVault` → same notice |
| Cached `vaultpick:<token>:<index>` list reply | `catalogService.select` → file lookup / checkout | `retiredVault`; never parses file index |
| Tokenless `Unlock Vault` button | `catalogService.start` → chooser | `retiredVault` |
| Generic `wd_vault` menu leaf | Bare `/vault/` site link | `retiredVault`; no invalid bare link |
| Signed existing `vaultoffer:<token>` quick reply | `catalogService.unlock` | Preserved with customer + file checks; invalid/revoked takes generic one-shot refusal |
| Drop Docs keyword, menu leaf, catalog order | Native F003 `catalogService.start` | Unchanged |
| Staff exact-file `sendPayment` / existing order updates | Staff Review & Pay and already-issued obligations | Unchanged |

The backend independently refuses `catalogService.start` with Vault lines and
all legacy `select` calls, even if an old inbound worker still forwards them.
No `owner-created-index` Vault chooser query or chooser pagination remains.
The exact-file authenticated customer page was addressed separately in #2138
and is not modified here.

## Sender and safety contract

A signed inbound WAMID hashes to a unique `VAULTRETIREDNOTICE#` CommerceKeys
audit row. A conditional `PutItem` stores `SENDING` and a stable outbound
idempotency key **before** the single service-window reply. The final state,
real provider message ID (if any), and safe status detail are recorded:

- `ACCEPTED`: sender 2xx and a real Meta message ID; handset delivery not proved.
- `REJECTED`: explicit 4xx or dry-run refusal; no successful send claimed.
- `UNKNOWN`: timeout, 5xx, 2xx without message ID, or failed audit update;
  requires manual reconciliation, never an automatic retry.

No response discloses a file name, file ID, owner identity, access state, renewal
offer, or the former Submit Request fallback. A revoked historical offer cannot
create a new payment. The existing owner-bound payment route for a valid,
already-issued offer is deliberately retained.

## Review and targeted checks (no production sends)

From a **clean checkout of the reviewed commit**:

```sh
python -m unittest discover -s tests -p 'test_vault_retirement_2133.py'
python scripts/deploy_all_lambdas.py --dry-run wecare-whatsapp-business-api wecare-inbound-whatsapp
```

Review the diff for the two Lambda sources, the standalone one-shot audit helper,
the removed chooser paginator and the tests. Validate business-api packaging
includes `flows/vault_retirement.py`, and inbound packaging still includes its
modules and shared libraries. Full existing test suite, staging/safe readback and
operator approval are additional gates. A passing source test is **not** evidence
of customer delivery or a live deployed version.

## Immutable production release (only after approval)

Record each function's current `live` alias version, alias revision, code
SHA256, reviewed Git SHA and rollback version. Avoid concurrent AWS deployments.
Use the repository's conditional deploy/publish path, not direct `$LATEST`
uploads or a mutable alias pointed at unreviewed code.

1. Release **`wecare-whatsapp-business-api` first**, publishing an immutable
   version and promoting its `live` alias. Its backend refusal is compatible
   with the old inbound worker and blocks existing chooser requests immediately:
   `python scripts/deploy_all_lambdas.py wecare-whatsapp-business-api`.
2. Verify `wecare-whatsapp-business-api:live` points to that exact reviewed
   artifact, the shared rollout flag is unchanged, and approved payment/download
   templates and Drop Docs readiness are unchanged.
3. Release the narrowed inbound routing as its **own immutable version**:
   `python scripts/deploy_inbound_whatsapp.py --apply`. The script performs
   guarded upload and `live` alias publication.
4. Record the new immutable versions, alias revisions and CodeSha256 values.
   Read-only checks must confirm there is no `catalogService.select` dispatch or
   chooser list send in the packaged version. Verify on a deliberately authorized
   test contact before any live-message assertion; do not generate a real checkout
   as a smoke test.
5. If an invariant fails, revert both aliases to their recorded prior immutable
   versions using revision-guarded alias updates, investigate before retrying, and
   reconcile `UNKNOWN` notice sends without resending.

**Do not** modify Meta templates, business pricing, existing capture/refund
state, Vault entitlement history, Drop Docs service routes or AWS flags as part
of this release.
