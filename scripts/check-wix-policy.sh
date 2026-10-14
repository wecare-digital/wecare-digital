#!/usr/bin/env bash
#
# Wix exit policy gate — spec .kiro/specs/aws-native-consolidation.
#
# The approved end state (Workstream A) is: AWS is authoritative for blog and
# commerce, and NO runtime code path calls Wix. This gate fails CI when runtime
# code depends on Wix, so that once the migration completes, Wix cannot creep
# back in silently.
#
# It is modelled on scripts/check-provider-policy.sh and shares its discipline:
# it is scoped to RUNTIME code only and matches Wix HOSTS / credential names /
# SDK imports, never the word "wix" in prose or historical data.
#
#   scanned:  amplify/functions/**  src/**
#   ignored:  docs/**  .kiro/**  tests/**  scripts/**  *.md  node_modules .next out
#
# BASELINE TODAY: Wix is still the live backend, so this gate is EXPECTED TO FAIL
# right now. Run it with --expect-fail in CI until Gate 4 (Wix independence) is
# proven; then drop --expect-fail to turn it into a real blocking gate.
#
# Exit codes:  0 compliant · 1 violations · 2 bad invocation
#
# Usage:
#   scripts/check-wix-policy.sh                 # gate mode (post-cutover)
#   scripts/check-wix-policy.sh --verbose
#   scripts/check-wix-policy.sh --expect-fail   # pre-cutover baseline (CI today)
set -uo pipefail

VERBOSE=0
EXPECT_FAIL=0
for arg in "$@"; do
  case "$arg" in
    --verbose) VERBOSE=1 ;;
    --expect-fail) EXPECT_FAIL=1 ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.." || exit 2

SCAN_DIRS=()
[ -d amplify/functions ] && SCAN_DIRS+=(amplify/functions)
[ -d src ] && SCAN_DIRS+=(src)
if [ ${#SCAN_DIRS[@]} -eq 0 ]; then
  echo "nothing to scan (no amplify/functions or src)" >&2
  exit 2
fi

VIOLATIONS=0
declare -a FAILED_RULES=()

rule() {
  local id="$1" desc="$2" pattern="$3" exclude="${4:-}"
  local hits
  hits=$(grep -rIn --extended-regexp "$pattern" "${SCAN_DIRS[@]}" \
           --include='*.py' --include='*.ts' --include='*.tsx' --include='*.js' \
           --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=out \
           --exclude-dir=__pycache__ --exclude-dir=.venv 2>/dev/null || true)
  if [ -n "$exclude" ] && [ -n "$hits" ]; then
    hits=$(printf '%s\n' "$hits" | grep -vE "$exclude" || true)
  fi
  local count
  count=$(printf '%s' "$hits" | grep -c . || true)
  if [ "$count" -gt 0 ]; then
    printf '  FAIL  %-26s %s\n' "$id" "$desc"
    printf '        %s match(es) in:\n' "$count"
    printf '%s\n' "$hits" | awk -F: '{print $1}' | sort -u | sed 's/^/          /'
    [ "$VERBOSE" -eq 1 ] && printf '%s\n' "$hits" | sed 's/^/          | /'
    VIOLATIONS=$((VIOLATIONS + count))
    FAILED_RULES+=("$id")
  else
    printf '  ok    %-26s %s\n' "$id" "$desc"
  fi
}

echo
echo "WIX EXIT POLICY GATE"
echo "  scanning: ${SCAN_DIRS[*]}"
echo "  goal: zero runtime Wix dependency (AWS authoritative for blog + commerce)"
echo

# Wix API hosts in runtime code — the clearest signal of a live call.
rule "wix-api-host" \
     "no wixapis.com / wix.com host in runtime code" \
     '(www\.wixapis\.com|wixapis\.com|manage\.wix\.com|/stores/v3/|/blog/v3/|/v3/posts/)'

# Wix SDK / client imports.
rule "wix-sdk-import" \
     "no @wix/ SDK import in runtime code" \
     '(@wix/|from .wix-|import .*wix_ecom|import .*cart_v2|wix_writeback|wix_address)'

# Wix credential + config identifiers (the public ids are allowed to exist only
# until cutover; this gate is why we keep --expect-fail until then).
rule "wix-credentials" \
     "no Wix credential/secret identifiers in runtime code" \
     "(WIX_API_KEY|WIX_API_KEY_SECRET|wecare/wix/|_load_visitor_access_token|_load_api_key.*wix|WIX_CLIENT_ID|WIX_BLOG_CLIENT_ID|WIX_SITE_ID|WIX_ACCOUNT_ID)"

# Wix feature flags that select a Wix code path.
rule "wix-mode-flags" \
     "no Wix-selecting mode flags in runtime code" \
     "(WIX_HEADLESS|WIX_CART_V2_ENABLED|WIX_WRITEBACK_ENABLED|CHECKOUT_MODE *= *['\"]WIX|BLOG_SOURCE *= *['\"]wix|CATALOG_SOURCE *= *['\"]wix)"

echo
if [ "$EXPECT_FAIL" -eq 1 ]; then
  if [ "$VIOLATIONS" -gt 0 ]; then
    echo "EXPECTED-FAIL MODE: $VIOLATIONS Wix match(es) present, as expected."
    echo "  failing rules: ${FAILED_RULES[*]}"
    echo "  This is the pre-cutover baseline. Flip to gate mode (drop --expect-fail)"
    echo "  once Gate 4 (Wix independence) in the spec is proven."
    exit 0
  fi
  echo "EXPECTED-FAIL MODE: no Wix runtime references found."
  echo "  Migration appears complete — remove --expect-fail and gate for real."
  exit 1
fi

if [ "$VIOLATIONS" -gt 0 ]; then
  echo "WIX EXIT POLICY VIOLATED: $VIOLATIONS finding(s) across ${#FAILED_RULES[@]} rule(s)."
  echo "  failing rules: ${FAILED_RULES[*]}"
  echo "  AWS must be authoritative for blog + commerce. See"
  echo "  docs/migrations/aws-native-wix-exit.md and the spec."
  exit 1
fi

echo "WIX EXIT POLICY OK — no runtime Wix references."
exit 0
