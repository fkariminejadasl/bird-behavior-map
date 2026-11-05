#!/bin/bash
# Classify all past months once: one CSV per tracker per month, made by
# bird_behavior_map.write_behavior. Run it once, then let nightly.sh keep the
# recent months up to date; both write the same files.
#
#     scripts/backfill.sh
#
# A month whose files exist is skipped, so a stopped run can simply be started
# again. A busy tracker-month takes about 30 s, mostly downloading.
#
# Settings come from a private file, by default ~/behavior/settings.env:
#     export DB_USER=... DB_PASS=...
#     TRACKERS="6004 6011"
#     PYTHON=~/behavior/venv/bin/python   # the Python with bird-behavior-map
#     OUT_DIR=~/behavior/out              # where the CSVs go
#     FIRST_MONTH=2013-01                 # first month to look at, YYYY-MM
# Each can also be given on the command line, for example a short test:
#     TRACKERS=6004 FIRST_MONTH=2013-05 LAST_MONTH=2013-06 scripts/backfill.sh

SETTINGS=${SETTINGS:-$HOME/behavior/settings.env}
[ -f "$SETTINGS" ] && source "$SETTINGS"
TRACKERS=${TRACKERS:?set TRACKERS, e.g. TRACKERS=\"6004 6011\", in $SETTINGS}
PYTHON=${PYTHON:-$HOME/behavior/venv/bin/python}
OUT_DIR=${OUT_DIR:-$HOME/behavior/out}
FIRST_MONTH=${FIRST_MONTH:-2013-01}
LAST_MONTH=${LAST_MONTH:-$(date -u +%Y-%m)}  # default: this month
mkdir -p "$OUT_DIR"

for device in $TRACKERS; do
    month=$FIRST_MONTH
    while [[ ! "$month" > "$LAST_MONTH" ]]; do
        # The per-fix file is written last, so it exists only for a month
        # that was finished.
        if [ ! -f "$OUT_DIR/behavior_per_fix_${device}_$month.csv" ]; then
            echo "$(date -u '+%F %T') tracker $device, $month"
            "$PYTHON" -u -m bird_behavior_map.write_behavior --device "$device" \
                --start "$month-01" \
                --end "$(date -u -d "$month-01 +1 month -1 day" +%F)" \
                --output "$OUT_DIR/behavior_${device}_$month.csv" \
                --per-fix "$OUT_DIR/behavior_per_fix_${device}_$month.csv"
        fi
        month=$(date -u -d "$month-01 +1 month" +%Y-%m)
    done
done
