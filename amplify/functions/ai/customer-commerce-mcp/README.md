# wecare-customer-commerce-mcp

The customer commerce MCP server behind the "ChatGPT WECARE Shopping" connector: `POST /mcp`
and the OAuth routes on HTTP API `mtx59syrt6`. Customers sign in on `connect.wecare.digital`.

It is deployed by the CloudFormation stack `wecare-customer-commerce-mcp`, not by
`scripts/deploy_all_lambdas.py`. The code is inline in the template (`Function.Code.ZipFile`),
which CloudFormation writes into the package as `index.py`.

- `handler.py` (the MCP tools), `customer_oauth.py` (the OAuth adapter and sign-in page) and
  `connection_assets.py` (loads the WECARE logo from `tools/customer-commerce/assets/logo.svg`
  and the country codes from `src/lib/dialCodes.ts`): the readable source. Edit these, not
  `index.py`.
- `index.py`: generated from them by `tools/customer-commerce/prepare_release.py`. The builder
  merges the two modules, writes the logo and country list in as constants, strips comments and
  docstrings, compacts whitespace, and fails if the result's Python AST differs from the source's.
  `scripts/check_deployed_source.py` compares the live package with this file.
- `template.json`: the stack template as deployed for v9 (`DeploymentRevision`
  `shopping-brand-redirect-20261026-v9`). Its `ZipFile` is `index.py`.

The template defaults are off: no approved products, no OAuth clients, no registration, no
WhatsApp payment requests and no `ConnectOrigin`. Production sets its own values on the stack
(on 2026-10-26: payment requests and registration on, `ConnectOrigin`
`https://connect.wecare.digital`). With `ConnectOrigin` set, the template also creates the API
Gateway domain `connect.wecare.digital`, its API mapping and the Route 53 alias record.
Discovery then sends authorization there; the issuer, token endpoint and MCP audience stay on
the `execute-api` origin.

To change the function:

1. Edit the readable source. Run `python3 tools/customer-commerce/verify.py` (25 conversation
   checks) and `python3 tools/customer-commerce/verify_oauth.py` (28 OAuth checks). Both use
   stubs only.
2. Run `python3 tools/customer-commerce/prepare_release.py --output <dir>`. It writes `index.py`,
   the compact template `customer-commerce-stack.json`, a runtime zip and a release manifest. Then
   `python3 tools/customer-commerce/verify_release.py <dir>/index.py` runs the same 53 checks on
   the generated file.
3. Copy `<dir>/index.py` here, and write the template to `template.json` as
   `json.dumps(template, indent=2, ensure_ascii=False) + "\n"`.
4. Update the stack through a change set, with a new `DeploymentRevision` and the stack's other
   current parameter values. CloudFormation publishes a new version only when the `Version`
   description (source hash and `DeploymentRevision`) changes. Otherwise it updates `$LATEST`
   and `live` keeps the old version.

The compact template is over CloudFormation's 51,200-byte limit for a template sent in the
request (v9: 60,745 bytes; `template.json` is pretty-printed, 69,443 bytes), and the release
manifest says so in `templateRequiresS3`. Upload it to the private CDK assets bucket as
`s3://cdk-hnb659fds-assets-775261844268-us-east-1/customer-commerce/<sourceSha256>/stack.json`,
where v9's template is, and pass that object as the change set's template URL.

The builder derives `SOURCE_SHA256`, the `Version` description and the `DeploymentRevision`
default from the hash of the generated code. For v9 the generated template equals the deployed
one exactly.

The live environment is recorded in `config/lambda-env-manifest.json`.

History: `template.json` and `index.py` were imported from the live stack on 2026-10-26. The
readable source, the builder and its checks came the same day from Codex commit `4914d67`, which
was never pushed. Rebuilt unchanged, that source reproduced the live v3 `index.py` byte for byte.
v4 added the three `wecare-commerce:live` call targets (`d96c8fe1c`). v6 to v9 were deployed from
that Codex branch before they reached this repository: `b895b11` (sign-in page referrer),
`230dabf` (OAuth `ui_locales`) and `f7215b0` (branded sign-in on `connect.wecare.digital`), which
is v9.

## Payment handoff

The connector never captures money inside ChatGPT. Its write tool is the guarded `request_whatsapp_payment` handoff: after authenticated customer confirmation it invokes `wecare-commerce:live` with the canonical checkout action, sends the payment request to the customer's verified WhatsApp identity, and returns a payment-attempt identifier. Only provider-verified Razorpay capture may create/finalize the paid order and invoice. The post-payment path guarantees the same customer receipt PNG used by website and WhatsApp commerce.
