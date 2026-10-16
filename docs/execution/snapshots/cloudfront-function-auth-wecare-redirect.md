# Deleted CloudFront Function — `auth-wecare-redirect`

Snapshot taken 2026-09-25, immediately before `cloudfront delete-function`.
This file is the rollback artifact: it holds everything needed to recreate the
function exactly.

## Why it was deleted

| Property | Measured value |
|---|---|
| Name | `auth-wecare-redirect` |
| ARN | `arn:aws:cloudfront::775261844268:function/auth-wecare-redirect` |
| Runtime | `cloudfront-js-2.0` |
| Created | 2026-02-11T05:16:28.179000+00:00 |
| Last modified | 2026-02-11T05:16:28.209000+00:00 |
| Stage | `DEVELOPMENT` only |
| `LIVE` stage | **absent** — `DescribeFunction --stage LIVE` returned `NoSuchFunctionExists` |
| Status | `UNPUBLISHED` |
| ETag at delete | `ETVPDKIKX0DER` |
| Distribution associations | **0** |

Association was proven by enumerating **every** cache behaviour of **every**
distribution in the account (2 distributions, default behaviour only on each) and
collecting all `FunctionAssociations`. The result was an empty list: there are zero
CloudFront Function associations anywhere in account `775261844268`. So the function
had never been wired to traffic, and deleting it cannot change any response.

Two further reasons it was wrong to keep:

1. **It 301s unconditionally.** The handler ignores `event.request` entirely — every
   request on any path would have been redirected to the same fixed URL. Attaching it
   to the `app.wecare.digital` distribution would have taken that host's static assets
   offline.
2. **The target double-hops.** It points at `https://wecare.digital/selfcare`, and
   `wecare.digital` itself 301s to the apex (Amplify custom rule). So a viewer
   would pay two redirects. Worse, measured 2026-09-25: `wecare.digital/selfcare`
   does not exist, so the chain terminated in a 404.

## Recreate

```bash
aws cloudfront create-function \
  --name auth-wecare-redirect \
  --function-config '{"Comment":"","Runtime":"cloudfront-js-2.0"}' \
  --function-code fileb://auth-wecare-redirect.js
```

## Body, verbatim (CRLF line endings in the original)

```javascript
function handler(event) {
  return {
    statusCode: 301,
    statusDescription: 'Moved Permanently',
    headers: {
      'location': { value: 'https://wecare.digital/selfcare' },
      'cache-control': { value: 'max-age=3600' }
    }
  };
}
```
