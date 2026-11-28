#!/usr/bin/env bash
# Build the Nano Climate historical-weather aggregate in resumable, cost-capped chunks.
#
# Run in Google Cloud Shell as an owner/BigQuery Data Editor of project wecaredigitalbw:
#   AGGREGATE_DATASET=<writable_dataset> bash scripts/build_weather_history_aggregate.sh
#   ... --apply    # load up to MAX_CHUNKS windows
#   ... --verify   # read-only aggregate checks
# The dataset may also be passed as --aggregate-dataset <name>.
#
# Destination: weather_insights is a linked, read-only dataset and is refused. The owner
# must create or choose a writable dataset (same location as the raw data) in advance;
# there is no default and this script never creates datasets. Only the small
# aggregate table is created, and only with --apply.
#
# Safety:
# - Each chunk is one half-month window (about 0.5 GiB for the raw table). A dry run runs
#   first; a chunk is skipped if its estimate is not below 1 GiB.
# - Every load also sets --maximum_bytes_billed=1073741824, so BigQuery refuses to run it
#   if the estimate was wrong. Quotas are never changed.
# - MAX_CHUNKS (default 4, about 2 GiB) leaves most of the 10 GiB/day project quota for
#   live 30d queries (about 0.99 GiB each). Run off-peak and check the day's usage first.
#   Run again on following days; completed windows are skipped (resumable).
# - Windows whose raw scan returns no rows get a sentinel row (NULL lat/lng, 0 hours)
#   in the small aggregate table, so they count as done and completeness is measurable.
# - Rows are de-duplicated to one per grid point per hour, matching the raw 30d path.
# - Only complete windows that ended before today (UTC) are loaded, one INSERT per window,
#   guarded by NOT EXISTS, so re-runs never duplicate rows.
# - --verify exits non-zero unless (1) every half-month window except the newest 16 days is
#   present and (2) the newest non-empty window's totals (grid points, hours, temperature
#   sum, precipitation sum) equal a fresh raw scan of that window (capped at 1 GiB billed,
#   skipped by VERIFY_COMPARE=0). The raw scan is the same de-duplicated SELECT as the load.
# - The service (gcp/vayulok-weather-insights/server.mjs) only reads this aggregate for
#   1y and 5y ranges. 30d continues to read the raw table (0.987 GiB dry run).
set -euo pipefail

PROJECT="${PROJECT:-wecaredigitalbw}"
SOURCE_DATASET="${SOURCE_DATASET:-weather_insights}"  # linked, read-only raw data
AGGREGATE_DATASET="${AGGREGATE_DATASET:-}"             # writable, no default
LOCATION="${LOCATION:-US}"
MODE="dry-run"
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) MODE="apply" ;;
    --verify) MODE="verify" ;;
    --aggregate-dataset) [ $# -ge 2 ] || { echo "--aggregate-dataset needs a value"; exit 2; }; AGGREGATE_DATASET="$2"; shift ;;
    --aggregate-dataset=*) AGGREGATE_DATASET="${1#*=}" ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
  shift
done
if [ -z "$AGGREGATE_DATASET" ]; then
  echo "ERROR: set AGGREGATE_DATASET (or --aggregate-dataset) to a writable dataset in ${PROJECT}."
  echo "There is no default. ${SOURCE_DATASET} is linked and read-only. The owner must create or choose the dataset first."
  exit 2
fi
if ! printf '%s' "$AGGREGATE_DATASET" | grep -Eq '^[A-Za-z0-9_]+$'; then
  echo "ERROR: invalid aggregate dataset name."; exit 2
fi
if [ "$(printf '%s' "$AGGREGATE_DATASET" | tr 'A-Z' 'a-z')" = "weather_insights" ] || [ "$AGGREGATE_DATASET" = "$SOURCE_DATASET" ]; then
  echo "ERROR: ${AGGREGATE_DATASET} is the linked, read-only source dataset and cannot hold the aggregate."; exit 2
fi
RAW="${PROJECT}.${SOURCE_DATASET}.weather_history_in"
AGG="${PROJECT}.${AGGREGATE_DATASET}.weather_history_in_windows"
YEARS="${YEARS:-5}"
MAX_CHUNKS="${MAX_CHUNKS:-4}"
# Raw column names. Override if the dry run reports a schema mismatch; confirm them
# first with: bq show --schema --format=prettyjson ${RAW}
C_GEO="${C_GEO:-geography}"
C_TIME="${C_TIME:-forecast_time}"
C_TEMP="${C_TEMP:-temperature_c}"
C_RAIN="${C_RAIN:-qpf_mm}"
C_HUM="${C_HUM:-relative_humidity_percent}"
CAP_BYTES=1073741824
[ "$MAX_CHUNKS" -ge 1 ] && [ "$MAX_CHUNKS" -le 12 ] || { echo "MAX_CHUNKS must be 1..12"; exit 2; }

bq_q() { bq --project_id="$PROJECT" --location="$LOCATION" query --use_legacy_sql=false --quiet "$@"; }

# Aggregate table: tiny, clustered by location. Created only with --apply.
CREATE_SQL="CREATE TABLE IF NOT EXISTS \`${AGG}\` (
  lat FLOAT64, lng FLOAT64, window_start DATE, window_end DATE,
  sample_hours INT64, temp_sum FLOAT64, temp_min FLOAT64, temp_max FLOAT64,
  precip_sum FLOAT64, humidity_sum FLOAT64, humidity_n INT64,
  first_observed_at TIMESTAMP, last_observed_at TIMESTAMP, loaded_at TIMESTAMP
) CLUSTER BY lat, lng
OPTIONS (description='Half-month aggregates of weather_history_in for Nano Climate 1y/5y summaries')"
if [ "$MODE" = "apply" ]; then bq_q "$CREATE_SQL" >/dev/null; fi

# Half-month windows [start, end) that ended before today (UTC), newest first.
WINDOWS=$(python3 - "$YEARS" <<'PY'
import sys, datetime as d
years = int(sys.argv[1]); today = d.datetime.now(d.timezone.utc).date()
floor = today.replace(year=today.year - years)
out = []; y, m = today.year, today.month
while True:
    first = d.date(y, m, 1); mid = d.date(y, m, 16)
    nxt = d.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    for s, e in ((mid, nxt), (first, mid)):
        if e <= today and s >= floor: out.append(f"{s} {e}")
    m -= 1
    if m == 0: y, m = y - 1, 12
    if d.date(y, m, 1) < floor.replace(day=1): break
print("\n".join(out))
PY
)

DONE=""
if bq show "${AGG}" >/dev/null 2>&1; then
  DONE=$(bq_q --format=csv "SELECT CAST(window_start AS STRING) FROM \`${AGG}\` GROUP BY 1" | tail -n +2)
fi

raw_select() { # $1=start $2=end ; one row per grid point per hour, like the raw 30d path
cat <<SQL
SELECT ROUND(ST_Y(${C_GEO}), 4) AS lat, ROUND(ST_X(${C_GEO}), 4) AS lng, ${C_TIME} AS t,
  SAFE_CAST(${C_TEMP} AS FLOAT64) AS temp, SAFE_CAST(${C_RAIN} AS FLOAT64) AS rain,
  SAFE_CAST(${C_HUM} AS FLOAT64) AS hum
FROM \`${RAW}\`
WHERE ${C_TIME} >= TIMESTAMP '$1' AND ${C_TIME} < TIMESTAMP '$2' AND ${C_TEMP} IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY ${C_GEO}, ${C_TIME} ORDER BY ${C_TIME}) = 1
SQL
}

if [ "$MODE" = "verify" ]; then
  bq show "${AGG}" >/dev/null 2>&1 || { echo "FAIL: ${AGG} does not exist"; exit 1; }
  bq_q --format=prettyjson "
    SELECT COUNT(*) AS rows_loaded, COUNT(DISTINCT window_start) AS windows,
           COUNTIF(sample_hours = 0) AS empty_windows,
           MIN(window_start) AS first_window, MAX(window_start) AS last_window,
           COUNT(DISTINCT CONCAT(CAST(lat AS STRING), ',', CAST(lng AS STRING))) AS grid_points
    FROM \`${AGG}\`"
  # (1) completeness: mirrors aggregateComplete() in gcp/vayulok-weather-insights/aggregate.mjs
  MISSING=$(python3 - "$DONE" "$WINDOWS" <<'PY'
import sys, datetime as d
done = set(sys.argv[1].split()); cutoff = d.datetime.now(d.timezone.utc).date() - d.timedelta(days=16)
miss = [l.split()[0] for l in sys.argv[2].splitlines() if l.strip() and l.split()[0] not in done and d.date.fromisoformat(l.split()[1]) <= cutoff]
print("\n".join(miss))
PY
)
  if [ -n "$MISSING" ]; then echo "FAIL: missing windows:"; echo "$MISSING"; exit 1; fi
  echo "OK: all required windows are present"
  # (2) raw versus aggregate for the newest non-empty window
  if [ "${VERIFY_COMPARE:-1}" = "1" ]; then
    W=$(bq_q --format=csv "SELECT CAST(MAX(window_start) AS STRING), CAST(MAX(window_end) AS STRING) FROM \`${AGG}\` WHERE sample_hours > 0" | tail -n +2)
    VS="${W%%,*}"; VE="${W##*,}"
    [ -n "$VS" ] && [ "$VS" != "$W" ] || { echo "FAIL: no non-empty window to compare"; exit 1; }
    RAWSUM=$(bq_q --maximum_bytes_billed="$CAP_BYTES" --format=csv "
      WITH h AS ($(raw_select "$VS" "$VE"))
      SELECT COUNT(DISTINCT CONCAT(CAST(lat AS STRING), ',', CAST(lng AS STRING))), COUNT(*),
             ROUND(SUM(temp), 3), ROUND(IFNULL(SUM(rain), 0), 3) FROM h" | tail -n +2)
    AGGSUM=$(bq_q --format=csv "
      SELECT COUNT(DISTINCT CONCAT(CAST(lat AS STRING), ',', CAST(lng AS STRING))), SUM(sample_hours),
             ROUND(SUM(temp_sum), 3), ROUND(IFNULL(SUM(precip_sum), 0), 3)
      FROM \`${AGG}\` WHERE window_start = DATE '$VS' AND sample_hours > 0" | tail -n +2)
    echo "window $VS..$VE raw=$RAWSUM aggregate=$AGGSUM (grid_points,hours,temp_sum,precip_sum)"
    python3 - "$RAWSUM" "$AGGSUM" <<'PY' || { echo "FAIL: aggregate differs from raw"; exit 1; }
import sys
r = [float(x) for x in sys.argv[1].split(",")]; a = [float(x) for x in sys.argv[2].split(",")]
ok = len(r) == len(a) == 4 and all(abs(x - y) <= 1e-6 * max(1.0, abs(x)) + 0.002 for x, y in zip(r, a))
sys.exit(0 if ok else 1)
PY
    echo "OK: aggregate matches raw for window $VS"
  fi
  exit 0
fi

insert_sql() { # $1=start $2=end
cat <<SQL
INSERT INTO \`${AGG}\`
WITH hourly AS ($(raw_select "$1" "$2"))
SELECT
  lat, lng, DATE '$1' AS window_start, DATE '$2' AS window_end,
  COUNT(*) AS sample_hours,
  SUM(temp) AS temp_sum, MIN(temp) AS temp_min, MAX(temp) AS temp_max,
  SUM(rain) AS precip_sum,
  SUM(hum) AS humidity_sum, COUNTIF(hum IS NOT NULL) AS humidity_n,
  MIN(t) AS first_observed_at, MAX(t) AS last_observed_at,
  CURRENT_TIMESTAMP() AS loaded_at
FROM hourly
WHERE NOT EXISTS (SELECT 1 FROM \`${AGG}\` WHERE window_start = DATE '$1')
GROUP BY lat, lng
SQL
}

# Touches only the small aggregate table: marks a window as done when it had no raw rows.
sentinel_sql() { # $1=start $2=end
cat <<SQL
INSERT INTO \`${AGG}\` (window_start, window_end, sample_hours, loaded_at)
SELECT DATE '$1', DATE '$2', 0, CURRENT_TIMESTAMP()
FROM (SELECT 1)
WHERE NOT EXISTS (SELECT 1 FROM \`${AGG}\` WHERE window_start = DATE '$1')
SQL
}

loaded=0; total_bytes=0
while read -r START END; do
  [ -n "${START:-}" ] || continue
  if printf '%s\n' "$DONE" | grep -qx "$START"; then continue; fi
  [ "$loaded" -lt "$MAX_CHUNKS" ] || { echo "Reached MAX_CHUNKS=$MAX_CHUNKS; run again tomorrow."; break; }
  SQL=$(insert_sql "$START" "$END")
  # The estimate is the identical raw scan as the INSERT.
  EST_SQL="$(raw_select "$START" "$END")"
  BYTES=$(bq_q --dry_run --format=json "$EST_SQL" 2>&1 | python3 -c '
import json,re,sys
t=sys.stdin.read()
m=re.search(r"process (\d+) bytes",t) or re.search(r"\"totalBytesProcessed\": \"(\d+)\"",t)
print(m.group(1) if m else "")')
  if [ -z "$BYTES" ]; then echo "Dry run failed for $START; stopping."; exit 1; fi
  echo "window $START..$END dry-run bytes=$BYTES"
  if [ "$BYTES" -ge "$CAP_BYTES" ]; then echo "  skipped: estimate is not below 1 GiB"; continue; fi
  total_bytes=$((total_bytes + BYTES))
  [ "$MODE" = "apply" ] || continue
  bq_q --maximum_bytes_billed="$CAP_BYTES" "$SQL" >/dev/null
  bq_q "$(sentinel_sql "$START" "$END")" >/dev/null
  echo "  loaded"
  loaded=$((loaded + 1))
done <<< "$WINDOWS"
echo "mode=$MODE windows_loaded=$loaded estimated_bytes_considered=$total_bytes"
[ "$MODE" = "apply" ] || echo "Dry run only. Re-run with --apply, then --verify."
