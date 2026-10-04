#!/usr/bin/env bash
#
# WECARE.DIGITAL - repair and configure the Cloud Run language relay
#
# Runs in Google Cloud Shell with nothing but gcloud, curl and jq. It
# deliberately does NOT require the aws CLI: scripts/google-cloud-setup.sh does,
# and that makes it unusable in Cloud Shell, which is where you actually have
# gcloud credentials.
#
# WHY THIS EXISTS
#
# Probing the live relay on 2026-08-26 established:
#
#   * Read-aloud WORKS.  POST {"text":"..","languageCode":"en-IN"}
#     -> 200 audio/mpeg, valid MP3.
#
#   * Translation is DOWN.  Every request shape tried - 40+ of them, across
#     both Google v2 and v3 field names, plus form encoding, nested bodies,
#     arrays and an empty {} - answers
#         400 {"error":{"message":"Translation unavailable"}}
#     An empty body failing identically to a well-formed one means this is not
#     a payload mismatch. The translation branch is failing before it ever
#     looks at the input, which points at the Cloud Translation API being off,
#     the relay's runtime service account lacking roles/cloudtranslate.user, or
#     billing not being attached.
#
#   * GET /health answers {"translation":true,...}. That flag is STATIC. It
#     reports configuration, not reachability, so it says "true" while every
#     real call fails. Do not trust it; trust `probe`.
#
#   * The CORS allow-list admits exactly https://www.wecare.digital and
#     https://wecare.digital. Everything else gets 403 with no
#     Access-Control-Allow-Origin header. That allow-list is now exactly right:
#     the site serves from the apex, and retired-legacy-host.invalid - which the relay
#     rejected and which this file used to flag as a gap - has been retired.
#
# Usage:
#   bash scripts/google-language-relay.sh probe        # what works right now
#   bash scripts/google-language-relay.sh describe     # service, region, SA, env
#   bash scripts/google-language-relay.sh enable-apis  # Translation + TTS on
#   bash scripts/google-language-relay.sh grant        # IAM for the runtime SA
#   bash scripts/google-language-relay.sh logs         # the real error, from logs
#   bash scripts/google-language-relay.sh origins      # show the CORS allow-list
#   bash scripts/google-language-relay.sh add-origin https://example.wecare.digital
#   bash scripts/google-language-relay.sh keyfix       # repair a broken SA key file
#   bash scripts/google-language-relay.sh fix          # enable-apis + grant + logs + probe
#
#   DRY_RUN=1 bash scripts/google-language-relay.sh <cmd>   # print, change nothing

set -euo pipefail

# -- configuration -----------------------------------------------------------
GCP_PROJECT="${GCP_PROJECT:-wecaredigitalbw}"
RELAY_URL="${RELAY_URL:-https://wecare-translation-relay-hrkl3sncxq-el.a.run.app}"

# Origin the relay already trusts, so probes exercise the real allowed path.
PROBE_ORIGIN="${PROBE_ORIGIN:-https://www.wecare.digital}"

# The origin the site serves from. Was retired-legacy-host.invalid, which the relay
# rejected; that host is retired and the apex is both canonical and already
# allow-listed, so these checks should now pass rather than warn.
SITE_ORIGIN="${SITE_ORIGIN:-https://wecare.digital}"

# Cloud Translation needs an explicit role. Cloud Text-to-Speech has no
# granular role - enabling the API and being an authenticated principal is
# sufficient - which is exactly why speech works today and translation does not.
TRANSLATE_ROLE="roles/cloudtranslate.user"

LANGUAGE_APIS=(
  translate.googleapis.com
  texttospeech.googleapis.com
)

SA_KEY_FILE="${SA_KEY_FILE:-$HOME/automation-service-account-key.json}"
SA_EMAIL="${SA_EMAIL:-automation@wecaredigitalbw.iam.gserviceaccount.com}"

DRY_RUN="${DRY_RUN:-0}"

# -- plumbing ----------------------------------------------------------------
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
info() { printf '%s\n' "$*"; }
ok()   { printf '%s  OK%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s  !!%s %s\n' "$YEL" "$RST" "$*"; }
bad()  { printf '%s FAIL%s %s\n' "$RED" "$RST" "$*"; }
die()  { printf '%s ERROR%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }
run()  { if [[ "$DRY_RUN" == "1" ]]; then printf '%s  DRY %s%s\n' "$DIM" "$*" "$RST"; else "$@"; fi; }

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required but not installed"; }

SVC=""      # Cloud Run service name
REGION=""   # its region
RUNTIME_SA="" # the identity the container runs as

preflight() {
  need gcloud; need curl; need jq
  gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q . \
    || die "no active gcloud account. Run: gcloud auth login"
}

# Locate the Cloud Run service behind RELAY_URL. Matching on the URL rather than
# assuming a name means a rename or a second copy cannot send us at the wrong
# service.
resolve_service() {
  [[ -n "$SVC" ]] && return 0
  local rows
  rows="$(gcloud run services list --platform=managed --project "$GCP_PROJECT" \
    --format='csv[no-heading](metadata.name,metadata.labels."cloud.googleapis.com/location",status.url)' \
    2>/dev/null || true)"
  [[ -n "$rows" ]] || die "no Cloud Run services visible in $GCP_PROJECT (wrong project, or missing run.services.list)"

  local want="${RELAY_URL%/}"
  while IFS=, read -r name region url; do
    [[ -z "${name:-}" ]] && continue
    if [[ "${url%/}" == "$want" ]]; then SVC="$name"; REGION="$region"; break; fi
  done <<< "$rows"

  if [[ -z "$SVC" ]]; then
    warn "no service in $GCP_PROJECT serves $RELAY_URL. Services found:"
    printf '%s\n' "$rows" | sed 's/^/     /'
    die "cannot continue without the relay service"
  fi

  RUNTIME_SA="$(gcloud run services describe "$SVC" --region "$REGION" \
    --project "$GCP_PROJECT" --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
  if [[ -z "$RUNTIME_SA" ]]; then
    # Empty means the Compute Engine default service account.
    local num
    num="$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)' 2>/dev/null || true)"
    [[ -n "$num" ]] && RUNTIME_SA="${num}-compute@developer.gserviceaccount.com"
  fi
}

# -- commands ----------------------------------------------------------------

# One POST, reported as "<status> <content-type> <bytes>". The body is discarded
# because a success is a wall of MP3 bytes.
#
# Headers are lower-cased with tr before awk sees them, rather than using awk's
# IGNORECASE: that is a GNU extension and Debian - which Cloud Shell is built on
# - ships mawk by default, where IGNORECASE silently does nothing.
relay_post() {
  local body="$1" origin="${2:-$PROBE_ORIGIN}"
  curl -s -o /dev/null -D - -X POST "$RELAY_URL" \
    -H 'Content-Type: application/json' \
    -H "Origin: $origin" \
    --max-time 30 \
    --data "$body" 2>/dev/null \
    | tr -d '\r' | tr '[:upper:]' '[:lower:]' \
    | awk '/^http\//{code=$2} /^content-type:/{ct=$2} /^content-length:/{len=$2} END{printf "%s %s %s", (code?code:"---"), (ct?ct:"-"), (len?len:"?")}'
}

relay_post_body() {
  local body="$1" origin="${2:-$PROBE_ORIGIN}"
  curl -s -X POST "$RELAY_URL" \
    -H 'Content-Type: application/json' \
    -H "Origin: $origin" \
    --max-time 30 --data "$body" 2>/dev/null | head -c 300
}

cmd_probe() {
  info "== probe $RELAY_URL =="
  info ""

  info "-- health (advisory only; this flag is static) --"
  curl -s --max-time 20 -H "Origin: $PROBE_ORIGIN" "$RELAY_URL/health" | head -c 300
  info ""
  info ""

  info "-- speech: {text, languageCode} --"
  local r
  r="$(relay_post '{"text":"WECARE relay check.","languageCode":"en-IN"}')"
  info "   $r"
  case "$r" in
    200*audio*) ok "read-aloud works" ;;
    *)          bad "read-aloud broken: $(relay_post_body '{"text":"x","languageCode":"en-IN"}')" ;;
  esac
  info ""

  info "-- translation: Google v2 + v3 field names together --"
  local tbody='{"q":["hello"],"contents":["hello"],"target":"hi","targetLanguageCode":"hi","source":"en","sourceLanguageCode":"en","format":"text"}'
  r="$(relay_post "$tbody")"
  info "   $r"
  if [[ "$r" == 200* ]]; then
    ok "translation works"
    info "   body: $(relay_post_body "$tbody")"
  else
    bad "translation still down: $(relay_post_body "$tbody")"
    info "   run '$0 fix' and then re-probe"
  fi
  info ""

  info "-- CORS allow-list --"
  for o in "$PROBE_ORIGIN" "$SITE_ORIGIN"; do
    local code acao
    code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$RELAY_URL" \
      -H 'Content-Type: application/json' -H "Origin: $o" --max-time 20 \
      --data '{"text":"x","languageCode":"en-IN"}' 2>/dev/null || echo '---')"
    acao="$(curl -s -o /dev/null -D - -X OPTIONS "$RELAY_URL" \
      -H "Origin: $o" -H 'Access-Control-Request-Method: POST' --max-time 20 2>/dev/null \
      | tr -d '\r' | tr '[:upper:]' '[:lower:]' \
      | awk '/^access-control-allow-origin:/{print $2}')"
    if [[ "$code" == "200" ]]; then
      ok "$o  (POST $code, ACAO ${acao:-none})"
    else
      warn "$o  (POST $code, ACAO ${acao:-none})  REJECTED"
    fi
  done
}

cmd_describe() {
  resolve_service
  info "== relay service =="
  info "  project     : $GCP_PROJECT"
  info "  service     : $SVC"
  info "  region      : $REGION"
  info "  url         : $RELAY_URL"
  info "  runtime SA  : ${RUNTIME_SA:-<unknown>}"
  info ""
  info "-- ingress / invoker --"
  gcloud run services describe "$SVC" --region "$REGION" --project "$GCP_PROJECT" \
    --format='value(metadata.annotations."run.googleapis.com/ingress")' 2>/dev/null \
    | sed 's/^/  ingress: /'
  if gcloud run services get-iam-policy "$SVC" --region "$REGION" --project "$GCP_PROJECT" \
       --format=json 2>/dev/null | jq -e '.bindings[]?|select(.role=="roles/run.invoker")|.members[]?|select(.=="allUsers")' >/dev/null; then
    warn "allUsers can invoke: the relay is PUBLIC."
    warn "     CORS is enforced by browsers only, so anyone can curl this and"
    warn "     spend your Cloud TTS and Translation quota. Consider a lightweight"
    warn "     shared token or per-IP rate limiting."
  else
    ok "not open to allUsers"
  fi
  info ""
  info "-- environment (names and values; secrets show as <from-secret>) --"
  gcloud run services describe "$SVC" --region "$REGION" --project "$GCP_PROJECT" \
    --format=json 2>/dev/null \
    | jq -r '.spec.template.spec.containers[0].env // [] | .[] | "  \(.name)=\(.value // "<from-secret>")"'
}

cmd_enable_apis() {
  info "== enable the language APIs on $GCP_PROJECT =="
  for api in "${LANGUAGE_APIS[@]}"; do
    if gcloud services list --enabled --project "$GCP_PROJECT" \
         --filter="config.name=$api" --format='value(config.name)' 2>/dev/null | grep -q .; then
      ok "$api already enabled"
    else
      warn "$api NOT enabled - this alone would explain the outage"
      run gcloud services enable "$api" --project "$GCP_PROJECT" --quiet
      ok "$api enabled"
    fi
  done
}

cmd_grant() {
  resolve_service
  [[ -n "$RUNTIME_SA" ]] || die "cannot determine the relay's runtime service account"
  info "== grant translation access to the relay's identity =="
  info "  service account : $RUNTIME_SA"
  info "  role            : $TRANSLATE_ROLE"

  if gcloud projects get-iam-policy "$GCP_PROJECT" --format=json 2>/dev/null \
       | jq -e --arg m "serviceAccount:$RUNTIME_SA" --arg r "$TRANSLATE_ROLE" \
         '.bindings[]?|select(.role==$r)|.members[]?|select(.==$m)' >/dev/null; then
    ok "already granted"
  else
    run gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
      --member="serviceAccount:$RUNTIME_SA" --role="$TRANSLATE_ROLE" \
      --condition=None --quiet
    ok "granted"
    info "  IAM is eventually consistent; allow a minute before re-probing."
  fi
}

cmd_logs() {
  resolve_service
  info "== relay errors from the last 7 days =="
  info "  This is the authoritative answer for why translation 400s."
  info ""
  gcloud logging read \
    "resource.type=cloud_run_revision AND resource.labels.service_name=\"$SVC\" AND severity>=WARNING" \
    --project "$GCP_PROJECT" --limit 40 --freshness=7d \
    --format='value(timestamp,severity,textPayload,jsonPayload.message,jsonPayload.error)' \
    2>/dev/null | sed 's/^/  /' || warn "cannot read logs (needs roles/logging.viewer)"
  info ""
  info "  Look for: SERVICE_DISABLED, PERMISSION_DENIED, 'Cloud Translation API"
  info "  has not been used', billing, or an unhandled exception in the"
  info "  translate handler."
}

# Find the env var that carries the CORS allow-list. Prefer an explicit name,
# fall back to any var whose value mentions our domain.
find_origin_var() {
  resolve_service
  local json
  json="$(gcloud run services describe "$SVC" --region "$REGION" --project "$GCP_PROJECT" \
    --format=json 2>/dev/null)"
  printf '%s' "$json" | jq -r '
    (.spec.template.spec.containers[0].env // []) as $e
    | ( [ $e[] | select(.name | test("ORIGIN|CORS|ALLOW";"i")) ]
        + [ $e[] | select((.value // "") | test("wecare\\.digital")) ] )
    | unique_by(.name) | .[0] // empty
    | "\(.name)\t\(.value // "")"'
}

cmd_origins() {
  local row
  row="$(find_origin_var || true)"
  info "== CORS allow-list =="
  if [[ -z "$row" ]]; then
    warn "no environment variable looks like an origin allow-list."
    warn "     The list is probably hard-coded in the relay's source, which is"
    warn "     NOT in either of the wecare repos - grep for the relay URL finds"
    warn "     nothing. You will need the relay's own repo to change it."
    info ""
    info "  Current environment:"
    cmd_describe 2>/dev/null | sed -n '/environment/,$p' | sed 's/^/  /'
    return 0
  fi
  local name value
  name="${row%%$'\t'*}"; value="${row#*$'\t'}"
  info "  variable : $name"
  info "  value    : $value"
  info ""
  if printf '%s' "$value" | grep -q "$SITE_ORIGIN"; then
    ok "$SITE_ORIGIN is already listed"
  else
    warn "$SITE_ORIGIN is NOT listed - the site will keep getting 403"
    info "  add it with:  $0 add-origin $SITE_ORIGIN"
  fi
}

cmd_add_origin() {
  local origin="${1:-$SITE_ORIGIN}"
  case "$origin" in
    https://*) ;;
    *) die "origin must start with https:// (got '$origin')" ;;
  esac

  local row
  row="$(find_origin_var || true)"
  [[ -n "$row" ]] || die "no origin allow-list env var found; see '$0 origins'"

  local name value
  name="${row%%$'\t'*}"; value="${row#*$'\t'}"

  if printf '%s' "$value" | grep -q -- "$origin"; then
    ok "$origin already present in $name"
    return 0
  fi

  local merged
  if [[ -z "$value" ]]; then merged="$origin"; else merged="${value},${origin}"; fi

  resolve_service
  info "== add $origin to $name =="
  info "  before : $value"
  info "  after  : $merged"
  # ^@^ switches gcloud's list delimiter to @, so commas survive inside the value.
  run gcloud run services update "$SVC" --region "$REGION" --project "$GCP_PROJECT" \
    --update-env-vars "^@^${name}=${merged}" --quiet
  ok "updated; Cloud Run is rolling out a new revision"
  info "  re-check with: $0 probe"
}

# The user hit:
#   json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
# on ~/automation-service-account-key.json. That error means the file is empty
# or does not start with JSON - a truncated copy-paste, not a bad key. Minting a
# fresh key with gcloud avoids pasting a private key through a terminal at all.
cmd_keyfix() {
  info "== service-account key file =="
  info "  path: $SA_KEY_FILE"

  if [[ ! -e "$SA_KEY_FILE" ]]; then
    warn "file does not exist"
  else
    local size
    size="$(wc -c < "$SA_KEY_FILE" | tr -d ' ')"
    info "  size: ${size} bytes"
    if [[ "$size" == "0" ]]; then
      warn "file is EMPTY - that is exactly the JSONDecodeError you saw"
    elif jq -e '.type == "service_account"' "$SA_KEY_FILE" >/dev/null 2>&1; then
      ok "valid service-account JSON"
      info "  client_email   : $(jq -r '.client_email' "$SA_KEY_FILE")"
      info "  private_key_id : $(jq -r '.private_key_id' "$SA_KEY_FILE")"
      cmd_searchconsole
      return 0
    else
      warn "not valid service-account JSON. First bytes:"
      head -c 80 "$SA_KEY_FILE" | sed 's/^/     /'
      info ""
    fi
  fi

  info ""
  info "  Minting a fresh key straight to disk - nothing is pasted, so it"
  info "  cannot be truncated. This ADDS a key and deletes nothing."
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '%s  DRY gcloud iam service-accounts keys create %s --iam-account %s%s\n' \
      "$DIM" "$SA_KEY_FILE" "$SA_EMAIL" "$RST"
    return 0
  fi
  ( umask 077; : > "$SA_KEY_FILE" )
  gcloud iam service-accounts keys create "$SA_KEY_FILE" \
    --iam-account "$SA_EMAIL" --project "$GCP_PROJECT" --quiet \
    || die "could not create a key for $SA_EMAIL"
  chmod 600 "$SA_KEY_FILE"
  jq -e '.type == "service_account"' "$SA_KEY_FILE" >/dev/null \
    || die "the new key is not valid JSON, which should be impossible"
  ok "wrote a valid key to $SA_KEY_FILE"
  info "  Mirror it into AWS Secrets Manager (the source of truth) with"
  info "  scripts/google-cloud-setup.sh from a machine that has the aws CLI."
  cmd_searchconsole
}

cmd_searchconsole() {
  info ""
  info "-- Search Console reachability --"
  local tok n
  tok="$(GOOGLE_APPLICATION_CREDENTIALS="$SA_KEY_FILE" \
    gcloud auth application-default print-access-token 2>/dev/null || true)"
  if [[ -z "$tok" ]]; then
    tok="$(gcloud auth print-access-token 2>/dev/null || true)"
    [[ -n "$tok" ]] && info "  (using your user credentials, not the service account)"
  fi
  [[ -n "$tok" ]] || { warn "no access token available"; return 0; }

  n="$(curl -s --max-time 25 -H "Authorization: Bearer $tok" \
        https://searchconsole.googleapis.com/webmasters/v3/sites \
        | jq '(.siteEntry // []) | length' 2>/dev/null || echo 0)"
  if [[ "$n" == "0" ]]; then
    warn "0 properties visible."
    warn "     Authentication is fine; the principal simply has no Search"
    warn "     Console access. There is NO API for granting it - add"
    warn "     $SA_EMAIL"
    warn "     under Search Console > Settings > Users and permissions,"
    warn "     as Restricted. That step is irreducibly manual."
  else
    ok "$n property(ies) visible"
  fi
}

cmd_fix() {
  cmd_enable_apis; info ""
  cmd_grant;       info ""
  cmd_logs;        info ""
  info "== re-probing =="
  info ""
  cmd_probe
}

usage() {
  sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

main() {
  [[ $# -ge 1 ]] || usage
  preflight
  info "project=$GCP_PROJECT dry_run=$DRY_RUN"
  info ""
  case "$1" in
    probe)        cmd_probe ;;
    describe)     cmd_describe ;;
    enable-apis)  cmd_enable_apis ;;
    grant)        cmd_grant ;;
    logs)         cmd_logs ;;
    origins)      cmd_origins ;;
    add-origin)   shift; cmd_add_origin "${1:-}" ;;
    keyfix)       cmd_keyfix ;;
    fix)          cmd_fix ;;
    *)            usage ;;
  esac
}

main "$@"
