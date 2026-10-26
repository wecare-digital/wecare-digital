# wecare-customer-commerce-mcp

The customer commerce MCP server behind the "ChatGPT WECARE Shopping" connector: `POST /mcp`
and the OAuth routes on HTTP API `mtx59syrt6`.

It is deployed by the CloudFormation stack `wecare-customer-commerce-mcp`, not by
`scripts/deploy_all_lambdas.py`. The code is inline in the template (`Function.Code.ZipFile`),
which CloudFormation writes into the package as `index.py`.

- `handler.py` (the MCP tools) and `customer_oauth.py` (the OAuth adapter): the readable source.
  Edit these, not `index.py`.
- `index.py`: generated from those two by `tools/customer-commerce/prepare_release.py`. The
  builder merges them, strips comments and docstrings, compacts whitespace, and fails if the
  result's Python AST differs from the source's. `scripts/check_deployed_source.py` compares the
  live package with this file.
- `template.json`: the stack template as deployed (`DeploymentRevision`
  `shopping-chatgpt-20261026-v4`), with Pay on WhatsApp enabled and delegated to the canonical
  `wecare-commerce:live` runtime. Its `ZipFile` is `index.py`.

To change the function:

1. Edit `handler.py` or `customer_oauth.py`. Run `python3 tools/customer-commerce/verify.py`
   (25 conversation checks) and `python3 tools/customer-commerce/verify_oauth.py` (22 OAuth
   checks). Both use stubs only.
2. Run `python3 tools/customer-commerce/prepare_release.py --output <dir>`. It writes `index.py`,
   the compact template `customer-commerce-stack.json`, a runtime zip and a manifest, and refuses
   a template over CloudFormation's 51,200-byte inline limit. Then
   `python3 tools/customer-commerce/verify_release.py <dir>/index.py` runs the same 47 checks on
   the generated file.
3. Copy `<dir>/index.py` here. Write the template to `template.json` as
   `json.dumps(template, indent=2, ensure_ascii=False) + "\n"`, with the new `DeploymentRevision`
   as its default.
4. Update the stack with that `DeploymentRevision` and the stack's other current parameter values.
   CloudFormation publishes a new version only when the `Version` description (source hash and
   `DeploymentRevision`) changes. Otherwise it updates `$LATEST` and `live` keeps the old version.

The builder derives `SOURCE_SHA256` and the `Version` description from the hash of the generated
code, and defaults `DeploymentRevision` to the first 16 characters of that hash. On 2026-10-26
(v4) the generated template equalled `template.json` except for that default.

On 2026-10-26 the compact template was 51,151 bytes (`template.json` is pretty-printed, 59,141
bytes). That leaves 49 bytes for growth before the template no longer fits inline.

The live environment is recorded in `config/lambda-env-manifest.json`.

History: `template.json` and `index.py` were imported from the live stack on 2026-10-26. The
readable source, the builder and its checks came the same day from Codex commit `4914d67`, which
was never pushed. Rebuilt unchanged, that source reproduced the live v3 `index.py` byte for byte.
With the three `wecare-commerce:live` call targets of `d96c8fe1c` it reproduces v4.

## Payment handoff

The connector never captures money inside ChatGPT. Its write tool is the guarded `request_whatsapp_payment` handoff: after authenticated customer confirmation it invokes `wecare-commerce:live` with the canonical checkout action, sends the payment request to the customer's verified WhatsApp identity, and returns a payment-attempt identifier. Only provider-verified Razorpay capture may create/finalize the paid order and invoice. The post-payment path guarantees the same customer receipt PNG used by website and WhatsApp commerce.
