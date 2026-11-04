#!/bin/bash
# Every night: classify this month again, one CSV per tracker, the same files
# as backfill.sh. During the first days of a month, last month is done again
# too: trackers send their data when the bird is near an antenna, so data can
# arrive days late. Each file is replaced, so no burst is written twice.
#
# Start it from cron, for example every night at 03:00 (crontab -e):
#     0 3 * * * /path/to/bird-behavior-map/scripts/nightly.sh >> $HOME/behavior/nightly.log 2>&1
#
# Settings: the same file as backfill.sh, by default ~/behavior/settings.env,
# with DB_USER, DB_PASS, TRACKERS, PYTHON and OUT_DIR. LATE_DAYS (default 7)
# is how many days late data may arrive.

SETTINGS=${SETTINGS:-$HOME/behavior/settings.env}
[ -f "$SETTINGS" ] && source "$SETTINGS"
TRACKERS=${TRACKERS:?set TRACKERS, e.g. TRACKERS=\"6004 6011\", in $SETTINGS}
PYTHON=${PYTHON:-$HOME/behavior/venv/bin/python}
OUT_DIR=${OUT_DIR:-$HOME/behavior/out}
LATE_DAYS=${LATE_DAYS:-7}
mkdir -p "$OUT_DIR"

# This month, and the month of LATE_DAYS ago if that is another one.
months=$(printf '%s\n' "$(date -u -d "$LATE_DAYS days ago" +%Y-%m)" \
    "$(date -u +%Y-%m)" | sort -u)

for month in $months; do
    for device in $TRACKERS; do
        echo "$(date -u '+%F %T') tracker $device, $month"
        "$PYTHON" -u -m bird_behavior_map.write_behavior --device "$device" \
            --start "$month-01" \
            --end "$(date -u -d "$month-01 +1 month -1 day" +%F)" \
            --output "$OUT_DIR/behavior_${device}_$month.csv" \
            --per-fix "$OUT_DIR/behavior_per_fix_${device}_$month.csv"
    done
done
