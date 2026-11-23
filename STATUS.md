# Status

## Maybe to do

- **Less memory for large Ornitela exports.** `make_data` on an export of 15
  tags over two months (2.7 GB, 659,656 bursts) took 2 minutes and 9.4 GB of
  memory; reading the file alone took 8.7 GB (measured 2026-11-23). For now
  the README asks to cut a large file into pieces. To lower it: read
  `datatype` as a category and the time straight as a date, or read the file
  in pieces.

## To remove later: reading Ornitela files

Ornitela data comes as a file now, and will come from the database later.
Then reading the file can go:

- `bird_behavior_map/ornitela.py`: `is_export`, `read_export`, `COLUMNS` and
  `TIME_FORMAT`. Keep `nearest_fix` and `TOLERANCE`: data from the database
  needs the same pairing of a burst with its GPS fix.
- `bird_behavior_map/make_data.py`: the first two lines of `load_input`
  (`if ornitela.is_export(path): ...`), the Ornitela export in the docstring
  and in the `--input` help, and `ornitela` in the import if no longer used.
- `README.md`: the Ornitela row of the input table in "Make the data" and the
  paragraph under it.
- `examples/243354_ornitela.csv`.

## For Ornitela in the database

- Pair each burst with `ornitela.nearest_fix` instead of `database.match_gps`,
  which needs a fix in the same second. The file rule allows 2 s; on the test
  database bursts started 0 to 3 s after their fix, so check the limit there.
- Calibration: Ornitela tags have none in the database. bird-behavior uses
  `ORNITELA_ACC_SCALE` (1058.8) or estimates it from the data
  (`behavior/data.py::acc_calibrate`).
