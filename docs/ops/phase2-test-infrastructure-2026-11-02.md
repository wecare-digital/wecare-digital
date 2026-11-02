# Phase 2 test infrastructure (2026-11-02)

This note records the additive test safety net stood up in Phase 2 and how to run it. It is additive only: no runtime behaviour, no Lambda packaging, and no deploy config was changed.

## What was added

### JavaScript (Node built-in test runner)

- New tests around `src/api/client.ts`:
  - `apiCallResult` failure and retry classification: which HTTP/network outcomes are treated as retryable versus terminal, and how the result envelope is shaped.
  - The pure normalizers (`normalizeTimestamp`, `normalizeEpochSeconds`, `normalizeCheckoutAddress`): input shaping and edge cases with no external dependencies.
- Run by `npm test` alongside the existing JS tests.

### Python (pytest, new harness)

A pytest suite under `tests/python` covering the highest-risk shared `lambda_utils`:

- Payment and pricing:
  - `money` (integer-paise `Money`, `positive_paise`, `from_decimal_string`).
  - `catalog_pricing` (`build_price_summary`, `supply_tax_paise`, `coupon_discount_paise`, `price_cart`, `authoritative_total_paise`).
  - `checkout_pricing` (`round_half_up`, `split_gst` and its CGST/SGST reconciliation, `validate_buyer_gstin`).
- Auth:
  - `customer_auth` (`bearer_token`, `is_cognito_subject`, `customer_id_from_attributes`).
- WhatsApp:
  - `template_validation` (`validate_body`, `validate_buttons`, `validate_template`, `first_error`).

## Coverage targets and why

The targets were chosen to form a regression safety net, not to chase a coverage percentage:

- `src/api/client.ts` is slated for decomposition in Phase 3. Pinning down `apiCallResult` classification and the pure normalizers protects the behaviour most likely to shift during that refactor.
- The Python money, auth, and template contracts are the highest-risk pure logic in the shared layer: integer-paise math and GST split reconciliation, Cognito subject and bearer-token validation, and WhatsApp template rules. These have documented behavioural contracts and are ideal regression anchors.

### Explicitly deferred

- Full wrapper coverage of `src/api/client.ts` (roughly 300 API wrappers). Only the refactor-sensitive core and the pure normalizers are covered now.
- Lambda handler entrypoints that need boto3/DynamoDB mocks. The suite targets pure shared utils instead.
- The second npm root under `amplify/`. It is intentionally not installed and not exercised here; the two npm roots stay separate.

## How to run locally

### One-time Python dev/test setup (DEV-ONLY)

```sh
python3 -m venv .venv && .venv/bin/python -m pip install boto3 pytest
```

The `.venv` is gitignored. `boto3` mirrors the SDK the python3.12 Lambda runtime provides and is required because importing any `lambda_utils.*` triggers the package `__init__`, which eagerly imports middleware and rate-limit modules that need boto3. This venv and boto3 are development-only: they do not change the Lambda runtime and are not added to `requirements-dev.txt`.

### JavaScript suite

```sh
npm test
```

### Python suite

```sh
PYTHONPATH=amplify/functions/shared .venv/bin/python -m pytest tests/python -q
```

`amplify/functions/shared` on `PYTHONPATH` lets the tests import utils as `lambda_utils.<pkg>.<mod>`.

## Test idioms

- client.ts (JS): extract-and-run-in-vm. A single function body is lifted from the source text and evaluated in a `node:vm` with injected dependencies (`apiCall`, `API_BASE`, `fetch`, retry config). This avoids the module's heavy top-level imports. Pure normalizers are extracted and run with no injected deps.
- Python: direct import with a sys.path shim. `tests/python/conftest.py` puts `amplify/functions/shared` on `sys.path`, so each test imports the shared util directly and asserts against its documented contract.

## CI

`.github/workflows/ci.yml` runs both suites in the single `verify` job: Node setup plus `npm ci`, then Python setup (actions/setup-python@v5, 3.12) plus `python -m pip install boto3 pytest`, then typecheck, lint, `npm test`, `python -m pytest tests/python -q` (with `PYTHONPATH` scoped to that step), and finally the production data safety guard. The amplify/ npm root is not installed in CI.
