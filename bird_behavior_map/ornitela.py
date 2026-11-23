"""Read an Ornitela export: one CSV with GPS rows and accelerometer rows.

The rules of bird-behavior (`docs/methods.md`, Ornitela data, and
`scripts/data/bird_behavior_app_data.py::prepare_calibrated_app_data`):

1. A burst is the SENSORS rows of one device with the same time. Only whole
   bursts of 20 are kept: 45 rows give 40 (two bursts), 15 give none. Rows are
   numbered from 0; the export has no index, so a missing sample cannot be
   found.
2. Each burst takes the GPS fix of the same device that is nearest in time, at
   most 2 s before or after, and the earlier one when two are equally near.
   Fixes without a position, or at latitude 0 and longitude 0, are not used.
   A burst without such a fix is dropped.
3. x and y are swapped, to the UvA-BiTS axes the model learned: the model's x
   is Ornitela `y_g`, and its y is `x_g`.
4. The speed goes from km/h to m/s.

The acceleration is already in g. The time of a row is the time of its burst,
not of its fix.

`nearest_fix` (rule 2) does not depend on the file, so Ornitela data read from
the database can use it too. `is_export` and `read_export` are only for the
file and can go once the data is in the database.
"""

from pathlib import Path

import pandas as pd

COLUMNS = [
    "device_id",
    "UTC_datetime",
    "datatype",
    "Latitude",
    "Longitude",
    "Altitude_m",
    "speed_km_h",
    "x_g",
    "y_g",
    "z_g",
]
TOLERANCE = pd.Timedelta(seconds=2)
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def nearest_fix(
    samples: pd.DataFrame, fixes: pd.DataFrame, tolerance: pd.Timedelta = TOLERANCE
) -> pd.DataFrame:
    """Give every sample the fix of the same device nearest in time.

    Both tables have the columns device_id and time (datetime). A fix at most
    `tolerance` before or after counts; when two are equally near, the earlier
    one. The fix's other columns are added, and its time as `fix_time`.
    Samples without a fix are dropped; the others keep their order.
    """
    fixes = fixes.rename(columns={"time": "fix_time"}).sort_values(
        "fix_time", kind="stable"
    )
    matched = pd.merge_asof(
        samples.reset_index(names="_order").sort_values("time", kind="stable"),
        fixes,
        left_on="time",
        right_on="fix_time",
        by="device_id",
        direction="nearest",
        tolerance=tolerance,
    )
    matched = matched[matched["fix_time"].notna()]
    return matched.sort_values("_order").drop(columns="_order").reset_index(drop=True)


def is_export(path: Path) -> bool:
    """True when the file's header is that of an Ornitela export."""
    return {"datatype", "x_g", "y_g", "z_g"} <= set(pd.read_csv(path, nrows=0).columns)


def read_export(path: Path, glen: int = 20) -> pd.DataFrame:
    """The bursts of an Ornitela export, in app format: columns 0 to 12,
    device_id, date_time, index, -1, x, y, z, gps_speed, -1, -1, latitude,
    longitude, altitude."""
    df = pd.read_csv(path, usecols=COLUMNS)
    df["time"] = pd.to_datetime(df["UTC_datetime"], format=TIME_FORMAT)

    has_position = (
        df["Latitude"].notna()
        & df["Longitude"].notna()
        & ~(df["Latitude"].eq(0) & df["Longitude"].eq(0))
    )
    fixes = df.loc[
        df["datatype"].eq("GPS") & has_position,
        ["device_id", "time", "Latitude", "Longitude", "Altitude_m", "speed_km_h"],
    ]
    samples = df.loc[
        df["datatype"].eq("SENSORS"), ["device_id", "time", "x_g", "y_g", "z_g"]
    ]
    samples = nearest_fix(samples, fixes)

    burst = samples.groupby(["device_id", "time"])
    index = burst.cumcount()
    size = burst["time"].transform("size")
    whole = index < size - size % glen
    samples, index = samples[whole], index[whole]

    return pd.DataFrame(
        {
            0: samples["device_id"],
            1: samples["time"].dt.strftime(TIME_FORMAT),
            2: index,
            3: -1,
            4: samples["y_g"],  # x and y swapped, rule 3
            5: samples["x_g"],
            6: samples["z_g"],
            7: samples["speed_km_h"] / 3.6,
            8: -1,
            9: -1,
            10: samples["Latitude"],
            11: samples["Longitude"],
            12: samples["Altitude_m"],
        }
    ).reset_index(drop=True)
