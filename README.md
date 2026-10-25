# WECARE.DIGITAL Admin Platform

Multi-channel messaging platform for WhatsApp, SMS, RCS, Email, and Voice communications.
Commerce and the blog run natively on AWS; voice uses Plivo and AWS, SMS uses AWS End User
Messaging, and RCS uses Sinch.

Website: [https://wecare.digital](https://wecare.digital).

## Quick Start

```bash
npm ci
npm run dev
```

## AWS Resources

- **Region**: us-east-1
- **Account**: 775261844268
- **Cognito User Pool**: us-east-1_cSx0RHCIR
- **App Client**: 1j8kbi48m4v2rped3n224rlevb

### S3 Bucket
Single bucket: **`wecare-digital-get`** (versioning **Enabled**; noncurrent versions
expire after 90 days).

> `wecare-digital-get` is an S3 bucket name, not a hostname. Use it for S3 API calls
> and use `wecare.digital/get` for browser-facing media URLs. Compose keys from the
> constants in `lambda_utils/media_paths.py` (Python, canonical) or `src/lib/media-paths.ts`
> (browser) rather than hand-building them.

Layout (verified live 2026-10-25):

```text
s3://wecare-digital-get/
├── secure/
│   ├── u/                              # INPUT / uploads (edge-gated)
│   │   ├── dropdocs/
│   │   └── service-requests/
│   └── d/                              # DELIVERABLES / generated output
│       └── public/                     # served publicly, see below
│           ├── Invoice/{customer_invoice,fonts}/
│           ├── receipts/
│           ├── whatsapp/
│           │   ├── incoming/ outgoing/ voice/ transcriptions/ downloads/
│           │   ├── calling-ai/ whatsapp-calling/ resumable/ template-headers/
│           │   └── wa-tpl/{img,docs,vid,aud,stk}/
│           ├── blog/{audits,categories,editorial,remediation}/
│           └── catalog-deploy/
│               ├── catalog/            # products/ masters + manifest, contact sheet, QA
│               ├── catalog-media/
│               ├── catalog-relocation/
│               └── catalog-always-available/
└── o/                                  # STATIC/CDN assets
    ├── stream/media/{m,ivr,reports,docs}/
    └── error.html, healthcheck.txt
```

Served as `https://wecare.digital/get/<key>` via CloudFront `E2GP22R4BIFGQ3`
(origin path `""`, so the root segment is part of the URL). Exposure is decided by
the `wecare-get-miss-redirect` Lambda@Edge, by prefix:

- `secure/d/public/**` is served **without authentication**. That includes invoices,
  receipts and WhatsApp media: they are unlisted, not access-controlled.
- Every other `secure/**` key (`secure/u/**`, any `secure/d/` key outside `public/`)
  is redirected at the edge and reachable only via a presigned URL.
- Everything else, including `o/**`, is public. `o/` is a **location, not a permission**.

Never move a key between subtrees to "make it work": that is a disclosure in one
direction and a broken link in the other. A Meta-approved template keeps fetching the
exact media URL it was approved with, so never move or rename an object that one names.


### DynamoDB Tables
- `stack-wecare-digital-ContactsTable`
- `stack-wecare-digital-WhatsAppInboundTable`
- `stack-wecare-digital-WhatsAppOutboundTable`
- `stack-wecare-digital-BulkJobsTable`
- `stack-wecare-digital-VoiceCalls`

### WhatsApp Phone Numbers (Direct API)
| Name | Phone | Configured Meta phone-number ID |
|------|-------|-----|
| WECARE.DIGITAL | +91 93309 94400 | 1016149501586345 |
| Manish Agarwal | +91 99033 00044 | 1055232054343117 |

### WhatsApp Business Accounts (WABA)
| Name | Configured Meta WABA ID |
|------|---------|
| WECARE.DIGITAL | 2094615664435155 |
| Manish Agarwal | 2513394156072604 |

These are the Meta IDs used by the current Direct API configuration in
[the WhatsApp backend](amplify/functions/messaging/whatsapp-business-api/handler.py) and
[calling workspace](src/components/workspace/whatsapp/calling.tsx). The AWS-linked identifiers
previously listed here are historical: AWS End User Messaging Social returned zero linked
WABAs in account `775261844268`, region `us-east-1`, on 19 October 2026. That readback concerns
AWS linkage; the Direct API account configuration is documented separately.

Current app connection settings are in
[the workspace connection configuration](config/workspace-mcp.json). The
[webhook audit](docs/webhook-consolidation-audit.md) records the primary WhatsApp app's
purpose and distinguishes the separate Business Agent app. The five paid services and
their catalogue variant ids are defined in [the service catalogue configuration](src/config/services.ts).

See [repository layout and maintenance boundaries](docs/execution/repository-layout.md) for the active web/backend install roots, operational scripts, generated outputs and retained history.

## Project Structure

```
├── amplify/           # AWS Amplify backend
│   ├── auth/          # Cognito configuration
│   ├── data/          # DynamoDB schema
│   ├── functions/     # Lambda functions (Python)
│   └── storage/       # S3 configuration
├── src/
│   ├── api/           # API client
│   ├── components/    # React components (Header, Footer, Layout, etc.)
│   ├── pages/         # Next.js pages
│   └── styles/        # CSS styles
├── docs/              # Documentation
├── shared/            # Shared config (FAQ)
└── scripts/           # Deploy & sync scripts
```

## Lambda Functions

All Lambda functions use Python 3.12 runtime with prefix `wecare-*`:
- `wecare-contacts-*` - Contact CRUD operations
- `wecare-messages-*` - Message read/delete
- `wecare-inbound-whatsapp` - Webhook handler
- `wecare-outbound-whatsapp` - Send messages
- `wecare-bulk-*` - Bulk messaging
- `wecare-ai-*` - AI/Bedrock integration

## Documentation

- [FAQ System](docs/FAQ-SYSTEM.md)
- [OpenAPI Spec](docs/openapi.yaml)
- [Wildcard fallback and hostname exclusions](docs/execution/wildcard-restoration-20261019.md)

## Admin Scripts

- `scripts/deploy_all_lambdas.py` - Deploy all 60 zip-packaged Lambda functions.
  Cross-platform, validates every top-level import against the function's live
  layers, checks the configured handler symbol exists, then publishes a version
  and moves the `live` alias. That last step matters: 53 of 62 functions are
  invoked through their `live` alias, so `update-function-code` alone does not
  reach production. `--dry-run` builds and validates without uploading,
  `--list` prints the function map.
- `scripts/deploy_seo_tools.py` - Deploys `wecare-seo-tools` (different in-zip
  layout; also owns its DynamoDB table and IAM policy).
- `scripts/snapstart_publish.py` - Publish a version + move the `live` alias
  on its own, e.g. after deploying a function by hand.
- `scripts/sync_faq.py` - Sync FAQ config to Python + TypeScript
- `scripts/make_demo_video.mjs` - Generate a demo `.mp4` UI walkthrough from a
  JSON scene spec (headless Chrome + ffmpeg). Run via `npm run demo-video -- <spec.json>`.
  Used for the Meta App Review walkthroughs in `s3://wecare-digital-get/o/app-review/`.
  See `scripts/make_demo_video.README.md` for the spec format, the S3 publish
  command, and the honesty note (rendered walkthrough, not a live-session capture).

The PowerShell and CMD deploy scripts were **deleted on 2026-09-20**. They could
not run on this platform at all (`\`-separated paths), they wrote zip entries with
`\` separators, and the deploy-all variant copied `flows\*.py` only, dropping the
`flows/*.json` flow definitions that `wecare-whatsapp-business-api` serves. Keeping
a broken deploy path in the tree is how someone runs it by mistake.
`scripts/deploy_all_lambdas.py` is the only deploy-all entrypoint; its docstring
records what those scripts got wrong. They remain in history if ever needed:

```sh
git log --diff-filter=D --format=%h -1 -- scripts/deploy_all.ps1   # the deleting commit
git show <that-sha>~1:scripts/deploy_all.ps1
```
