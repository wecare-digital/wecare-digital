# WhatsApp Flow opening-path performance: 2026-11-01

## Scope and baseline
Customer-initiated WhatsApp Flows F001 Subscribe, F002 Leave Review and F008 Referral use published, approved assets and signed Meta data-exchange callbacks. This change is source-only; it does **not** edit a published Meta Flow, switch a template's button type, send messages, modify an AWS alias, or change authentication.

Read-only AWS CloudWatch Logs Insights correlation of the **six observed INIT callbacks** in the preceding 72 hours, matching the flow_response_full event to the same Lambda REPORT request ID:

| First screen | Observed Lambda durations (ms) | Count |
| --- | --- | --- |
| F001 PROFILE (dynamic prefill) | 201.65, 214.90, 194.56, 327.17 | 4 |
| F002 FEEDBACK (static) | 125.59 | 1 |
| F008 REFER (static) | 152.55 | 1 |

This is a very small sample of Lambda **invocation duration** only, not Meta/network/handset first-paint latency, and does not establish any improvement. Actual cold-start initialization adds overhead. The function was `python3.12`, 256 MB, x86_64 with `live` alias v412 on 2026-11-01; provisioned concurrency was not configured.

## Source changes
1. **Lazy Flow routing imports.** `flows/router.py` no longer loads unrelated handlers (paid services, appointments, documents, generic, etc.) before ping, F002/F008 static INIT, or F001 INIT. Each branch imports its module on first actual use. This affects cold starts, not security checks.
2. **One F001 INIT metrics write.** The `init_received` and the final `init_success` / `init_rejected` / `init_failed` counters now share one atomic `UpdateItem` (previously two serial writes). `FlowLogTable` row schema, both per-stage counters and both structured funnel log lines remain. An INIT that crashes before producing an outcome no longer increments `init_received`; CloudWatch REPORT failures remain the signal in that case.
3. **Timing inside existing response event.** `flow_response_full` now includes `decryptMs` and `routeMs` for the signed DATA_EXCHANGE callback. Values are computed from `time.perf_counter`, rounded to 0.01 ms. No raw phone, token, user data or new log event is added.

All customers still require the server-issued F001 session and its authoritative ContactsTable read; F002/F008 signed `nfm_reply` completion and consent rules remain intact. No async post-return writes, relaxed identity validation, response caching, automatic retry or payment changes.

## Review and release validation
- Review diff against `AGENTS.md` and `docs/operations/repository-validation.md`; do not restore retired offline suites or CI.
- Compile the changed Python files, package only `wecare-whatsapp-business-api` with its shared `lambda_utils` closure, run dry-run packaging/manifest verification.
- Exercise a safe, isolated local mock of `flow_funnel.record_stages`: one UpdateItem increments two named ADD attributes, keeps the original TTL and daily ID, returns false on failure, logs both stages.
- For F001 on a consenting QA handset: valid session prefill (including revision), expired/mismatched token rejected, successful REVIEW persistence, no premature COMPLETE, and exactly one received and one outcome counter per verified INIT.
- For F002/F008: approved template, delivery/INIT then signed `nfm_reply`, submission idempotency and referral consent. Invalid Meta signature must still fail closed. Confirm the FlowLogTable journey entry still exists.
- Compare new `decryptMs` / `routeMs` and Lambda REPORT per-request results against baseline **and measure handset flow-button tap to first visible screen**, including warm and cold paths. Do not claim speed improvement until QA.
- Separately benchmark 512 MB memory or provisioned concurrency before any paid AWS configuration change. The shared WhatsApp API serves many routes; avoid blanket unreviewed scaling.
- Meta `NAVIGATE` is a separate approved-template change for static F002/F008; never silently change the existing `DATA_EXCHANGE` buttons or omit F001 prefill/verification.

Deployment requires independently reviewed immutable Lambda version and `live` alias verification; merging source alone is not production deployment.
