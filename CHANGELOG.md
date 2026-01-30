# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-01-30

### Added

- Initial release with Body Bike export support
- `bodybike.load()` function to parse exported ZIP archives
- `BodyBikeExport` dataclass with app info, user settings, and workouts
- `WorkoutCollection` with indexing, slicing, iteration, and filtering via `where()`
- `closest_to()` method for finding workouts nearest to a timestamp
- `Metric` objects with summary statistics (`.mean`, `.max`, `.min`, `.sum`) and time series (`.ts`)
- Collection-level metric access returning numpy arrays (e.g., `workouts.power.mean`)
- Export to pandas and polars DataFrames via `to_pandas()` and `to_polars()`
- Markdown export for workouts and workout collections via `to_markdown()`
- Support for Python 3.11+
