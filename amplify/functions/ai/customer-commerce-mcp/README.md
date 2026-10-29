# wecare-customer-commerce-mcp

Customer commerce MCP and OAuth protocol service behind `POST /mcp` on HTTP API
`mtx59syrt6`.

## Ownership boundary

- **Website presentation:** `src/pages/auth.tsx`, wrapped by the shared public shell.
- **Auth protocol and state:** the `customer_oauth_*.py` modules.
- **MCP tools:** `handler.py`.
- **Phone validation data:** `connection_assets.py`; release validation compares it
  with `src/lib/dialCodes.ts`.
- **Post-sign-in destinations:** `src/lib/safeReturnPath.ts` and
  `customer_oauth_config.py`; release validation requires the two allowlists and
  every configured service path to agree exactly.

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
- strict same-site return-path allowlisting;
- isolation between website and host OAuth pending sessions;
- CSRF binding and exact-origin checks;
- non-cacheable, anti-framing and noindex responses;
- no OTP, Cognito token or credential in MCP arguments, results or logs.

## Verification and release

Run the complete source and packaged-runtime suite with:

```bash
python3 tools/customer-commerce/validate_pipeline.py \
  --output /tmp/customer-commerce-release \
  --report /tmp/customer-commerce-validation.json
```

The runner executes the conversation checks, OAuth/OTP checks, website/OAuth
session-isolation checks, deterministic release build, and exact packaged-runtime
checks. `prepare_release.py` also rejects backend presentation code, dial-code
drift, return-path drift, and unallowlisted service paths.

A successful build emits:

- `customer-commerce-runtime.zip`
- `customer-commerce-stack.json`
- `release-manifest.json`

Amplify stages these verified, content-addressed files under the private, encrypted,
versioned CDK assets bucket. Staging does not update CloudFormation or move the
`live` alias.

For every production deployment:

1. merge the reviewed source after the branch Amplify build passes;
2. start and verify the production Amplify release;
3. inspect a CloudFormation change set built from the staged template and the
   stack's existing production parameters;
4. require the change set to contain only intended function/version/alias and
   route changes;
5. execute it with a new `DeploymentRevision`;
6. verify alias `live`, the exact nine API routes, OAuth metadata, `/auth/state`,
   `/auth/step`, and the shared website `/auth` page;
7. run `scripts/generate_release_manifest.py` to join the Git commit, Lambda
   version, route hash and Amplify job in one release record.

Production configuration fingerprints are recorded in
`config/lambda-env-manifest.json`.
