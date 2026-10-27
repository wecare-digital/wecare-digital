# wecare-customer-commerce-mcp

The customer commerce MCP server behind the "ChatGPT WECARE Shopping" connector: `POST /mcp`
and the OAuth routes on HTTP API `mtx59syrt6`. Customers sign in on `https://wecare.digital/auth`,
which the Amplify Hosting custom rules `/auth` and `/auth/` rewrite (status 200) to
`https://mtx59syrt6.execute-api.us-east-1.amazonaws.com/auth`. Those rules live in the Amplify
app, not in this repository.

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
- `template.json`: the stack template as deployed for v12 (`DeploymentRevision`
  `main-site-auth-stable-routes-20261027-v12`, source hash `3b99b7ce…`). Its `ZipFile` is
  `index.py`.

The template defaults are off: no approved products, no OAuth clients, no registration, no
WhatsApp payment requests and no `AuthOrigin`. Production sets its own values on the stack
(on 2026-10-27: payment requests and registration on, `AuthOrigin` `https://wecare.digital`).
With `AuthOrigin` set, discovery sends authorization to `https://wecare.digital/auth`, and a GET
on the legacy `/oauth/authorize` path (from a host that cached older discovery) redirects there
before any session exists. The issuer, token endpoint and MCP audience stay on the
`execute-api` origin. There is no sign-in subdomain: v12 removed the `connect.wecare.digital`
API domain, API mapping and Route 53 alias that v9 created.

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
request (v12: 63,658 bytes), and the release manifest says so in `templateRequiresS3`. Upload it
to the private CDK assets bucket as
`s3://cdk-hnb659fds-assets-775261844268-us-east-1/customer-commerce/<sourceSha256>/stack.json`
and pass that object as the change set's template URL.

The builder derives `SOURCE_SHA256`, the `Version` description and the `DeploymentRevision`
default from the hash of the generated code. For v12 the generated `index.py` is byte-identical
to the live package and the generated template equals the deployed one exactly.

The live environment is recorded in `config/lambda-env-manifest.json`.

History: `template.json` and `index.py` were imported from the live stack on 2026-10-26. The
readable source, the builder and its checks came the same day from Codex commit `4914d67`, which
was never pushed. Rebuilt unchanged, that source reproduced the live v3 `index.py` byte for byte.
v4 added the three `wecare-commerce:live` call targets (`d96c8fe1c`). v6 to v9 were deployed from
that Codex branch before they reached this repository: `b895b11` (sign-in page referrer),
`230dabf` (OAuth `ui_locales`) and `f7215b0` (branded sign-in on `connect.wecare.digital`), which
is v9.

v10 to v12 were deployed on 2026-10-27 (04:07 to 04:17 IST) through AWS MCP change sets whose
source was never committed, so for a while production ran code this repository did not have.
It was reconstructed from the live stack the same day: the readable source, the builder and the
logo asset now regenerate live v12 exactly. v12 moved sign-in to the main site (`/auth`, the
`AuthOrigin` parameter, `CUSTOMER_AUTH_ORIGIN`), split custody records over 4,096 bytes into
per-part KMS ciphertexts (`kms2:`), added `X-Robots-Tag: noindex` to every response, logs the
failing sign-in step and exception class (never a number, code or provider message), and
replaced the logo and sign-in page design. `verify_oauth.py` pins the `/auth` behaviour.

## Payment handoff

The connector never captures money inside ChatGPT. Its write tool is the guarded `request_whatsapp_payment` handoff: after authenticated customer confirmation it invokes `wecare-commerce:live` with the canonical checkout action, sends the payment request to the customer's verified WhatsApp identity, and returns a payment-attempt identifier. Only provider-verified Razorpay capture may create/finalize the paid order and invoice. The post-payment path guarantees the same customer receipt PNG used by website and WhatsApp commerce.
