# bird-behavior-map

Interactive app mapping bird GPS tracks, coloured by behavior predicted from
accelerometer bursts and GPS speed.

Each point on the map is one burst: 20 accelerometer samples at 20 Hz, taken
at a GPS fix. Its colour is the behavior a trained classifier predicts for it.
Click a point to see its accelerometer trace. Where a burst also has an expert
label, the app shows both.

## Install

Python 3.10 or newer. Git is not needed: pip downloads the repository itself.

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install https://github.com/fkariminejadasl/bird-behavior-map/archive/refs/heads/main.zip
```

New to Python? [INSTALL.md](INSTALL.md) goes through it step by step on
Windows, macOS and Linux. The classifier is small and runs on the processor,
so the CPU build of PyTorch is enough. The trained weights ship inside the
package.

## Make the data

The app reads one CSV. `make_data.py` writes it, from three kinds of input:

| input | command |
|---|---|
| the e-ecology database | `python -m bird_behavior_map.make_data --device 6004 --start 2013-05-24 --end 2013-05-31 --output 6004.csv` |
| an 8-column CSV, no GPS fix yet | `python -m bird_behavior_map.make_data --input imu.csv --output out.csv` |
| a 12- or 13-column CSV | `python -m bird_behavior_map.make_data --input app.csv --output out.csv` |

The first two need the database account: `export DB_USER=... DB_PASS=...`, or
`--database-url postgresql://user:password@pub.e-ecology.nl:5432/eecology`.
`--start` and `--end` are inclusive, as `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`.

In every case the rows are sorted by device, time and index, bursts with a GPS
speed of 30 m/s or more are dropped (sensor error), the acceleration is clipped
to [-2, 2] g, and every burst gets a class and a confidence.

## Run the app

```bash
python -m bird_behavior_map.app 6004.csv        # http://127.0.0.1:8050
python -m bird_behavior_map.app 6004.csv 8060   # another port
```

- **Bird/device** and the **time window** slider choose what the map shows.
- **Inspect point**: click a burst to see its accelerometer trace, predicted
  and expert label, confidence, GPS speed and altitude.
- **Select region**: click a start and an end burst. The altitude and GPS speed
  of the bursts in between are plotted below the map.
- **Apply label to selected region** changes the label of those bursts. The
  whole CSV is rewritten to `<input>_relabelled.csv`, and one line per change
  goes to `<input>_label_changes.csv`, both next to the input. The input file
  itself is not changed.

## Data format

CSV without header, one row per accelerometer sample, 20 rows per burst. A
burst is one `device_id` and `date_time`. A fix carries 20, 40 or 60 samples,
that is 1 to 3 bursts.

| column | value |
|---|---|
| device_id | tracker number |
| date_time | time of the GPS fix, `YYYY-MM-DD HH:MM:SS` UTC, the same for the 20 rows of a burst |
| index | sample number within the fix, from 0 |
| gt_label | expert label, -1 when there is none |
| imu_x, imu_y, imu_z | acceleration in g |
| gps_speed | 2D speed of the fix, m/s |
| label | predicted class |
| confidence | its probability |
| latitude, longitude | of the fix |
| altitude | of the fix, m. Optional: shown as -1 when the column is missing |

Classes: 0 Flap, 1 ExFlap, 2 Soar, 3 Boat, 4 Float, 5 SitStand, 6 TerLoco,
7 Other, 8 Manouvre, 9 Pecking. The classifier never predicts 7.

## Model

A small one-dimensional convolutional network, `BirdModelSmallDilated`,
trained in [bird-behavior](https://github.com/fkariminejadasl/bird-behavior)
(experiment 197). The same network and weights are in
[gulliver-behavior-classifier](https://github.com/fkariminejadasl/gulliver-behavior-classifier),
whose [METHODS.md](https://github.com/fkariminejadasl/gulliver-behavior-classifier/blob/main/METHODS.md)
describes the data rules, the model and its training.
