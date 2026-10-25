#!/usr/bin/env bash
#
# WECARE.DIGITAL - Google SEO / Ads / Analytics / GBP enablement + access audit
#
# Enables the Google APIs this business uses, grants the baseline project roles,
# and then proves - with real authenticated calls - what the automation service
# account can actually see. Enabling an API and having access to the product
# behind it are different things, and this script is built to show the gap
# rather than hide it.
#
# Runs in Cloud Shell. Requires: gcloud, curl, jq, python3 with google-auth.
#
# NEVER creates, rotates or deletes a service-account key. It uses the existing
# uploaded key and asserts the key id matches before doing anything.
#
# Usage:
#   bash scripts/google-marketing-audit.sh
#   KEY_FILE="$HOME/your-existing-key.json" bash scripts/google-marketing-audit.sh
#   DRY_RUN=1 bash scripts/google-marketing-audit.sh      # audit only, no writes
#
# ---------------------------------------------------------------------------
# Changes from the first draft, and why:
#
#  1. ADDED translate.googleapis.com and texttospeech.googleapis.com. These were
#     missing and they are the two that matter most right now: the Cloud Run
#     language relay answers 400 "Translation unavailable" for every request,
#     while speech works. A disabled Translation API is the leading explanation.
#
#  2. FIXED the Business Profile locations call. `accounts/-/locations` is not a
#     supported parent - the Business Information API wants a concrete
#     accounts/{id} - so that request 400s and silently reported nothing. It now
#     iterates the accounts returned by step 6.
#
#  3. CORRECTED the Google Ads guidance. A bare service account cannot be added
#     to a Google Ads account at all: the Ads API needs OAuth as a human, or a
#     service account with Workspace domain-wide delegation impersonating one.
#     "Add the service account under Access and Security" is not a step that
#     exists, so following it would waste time.
#
#  4. CLOSED a token-file race. The original wrote the bearer token and chmod'ed
#     it afterwards, leaving it briefly readable at the default umask. The umask
#     is now set before the file is created.
#
#  5. REMOVED a no-op `trap - EXIT` / re-arm sequence that cleared the cleanup
#     trap and immediately reinstalled it.
#
#  6. Ads API version is now a variable instead of a hard-coded v25, and DRY_RUN
#     was added because this script mutates project IAM.
#
# The wide API list is kept deliberately - broad enablement is the stated intent.
# Note it does pull against scripts/google-cloud-setup.sh, which keeps a minimal
# allow-list on purpose. Enabling an API costs nothing directly, but each one is
# extra surface, so prune anything here that never gets called.
# ---------------------------------------------------------------------------

set -uo pipefail

PROJECT_ID="${PROJECT_ID:-wecaredigitalbw}"
ADMIN="${ADMIN:-wecare.digital.bw@gmail.com}"
SA="${SA:-automation@wecaredigitalbw.iam.gserviceaccount.com}"
EXPECTED_KEY_ID="${EXPECTED_KEY_ID:-d281dbfcf7efd9dad587bc833a30fec9be669a4d}"
ADS_API_VERSION="${ADS_API_VERSION:-v25}"
# Manager (MCC) account, digits only - the API rejects the dashed display form
# 427-041-2231. An identifier, not a credential: it travels in a request header and
# appears in the Ads UI, so it belongs here rather than in Secrets Manager.
ADS_LOGIN_CUSTOMER_ID="${ADS_LOGIN_CUSTOMER_ID:-4270412231}"
DRY_RUN="${DRY_RUN:-0}"

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '      DRY %s\n' "$*"
    return 0
  fi
  "$@"
}

# -- locate the existing key --------------------------------------------------
KEY_FILE="${KEY_FILE:-}"
if [[ -z "$KEY_FILE" ]]; then
  for candidate in \
    "$HOME/wecaredigitalbw-d281dbfcf7ef- automation google.json" \
    "$HOME/wecaredigitalbw-d281dbfcf7ef-automation-google.json" \
    "$HOME/wecare-automation-existing.json"; do
    if [[ -s "$candidate" ]]; then KEY_FILE="$candidate"; break; fi
  done
fi
if [[ -z "$KEY_FILE" ]]; then
  KEY_FILE="$(find "$HOME" -maxdepth 1 -type f -name '*d281dbfcf7ef*.json' -print -quit 2>/dev/null || true)"
fi
if [[ -z "$KEY_FILE" || ! -s "$KEY_FILE" ]]; then
  echo "ERROR: existing uploaded JSON key not found in the Cloud Shell home directory."
  echo "Upload the SAME existing key, then rerun. Or point at it directly:"
  echo "  KEY_FILE=\"\$HOME/your-existing-key.json\" bash \$0"
  exit 2
fi
chmod 600 "$KEY_FILE"

TMP_DIR="$(mktemp -d)"
chmod 700 "$TMP_DIR"
cleanup() {
  if command -v shred >/dev/null 2>&1; then
    find "$TMP_DIR" -type f -exec shred -u {} \; 2>/dev/null || true
  fi
  rm -rf "$TMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Mint a bearer token into a 0600 file. curl reads it with -H @file so the token
# never appears in argv, where `ps` would expose it. umask is set before the
# file is created rather than chmod'ed after, so it is never briefly readable.
make_auth_header() {
  local scope="$1" outfile="$2"
  python3 - "$KEY_FILE" "$scope" "$outfile" <<'PY'
import os, sys
from google.oauth2 import service_account
from google.auth.transport.requests import Request

key, scope, out = sys.argv[1], sys.argv[2], sys.argv[3]
creds = service_account.Credentials.from_service_account_file(key, scopes=[scope])
creds.refresh(Request())
old = os.umask(0o077)
try:
    with open(out, "w") as fh:
        fh.write("Authorization: Bearer " + creds.token + "\n")
finally:
    os.umask(old)
PY
}

json_count() { jq -r "$2" "$1" 2>/dev/null || echo "?"; }

# Print an API response compactly whether or not it is valid JSON.
show_body() { jq -c . "$1" 2>/dev/null || cat "$1" 2>/dev/null || true; }

echo "============================================================"
echo " WECARE GOOGLE SEO / ADS / ANALYTICS / GBP SETUP + AUDIT"
echo "============================================================"
echo " project=$PROJECT_ID dry_run=$DRY_RUN"
echo

echo "[1/9] Verifying the EXISTING JSON key (nothing is created or deleted)..."
python3 - "$KEY_FILE" "$PROJECT_ID" "$SA" "$EXPECTED_KEY_ID" <<'PY' || { echo "ERROR: not the expected existing key. Stopping."; exit 3; }
import json, sys
path, project, sa, kid = sys.argv[1:5]
with open(path) as fh:
    d = json.load(fh)
assert d.get("type") == "service_account", "not a service_account key"
assert d.get("project_id") == project, "wrong project: %s" % d.get("project_id")
assert d.get("client_email") == sa, "wrong service account: %s" % d.get("client_email")
assert d.get("private_key_id") == kid, "wrong key id: %s" % d.get("private_key_id")
print("  PASS: %s | %s | %s" % (d["project_id"], d["client_email"], d["private_key_id"]))
PY
echo

echo "[2/9] Pointing gcloud at the administrator account..."
unset CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE 2>/dev/null || true
gcloud config set account "$ADMIN" --quiet || exit 4
gcloud config set project "$PROJECT_ID" --quiet || exit 4
ACTIVE_ACCOUNT="$(gcloud config get-value account 2>/dev/null)"
echo "  active gcloud account: $ACTIVE_ACCOUNT"
if [[ "$ACTIVE_ACCOUNT" != "$ADMIN" ]]; then
  echo "ERROR: expected the admin account $ADMIN"
  echo "       run: gcloud auth login $ADMIN"
  exit 4
fi
echo

echo "[3/9] Enabling Google APIs..."
APIS=(
  # -- language: the current blocker for on-site translation ------------------
  translate.googleapis.com
  texttospeech.googleapis.com
  # -- platform ---------------------------------------------------------------
  serviceusage.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  sts.googleapis.com
  secretmanager.googleapis.com
  # -- SEO --------------------------------------------------------------------
  searchconsole.googleapis.com
  pagespeedonline.googleapis.com
  siteverification.googleapis.com
  indexing.googleapis.com
  # -- analytics --------------------------------------------------------------
  analyticsdata.googleapis.com
  analyticsadmin.googleapis.com
  tagmanager.googleapis.com
  # -- ads / commerce ---------------------------------------------------------
  googleads.googleapis.com
  datamanager.googleapis.com
  merchantapi.googleapis.com
  searchads360.googleapis.com
  displayvideo.googleapis.com
  doubleclickbidmanager.googleapis.com
  dfareporting.googleapis.com
  marketingplatformadmin.googleapis.com
  adsense.googleapis.com
  adsenseplatform.googleapis.com
  admanager.googleapis.com
  admob.googleapis.com
  # -- Business Profile -------------------------------------------------------
  mybusinessaccountmanagement.googleapis.com
  mybusinessbusinessinformation.googleapis.com
  mybusinessnotifications.googleapis.com
  mybusinessverifications.googleapis.com
  mybusinessplaceactions.googleapis.com
  mybusinesslodging.googleapis.com
  mybusinessqanda.googleapis.com
  businessprofileperformance.googleapis.com
  # -- data / media -----------------------------------------------------------
  pubsub.googleapis.com
  bigquery.googleapis.com
  bigquerystorage.googleapis.com
  youtube.googleapis.com
  youtubeanalytics.googleapis.com
  youtubereporting.googleapis.com
)
# Shut down or access-gated; failure here is expected and not a problem.
OPTIONAL_APIS=( mybusiness.googleapis.com )

ENABLED=0; FAILED=0
for api in "${APIS[@]}"; do
  printf "  %-52s" "$api"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY"
  elif gcloud services enable "$api" --project="$PROJECT_ID" --quiet >"$TMP_DIR/enable.log" 2>&1; then
    echo "ENABLED"; ENABLED=$((ENABLED+1))
  else
    echo "FAILED/RESTRICTED"
    tail -n 2 "$TMP_DIR/enable.log" | sed 's/^/      /'
    FAILED=$((FAILED+1))
  fi
done
for api in "${OPTIONAL_APIS[@]}"; do
  printf "  %-52s" "$api"
  if [[ "$DRY_RUN" == "1" ]]; then echo "DRY"
  elif gcloud services enable "$api" --project="$PROJECT_ID" --quiet >/dev/null 2>&1; then echo "ENABLED (legacy)"
  else echo "RESTRICTED (expected - this API was shut down)"; fi
done
echo "  summary: enabled=$ENABLED failed_or_restricted=$FAILED"
echo

echo "[4/9] Granting baseline project roles to the service account..."
for role in roles/serviceusage.serviceUsageConsumer roles/bigquery.jobUser; do
  if run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:$SA" --role="$role" \
      --condition=None --quiet >/dev/null 2>&1; then
    echo "  PASS $role"
  else
    echo "  WARN could not grant $role"
  fi
done
echo

echo "[5/9] Allowing the admin to impersonate the service account..."
echo "      This is what makes keyless access possible later:"
echo "      gcloud auth print-access-token --impersonate-service-account=$SA"
for role in roles/iam.serviceAccountTokenCreator roles/iam.serviceAccountUser; do
  if run gcloud iam service-accounts add-iam-policy-binding "$SA" \
      --project="$PROJECT_ID" --member="user:$ADMIN" --role="$role" \
      --quiet >/dev/null 2>&1; then
    echo "  PASS $role"
  else
    echo "  WARN could not grant $role"
  fi
done
echo

echo "[6/9] Google Business Profile visibility..."
GBP_HEADER="$TMP_DIR/gbp.header"
GBP_ACCOUNTS="$TMP_DIR/gbp-accounts.json"
if make_auth_header "https://www.googleapis.com/auth/business.manage" "$GBP_HEADER"; then
  GBP_HTTP="$(curl -sS -o "$GBP_ACCOUNTS" -w '%{http_code}' -H @"$GBP_HEADER" \
    'https://mybusinessaccountmanagement.googleapis.com/v1/accounts' || true)"
  echo "  accounts HTTP: $GBP_HTTP"
  if [[ "$GBP_HTTP" == "200" ]]; then
    echo "  visible GBP accounts: $(json_count "$GBP_ACCOUNTS" '(.accounts // []) | length')"
    jq -r '.accounts[]? | "    - " + (.accountName // .name // "unknown") + " | " + (.type // "") + " | role=" + (.role // "")' \
      "$GBP_ACCOUNTS" 2>/dev/null || true

    # Locations must be listed per account. `accounts/-/locations` is not a
    # supported parent and returns 400, which is why the first draft always
    # came back empty here.
    while IFS= read -r acct; do
      [[ -z "$acct" ]] && continue
      LOC="$TMP_DIR/loc.json"
      LOC_HTTP="$(curl -sS -G -o "$LOC" -w '%{http_code}' -H @"$GBP_HEADER" \
        --data-urlencode 'readMask=name,title,websiteUri,storefrontAddress' \
        "https://mybusinessbusinessinformation.googleapis.com/v1/${acct}/locations" || true)"
      echo "    $acct -> locations HTTP $LOC_HTTP"
      if [[ "$LOC_HTTP" == "200" ]]; then
        echo "      count: $(json_count "$LOC" '(.locations // []) | length')"
        jq -r '.locations[]? | "      - " + (.title // .name // "unknown") + " | " + (.websiteUri // "no website")' \
          "$LOC" 2>/dev/null || true
      else
        show_body "$LOC" | sed 's/^/      /'
      fi
    done < <(jq -r '.accounts[]?.name // empty' "$GBP_ACCOUNTS" 2>/dev/null)
  else
    show_body "$GBP_ACCOUNTS" | sed 's/^/    /'
    echo "    note: Business Profile APIs ship with a default quota of zero."
    echo "          Even once enabled, calls stay blocked until Google approves"
    echo "          the GBP API access request for this project."
  fi
else
  echo "  FAIL could not mint a Business Profile token"
fi
echo

echo "[7/9] Search Console visibility..."
SC_HEADER="$TMP_DIR/sc.header"; SC_OUT="$TMP_DIR/sc.json"
if make_auth_header "https://www.googleapis.com/auth/webmasters.readonly" "$SC_HEADER"; then
  SC_HTTP="$(curl -sS -o "$SC_OUT" -w '%{http_code}' -H @"$SC_HEADER" \
    'https://searchconsole.googleapis.com/webmasters/v3/sites' || true)"
  echo "  HTTP: $SC_HTTP"
  if [[ "$SC_HTTP" == "200" ]]; then
    SC_N="$(json_count "$SC_OUT" '(.siteEntry // []) | length')"
    echo "  visible properties: $SC_N"
    jq -r '.siteEntry[]? | "    - " + .siteUrl + " | " + (.permissionLevel // "")' "$SC_OUT" 2>/dev/null || true
    if [[ "$SC_N" == "0" ]]; then
      echo "    Authentication succeeded and the property list is genuinely empty."
      echo "    There is no API for granting Search Console access - add"
      echo "    $SA"
      echo "    under Settings > Users and permissions as Restricted. Manual, unavoidable."
    fi
  else
    show_body "$SC_OUT" | sed 's/^/    /'
  fi
else
  echo "  FAIL could not mint a Search Console token"
fi
echo

echo "[8/9] GA4 visibility..."
GA_HEADER="$TMP_DIR/ga.header"; GA_OUT="$TMP_DIR/ga.json"
if make_auth_header "https://www.googleapis.com/auth/analytics.readonly" "$GA_HEADER"; then
  GA_HTTP="$(curl -sS -o "$GA_OUT" -w '%{http_code}' -H @"$GA_HEADER" \
    'https://analyticsadmin.googleapis.com/v1beta/accountSummaries?pageSize=200' || true)"
  echo "  HTTP: $GA_HTTP"
  if [[ "$GA_HTTP" == "200" ]]; then
    echo "  visible account summaries: $(json_count "$GA_OUT" '(.accountSummaries // []) | length')"
    jq -r '.accountSummaries[]? | "    - " + (.displayName // .account // "unknown") + " | properties=" + (((.propertySummaries // []) | length) | tostring)' \
      "$GA_OUT" 2>/dev/null || true
    echo "    If this is 0: add $SA"
    echo "    in GA4 Admin > Account Access Management (service accounts are"
    echo "    added exactly like a user there - this one DOES work by email)."
  else
    show_body "$GA_OUT" | sed 's/^/    /'
  fi
else
  echo "  FAIL could not mint a GA4 token"
fi
echo

echo "[9/9] Google Ads readiness..."
echo "  CORRECTED 2026-09-30. This section used to say a plain service account CANNOT be"
echo "  granted access to a Google Ads account, that Ads accepts real Google accounts only,"
echo "  and that the practical route was an OAuth refresh token plus an approved developer"
echo "  token. All of that is wrong, and it sent readers to build a flow they do not need."
echo
echo "  A SERVICE ACCOUNT CAN BE ADDED DIRECTLY AS AN ADS USER. Google's service-account"
echo "  workflow guide documents it:"
echo "      Google Ads -> Admin -> Access and security -> Users -> +"
echo "      enter the service account email, choose an access level, Add account"
echo "      (service accounts do not support the 'Email only' level - that is the only limit)"
echo "  No domain-wide delegation, no Workspace domain, no human refresh token."
echo
echo "  DEVELOPER TOKENS WERE SUNSET 2026-09-09. They may still be sent and are IGNORED by"
echo "  the API servers; access level now attaches to the Google Cloud project that owns the"
echo "  credential. So the live call below no longer needs GOOGLE_ADS_DEVELOPER_TOKEN, and"
echo "  putting one on a command line is prohibited here anyway - see"
echo "  .kiro/steering/secret-handling.md (retired; now .kiro/steering/00-common.md). Prefer: python scripts/google_products_pull.py"
echo
echo "  Grant read access to: $SA"
echo
# THE DEVELOPER-TOKEN HEADER IS GONE FROM THIS CALL, ON GOOGLE'S OWN INSTRUCTION.
#
#   "Fix your app code: We encourage you to update your app to stop sending a developer
#    token as part of your API calls. We will start rejecting developer tokens in API
#    calls in a future major version of the Google Ads API."
#   -- developer-token sunset guide, 2026-09-09
#
# So sending it is not merely pointless now, it is a scheduled future breakage. It also
# had to go for a second, local reason: the only way this script could obtain the value
# was `GOOGLE_ADS_DEVELOPER_TOKEN=...` on a command line, and an "Always allow" on that
# shape records the whole command - secret included - into a Kiro permissions file. That
# is precisely how four live credentials landed on disk here on 2026-09-19, so
# .kiro/steering/secret-handling.md (retired; now .kiro/steering/00-common.md) forbids it and .kiro/hooks/block-inline-secrets.json
# blocks it. Removing the header removes the only reason to ever set that variable.
#
# The call still works without it: access level now attaches to the Google Cloud project
# that owns the credential, not to a token.
ADS_HEADER="$TMP_DIR/ads.header"; ADS_OUT="$TMP_DIR/ads.json"
if make_auth_header "https://www.googleapis.com/auth/adwords" "$ADS_HEADER"; then
  ADS_HTTP="$(curl -sS -o "$ADS_OUT" -w '%{http_code}' -H @"$ADS_HEADER" \
    -H "login-customer-id: $ADS_LOGIN_CUSTOMER_ID" \
    "https://googleads.googleapis.com/${ADS_API_VERSION}/customers:listAccessibleCustomers" || true)"
  echo "  HTTP: $ADS_HTTP  (no developer token sent)"
  if [[ "$ADS_HTTP" == "200" ]]; then
    ADS_N="$(json_count "$ADS_OUT" '(.resourceNames // []) | length')"
    echo "  accessible customers: $ADS_N"
    jq -r '.resourceNames[]? | "    - " + .' "$ADS_OUT" 2>/dev/null || true
    if [[ "$ADS_N" == "0" ]]; then
      echo "  READ THIS: 200 with ZERO customers is not success. Authentication worked and"
      echo "  the access list is empty, because $SA is not yet a user on the Ads account."
      echo "  Add it at Admin > Access and security > Users > + and re-run."
    fi
  else
    show_body "$ADS_OUT" | sed 's/^/    /'
    echo "  USER_PERMISSION_DENIED                    -> not an Ads user; project is fine"
    echo "  CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION -> project on Test access; a user"
    echo "                                               grant will NOT fix it, apply for"
    echo "                                               Explorer/Basic in Cloud Console"
  fi
fi
if [[ -n "${GOOGLE_ADS_DEVELOPER_TOKEN:-}" ]]; then
  echo
  echo "  WARNING: GOOGLE_ADS_DEVELOPER_TOKEN is set in this environment. It is ignored"
  echo "  by this script and by Google's servers since the 2026-09-09 sunset, and holding"
  echo "  a credential in an environment variable is what .kiro/steering/secret-handling.md (retired; now .kiro/steering/00-common.md)"
  echo "  exists to prevent. Unset it."
fi
echo

echo "============================================================"
echo " FINAL STATUS"
echo "============================================================"
echo "key used        : $KEY_FILE"
echo "service account : $SA"
echo "project         : $PROJECT_ID"
echo "No service-account key was created, rotated or deleted."
echo
echo "Where access still has to be granted by hand:"
echo "  Search Console : add the service account email as a Restricted user"
echo "  GA4            : add it in Account/Property Access Management"
echo "  GTM / Merchant / SA360 / DV360 / CM360 : grant inside each product UI"
echo "  Business Profile: request GBP API quota, then add the account as a manager"
echo "  Google Ads     : not possible for a service account - use OAuth as $ADMIN"
echo
echo "For the on-site translation outage specifically, verify the language APIs"
echo "landed and then re-probe the relay:"
echo "  gcloud services list --enabled --project $PROJECT_ID \\"
echo "    | grep -E 'translate|texttospeech'"
echo "  bash scripts/google-language-relay.sh fix"
echo
echo "DONE"
