# Wildcard fallback retirement

On 19 October 2026 the owner confirmed that wildcard forwarding is unused and
authorized live testing and cleanup. The desired state is no `*.wecare.digital`
DNS alias and no home-fallback CloudFront distribution or redirect function.
Older inventory and cutover documents remain historical snapshots; they are not
instructions to restore the wildcard.

## Verified boundary before retirement

The AWS readback at `2026-10-19T00:15:33Z` still found wildcard A and AAAA aliases
in hosted zone `Z03939753QJGZ6ZD6BXO8`, pointing to
`d27evp2npt2kzr.cloudfront.net`. Distribution `E1ZZ786I3YH65O` was enabled and
deployed. Its CloudFormation management path is stack `wecare-home-fallback` in
`us-east-1`, with exactly these three resources:

| Logical resource | Resource | Retirement boundary |
| --- | --- | --- |
| `Distribution` | CloudFront `E1ZZ786I3YH65O` | Remove with the retired stack after wildcard DNS is removed. |
| `RedirectFunction` | CloudFront function `wecare-home-fallback` | Remove with the retired distribution. |
| `LogBucket` | S3 `wecare-home-fallback-logbucket-zl8wltb0on7s` | Retain. The template has both `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`. |

The stack does not own a certificate or any Route53 record. Certificate
`f75d0db0-d476-443a-b787-96c4931862d2` is shared by the apex Amplify site and the
MTA-STS distribution `E1SZBXLQ4XNLJ7`. **Keep that certificate and its validation
DNS.** Keep the apex, `/api`, `/get`, `/r`, `/mcp`, MTA-STS and SIP services.

## Live completion

At `2026-10-19T00:22:04Z`, the retirement readback confirmed the Route53 change
was `INSYNC`, stack `wecare-home-fallback` was `DELETE_COMPLETE`, and both
distribution `E1ZZ786I3YH65O` and function `wecare-home-fallback` were absent.
The 23 retained DNS record sets exactly matched the saved baseline after
subtracting only the two wildcard aliases. The shared certificate remains in
use by apex Amplify and MTA-STS. The retained log bucket keeps its existing
30-day expiration policy.

## Repository behavior

The creation template `amplify/infra/home-fallback.json` and obsolete redirect
source `scripts/home-fallback-function.js` have been removed. The retained
`scripts/home_fallback_dns.py` is a pure retirement planner: it makes no AWS calls
and returns only `DELETE` entries for exact wildcard A/AAAA aliases to the known
retired distribution. Empty or already retired inventories return no changes.
Unexpected wildcard addresses, CNAMEs, service records or routing policies stop
the plan for review. Explicit names such as `xout.wecare.digital`, apex/service
records and certificate-validation records are outside its deletion scope.

The planner must receive a freshly saved Route53 inventory. Review its output,
remove only those exact aliases, verify the DNS change, then delete the known
stack with its log-retention policy intact. A repository test cannot establish
that AWS deletion has completed: confirm Route53, CloudFormation and CloudFront
readbacks, then repeat canonical public-page and service checks. The completion
above records the control-plane readback; public-page and service test results
are recorded separately in the cleanup audit.

`tests/test_home_fallback_dns.py` exercises deletion-only behavior, preservation
of explicit services and rejection of unexpected records, and prevents restoring
the retired CloudFront template or edge function.
