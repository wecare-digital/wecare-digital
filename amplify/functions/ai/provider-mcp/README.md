# provider-mcp

Source of the two read-only provider MCP Lambdas, `wecare-sinch-provider-mcp` and
`wecare-plivo-provider-mcp`. Both run this one `index.py` (handler `index.handler`,
python3.14). The `PROVIDER` environment value (`sinch` or `plivo`) selects the tools.

`index.py` was copied byte for byte from the deployed artifact on 28 Nov 2026. Both functions
then had CodeSha256 `o4muEZyKTCSGvIosS5/xfl0XBEAsVPv9DqTLjxE9ojs=`, a zip holding only
`index.py` (sha256 `554e5813779f8325dfaf0df10c14b79fc50b2ddf2ec66783f839be343761d1d6`).
Change the code here first, then deploy it, so this file stays the deployed code.

## Deployment

- `scripts/deploy_all_lambdas.py` does not deploy these functions.
- Both run on `$LATEST`, with no published version and no `live` alias, so an
  `update-function-code` is live at once.
- `ANY /mcp` on the HTTP APIs `wecare-sinch-mcp` and `wecare-plivo-mcp` invokes them. The OAuth
  routes on the same APIs invoke `wecare-workspace-mcp:live`.
  `amplify/infra/workspace-mcp.json` points every route on those APIs, `/mcp` included, at
  `wecare-workspace-mcp:live`, so the live `/mcp` integrations differ from the template.
- Environment keys: `PROVIDER`; `SECRET_ID`, the Secrets Manager id the provider credentials are
  read from at call time; `API_BASE`, the API origin used for the token audience and the OAuth
  challenge; `CHAT_CLIENT_ID`, the staff-pool app client whose tokens are accepted. The code
  holds no credentials.

## Behaviour

- A request needs a staff-pool access token. Issuer, `client_id`, `aud` (`API_BASE` + `/mcp`),
  `token_use`, scope and `exp` are checked before Cognito `GetUser`. The Cognito subject must
  then match the token and the user must be in the `Admin` group.
- Tools are read-only: Plivo `connection_verify`, `get_cdr`, `get_mdr`; Sinch
  `connection_verify`, `get_application`.

## Compare the deployed code with this file

    url=$(aws lambda get-function --function-name wecare-plivo-provider-mcp --query Code.Location --output text)
    curl -s -o /tmp/provider-mcp.zip "$url" && unzip -p /tmp/provider-mcp.zip index.py | shasum -a 256
    shasum -a 256 amplify/functions/ai/provider-mcp/index.py

Tests: `tests/python/test_core_provider_mcp.py`.
