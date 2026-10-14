# AWS cost optimization

All figures from the deterministic model `scripts/aws_cost_model.py` (run
`--live`); none are hand-typed. POTENTIAL ≠ REALISED. Baselines to inspect are
listed per area; where a number needs Cost Explorer it is marked INSPECT (a
Cost Explorer API call is itself billable at $0.01/call, so run it deliberately).

## Verified recurring figures (us-east-1, 2026-10-14)
- Secrets Manager: 22 active × $0.40 = **$8.80/mo** storage; request ≈ **$2.50/mo**
  at an assumed 500k calls (confirm real call volume via CloudWatch). 13
  scheduled-for-deletion secrets already stopped billing — NOT a future saving.
- Lightsail: `micro_3_0` = **$7.00/mo**; `nano_3_0` = $5.00/mo (live `get-bundles`).
- KMS: 4 secrets on a customer CMK (`9b5b…`); 18 on the AWS-managed key (free).

## Scenario model (from the script, `outputs/aws-cost-model.json`)
| scenario | label | secrets $/mo | lightsail $/mo | total $/mo | Δ vs base |
|---|---|---|---|---|---|
| baseline | BASELINE | 11.30 | 7.00 | 18.30 | 0.00 |
| after Wix secret removal | POTENTIAL | 10.10 | 7.00 | 17.10 | −1.20 |
| after safe consolidation | POTENTIAL | 9.30 | 7.00 | 16.30 | −2.00 |
| after Lightsail nano | POTENTIAL | 9.30 | 5.00 | 14.30 | −4.00 |
| after Lightsail retire | POTENTIAL | 9.30 | 0.00 | 9.30 | −9.00 |

Every Δ is POTENTIAL. None is realised cash until the deletion window closes /
the micro stops being billed. The nano Δ also carries a temporary +$5/mo dual-run
overlap during migration.

## Area baseline table (what to inspect)
| Area | Baseline to inspect | Note |
|---|---|---|
| Wix subscription | INSPECT (provider billing, off-AWS) | The real prize — but only after full Workstream A + owner cancels. Not an AWS line item. |
| Amplify | Hosting + build minutes (INSPECT Cost Explorer) | A known Sept driver. Avoid unnecessary rebuilds (A7); the 6-hourly Wix catalogue-sync triggers prod builds today. |
| DynamoDB | PAY_PER_REQUEST, low | New `BlogPostsTable`/`ProductsTable`/`CartTable` add marginal on-demand cost. |
| Lambda | invoke + duration, low | 77 functions; pay-per-invoke. |
| API Gateway | request cost, low | Preserve routes until new consumers verified. |
| S3 | 7 buckets; storage/requests/backups | Blog media/content move adds storage; add lifecycle rules. |
| Secrets Manager | $8.80 storage + request (verified) | See scenarios above. |
| Parameter Store | Standard tier = $0 | Target for non-secret config only. |
| Lightsail | micro $7 vs nano $5 (verified) | See feasibility doc; feasibility INCOMPLETE (no host access). |
| Support plan | Business Support+ (INSPECT) | Known Sept driver; a support-tier decision is an owner call, not in scope here. |
| Cost Explorer | $0.01/call (INSPECT) | Was itself a Sept driver — query sparingly, cache results. |
| Payment processing | Razorpay fees (off-AWS) | Preserved; AWS has no card acquiring. |

## Honest trade-off (task requirement)
The directly-controllable AWS recurring saving from these three workstreams is
**small**: ≈$1.20/mo (Wix secrets) + ≈$0.80/mo (SSM move) + up to $2/mo
(Lightsail nano, potential) ≈ **$4/mo**, with Lightsail retirement (a separate
approved program) reaching ≈$9/mo. The Wix migration's main financial payoff is
cancelling the **Wix subscription** (off-AWS) and removing the Amplify rebuild
churn the catalogue-sync causes — both larger than the AWS line items but both
behind the full migration. The engineering effort to exit 203 runtime Wix
references across ~40 files is substantial; it is justified primarily by
*independence, security, and the Wix subscription*, not by the sub-$10/mo AWS
delta. Do not spend large migration effort chasing the AWS-side pennies alone.

## Payback
One-time cost is engineering time (export + native stores + commerce cutover) plus
a brief Lightsail dual-run overlap. Against ~$4–9/mo AWS savings, the AWS-only
payback is long; the real payback is the Wix subscription saving + reduced build
minutes, which must be measured post-cutover with `--live` and Cost Explorer.
