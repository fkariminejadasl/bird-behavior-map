"""Make the CSV the app reads: one row per accelerometer sample, with the GPS
fix and the predicted behavior of its burst.

Three ways in:

    python -m bird_behavior_map.make_data --device 6004 --start 2013-05-24 --end 2013-05-31 --output 6004.csv
        downloads the bursts and fixes of one device from the e-ecology database
    python -m bird_behavior_map.make_data --input imu.csv --output out.csv
        an 8-column CSV (device_id, date_time, index, gt_label, x, y, z,
        gps_speed): the fix is added from the database
    python -m bird_behavior_map.make_data --input app.csv --output out.csv
        a 12- or 13-column CSV that already has the fix: only the classes
        are redone

Then, as in bird-behavior `scripts/data/bird_behavior_app_data.py`: rows are
sorted by device, time and index; bursts with a GPS speed of 30 m/s or more are
dropped (sensor error); the acceleration is clipped to [-2, 2] g; every burst
of 20 rows gets a class and a confidence; the file is written without header,
6 decimals.

Output columns:
    device_id, date_time, index, gt_label, imu_x, imu_y, imu_z, gps_speed,
    label, confidence, latitude, longitude, altitude

The database needs the DB_USER and DB_PASS environment variables, or
--database-url.
"""

import argparse
from pathlib import Path

import pandas as pd

from bird_behavior_map import database, model

MAX_SPEED = 30.0  # m/s; faster is sensor error
CLIP = 2.0  # g


def prepare(df: pd.DataFrame, checkpoint: Path, glen: int = model.GLEN) -> pd.DataFrame:
    """Sort, drop fast bursts, clip the acceleration and classify."""
    df = df.sort_values([0, 1, 2])
    df = df[df[7] < MAX_SPEED].copy()
    df[[4, 5, 6]] = df[[4, 5, 6]].clip(-CLIP, CLIP)
    return model.classify(df, model.load_model(checkpoint), glen)


def load_input(path: Path, url: str | None, chunk_days: int) -> pd.DataFrame:
    df = pd.read_csv(path, header=None)
    if df.shape[1] == 8:
        df = df.sort_values([0, 1, 2])
        df[8] = -1
        df[9] = -1
        return database.add_gps(df, url, chunk_days)
    if df.shape[1] >= 12:
        return df
    raise ValueError(f"Expected 8, 12 or 13 columns, found {df.shape[1]}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, help="an 8-, 12- or 13-column CSV")
    parser.add_argument("--device", type=int, help="device to download")
    parser.add_argument("--start", help="first time, YYYY-MM-DD [HH:MM:SS]")
    parser.add_argument("--end", help="last time, inclusive")
    parser.add_argument("--output", type=Path, required=True, help="the CSV to write")
    parser.add_argument("--database-url", help="default: from DB_USER and DB_PASS")
    parser.add_argument(
        "--chunk-days", type=int, default=30, help="days per database query"
    )
    parser.add_argument("--checkpoint", type=Path, default=model.CHECKPOINT)
    args = parser.parse_args(argv)

    download = bool(args.device is not None or args.start or args.end)
    if download == (args.input is not None):
        parser.error("give --input, or --device with --start and --end")
    if download and not (args.device is not None and args.start and args.end):
        parser.error("--device, --start and --end go together")

    url = None
    if download or pd.read_csv(args.input, header=None, nrows=1).shape[1] == 8:
        url = args.database_url or database.database_url()

    if download:
        df = database.download(
            url, args.device, args.start, args.end, model.GLEN, args.chunk_days
        )
    else:
        df = load_input(args.input, url, args.chunk_days)
    n_in = len(df) // model.GLEN

    df = prepare(df, args.checkpoint)
    df.to_csv(args.output, index=False, header=None, float_format="%.6f")
    print(
        f"{len(df) // model.GLEN} bursts written to {args.output}"
        f" ({n_in - len(df) // model.GLEN} dropped for GPS speed >= {MAX_SPEED:g} m/s)"
    )


if __name__ == "__main__":
    main()
