"""Write the behavior of every burst to a CSV, one row per burst.

The data, the filters and the model are those of make_data.py; only the output
differs. make_data.py writes one row per sample, which the map app needs. This
writes one row per burst, which other apps need, and which a database table of
behaviors would hold. Columns, with a header:

    device_info_serial  tracker
    date_time           time of the GPS fix, UTC
    first_index         index of the first sample of the burst: 0, 20, 40, ...
    burst_time          time of that sample: date_time + first_index x 0.05 s
                        (20 samples per second), as in gulliver-behavior-classifier
    model               the model that made the class, e.g. exp197
    class_id            class number, as in the app CSV
    class_name          class name, e.g. Flap
    confidence          probability of the class, 0 to 1

A fix with 200 samples gives 10 rows. Bursts dropped by the filters (missing
values, no GPS fix in the same second, GPS speed of 30 m/s or more) have none.

    python -m bird_behavior_map.write_behavior --device 6004 --start 2013-05-24 --end 2013-05-31 --output 6004_behavior.csv
    python -m bird_behavior_map.write_behavior --device 6004 6011 --start 2013-05-01 --end 2013-05-31 --output behavior.csv

The database needs the DB_USER and DB_PASS environment variables, or
--database-url.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from bird_behavior_map import database, make_data, model

SAMPLE_RATE = 20  # samples per second, as in the training data
MODEL_NAME = "exp197"


def to_bursts(
    df: pd.DataFrame, model_name: str, glen: int = model.GLEN
) -> pd.DataFrame:
    """One row per burst from the rows make_data.prepare returns, `glen` per
    burst."""
    index = df[2].to_numpy().reshape(-1, glen)
    times = df[1].to_numpy().reshape(-1, glen)
    if not ((np.diff(index, axis=1) == 1).all() and (times == times[:, :1]).all()):
        raise ValueError(f"The rows are not bursts of {glen} consecutive samples")

    first = df.iloc[::glen]
    fix_time = pd.to_datetime(first[1].to_numpy())
    burst_time = fix_time + pd.to_timedelta(first[2].to_numpy() / SAMPLE_RATE, "s")
    return pd.DataFrame(
        {
            "device_info_serial": first[0].to_numpy(),
            "date_time": first[1].to_numpy(),
            "first_index": first[2].to_numpy(),
            "burst_time": burst_time.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3],
            "model": model_name,
            "class_id": first[8].to_numpy(),
            "class_name": first[8].map(model.ind2name).to_numpy(),
            "confidence": first[9].to_numpy(),
        }
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--device", type=int, nargs="+", required=True, help="one or more trackers"
    )
    parser.add_argument(
        "--start", required=True, help="first time, YYYY-MM-DD [HH:MM:SS]"
    )
    parser.add_argument("--end", required=True, help="last time, inclusive")
    parser.add_argument("--output", type=Path, required=True, help="the CSV to write")
    parser.add_argument(
        "--model", default=MODEL_NAME, help="name stored with each class"
    )
    parser.add_argument("--checkpoint", type=Path, default=model.CHECKPOINT)
    parser.add_argument("--database-url", help="default: from DB_USER and DB_PASS")
    parser.add_argument(
        "--chunk-days", type=int, default=30, help="days per database query"
    )
    args = parser.parse_args(argv)

    url = args.database_url or database.database_url()
    parts = []
    for device in args.device:
        try:
            df = database.download(
                url, device, args.start, args.end, model.GLEN, args.chunk_days
            )
        except ValueError as error:  # no calibration, or no bursts in this range
            print(f"{device}: {error}")
            continue
        rows = to_bursts(make_data.prepare(df, args.checkpoint), args.model)
        print(f"{device}: {len(rows)} bursts")
        parts.append(rows)
    if not parts:
        raise SystemExit("No bursts to write")

    rows = pd.concat(parts)
    rows.to_csv(args.output, index=False, float_format="%.6f")
    print(f"{len(rows)} bursts written to {args.output}")


if __name__ == "__main__":
    main()
