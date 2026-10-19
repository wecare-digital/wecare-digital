# Wildcard fallback retirement

**Historical deletion record — superseded later on 19 October 2026.** The owner
subsequently requested wildcard forwarding again while keeping two hostnames
excluded. Follow [the restoration record](wildcard-restoration-20261019.md) for
current configuration and recovery. The deletion evidence below is retained
unchanged; it does not authorize restoring the deleted distribution or its DNS target.

On 19 October 2026 the owner confirmed that wildcard forwarding is unused and
authorized live testing and cleanup. At that point the requested state was no `*.wecare.digital`
DNS alias and no home-fallback CloudFront distribution or redirect function.

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

## Repository behavior at that point

The retirement change removed the creation template and redirect source and
replaced the DNS helper with a deletion-only planner. The later owner instruction
supersedes that source policy: the current template creates a new distribution,
reuses the retained log bucket and shared certificate, and owns six DNS records
including two exclusions. The current pure helper validates that topology without
calling AWS. Tests now protect these restoration and preservation requirements.

The old distribution `E1ZZ786I3YH65O` and its hostname remain retired. Never replay
their aliases from an old snapshot. See the restoration record for current
validation, CloudFormation ownership and rollback instructions.
