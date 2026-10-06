# Installing step by step

For people who have not used Python before. It takes about 15 minutes and an
internet connection. Git is not needed. Python comes with Miniconda, a small
installer that works the same on Windows, macOS and Linux.

## 1. Install Miniconda

- **Windows**: download
  [Miniconda3-latest-Windows-x86_64.exe](https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe),
  run it and keep the defaults.
- **macOS**: download the installer for your chip and click through it. Apple
  menu, *About This Mac*, *Chip*: an *Apple M* chip takes
  [Miniconda3-latest-MacOSX-arm64.pkg](https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.pkg),
  an Intel chip takes
  [Miniconda3-latest-MacOSX-x86_64.pkg](https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-x86_64.pkg).
- **Ubuntu**: press Ctrl+Alt+T for a terminal and type

  ```
  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  bash Miniconda3-latest-Linux-x86_64.sh
  ```

  Press Enter to read the licence, type `yes`, press Enter for the default
  location, and type `yes` when asked to initialize conda. Then close the
  terminal.

Other systems: the [Miniconda page](https://www.anaconda.com/docs/getting-started/miniconda/install)
has every installer.

## 2. Open a terminal

- **Windows**: press the Start key, type `Anaconda Prompt`, press Enter. Use
  this prompt, not PowerShell, for everything below.
- **macOS**: press Cmd+Space, type `Terminal`, press Enter.
- **Ubuntu**: press Ctrl+Alt+T.

The prompt starts with `(base)`. Check:

```
conda --version
```

It prints `conda` and a version number. If not, see the end of this page.

## 3. Make an environment

An environment is a folder that holds the Python packages of this app, apart
from everything else on the computer.

```
conda create -n bird-map python=3.12
conda activate bird-map
```

Answer `y` when asked. The prompt now starts with `(bird-map)`. Type the
`conda activate bird-map` line every time you open a new terminal to use the
app.

## 4. Install the app

```
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install https://github.com/fkariminejadasl/bird-behavior-map/archive/refs/heads/main.zip
```

This takes a few minutes; PyTorch alone is a few hundred megabytes. The second
line downloads this repository as a zip file, so git is not needed. To update
to a newer version later, run it again with `--force-reinstall --no-deps`
added after `install`.

## 5. Give the database account

Downloading data needs an account on the e-ecology database. Store the user
name and password in the environment, once:

```
conda env config vars set DB_USER=name DB_PASS=secret
conda deactivate
conda activate bird-map
```

Skip this step if someone gave you the CSV file already.

## 6. Make the data and run the app

```
mkdir bird-map
cd bird-map
python -m bird_behavior_map.make_data --device 6004 --start 2013-05-24 --end 2013-05-31 --output 6004.csv
python -m bird_behavior_map.app 6004.csv
```

Open [http://127.0.0.1:8050](http://127.0.0.1:8050) in a browser. The files
are written in the `bird-map` folder. Stop the app with Ctrl+C in the
terminal. The [README](README.md) says what the app shows and what else
`make_data` can read.

## If something goes wrong

| message | what to do |
|---|---|
| `conda is not recognized` (Windows) | This is PowerShell or cmd. Open the *Anaconda Prompt* from the Start menu instead. |
| `conda: command not found` (macOS, Ubuntu) | Close the terminal and open a new one. If it stays, run `~/miniconda3/bin/conda init` and open a new terminal again. |
| `No module named bird_behavior_map` | The environment is off. Type `conda activate bird-map`. |
| `Set DB_USER and DB_PASS, or give --database-url` | Step 5. The last two lines, deactivate and activate, are needed. |
| `No bursts with a GPS fix in this range` | The device recorded no accelerometer data then. Try another range. |
| `Address already in use` | Another program uses port 8050. Add a port: `python -m bird_behavior_map.app 6004.csv 8060`, and open 127.0.0.1:8060. |
