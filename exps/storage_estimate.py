"""How much space the behavior table would take, from the database's own numbers.

A side calculation, not part of the app: it answered "how much storage would
the behavior table need?" (2026-11-05). Read-only: it only asks the database
questions and writes nothing. Run from the repository folder, with the
CSV files of bird_behavior_map.write_behavior as an option:

    python exps/storage_estimate.py
    python exps/storage_estimate.py --csv 6004_behavior.csv --per-fix-csv 6004_behavior_per_fix.csv

The steps:

1. Acceleration samples in the database. PostgreSQL keeps a row count for
   every table in its catalog (pg_class.reltuples: an estimate, refreshed
   when the table is vacuumed or analyzed). Every login can read the catalog,
   also for tables and rows it may not read itself, so this count covers all
   birds of all projects, not only the birds of your login. The view our
   download reads, gps.ee_acceleration_limited, takes its samples from two
   tables, gps.uva_acceleration101_data and gps.ee_bccelero_point, with one
   row per sample.
2. Behavior rows: one per 20 samples (one burst, 1 s at 20 Hz), per model.
   A fix with 200 samples gives 10 rows; how the samples are grouped into
   fixes does not change the total. It is an upper limit: bursts the filters
   drop, and leftover samples (fewer than 20 at the end of a fix), give no
   row.
3. Bytes per row. The server reports the size of a row with the columns of
   sql/behavior.sql (pg_column_size), including PostgreSQL's 24-byte header
   per row. On disk come on top: a 4-byte pointer per row in its 8 kB page,
   an entry in the primary key (an index, used to find and replace rows), and
   a share of the summary per GPS fix (one row per fix, shared by the rows of
   that fix, so it costs less per row when a fix has more bursts). Computed,
   not measured on a real table: how full the primary key's pages get is
   assumed (KEY_FILL).
4. With --csv (and --per-fix-csv), the size of the CSV files of
   write_behavior.py, measured.

Sizes are in decimal units (1 GB = 1,000,000,000 bytes). PostgreSQL's own
tools print 1024-based units, so they show a smaller number (1,969 instead of
2,114 GB for the whole database on 2026-11-05).

The database needs the DB_USER and DB_PASS environment variables, or
--database-url.
"""

import argparse
import math
from pathlib import Path

import pandas as pd

from bird_behavior_map import database

SAMPLES_PER_ROW = 20  # one burst: 1 s at 20 Hz
SAMPLE_TABLES = ["gps.uva_acceleration101_data", "gps.ee_bccelero_point"]

# PostgreSQL storage, in bytes.
PAGE = 8192  # tables and indexes are stored in pages of 8 kB
PAGE_HEADER = 24
BTREE_SPECIAL = 16  # an index page keeps this much for itself
INDEX_ENTRY_HEADER = 8
POINTER = 4  # per row or index entry, in its page
KEY_FILL = 0.8  # assumed: about 0.9 when rows arrive in key order, 0.7 in random order
SUMMARY_INDEX_FILL = 0.9  # the summary's index is rebuilt on every refresh, 90% full

# Typical values. SitStand is the longest class name, so sizes are not too low.
MODEL = "exp197"
CLASS = "SitStand"
FIX_TIME = "'2013-05-24 14:20:30'::timestamp(0)"


def align8(n: int) -> int:
    """PostgreSQL starts each row and each index entry at a multiple of 8 bytes."""
    return (n + 7) // 8 * 8


def bytes_per_entry(size: int, usable: int, fill: float = 1.0) -> float:
    """Page bytes per row or index entry of `size` bytes, pages `fill` full."""
    per_page = math.floor(usable * fill / (align8(size) + POINTER))
    return PAGE / per_page


def row_sizes(url: str, bursts_per_fix: float) -> dict[str, int]:
    """Sizes the server reports, in bytes, header included for whole rows."""
    all_classes = ",".join([CLASS] * math.ceil(bursts_per_fix))
    behavior_row = (
        f"ROW(6004, {FIX_TIME}, 20::smallint, '2013-05-24 14:20:31'::timestamp(3),"
        f" '{MODEL}'::text, 5::smallint, '{CLASS}'::text, 0.998::real, now())"
    )
    key = f"ROW('{MODEL}'::text, 6004, {FIX_TIME}, 20::smallint)"
    summary_row = (
        f"ROW(6004, {FIX_TIME}, '{MODEL}'::text, '{CLASS}'::text,"
        f" '{all_classes}'::text, 3::bigint)"
    )
    summary_key = f"ROW(6004, {FIX_TIME})"
    sql = (
        f"SELECT pg_column_size({behavior_row}), pg_column_size({key}),"
        f" pg_column_size({summary_row}), pg_column_size({summary_key}),"
        f" pg_column_size(ROW())"
    )
    row, key, summary, summary_key, empty = database.query(url, sql)[0]
    return {
        "row": row,
        # An index entry holds the key's values without the row header.
        "key": INDEX_ENTRY_HEADER + key - empty,
        "summary": summary,
        "summary_key": INDEX_ENTRY_HEADER + summary_key - empty,
    }


def per_row(sizes: dict[str, int], bursts_per_fix: float) -> dict[str, float]:
    """Page bytes per behavior row: table, primary key, share of the summary."""
    table = bytes_per_entry(sizes["row"], PAGE - PAGE_HEADER)
    index_usable = PAGE - PAGE_HEADER - BTREE_SPECIAL
    key = bytes_per_entry(sizes["key"], index_usable, KEY_FILL)
    summary_fix = bytes_per_entry(
        sizes["summary"], PAGE - PAGE_HEADER
    ) + bytes_per_entry(sizes["summary_key"], index_usable, SUMMARY_INDEX_FILL)
    return {
        "table": table,
        "key": key,
        "summary_fix": summary_fix,
        "summary": summary_fix / bursts_per_fix,
    }


def samples(url: str) -> list[tuple[str, int, int]]:
    """(table, samples, bytes on disk) of each table that holds samples."""
    names = ", ".join(f"'{name}'::regclass" for name in SAMPLE_TABLES)
    sql = (
        "SELECT c.oid::regclass::text, c.reltuples::bigint, pg_total_relation_size(c.oid)"
        f" FROM pg_class c WHERE c.oid IN ({names})"
    )
    return database.query(url, sql)


def csv_bytes(csv: Path, per_fix_csv: Path | None) -> tuple[float, float, float | None]:
    """Bytes per row of the per-burst CSV, of the per-fix CSV per burst, and
    the mean number of bursts per fix."""
    rows = len(pd.read_csv(csv, usecols=[0]))
    burst = csv.stat().st_size / rows
    if per_fix_csv is None:
        return burst, 0.0, None
    n_bursts = pd.read_csv(per_fix_csv, usecols=["n_bursts"]).n_bursts
    return burst, per_fix_csv.stat().st_size / rows, n_bursts.mean()


def size(n_bytes: float) -> str:
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n_bytes >= scale:
            return f"{n_bytes / scale:,.1f} {unit}"
    return f"{n_bytes:.0f} bytes"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--database-url", help="default: from DB_USER and DB_PASS")
    parser.add_argument("--csv", type=Path, help="a per-burst CSV of write_behavior.py")
    parser.add_argument("--per-fix-csv", type=Path, help="its --per-fix CSV")
    parser.add_argument(
        "--bursts-per-fix",
        type=float,
        help="mean rows per GPS fix; default: from --per-fix-csv, else 2.5",
    )
    args = parser.parse_args()
    url = args.database_url or database.database_url()

    csv = csv_bytes(args.csv, args.per_fix_csv) if args.csv else None
    n = args.bursts_per_fix or (csv[2] if csv and csv[2] else 2.5)

    print("Acceleration samples in the database (all birds of all projects):")
    tables = samples(url)
    for name, count, on_disk in tables:
        print(f"  {name:32} {count:>15,} samples  {size(on_disk)} on disk")
    total = sum(count for _, count, _ in tables)
    rows = total // SAMPLES_PER_ROW
    print(f"  {'total':32} {total:>15,} samples")
    print(
        f"Upper limit of behavior rows, one per {SAMPLES_PER_ROW} samples: {rows:,} per model"
    )

    sizes = row_sizes(url, n)
    parts = per_row(sizes, n)
    one_model = parts["table"] + parts["key"] + parts["summary"]
    extra_model = parts["table"] + parts["key"]
    print("\nBytes per behavior row, computed from the sizes the server reports:")
    print(
        f"  table row            {parts['table']:6.1f}  ({sizes['row']} bytes + pointer, in 8 kB pages)"
    )
    print(
        f"  primary key entry    {parts['key']:6.1f}  (pages assumed {KEY_FILL:.0%} full)"
    )
    print(
        f"  summary              {parts['summary']:6.1f}"
        f"  ({parts['summary_fix']:.0f} bytes per GPS fix, {n:.2f} rows per fix)"
    )
    print(f"  total, one model     {one_model:6.1f}")
    print(
        f"  each extra model     {extra_model:6.1f}  (no summary: it shows one model per tracker)"
    )
    for k in (1, 10):
        other = per_row(row_sizes(url, k), k)
        print(
            f"  total at {k:2} row(s) per fix: {other['table'] + other['key'] + other['summary']:.1f}"
        )

    database_size = database.query(url, "SELECT pg_database_size(current_database())")[
        0
    ][0]
    print(
        f"\nUpper limit, one model: {size(rows * one_model)},"
        f" {rows * one_model / database_size:.1%} of the database ({size(database_size)})"
    )

    if csv:
        burst, fix, mean = csv
        print(f"\nCSV files, measured: {burst:.1f} bytes per row", end="")
        if args.per_fix_csv:
            print(
                f" + {fix:.1f} for the per-fix file = {burst + fix:.1f}; {mean:.2f} rows per fix",
                end="",
            )
        print(f"\nUpper limit as CSV: {size(rows * (burst + fix))}")


if __name__ == "__main__":
    main()
