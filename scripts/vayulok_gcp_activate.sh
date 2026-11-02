#!/usr/bin/env bash
# VayuLok Google Cloud activation. Run only from a trusted Google Cloud Shell
# with an authenticated project administrator and a checked-out repository.
# Default is read-only. --apply lowers (never raises) the BigQuery project
# quota to at most 10 GiB/day and deploys the reviewed Cloud Run backend.
# Google Maps quota controls require separate SKU/project verification and are
# intentionally NOT changed by this script.
set -euo pipefail

PROJECT='wecaredigitalbw'
PROJECT_NUMBER='756034744787'
REGION='asia-south1'
SERVICE='wecare-digital'
EXPECTED_URL='https://wecare-digital-hrkl3sncxq-el.a.run.app'
BQ_DAILY_BYTES='10737418240' # 10 GiB/day = 310 GiB in a 31-day month
BQ_QUOTA_ID='QueryUsagePerDay'
BQ_SERVICE='bigquery.googleapis.com'
SOURCE_FILE='gcp/vayulok-weather-insights/server.mjs'
SOURCE_SHA='3014c5fdef052a1e4ad527558aeb60d84fe80183'
BUILD_CONFIG='gcp/vayulok-weather-insights/cloudbuild.yaml'
MODE="${1:---check}"

case "$MODE" in
  --check|--apply) ;;
  *) printf 'Usage: bash %s [--check|--apply]\n' "$0" >&2; exit 2 ;;
esac
for binary in gcloud git python3; do
  command -v "$binary" >/dev/null || { echo "Missing $binary" >&2; exit 3; }
done
[ -f "$SOURCE_FILE" ] && [ -f "$BUILD_CONFIG" ] || {
  echo 'Run this script from the wecare-digital repository root (wecare.digital branch).' >&2
  exit 3
}
actual_source_sha="$(git hash-object "$SOURCE_FILE")"
[ "$actual_source_sha" = "$SOURCE_SHA" ] || {
  echo 'Source does not match approved Cloud Run guard (expected Git blob SHA)' >&2
  echo "Found: $actual_source_sha. Stop; review the latest backend before deploying." >&2
  exit 3
}
commit_sha="$(git rev-parse HEAD)"
[ "$(git branch --show-current)" = 'wecare.digital' ] || {
  echo 'Check out wecare.digital, not a feature branch, before deployment.' >&2
  exit 3
}
actual_project_number="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
[ "$actual_project_number" = "$PROJECT_NUMBER" ] || {
  echo "Project mismatch (expected $PROJECT_NUMBER; found $actual_project_number)." >&2
  exit 3
}
active_account="$(gcloud auth list --filter='status:ACTIVE' --format='value(account)' | head -n 1)"
[ -n "$active_account" ] || { echo 'Please sign in to Google Cloud first.' >&2; exit 3; }

url="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.url)')"
[ "${url%/}" = "$EXPECTED_URL" ] || {
  echo "Wrong Cloud Run service URL (expected $EXPECTED_URL; got $url)." >&2
  exit 3
}
ready_before="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.latestReadyRevisionName)')"
echo "Verified project: $PROJECT ($PROJECT_NUMBER)"
echo "Active identity: $active_account"
echo "Verified Cloud Run: $url, revision $ready_before"
echo "Verified backend source blob: $actual_source_sha"
echo "Selected BigQuery project cap: 10 GiB per day ($BQ_DAILY_BYTES bytes)"

# Cloud Quotas commands are client-based API calls. Always supply the *same*
# explicitly verified billing/quota project, not the Cloud Shell shared ADC project.
# This check must never enable a service during read-only --check.
if ! gcloud services list --enabled --project="$PROJECT" \
  --filter='config.name:cloudquotas.googleapis.com' \
  --format='value(config.name)' | grep -Fxq 'cloudquotas.googleapis.com'; then
  echo "Cloud Quotas API is not enabled in $PROJECT (or its status is unreadable)." >&2
  echo "Fix in Cloud Shell: gcloud services enable cloudquotas.googleapis.com --project=$PROJECT" >&2
  echo "Then rerun: bash scripts/vayulok_gcp_activate.sh --check" >&2
  exit 5
fi

# Validate that this is the project-wide on-demand QUERY usage limit,
# not the user-level quota or an unrelated BigQuery API operation limit.
quota_info="$(gcloud quotas info describe "$BQ_QUOTA_ID" \
  --project="$PROJECT" --service="$BQ_SERVICE" --billing-project="$PROJECT" --format=json)"
printf '%s' "$quota_info" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("quotaId")=="QueryUsagePerDay", d; assert d.get("metric")=="bigquery.googleapis.com/quota/query/usage", d; assert not d.get("dimensions"), d.get("dimensions"); print("Quota identity verified:",d["quotaId"],d["metric"])'

preferences="$(gcloud quotas preferences list --project="$PROJECT" --billing-project="$PROJECT" --format=json)"
pref_details="$(printf '%s' "$preferences" | python3 -c '
import json,sys
rows=json.load(sys.stdin)
assert isinstance(rows,list), "Unexpected Cloud Quotas response"
m=[r for r in rows if r.get("service")=="bigquery.googleapis.com" and r.get("quotaId")=="QueryUsagePerDay" and not r.get("dimensions")]
assert len(m)<=1, "Multiple conflicting project-wide QueryUsagePerDay preferences"
p=m[0] if m else {}
value=p.get("quotaConfig",{}).get("preferredValue", "unconfigured")
print((p["name"].split("/")[-1] if p else "vayulok-bigquery-daily-free-tier")+" "+str(value))
')"
read -r pref_id existing_preferred <<< "$pref_details"
skip_quota_update=0
if [[ "$existing_preferred" =~ ^[0-9]+$ ]] && (( existing_preferred <= BQ_DAILY_BYTES )); then
  skip_quota_update=1
  echo "An existing BigQuery daily preference is stricter or equal ($existing_preferred bytes); it will NOT be raised."
fi

if [ "$MODE" = '--check' ]; then
  echo
  echo 'READ-ONLY CHECK COMPLETE. No quotas or services changed.'
  if [ "$skip_quota_update" = 1 ]; then
    echo "Keep stricter existing BigQuery preference: $pref_id ($existing_preferred bytes/day)"
  else
    echo "Apply BigQuery preference: $pref_id -> at most $BQ_DAILY_BYTES bytes/day"
  fi
  echo "Deploy pinned backend from commit: $commit_sha"
  echo 'For Cloud Run and quota changes, run: bash scripts/vayulok_gcp_activate.sh --apply'
  echo 'Google Maps quotas must be set separately in the actual key-owning project.'
  exit 0
fi

# A deliberate project-wide quota decrease; existing traffic could be stopped
# when the quota is reached. Reuses an existing preference if one is present.
if [ "$skip_quota_update" = 1 ]; then
  echo 'Keeping the existing, more restrictive BigQuery daily preference.'
else
  echo 'Applying the project-wide BigQuery daily query quota...'
  gcloud quotas preferences update "$pref_id" \
    --project="$PROJECT" --service="$BQ_SERVICE" --quota-id="$BQ_QUOTA_ID" \
    --preferred-value="$BQ_DAILY_BYTES" --billing-project="$PROJECT" \
    --allow-missing --allow-high-percentage-quota-decrease \
    --allow-quota-decrease-below-usage --quiet
fi

quota_verify="$(gcloud quotas preferences describe "$pref_id" --project="$PROJECT" --billing-project="$PROJECT" --format=json)"
printf '%s' "$quota_verify" | python3 -c '
import json,sys
s=json.load(sys.stdin)
assert s.get("quotaId")=="QueryUsagePerDay", "Wrong BigQuery quota ID"
p=s.get("quotaConfig",{}).get("preferredValue")
assert p is not None and 0<=int(p)<=10737418240, "Quota preference is not <= 10 GiB"
g=s.get("quotaConfig",{}).get("grantedValue")
print("BigQuery quota preference:",p,"bytes/day; grantedValue:",g,"; reconciling:",s.get("reconciling"))
if s.get("reconciling") or g is None or int(g)>10737418240:
 print("WARNING: 10 GiB effective quota NOT YET VERIFIED. Check grantedValue after propagation.")
'
echo 'Deploying the pinned VayuLok Cloud Run backend through the existing Cloud Build pipeline...'
gcloud builds submit . \
  --config="$BUILD_CONFIG" \
  --substitutions="COMMIT_SHA=$commit_sha" \
  --project="$PROJECT" --region="$REGION" --quiet

url_after="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.url)')"
ready_after="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.latestReadyRevisionName)')"
[ "${url_after%/}" = "$EXPECTED_URL" ] || { echo 'Post-deployment URL changed; investigate.' >&2; exit 4; }
[ -n "$ready_after" ] || { echo 'Cloud Run revision not ready.' >&2; exit 4; }
echo "Cloud Run revision: $ready_before -> $ready_after"

# Do not trigger a paid BigQuery data query. Status introspection only.
if command -v curl >/dev/null; then
  status_file="$(mktemp)"
  trap 'rm -f "$status_file"' EXIT
  if ! curl --fail --silent --show-error --max-time 25 \
       -H 'Origin: https://wecare.digital' \
       "$url_after/v1/weather-insights/status" > "$status_file"; then
    echo 'Cloud Run status not available. Do not claim the new cap is live.' >&2
    exit 4
  fi
  python3 - "$status_file" <<'PY'
import json,sys
with open(sys.argv[1],encoding='utf-8') as f:d=json.load(f)
g=d.get('costGuard',{})
limits=g.get('maxBytesBilledByRange',{})
assert limits and all(0<int(limits[r])<=1073741824 for r in ('30d','1y','5y')), ('Unsafe or absent BigQuery guard',g)
assert 0 <= int(g.get('instanceMaxDailyQueryAttempts',-1)) <= 12, ('Unexpected daily attempt guard',g)
print('VERIFIED: live Cloud Run status advertises <=1 GiB per query and bounded per-instance query attempts')
PY
else
  echo 'curl absent. Verify live /v1/weather-insights/status manually before declaring deployment complete.' >&2
  exit 4
fi

echo
printf 'Cloud Run: %s\nBigQuery quota preference: %s\n' "$ready_after" "$pref_id"
echo 'IMPORTANT: Check quota grantedValue/reconciling, then separately cap Google Maps API SKU requests in its key-owning project.'
