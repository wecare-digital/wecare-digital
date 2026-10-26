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

Imported from the live stack on 2026-10-26. Until then this source was on no branch.
