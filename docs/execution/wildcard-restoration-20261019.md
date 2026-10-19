# Wildcard home fallback with hostname exclusions

On 19 October 2026 the owner requested removal of two hostnames, then explicitly
requested wildcard forwarding again. This is the current source policy. It
supersedes the earlier [wildcard retirement](wildcard-retirement-20261019.md) while
preserving that deletion's evidence and all unrelated cleanup.

## Routing and ownership

`amplify/infra/home-fallback.json` owns a CloudFront function, its distribution and
one atomic Route53 RecordSetGroup. The group adds six records to the 23 retained
service/validation records, for a 29-record topology:

| DNS name | Stack-owned records | Intended behavior |
| --- | --- | --- |
| `*.wecare.digital` | A + AAAA aliases to the new distribution | Allowed unmatched hosts redirect to the canonical home. |
| `xout.wecare.digital` | A + AAAA aliases to the same distribution | Explicit fallback, preserving this name beneath the nested exclusion. |
| `www.wecare.digital` | TXT only: `"retired-host"`, TTL 300 | No address or CNAME; excluded from wildcard routing. |
| `www.xout.wecare.digital` | TXT only: `"retired-host"`, TTL 300 | No address or CNAME; excluded from wildcard routing. |

Explicit DNS nodes suppress wildcard synthesis at their names. The nested TXT
record also creates an existing `xout` ancestor, so `xout` needs its own address
aliases. Other descendants beneath `xout` no longer inherit the apex wildcard;
only the first-level `xout` alias is restored. This follows the closest-encloser
rules in [RFC 4592 §§2.2.2 and 3.3.1](https://www.rfc-editor.org/rfc/rfc4592.html).
No `*.xout` record or nested wildcard certificate is introduced. DNS wildcards
and certificate coverage differ: an ACM wildcard certificate covers one
subdomain level, as explained in [the Route53 domain-name guide](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/DomainNameFormat.html).

The function returns HTTP 302 to the fixed `https://wecare.digital/` destination
for allowed hosts, discarding their path and query and setting `Cache-Control:
no-store`. It normalizes host case, a numeric port suffix and a trailing dot.
If either excluded name reaches the function, it returns HTTP 404 with no
`Location` header. This is a defense beyond the TXT-only DNS exclusions, not a
promise of working TLS for the nested name. The distribution retains its HTTP
to HTTPS protocol policy.

There is no active `stack.wecare.digital` website or explicit DNS/app alias in
this restoration. That name appears in historical retirement records; any later
request to it is only an unconfigured-host wildcard test, not an inventory entry
for a provisioned website. The current probe uses `release-check-unknown` as its
synthetic unmatched name. No `stack` DNS record or CloudFront alias is created.

## Preserve shared resources and other services

Supply the existing public `HostedZoneId`, the shared us-east-1 `CertificateArn`
and `ExistingLogBucketDomain` as stack parameters. The template creates neither
an ACM certificate nor an S3 bucket, so those existing resources remain outside
its deletion scope. Preserve the logging bucket's existing ACLs and 30-day
expiration policy. Preserve the 23 service records, including the apex, mail,
MTA-STS, SIP and certificate validation. No Amplify rule, API route, `/get`,
`/r`, `/mcp`, application authorization or provider configuration changes here.

The deleted distribution `E1ZZ786I3YH65O` and hostname
`d27evp2npt2kzr.cloudfront.net` are historical only. Restore the topology using
the new stack output, never by replaying those targets.

## Validation and recovery

1. Save a fresh Route53 inventory and inspect the shared certificate and logging
   bucket. Confirm the six stack-owned names are absent before initial creation,
   or verify their existing CloudFormation ownership before an update.
2. Validate the template and review a CloudFormation change set. The four
   `Distribution.DomainName` references enforce creation of the DNS group only
   after the distribution is available; DNS aliases and TXT exclusions are part
   of the same group.
3. Deploy through CloudFormation. `scripts/home_fallback_dns.py` is a pure
   desired-state/validation helper; it makes no AWS call and emits no mutation
   batch. `validate_existing(new_distribution_domain, saved_records)` rejects
   conflicting managed records and reports missing records without modifying
   the inventory. A matching DNS record does not by itself establish stack ownership.
4. Read back the stack, distribution, LIVE function and complete Route53 zone.
   Confirm six expected records, exactly 23 unchanged baseline records, no
   address/CNAME for either excluded name, and unchanged shared-resource settings.
5. Check authoritative DNS separately from public HTTP. Allowed representative
   single-label hosts should redirect to the apex; the two exclusions should
   have no address. An HTTP probe's status 0 means no HTTP response, not proof of
   NXDOMAIN. A proxy's HTTP 503 remains a response and must not be counted as 0.
   Confirm canonical pages, APIs, media and MTA-STS independently.

The active account-migration export intentionally contains only the 23 retained
records. Do not add the six stack-owned records to that manual replay input.
The [migration runbook](../migrations/account-migration-plan.md) recreates them
through this template after the target account's certificate and logging bucket
exist. Tests check template/helper parity, unrelated-record preservation,
conflict rejection and the function's fixed destination/exact exclusions.

Rollback of this restoration removes this stack and its six owned records. It
does not delete the shared certificate, retained logs or the 23 baseline records.
Rediscover current resources and review the deletion plan before rollback.

## Evidence status

The source defines the intended restoration and automated synthetic checks.
Deployment completion and public behavior require the separate AWS and HTTP
readbacks; an infrastructure template or passing unit test alone does not prove
the live configuration.
