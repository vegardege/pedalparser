# Pedal Parser

A Python library for analyzing workout data exported from stationary bikes.

- Load exported archives and access workout metrics (power, heartrate, cadence, distance, calories)
- Per-second time series data as numpy arrays
- Aggregate statistics across workout collections
- Filter, slice, and search workouts
- Export to `pandas` or `polars` DataFrames

## Bike Support

* [Body Bike v2.3.4](https://body-bike.com/) - see [format documentation](docs/BODYBIKE.md) for details and data quirks.

Contributions for other bikes welcome.

## Installation

```bash
pip install pedalparser              # Core library
pip install pedalparser[pandas]      # With pandas support
pip install pedalparser[polars]      # With polars support
```

## Usage

### Loading an export

```python
from pedalparser import bodybike

export = bodybike.load("20260128T120516994Z_backup.zip")

print(len(export.workouts))  # 73
print(export.user_settings.weight)  # 80
print(export.app_info.version)  # "2.3.4"
```

### Collection-level analysis

Access metrics across all workouts with the same API - returns numpy arrays instead of scalars:

```python
ws = export.workouts

# Same attribute path, array instead of scalar
print(ws.power.mean)      # array([185.5, 190.2, 178.3, ...])
print(ws.power.max)       # array([342, 356, 298, ...])
print(ws.heartrate.mean)  # array([145.2, 148.1, 142.5, ...])
```

### Filtering

Use `where()` to filter workouts by any predicate:

```python
from datetime import datetime, timedelta, timezone

# Filter by metric thresholds
high_power = export.workouts.where(lambda w: w.power.mean > 180)
long_rides = export.workouts.where(lambda w: w.duration > timedelta(minutes=60))

# Filter by date
cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
recent = export.workouts.where(lambda w: w.start_time >= cutoff)

# Chain filters
intense = (
    export.workouts
    .where(lambda w: w.power.mean > 200)
    .where(lambda w: w.heartrate.max > 180)
)
```

### Finding a specific workout

Use `closest_to()` to find the workout nearest to a given timestamp:

```python
# Find workout closest to a date
w = export.workouts.closest_to("2026-01-15T10:00:00")

# With a maximum search distance (returns None if nothing within range)
w = export.workouts.closest_to("2026-01-15", max_distance=timedelta(hours=24))
```

### Single workout analysis

```python
w = export.workouts[-1]  # Most recent workout

# Summary statistics
print(w.power.mean)       # 185.5
print(w.power.max)        # 342
print(w.heartrate.mean)   # 145.2

# Time series data (numpy arrays)
print(w.power.ts)         # array([142, 145, 148, ...])
print(w.power.ts.std())   # numpy operations work

# Power zone distribution
print(w.power_zones)      # (0.05, 0.45, 0.30, 0.15, 0.05)
```

### Exporting to pandas or polars

Convert workout data to DataFrames for further analysis. Both pandas and polars are optional dependencies:

```bash
pip install pedalparser[pandas]   # or [polars]
```

**Collection to DataFrame** (one row per workout, aggregate metrics):

```python
df = export.workouts.to_pandas()  # or .to_polars()

# Columns: start_time, duration, power_mean, power_max, heartrate_mean, ...
df.plot(x="start_time", y="power_mean")
```

**Single workout to DataFrame** (time series data):

```python
df = export.workouts[-1].to_pandas()  # or .to_polars()

# Columns: time_ms, power, heartrate, cadence, distance, calories
df.plot(x="time_ms", y="power")
```

### Plotting

```python
import matplotlib.pyplot as plt

# Plot power over time for a single workout
w = export.workouts[-1]
plt.plot(w.time_ms / 1000 / 60, w.power.ts)
plt.xlabel("Time (minutes)")
plt.ylabel("Power (W)")
plt.show()

# Plot average power trend across all workouts
ws = export.workouts
plt.plot(ws.start_times, ws.power.mean)
plt.xlabel("Date")
plt.ylabel("Avg Power (W)")
plt.show()
```

## Development

`pedalparser` uses [uv](https://docs.astral.sh/uv/) as project manager, [Ruff](https://docs.astral.sh/ruff/) for linting/formatting, and [ty](https://docs.astral.sh/ty/) for type checking.

```bash
uv run pytest          # Run tests
uv run ruff check      # Lint
uv run ruff format     # Format
uv run ty check        # Type check
```

## License

MIT

*Note that this project is not affiliated with Body Bike.*
