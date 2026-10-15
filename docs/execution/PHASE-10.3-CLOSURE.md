# Phase 10.3 — production checkpoint and closure report

Generated 2026-09-24. Account `775261844268`, `us-east-1`, branch `stack`, HEAD
`c2214a9e`. Every count below was re-measured against the live account, per the execution
rule in `00-current-owner-overrides.md`: **do not trust dated counts in the master
prompt.** The prompt's own baseline says 332 routes and 2 HTTP APIs; both are stale.

---

## 1. Live state

| | Measured |
|---|---|
| Lambda functions | **62** |
| Functions whose `live` alias serves the same sha as `$LATEST` | **56** |
| Alias behind `$LATEST` (drift) | **0** |
| Functions with no `live` alias (invoke `$LATEST` directly) | **6**, documented |
| HTTP APIs | **1** (`zllr9lrg7j`) |
| HTTP API routes | **353** |
| Routes open at both gateway and handler | **0** |
| Routes explicitly allowlisted public | **5**, each justified |
| DynamoDB tables | 77 |
| WAF web ACLs | **2** (Amplify CLOUDFRONT, Cognito REGIONAL) |
| Cognito MFA | `OPTIONAL`, TOTP + email + SMS enabled |
| npm advisories / open Dependabot alerts | **0 / 0** |
| Log groups with no retention | **0** |
| Amplify build | job **832 SUCCEED** |
| CI workflows on HEAD | **5/5 success** |

The six functions without a `live` alias: `wecare-ad-attribution`, `wecare-docs-scraper`,
`wecare-partner-token-refresh`, `wecare-seo-tools`, `wecare-sla-engine`, and the unused
`wecare-url-shortener` twin. Two of those exclusions are deliberate and named in
`scripts/provision_live_alias.py`: `seo-tools` and `docs-scraper` have deployers that only
run `update-function-code`, so giving either an alias would make every future deploy report
success and never reach production.

## 2. Gates

```
pytest                       3021 passed
vitest                        181 passed
tsc --noEmit                 clean
npm run build                 125 sitemap URLs (109 blog posts)
check_design_drift --gate     OK
check_ui_labels --gate        OK at EVERY severity
check-provider-policy.sh      OK
verify_secret_hook            26/26
block_catastrophic --self-test 97/97
generate_integration_inventory --check  current
```

## 3. Flags — every one still in its safe state

| Flag | State | Note |
|---|---|---|
| `PSTN_BROWSER_ROUTING_ENABLED` | **false** | never enabled; a standing refusal |
| `PSTN_CONNECTED_NOTIFICATIONS_ENABLED` | **absent** | |
| `WA_LIVE_SMOKE_TEST` | **absent** | a lockdown, not a permission — ON narrows sending |
| `SINCH_RCS_ENABLED` | **absent** | |
| 18 agent APPLY tools | **disabled** | refused in `governance.py`; enabling is a refusal |
| `NEXT_PUBLIC_ENABLE_GROWTH_MODULE` | **absent → false** | |
| `NEXT_PUBLIC_ENABLE_COMMERCE_MODULE` | **absent → false** | |
| `ADMIN_MFA_REQUIRED` | **absent → warn** | see §6 |

## 4. Rollback

- **Lambda** — `docs/execution/snapshots/lambda-aliases-before-full-deploy.txt` holds the
  pre-deploy `live` version for all 62. Any one reverts with
  `aws lambda update-alias --function-name <n> --name live --function-version <v>`.
- **Amplify redirects** — `docs/execution/snapshots/amplify-custom-rules-before-8.4.json`
  is the pre-8.4 rule set; restore with `update-app --custom-rules`.
- **WAF** — `aws wafv2 disassociate-web-acl --resource-arn <arn>` removes enforcement
  without deleting the ACL.
- **Frontend** — Amplify keeps every build; redeploy job 831 or earlier.
- **Cognito branding** — `delete-managed-login-branding` returns the custom domain to its
  prior 403 state, which is the state it was in, not a better one.

## 5. Phase result

| Phase | Result |
|---|---|
| 0 safety freeze | ✅ COMPLETE |
| 1 discovery | ✅ COMPLETE |
| 2 Meta ingress | ✅ COMPLETE |
| 3 connected-call domain | ✅ COMPLETE (flags off) |
| 4 CRM / payments | ✅ COMPLETE |
| 5 Plivo PSTN + softphone | ✅ COMPLETE (5.1–5.4) |
| 6 chatbot + governed ops | ✅ COMPLETE (6.1–6.4) |
| 7.1 integration registry | ✅ **COMPLETE** — 88 fixture-driven contract tests; live reads `WAITING_FOR_OWNER`, which the prompt names as a completion state |
| 7.2 Meta Ads / storefront refactor | ✅ **COMPLETE** — domain layer lifted (handler 1,761 → 1,512 lines), equivalence proven over 64 golden cases, 0 differences; that storefront handler has since been retired |
| 7.3 Growth + Commerce homes | ✅ COMPLETE (behind flags, both off) |
| 8.1 eight module homes | ✅ COMPLETE |
| 8.2 productVocabulary + CI | ✅ COMPLETE, now blocking at every severity |
| 8.3 adaptive navigation | ✅ COMPLETE |
| 8.3a inner design contract | ✅ COMPLETE |
| 8.4 legacy redirects | ✅ COMPLETE — 20 rules, all live-verified 301 |
| 9.1 retire old providers | ✅ COMPLETE |
| 9.2 route/dependency/bundle | ✅ COMPLETE |
| 9.3 native packaging | ⏳ `WAITING_FOR_OWNER` — POST-PROJECT by owner override, cannot block closure |
| 10.1 Admin MFA | ✅ COMPLETE (enforcement staged — §6) |
| 10.1b sign-in URLs | ✅ COMPLETE |
| 10.2 WAF | ✅ COMPLETE, enforcement proven by a blocked request |
| 10.3 this report | ✅ COMPLETE |

## 6. Gaps and improvements

### Blocked on the owner — not on engineering

1. **Admin group membership.** `aws cognito-idp admin-add-user-to-group --user-pool-id
   us-east-1_cSx0RHCIR --username wecare.digital --group-name Admin`. Until then 16
   handlers refuse the only user, including the new approve route. I can prove those
   routes exist and refuse anonymous callers; I **cannot** prove they return data for a
   signed-in Admin.
2. ~~**`ADMIN_MFA_REQUIRED` stays at warn** and that is correct, not an oversight.~~
   **Superseded 2026-09-29.** It no longer stays at warn. `ADMIN_MFA_REQUIRED=true` is set
   on all **13** functions that gate anything on an `Admin` role — measured across all 66,
   and matching `config/lambda-env-manifest.json` exactly — so enforcement is live. The
   paragraph is kept struck through rather than deleted because its reasoning was sound at
   the time and the flag's own docstring in `middleware.py` now carries the same correction:
   the lock-out risk the warn default protected against has expired, so an argument for
   staying at warn would today be an argument against a change that already shipped.
   Item (1) is unaffected and still owner-held.
3. **Cognito client `1jrnb80tcvceg7uln9vuoe8va5`** should be deleted; that invalidates the
   app-client secret disclosed earlier in this work.
4. **Provider credential rotation** — the exposed families remain `MANUAL_OWNER_ACTION`.
5. **7 of 8 integration providers at `SCOPE_UNVERIFIED`**, one with no credential. Every
   unblock is listed on `/growth`. No code change will move these.

### Recorded, not fixed

| Gap | Severity | Note |
|---|---|---|
| `origin` still threads through 22 signatures via a module global | MEDIUM | The cross-request leak is fixed (reset in `finally`, 7 tests) and the domain layer is out, but `_response` still reads a global rather than taking an argument. 36 call sites, only 2 with an origin to pass |
| Meta Ads monolith boundaries | LOW | `marketing-ads` is 448 lines with 0 DynamoDB scans, so there is no scan debt. The adapter/domain split there was not needed to close 7.2 and was not done |
| `wecare-customer-whatsapp-auth` in the deploy map, absent from the account | LOW | The customer-pool script was written and never run. One `failed=1` in every deploy-all |
| `wecare-invoice-engine` imports `qrcode`, not in package or layers | LOW | Guarded by try/except, so it degrades rather than crashes |
| `/vayulok` ships one `h1` and no `h2` | LOW | 489 chars of body text. A content gap, not a rendering one |
| 6 routes still invoke `$LATEST` | LOW | Both sets deliberate and named |
| `apiCall` returns `null` on any non-ok response | MEDIUM | An auth failure, a timeout and an empty table render the same screen. Fixed for the inbox; still true elsewhere |
| `AIInteractionsTable` has no writer | LOW | Readers only; the architecture page's claim that `ai-generate-response` writes it is unsupported |
| 10 carried-forward gaps from phases 4c/4d/RCS | MEDIUM | Unchanged; listed in `.kiro/work/phases-5-10/plan.md` |
| Cognito `VdmOptions.EngagementMetrics` still ENABLED | LOW | May still inject a tracking pixel into OTP mail. Unverified |

### Improvements delivered this run

- **P1** — 8.1's lazy split: per-page initial load down **37%** on two hubs, **26%** on a
  third. Measured per page, because total `_next/static` went *up* 6% and reporting that
  alone would have said the change made things worse.
- **P1** — 20 dead URLs became 301s instead of 404s.
- **P1** — WAF enforcing on both surfaces that can carry it.
- **P2** — phone bottom bar and tablet rail; a tablet was getting the phone treatment.
- **P2** — the UI label gate went from advisory to blocking at every severity.
- **P2** — `#111827` retired from 129 inline-style uses, and `design-tokens.ts` stopped
  contradicting the file it claims to mirror.

## 7. Final result

**⚠️ COMPLETE WITH IMPROVEMENTS**

All eleven phases are now closed. The verdict stays `COMPLETE WITH IMPROVEMENTS` rather
than `ALL REQUIRED WORK VERIFIED`, and the reason is narrow and specific: **the single most
useful verification left cannot be performed by me.** Sixteen handlers require the `Admin`
group, the pool's only user is in no group, so I can prove those routes exist and refuse
anonymous callers but not that they return data to a signed-in Admin. One `admin-add-user-to-group`
call closes that.

Also outstanding and owner-held: provider access for 7 `SCOPE_UNVERIFIED` integrations,
credential rotation for the exposed families, and deletion of the disclosed Cognito client.
Those are `WAITING_FOR_OWNER` with exact unblocks, which the master prompt treats as a
completion state — not as engineering hiding behind a label.

Engineering remainders are listed in §6 and none blocks closure: `origin` still reaches
`_response` through a module global (the leak is fixed, the signature change is not), the
Meta Ads adapter split was not needed and was not done, and `_money_amount` does not
validate. Each is recorded with its severity rather than folded into a green tick.
