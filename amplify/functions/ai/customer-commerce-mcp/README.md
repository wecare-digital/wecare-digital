# wecare-customer-commerce-mcp

Customer commerce MCP and OAuth protocol service behind `POST /mcp` on HTTP API
`mtx59syrt6`.

## Ownership boundary

- **Website presentation:** `src/pages/auth.tsx`, wrapped by the shared public shell.
- **Auth protocol/state:** `customer_oauth.py`.
- **MCP tools:** `handler.py`.
- **Phone validation data:** `connection_assets.py`; `prepare_release.py` fails if
  it differs from the canonical `src/lib/dialCodes.ts` list.

The Lambda does **not** render the `/auth` page, header, menu, cart, hero, footer,
Stay connected block, language/support widget, or any other website HTML.

## Public routes

The backend exposes only:

- `POST /mcp`
- `GET /.well-known/oauth-protected-resource`
- `GET /.well-known/oauth-authorization-server`
- `GET /oauth/authorize` — validates a cached authorization request and redirects
  to `https://wecare.digital/auth`
- `POST /oauth/authorize` — one-step compatibility for already-open legacy forms
- `POST /oauth/token`
- `POST /oauth/revoke`
- `GET /auth/state`
- `POST /auth/step`

`GET /auth` and `POST /auth` are intentionally absent. The website is the only
presentation owner.

## Security contract

The service retains:

- exact registered HTTPS redirect matching;
- OAuth authorization code flow with PKCE S256;
- resource-bound scopes and opaque one-use access/refresh records;
- KMS-encrypted Cognito custody;
- Cognito `GetUser` verification before customer authority is accepted;
- strict website return-path allowlisting;
- CSRF binding and exact-origin checks;
- non-cacheable, anti-framing and noindex responses;
- no OTP, Cognito token or credential in MCP arguments, results or logs.

## Verification and release

```bash
python3 tools/customer-commerce/verify.py
python3 tools/customer-commerce/verify_oauth.py
python3 tools/customer-commerce/prepare_release.py --output /tmp/customer-commerce-release
python3 tools/customer-commerce/verify_release.py /tmp/customer-commerce-release/customer-commerce-runtime.zip
```

`prepare_release.py` compiles the exact reviewed modules, verifies the dial-code
contract, writes a deterministic modular zip, and emits:

- `customer-commerce-runtime.zip`
- `customer-commerce-stack.json`
- `release-manifest.json`

The generated template references the content-addressed runtime zip in S3,
publishes an immutable Lambda version and moves alias `live`; production never
invokes `$LATEST`.

For every deployment:

1. merge the reviewed source;
2. run the four commands above;
3. create a CloudFormation change set using the generated template and the
   stack's existing parameter values;
4. use a new `DeploymentRevision`;
5. execute the change set;
6. verify alias `live`, exact API routes, OAuth metadata, `/auth/state`,
   `/auth/step`, and the website `/auth` page;
7. run `generate_release_manifest.py` to join the Git commit, Lambda version,
   API route hash and Amplify job in one release record.

Production configuration is recorded in `config/lambda-env-manifest.json`.
