"""Read accelerometer bursts and GPS fixes from the e-ecology database.

Copied from bird-behavior: `query_database_improved`, `fetch_calibration_data`,
`fetch_gps_data`, `fetch_imu_data`, `raw2meas`, `calibrate_imu_data`,
`identify_and_process_groups` and `match_gps_to_groups` from
`behavior/data.py`, and `fetch_merge_gps` from
`scripts/data/bird_behavior_app_data.py`.

A burst is 20 accelerometer samples with consecutive indices, all stamped with
the time of one GPS fix. The database holds raw counts; the tracker's
calibration (offset and scale per axis) turns them into g. Dropped: samples
with a missing axis, runs shorter than 20 samples and the tail of a longer
run, and bursts whose fix has no GPS speed.

The connection needs the DB_USER and DB_PASS environment variables, or a full
URL, `postgresql://user:password@pub.e-ecology.nl:5432/eecology`.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg2

HOST = "pub.e-ecology.nl:5432/eecology"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def database_url(user: str | None = None, password: str | None = None) -> str:
    """The connection URL, by default from the DB_USER and DB_PASS variables."""
    user = user or os.getenv("DB_USER")
    password = password or os.getenv("DB_PASS")
    if not user or not password:
        raise ValueError("Set DB_USER and DB_PASS, or give --database-url.")
    return f"postgresql://{user}:{password}@{HOST}"


def query(url: str, sql: str, retries: int = 5, delay: int = 5) -> list[tuple]:
    """Run one SQL query. Retried when the replica cancels it for recovery."""
    for attempt in range(retries):
        try:
            connection = psycopg2.connect(
                url,
                options="-c statement_timeout=60000 -c lock_timeout=5000"
                " -c idle_in_transaction_session_timeout=60000",
            )
            cursor = connection.cursor()
            cursor.execute(sql)
            result = cursor.fetchall()
            cursor.close()
            connection.close()
            return result
        except (psycopg2.OperationalError, psycopg2.errors.QueryCanceled) as e:
            recovery = "canceling statement due to conflict with recovery" in str(e)
            if recovery and attempt < retries - 1:
                print(f"Query conflict with recovery, retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                raise


def _epoch(date_time: datetime) -> int:
    """A naive database time, read as UTC, to whole seconds since the epoch."""
    return int(date_time.replace(tzinfo=timezone.utc).timestamp())


def _text(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(TIME_FORMAT)


def fetch_calibration(url: str, device_id: int) -> list[float]:
    """Offset and scale per axis: [x_o, x_s, y_o, y_s, z_o, z_s]."""
    rows = query(
        url,
        "SELECT x_o, x_s, y_o, y_s, z_o, z_s FROM gps.ee_tracker_limited"
        f" WHERE device_info_serial = {device_id}",
    )
    if not rows:
        raise ValueError(f"No calibration data for device {device_id}")
    return [float(v) for v in rows[0]]


def fetch_gps(url: str, device_id: int, start: str, end: str) -> pd.DataFrame:
    """GPS fixes with a speed, `start` to `end` inclusive.

    Columns: device_id, epoch (int seconds), date_time (text), gps_speed
    (m/s), latitude, longitude, altitude.
    """
    rows = query(
        url,
        "SELECT device_info_serial, date_time, latitude, longitude, altitude,"
        " speed_2d FROM gps.ee_tracking_speed_limited"
        f" WHERE device_info_serial = {device_id}"
        f" AND date_time BETWEEN '{start}' AND '{end}' ORDER BY date_time",
    )
    rows = [
        [r[0], _epoch(r[1]), _text(_epoch(r[1])), float(r[5]), r[2], r[3], r[4]]
        for r in rows
        if r[5] is not None
    ]
    columns = [
        "device_id",
        "epoch",
        "date_time",
        "gps_speed",
        "latitude",
        "longitude",
        "altitude",
    ]
    return pd.DataFrame(rows, columns=columns)


def fetch_imu(url: str, device_id: int, start: str, end: str) -> list[tuple]:
    """Raw accelerometer rows (date_time, index, x, y, z), `start` to `end`
    inclusive, ordered by time and index, without missing values."""
    rows = query(
        url,
        "SELECT date_time, index, x_acceleration, y_acceleration, z_acceleration"
        " FROM gps.ee_acceleration_limited"
        f" WHERE device_info_serial = {device_id}"
        f" AND date_time BETWEEN '{start}' AND '{end}' ORDER BY date_time, index",
    )
    return [r for r in rows if None not in r[2:]]


def calibrate(imu_rows: list[tuple], calibration: list[float]) -> list[list]:
    """Raw counts to g, rounded to 8 decimals: [index, epoch, x, y, z] per row.

    Indices start at 0. A device that counts from 1 is shifted down by one.
    """
    x_o, x_s, y_o, y_s, z_o, z_s = calibration
    shift = 1 if imu_rows and imu_rows[0][1] == 1 else 0
    return [
        [
            r[1] - shift,
            _epoch(r[0]),
            round((r[2] - x_o) / x_s, 8),
            round((r[3] - y_o) / y_s, 8),
            round((r[4] - z_o) / z_s, 8),
        ]
        for r in imu_rows
    ]


def group_bursts(rows: list[list], glen: int = 20) -> list[list[list]]:
    """Cut runs of consecutive indices into bursts of `glen` rows.

    A run shorter than `glen` is dropped, and so is the tail of a longer run.
    """
    runs = []
    current = [rows[0]] if rows else []
    for previous, row in zip(rows, rows[1:]):
        if row[0] == previous[0] + 1:
            current.append(row)
        else:
            runs.append(current)
            current = [row]
    if current:
        runs.append(current)

    bursts = []
    for run in runs:
        for i in range(0, len(run) - glen + 1, glen):
            bursts.append(run[i : i + glen])
    return bursts


def match_gps(bursts: list[list[list]], gps: pd.DataFrame) -> list[tuple]:
    """Pair each burst with the fix of its time. Bursts without one are dropped."""
    fixes = {}
    for fix in gps.itertuples(index=False):
        fixes.setdefault(fix.epoch, fix)
    matched = []
    for burst in bursts:
        epochs = {row[1] for row in burst}
        if len(epochs) != 1:
            raise ValueError("Different timestamps for a burst")
        fix = fixes.get(epochs.pop())
        if fix is not None:
            matched.append((burst, fix))
    return matched


def _chunks(start: str, end: str, days: int) -> list[tuple[str, str]]:
    """Split the inclusive range into inclusive pieces of at most `days` days."""
    t0 = datetime.fromisoformat(start)
    t1 = datetime.fromisoformat(end)
    pieces = []
    while t0 <= t1:
        t_next = min(t0 + timedelta(days=days), t1 + timedelta(seconds=1))
        pieces.append(
            (
                t0.strftime(TIME_FORMAT),
                (t_next - timedelta(seconds=1)).strftime(TIME_FORMAT),
            )
        )
        t0 = t_next
    return pieces


def download(
    url: str, device_id: int, start: str, end: str, glen: int = 20, chunk_days: int = 30
) -> pd.DataFrame:
    """The bursts of one device from `start` to `end` inclusive, in app format.

    Columns 0 to 12: device_id, date_time, index, -1, x, y, z, gps_speed, -1,
    -1, latitude, longitude, altitude. The database is asked `chunk_days` at
    a time, to stay under its 60 s limit per query.
    """
    calibration = fetch_calibration(url, device_id)
    rows = []
    for piece_start, piece_end in _chunks(start, end, chunk_days):
        imu = calibrate(fetch_imu(url, device_id, piece_start, piece_end), calibration)
        gps = fetch_gps(url, device_id, piece_start, piece_end)
        for burst, fix in match_gps(group_bursts(imu, glen), gps):
            for index, epoch, x, y, z in burst:
                rows.append(
                    [
                        device_id,
                        _text(epoch),
                        index,
                        -1,
                        x,
                        y,
                        z,
                        fix.gps_speed,
                        -1,
                        -1,
                        fix.latitude,
                        fix.longitude,
                        fix.altitude,
                    ]
                )
    if not rows:
        raise ValueError("No bursts with a GPS fix in this range")
    return pd.DataFrame(rows, columns=range(13))


def add_gps(df: pd.DataFrame, url: str, chunk_days: int = 30) -> pd.DataFrame:
    """Add latitude, longitude and altitude (columns 10 to 12) to 8-column
    data, from the fixes of each device between its first and last time.
    Rows whose time has no fix with a speed are dropped. `df` must be sorted
    by device and time."""
    gps = []
    for device_id, group in df.groupby(0):
        start, end = group.iloc[0, 1], group.iloc[-1, 1]
        for piece_start, piece_end in _chunks(start, end, chunk_days):
            gps.append(fetch_gps(url, int(device_id), piece_start, piece_end))
    gps = pd.concat(gps)[
        ["device_id", "date_time", "latitude", "longitude", "altitude"]
    ]
    gps.columns = [0, 1, 10, 11, 12]
    return df.merge(gps, on=[0, 1], how="inner")
