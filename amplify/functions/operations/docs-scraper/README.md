# docs-scraper — external documentation scraper

Fetches external docs (Meta / WhatsApp Business, etc.), renders JS with headless
Chromium, cleans to Markdown, detects changes by content hash, keeps an
append-only changelog, and stores everything in the `wecare-digital-get` bucket
under `o/stream/media/docs/` (served as `https://wecare.digital/get/o/stream/media/docs/`).

## Why a container Lambda
Playwright + Chromium exceeds the 250 MB zip limit, so this function ships as a
**container image** via ECR (unlike the other zip-based Python lambdas).

## S3 layout (bucket: `wecare-digital-get`)
```
o/stream/media/docs/_sources.json               # sources list (frontend-editable)
o/stream/media/docs/_index.json                 # {url: {hash, key, source, lastSeen}} for change detection
o/stream/media/docs/_changelog.jsonl            # append-only change log (1 JSON/line)
o/stream/media/docs/<source>/<page>.md          # cleaned page content
```
The `o/` root is part of the key, not decoration — `DOCS_PREFIX` defaults to
`media_paths.public('stream/docs')`, which resolves to `o/stream/media/docs`. Keys written
one level up (at the bucket root) used to return HTTP 200 from the old apex host, so
getting this wrong fails silently rather than loudly.

## Invocation modes (event payload)
| Purpose | Payload |
|---|---|
| Daily cron / scrape all | `{}` or `{"action":"scrape"}` |
| Re-fetch one source ("upgrade") | `{"action":"scrape","source":"meta-business-agent"}` |
| Add a source from frontend | `{"action":"add_source","name":"meta-business-agent","rootUrl":"https://developers.facebook.com/documentation/meta-business-agent/overview","pathPrefix":"(optional)","contentSelector":"main"}` |

Sub-page discovery follows links sharing the doc-section **URL path prefix**
(auto-derived from `rootUrl`, e.g. `.../documentation/meta-business-agent/`).
Verified against the Meta Business Agent docs: main page + 16 real sub-pages
(get-started, reference/onboard/*, configure/*, operate/*) extract correctly.
This is more robust than a CSS sidebar selector for JS-heavy sites with
obfuscated class names.
| List sources | `{"action":"list_sources"}` |
| Recent changelog | `{"action":"changelog","limit":50}` |

Change detection: each page's cleaned text is SHA-256 hashed and compared to
`_index.json`. Only new/changed pages are re-written and appended to the
changelog, so re-runs are cheap and the changelog shows exactly what moved.

`MAX_PAGES_PER_RUN` (env, default 40) caps breadth per run to stay within the
Lambda timeout; the daily cron picks up the remainder over subsequent runs.

## Deploy (container image)
> Requires a working shell + AWS creds (do this after the window reload).
```powershell
$ACCOUNT=775261844268; $REGION="us-east-1"; $REPO="wecare-docs-scraper"
aws ecr create-repository --repository-name $REPO --region $REGION   # first time only
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
docker build -t $REPO .
docker tag "$REPO`:latest" "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO`:latest"
docker push "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO`:latest"

# Create the Lambda from the image (memory/timeout sized for Chromium)
aws lambda create-function --function-name wecare-docs-scraper `
  --package-type Image `
  --code ImageUri="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO`:latest" `
  --role arn:aws:iam::$ACCOUNT`:role/wecare-digital-lambda-role `
  --timeout 300 --memory-size 2048 --region $REGION
```
IAM: the existing `wecare-digital-lambda-role` already has S3 access to
`wecare-digital-get`; confirm it allows `s3:PutObject`/`GetObject` on
`o/stream/media/docs/*`.

## Daily trigger (EventBridge)
```powershell
aws events put-rule --name wecare-docs-scraper-daily --schedule-expression "rate(1 day)" --region us-east-1
aws lambda add-permission --function-name wecare-docs-scraper --statement-id docs-cron `
  --action lambda:InvokeFunction --principal events.amazonaws.com `
  --source-arn arn:aws:events:us-east-1:775261844268:rule/wecare-docs-scraper-daily
aws events put-targets --rule wecare-docs-scraper-daily `
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:775261844268:function:wecare-docs-scraper"
```

## API + frontend wiring
Add routes to the main HTTP API (`zllr9lrg7j`) pointing at this Lambda:
```
POST /docs/sources     -> {action:add_source}    (feed a new main page link from the UI)
GET  /docs/sources     -> {action:list_sources}
POST /docs/scrape      -> {action:scrape[,source]} (the "upgrade / re-fetch now" button)
GET  /docs/changelog   -> {action:changelog}       (show what changed)
```
Frontend (admin page): a small form to submit a new doc URL (name + rootUrl),
a "Re-fetch now" button per source, and a changelog feed reading `GET /docs/changelog`.

## Optional: vector re-index
An S3 `ObjectCreated` notification on `stream/docs/*.md` can trigger a separate
embedding/indexer Lambda to keep a vector store in sync. Not included here.
