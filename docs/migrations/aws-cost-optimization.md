# AWS cost optimization — measured baseline and levers

Source of every figure: `scripts/aws_cost_model.py` over
[`evidence/cost-explorer-20261014.json`](evidence/cost-explorer-20261014.json) (four read-only
Cost Explorer calls on 2026-10-14, $0.04 total). Labels: MEASURED, REALISED, POTENTIAL,
HISTORICAL.

## Measured (gross usage, credits excluded)

| Month | Gross | Credits | Net billed |
| --- | --- | --- | --- |
| 2026-08 | $61.72 | −$61.73 | $0.00 |
| 2026-09 | $101.30 | −$101.30 | $0.00 |
| 2026-10 (1–14, estimated) | $72.48 | −$72.49 | $0.00 |

October run-rate: **$125.28/month** (Support as billed, usage scaled ×31/14).

**Cash reality:** credits covered 100% of gross usage for three months. Until they run out,
every saving below extends the credit runway; none is a cash saving. The Cost Explorer API does
not expose the credit balance or expiry; read them in the Billing console.

| Service (Sep 2026) | Gross | Driver |
| --- | --- | --- |
| AWS Business Support+ | $29.00 | fixed monthly plan |
| AWS Amplify | $28.59 | 2,581 build minutes ($25.81); October pace 4,628 min ($46/mo) |
| AWS Cost Explorer | $15.07 | API call storm, already fixed (Oct MTD $0.22) |
| AWS Secrets Manager | $7.95 | 19.7 secret-months |
| Amazon Lightsail | $7.03 | `micro_3_0` + 5.3 GB-month snapshot |
| AWS End User Messaging | $4.24 | toll-free number + SMS |
| Amazon CloudWatch | $3.51 | 44.6 alarm-months (73 alarms now) |
| Other | $5.91 | WAF (since removed), KMS, API Gateway, Route 53, S3, DynamoDB, ECR |

## Levers

| Lever | Label | $/month | Decision |
| --- | --- | --- | --- |
| Wix secrets deleted | REALISED | −1.20 | done 2026-10-14 (force-deleted) |
| Support plan Business+ → Basic | POTENTIAL | −29.00 | owner: trade-off is losing Business-tier support |
| Amplify build minutes −50% | POTENTIAL | −23.14 | batch merges to `stack`, skip docs-only builds |
| Amplify egress back to September level | POTENTIAL | −15.61 | investigate 49.1 GB in Oct 1–14 vs 4.6 GB in Sep first |
| Secrets: up to 3 retired/moved | POTENTIAL | −1.20 | owner confirms each in the access matrix |
| Lightsail Micro → Nano | POTENTIAL | −2.00 | cut over 2026-10-15; REALISED when the Micro standby is deleted |
| Lightsail retirement | POTENTIAL | −5.00 | not authorised; needs an approved SIP replacement (now the Nano's $5) |
| CloudWatch alarms (73 → $6.30/mo) | POTENTIAL | 0.00 | review only |
| KMS customer keys (4 → $4/mo) | NOT A LEVER | 0.00 | keep |
| Cost Explorer calls | HISTORICAL | 0.00 | fixed in September; not counted again |

Sum of POTENTIAL levers excluding Lightsail retirement: **−$70.95/month**, 95% of it from
three owner decisions (Support, Amplify builds, Amplify egress) that need no migration work.

## Scenario comparison (monthly, gross)

| Scenario | Change vs October run-rate |
| --- | --- |
| Current production | $125.28 |
| After Wix migration | already included (Wix Lambdas, tables and secrets are deleted; the Wix subscription is outside AWS and must be checked in Wix billing) |
| After safe secret consolidation | −$1.20 POTENTIAL |
| After the Lightsail downsizing | −$2.00, cut over 2026-10-15; both instances bill ($12/mo, hourly) until the Micro is deleted |
| After possible Lightsail retirement | −$5.00 POTENTIAL, not authorised |

Recommendation: spend effort on the Support decision and the Amplify build cadence first.
The Nano move is done (`lightsail-nano-cutover.md`); re-run the model with `--live` after the
Micro is deleted and it reports the $2.00 as REALISED.

## Not visible from AWS

- **Wix subscription:** the owner reports the site deleted; confirm no renewal in Wix billing.
- **Razorpay fees:** per-transaction, billed by Razorpay; no AWS line.
