# Ornitela files

Ornitela data is not in the e-ecology database yet; for now it comes as a
file. This page shows how to make the map from such a file. Once the data is
in the database, Ornitela tags work like UvA-BiTS tags, as in the
[README](README.md), and this page is no longer needed.

First install the app: steps 1 to 4 of [INSTALL.md](INSTALL.md). A database
account is not needed.

## Try the example

The example is about 8 hours of tag 243354 on 1 June 2025, cut from an
export. Type these lines one at a time, pressing Enter after each:

```
conda activate bird-map
mkdir bird-map
cd bird-map
curl -L -O https://github.com/fkariminejadasl/bird-behavior-map/raw/main/examples/243354_ornitela.csv
python -m bird_behavior_map.make_data --input 243354_ornitela.csv --output 243354.csv
python -m bird_behavior_map.app 243354.csv
```

The `curl` line downloads the example, `make_data` adds the behavior, and the
last line starts the map. Open [http://127.0.0.1:8050](http://127.0.0.1:8050)
in a browser, and stop the map with Ctrl+C in the terminal. The `mkdir` line
is only needed the first time.

## Your own file

`make_data` reads the calibrated export: one CSV with a header, with GPS rows
and accelerometer rows (`datatype` GPS or SENSORS), and the columns
`device_id`, `UTC_datetime`, `datatype`, `Latitude`, `Longitude`,
`Altitude_m`, `speed_km_h`, `x_g`, `y_g` and `z_g`. Other columns are not
used. Put the file in the `bird-map` folder, then:

```
python -m bird_behavior_map.make_data --input all_devices_calibrated.csv --output ornitela.csv
python -m bird_behavior_map.app ornitela.csv
```

A large file needs a lot of memory: an export of 15 tags over two months
(2.7 GB) took about 2 minutes and 9.4 GB. With less memory, cut the file into
pieces, for example one per tag or per month, each starting with the header
line.

## What make_data does with the file

1. A burst is the accelerometer rows of one tag with the same time. Only
   whole bursts of 20 rows are kept: 45 rows give 40 (two bursts), 15 give
   none.
2. Each burst takes the GPS fix of the same tag that is nearest in time, at
   most 2 s before or after, and the earlier one when two are equally near.
   Fixes without a position, or at latitude 0 and longitude 0, are not used.
   A burst without such a fix is dropped.
3. x and y are swapped, to the UvA-BiTS axes the model learned.
4. The speed goes from km/h to m/s.

Then, as for all data: bursts with a GPS speed of 30 m/s or more are dropped,
the acceleration is clipped to [-2, 2] g, and every burst gets a class. The
time of a point on the map is that of its burst, about 1 s after its fix.

## Once Ornitela data is in the database

Then it is read like UvA-BiTS data, with `--device`, `--start` and `--end`.
The database holds the calibration and has x and y already swapped, so rules
3 and 4 are not needed. The one difference from UvA-BiTS that stays is rule
2: an Ornitela burst does not start in the same second as its GPS fix, so it
takes the nearest fix. [STATUS.md](STATUS.md) lists what to change and remove
then.
