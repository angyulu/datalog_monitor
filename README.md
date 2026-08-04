# Datalog Monitor

A local Streamlit app for reviewing and comparing process-log CSV runs (pressure, temperature,
gas flow, PV/SV channels) logged by an HA data recorder.

## Features

- Point it at a folder; it recursively finds every run CSV inside, including subfolders.
- Browse runs in a searchable, sortable table (start time, program, duration, row count).
- Tag runs with your own runcard name/ID, searchable alongside timestamps.
- Plot any combination of channels as stacked, linked time-series charts.
- Compare multiple runs at once, aligned on when the run first reaches its growth
  temperature (`Heater PV` reaching its peak `Heater SV`), not on run start time.
- Flags PV/SV pairs that drift outside a configurable tolerance (global default with
  per-channel overrides), both on the chart and in a violations table.
- Background-rescans the folder every 60s to pick up new runs automatically.

## Running from source

Requires Python 3.12+.

```
pip install -r requirements.txt
streamlit run app.py
```

## Running without Python installed

See [`installer/README.md`](installer/README.md) for the portable, no-install build --
a self-contained folder with its own Python runtime that you can copy to any Windows
machine and launch from a desktop shortcut. It checks this repo for updates on every
launch.
