# wecare-customer-commerce-mcp

The customer commerce MCP server behind the "ChatGPT WECARE Shopping" connector: `POST /mcp`
and the OAuth routes on HTTP API `mtx59syrt6`.

It is deployed by the CloudFormation stack `wecare-customer-commerce-mcp`, not by
`scripts/deploy_all_lambdas.py`. The code is inline in the template (`Function.Code.ZipFile`),
which CloudFormation writes into the package as `index.py`.

- `template.json`: the stack template as deployed (`DeploymentRevision`
  `shopping-chatgpt-20261025-v3`), read back with `aws cloudformation get-template`.
- `index.py`: the same code as a file. It is byte-identical to the template's `ZipFile` and to
  the live `index.py` (`SOURCE_SHA256` `f52852d9ad279d48...`).

To change the function, edit `index.py`, copy it into `template.json` as `ZipFile`, and update the
stack with its current parameters. `scripts/check_deployed_source.py` compares the live package
with `index.py`. The live environment is recorded in `config/lambda-env-manifest.json`.

`index.py` is generated, not hand-written: comments and docstrings are stripped and whitespace is
compacted so the template fits CloudFormation's inline limit. Its readable source, `handler.py`
and `customer_oauth.py`, plus the builder `tools/customer-commerce/prepare_release.py` and its
tests, are on branch `cleanup/aws-drift-reconciliation-20261025` (commit `4914d67`) in a local
Codex workspace, and that branch has never been pushed. Rebuilding from it reproduces `index.py`
and `template.json` byte for byte (checked 2026-10-26).

CloudFormation rejects an inline template body over 51,200 bytes. `template.json` here is
pretty-printed (59,130 bytes); sent compact (`json.dumps(template, separators=(",", ":"))`) it is
51,140 bytes. That leaves 60 bytes for any code change before the template no longer fits inline.

Imported from the live stack on 2026-10-26. Until then this source was on no branch.
