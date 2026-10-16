# Razorpay merchant cleanup and dedicated www DNS removal

Owner instruction on 2026-10-02 explicitly requests removal of the retired merchant identifier and the dedicated www record in Route 53.

- Current merchant: `acc_TTFSyolquKEZEy`. Current tracked files contain zero occurrences of the retired merchant ID. Historical descriptions use a retired-account placeholder, and mismatch tests use a synthetic fixture rather than substituting the real current merchant into old evidence.
- `wecare-whatsapp-business-api:live` moved from version 58 to version 59 with the corrected `RAZORPAY_MID`. The code hash was unchanged; all other environment settings were preserved inside AWS without returning credential values.
- `wecare-partner-onboarding:live` moved from version 24 to version 25. The deployed archive was patched narrowly from the existing live package: API credential lookup now reads only `wecare/razorpay/api`, never `wecare/razorpay-webhook`. Deployment SHA: `3372ec0333e96cdc8ccb0be3a2db60049a65c68d4768e57a059d2ba746face99`.
- Fresh AWS-backed Razorpay `connection_verify` returned `verified`, read-only collection count 1. This establishes that canonical API credentials authenticate; it does not establish their merchant ownership.
- 125 focused tests passed, including canonical credential lookup success and fail-closed behavior without the webhook fallback.
- Route 53 public zone `Z03939753QJGZ6ZD6BXO8`: deleted the exact `wecare.digital.` CNAME to `d2av2go6w170k.cloudfront.net`, TTL 500. Change `/change/C06297751I3QU3K63OS4O` reached `INSYNC`; zero exact www records remain.
- The existing wildcard A/AAAA records remain (Route 53 encodes their names as `\\052.wecare.digital.`). They can still answer www queries. The apex and all public pages are unchanged. No certificates were issued, changed, or deleted.

## Credential deletion remains unverified

Secrets Manager currently has `wecare/razorpay/api` (AWSCURRENT plus AWSPREVIOUS) and the separately used `wecare/razorpay-webhook`. Metadata does not identify either version as the retired account's credential. No secret or version was deleted, no credential value was fetched into context, and no payment capture/refund was attempted. Old-key removal requires an account-to-key mapping or owner-provided replacement through a secure credential-entry path. Do not delete the webhook signing secret merely to reduce the secret count.

## Recovery record

No rollback was performed. Prior Lambda versions remain available under the normal deployment safety policy; restoring them is not part of this task. The saved DNS record is evidence only and must not be recreated without a new owner instruction. Git history and old published artifacts were not rewritten.
