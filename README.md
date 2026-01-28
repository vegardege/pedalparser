# Pedal Parser

An open source Python library to read and parse exported data files from stationary bikes.

Currently supports [Body Bike v2.3.4](https://body-bike.com/) which is the brand I use, but feel free to contribute parsers to other versions or bikes.

## Usage

### Loading an export

```python
from pedalparser import bodybike

export = bodybike.load("bodybike-export.zip")

print(len(export.workouts))  # 73
print(export.user_settings.weight)  # 80
print(export.app_info.version)  # "2.3.4"
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

### Collection-level analysis

Access metrics across all workouts with the same API - returns numpy arrays instead of scalars:

```python
ws = export.workouts

# Same attribute path, array instead of scalar
print(ws.power.mean)      # array([185.5, 190.2, 178.3, ...])
print(ws.power.max)       # array([342, 356, 298, ...])
print(ws.heartrate.mean)  # array([145.2, 148.1, 142.5, ...])
```

### Slicing

Slicing returns a new `WorkoutCollection`, so you can chain operations:

```python
recent = export.workouts[-10:]  # Last 10 workouts
print(recent.power.mean)        # array of 10 values
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
recent = export.workouts.where(lambda w: w.start_date >= cutoff)

# Chain filters
intense = (
    export.workouts
    .where(lambda w: w.power.mean > 150)
    .where(lambda w: w.heartrate.mean > 140)
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
plt.plot(ws.start_dates, ws.power.mean)
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
