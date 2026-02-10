import json
import sqlite3
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zipfile import BadZipfile, ZipFile

import numpy as np
import pytest

from pedalparser.bodybike import (
    BodyBikeExport,
    Gender,
    InvalidBodyBikeExport,
    MedalLevel,
    Metric,
    MetricAccessor,
    Unit,
    Workout,
    WorkoutCollection,
    load,
)

# Where to find our sample archive
FIXTURES_DIR = Path(__file__).parent / "files"

# Sentinel object to mark a file or field for deletion in a modified zip
DELETE = object()


def modified_zip(changes: dict) -> BytesIO:
    """Create a modified copy of the test zip.

    This allows us to create invalid archives from the valid sample archive,
    which in turns allows us to test error handling without having to create
    multiple invalid archives.

    Args:
        changes: Dict mapping filename (e.g. "appInfo") to either:
            - DELETE: remove the file entirely
            - dict: fields to modify/delete in that file's JSON
              Use DELETE as a value to remove a field.

    Examples:
        modified_zip({"appInfo": DELETE})  # remove file
        modified_zip({"userSettings": {"gender": DELETE}})  # remove field
        modified_zip({"userSettings": {"weight": 100}})  # change field

    Returns:
        BytesIO containing the modified zip, ready to pass to load().
    """
    buf = BytesIO()
    with (
        ZipFile(FIXTURES_DIR / "bodybike.zip", "r") as src,
        ZipFile(buf, "w") as dst,
    ):
        for info in src.infolist():
            # Extract the simple name (e.g. "appInfo" from "files/appInfo")
            name = info.filename.removeprefix("files/")

            # Skip if file should be deleted
            if changes.get(name) is DELETE:
                continue

            content = src.read(info.filename)

            # Apply field changes if specified
            if name in changes and isinstance(changes[name], dict):
                data = json.loads(content)
                for key, value in changes[name].items():
                    if value is DELETE:
                        data.pop(key, None)
                    else:
                        data[key] = value
                content = json.dumps(data).encode()

            dst.writestr(info, content)

    buf.seek(0)
    return buf


@pytest.fixture
def data() -> BodyBikeExport:
    return load(FIXTURES_DIR / "bodybike.zip")


@pytest.fixture
def workouts(data: BodyBikeExport) -> WorkoutCollection:
    return data.workouts


@pytest.fixture
def workout(workouts: WorkoutCollection) -> Workout:
    return workouts[0]


@pytest.fixture
def empty_workouts(workouts: WorkoutCollection) -> WorkoutCollection:
    return workouts.where(lambda w: False)


#
# Loading and Settings
#


def test_load_app_info(data: BodyBikeExport):
    assert data.app_info.version == "2.3.4"


def test_load_app_settings(data: BodyBikeExport):
    assert data.app_settings.theme_name == "BLACK_ATTACK"
    assert data.app_settings.ranges.power == (0, 500, 1500, 500)
    assert data.app_settings.ant_plus_enabled is False


def test_load_user_settings(data: BodyBikeExport):
    assert data.user_settings.name == "BodyBike"
    assert data.user_settings.gender == Gender.MALE
    assert data.user_settings.weight == 80
    assert data.user_settings.height == 188
    assert data.user_settings.unit == Unit.METRIC
    assert data.user_settings.heartrate_max is None
    assert data.user_settings.ftp is None
    assert data.user_settings.level_system.level == 3
    assert data.user_settings.level_system.medal_level == MedalLevel.GOLD
    assert data.user_settings.level_system.gold == 7


#
# Error Handling
#


def test_error_file_not_found():
    with pytest.raises(FileNotFoundError):
        load("nonexistent_file.zip")


def test_error_not_a_zip():
    with pytest.raises(BadZipfile):
        load(BytesIO(b"not a zip file"))


def test_error_missing_file():
    with pytest.raises(
        InvalidBodyBikeExport,
        match="Missing required file: 'appInfo'",
    ):
        load(modified_zip({"appInfo": DELETE}))


def test_error_invalid_json():
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("files/appInfo", b"not valid json {{{")
    buf.seek(0)
    with pytest.raises(
        InvalidBodyBikeExport,
        match="Invalid JSON file: 'appInfo'",
    ):
        load(buf)


def test_error_missing_field():
    with pytest.raises(
        InvalidBodyBikeExport,
        match="Missing field 'name' in 'userSettings'",
    ):
        load(modified_zip({"userSettings": {"name": DELETE}}))


def test_error_invalid_enum():
    with pytest.raises(
        InvalidBodyBikeExport,
        match="5 is not a valid TrainingLevel",
    ):
        load(modified_zip({"userSettings": {"trainingLevel": 5}}))


def test_error_wrong_type():
    with pytest.raises(
        InvalidBodyBikeExport,
        match="Invalid data in 'applicationSettings':",
    ):
        load(modified_zip({"applicationSettings": {"ranges": "not a dict"}}))


#
# WorkoutCollection
#


def test_workout_collection_length(workouts: WorkoutCollection):
    assert len(workouts) == 14


def test_workout_collection_indexing(workouts: WorkoutCollection):
    first = workouts[0]
    last = workouts[-1]
    assert isinstance(first, Workout)
    assert isinstance(last, Workout)
    assert first.start_time < last.start_time


def test_workout_collection_iteration(workouts: WorkoutCollection):
    items = list(workouts)
    assert len(items) == 14
    assert all(isinstance(w, Workout) for w in items)


def test_workout_collection_contains(workouts: WorkoutCollection, workout: Workout):
    assert workout in workouts


def test_workout_collection_slicing(workouts: WorkoutCollection):
    first_three = workouts[:3]
    assert isinstance(first_three, WorkoutCollection)
    assert len(first_three) == 3
    assert first_three[0] is workouts[0]


def test_workouts_sorted_by_date(workouts: WorkoutCollection):
    dates = [w.start_time for w in workouts]
    assert dates == sorted(dates)


def test_start_times_property(workouts: WorkoutCollection):
    times = workouts.start_times
    assert isinstance(times, np.ndarray)
    assert times.dtype == np.dtype("datetime64[ms]")
    assert len(times) == len(workouts)
    assert np.all(times[:-1] <= times[1:])


def test_durations_property(workouts: WorkoutCollection):
    durations = workouts.durations
    assert isinstance(durations, np.ndarray)
    assert durations.dtype == np.dtype("timedelta64[ms]")
    assert len(durations) == len(workouts)
    assert all(d > np.timedelta64(0, "ms") for d in durations)


#
# Workout
#


def test_workout_start_time(workout: Workout):
    expected = datetime.fromtimestamp(1767608564932 / 1000, tz=timezone.utc)
    assert workout.start_time == expected


def test_workout_duration(workout: Workout):
    assert workout.duration == timedelta(milliseconds=3601001)
    assert workout.duration > timedelta(hours=1)


def test_workout_timestamps_array(workout: Workout):
    assert isinstance(workout.timestamps, np.ndarray)
    assert workout.timestamps.dtype == np.int64
    assert len(workout.timestamps) == 3601
    assert workout.timestamps[0] == 0


def test_workout_power_zones(workout: Workout):
    assert len(workout.power_zones) == 5
    assert workout.power_zones[1] == pytest.approx(0.7253540683143571)


def test_workout_repr(workout: Workout):
    r = repr(workout)
    assert "Workout(" in r
    assert "2026-01-05" in r
    assert "60 min" in r
    assert "W avg)" in r


#
# Metric
#


def test_metric_aggregate_values(workout: Workout):
    assert isinstance(workout.power, Metric)
    assert workout.power.mean == pytest.approx(196.98515095043686)
    assert workout.power.max == 284


def test_metric_time_series(workout: Workout):
    assert isinstance(workout.power.ts, np.ndarray)
    assert workout.power.ts.dtype == np.float64
    assert len(workout.power.ts) == 3601
    assert workout.power.ts[0] == 0


def test_all_metrics_present(workout: Workout):
    for metric in [
        workout.heartrate,
        workout.cadence,
        workout.power,
        workout.distance,
        workout.calories,
    ]:
        assert isinstance(metric, Metric)
        assert isinstance(metric.ts, np.ndarray)
        assert len(metric.ts) == len(workout.timestamps)


#
# MetricAccessor
#


def test_metric_accessor_returns_accessor(workouts: WorkoutCollection):
    assert isinstance(workouts.power, MetricAccessor)
    assert isinstance(workouts.heartrate, MetricAccessor)
    assert isinstance(workouts.cadence, MetricAccessor)
    assert isinstance(workouts.distance, MetricAccessor)
    assert isinstance(workouts.calories, MetricAccessor)


def test_metric_accessor_mean_returns_array(workouts: WorkoutCollection):
    means = workouts.power.mean
    assert isinstance(means, np.ndarray)
    assert means.dtype == np.float64
    assert len(means) == len(workouts)


def test_metric_accessor_values_match_individual_workouts(workouts: WorkoutCollection):
    expected_means = np.array([w.power.mean for w in workouts])
    expected_maxes = np.array([w.power.max for w in workouts])
    expected_mins = np.array([w.power.min for w in workouts])
    expected_sums = np.array([w.power.sum for w in workouts])

    np.testing.assert_array_equal(workouts.power.mean, expected_means)
    np.testing.assert_array_equal(workouts.power.max, expected_maxes)
    np.testing.assert_array_equal(workouts.power.min, expected_mins)
    np.testing.assert_array_equal(workouts.power.sum, expected_sums)


def test_metric_accessor_all_metrics(workouts: WorkoutCollection):
    for accessor in [
        workouts.power,
        workouts.heartrate,
        workouts.cadence,
        workouts.distance,
        workouts.calories,
    ]:
        assert len(accessor.mean) == len(workouts)
        assert len(accessor.max) == len(workouts)
        assert len(accessor.min) == len(workouts)
        assert len(accessor.sum) == len(workouts)
        assert len(accessor.value) == len(workouts)


def test_metric_accessor_repr(workouts: WorkoutCollection):
    r = repr(workouts.power)
    assert r == "MetricAccessor('power', 14 workouts)"


def test_sliced_collection_has_metric_accessors(workouts: WorkoutCollection):
    sliced = workouts[:5]
    assert len(sliced.power.mean) == 5
    np.testing.assert_array_equal(
        sliced.power.mean,
        workouts.power.mean[:5],
    )


def test_workout_collection_repr(workouts: WorkoutCollection):
    r = repr(workouts)
    assert "WorkoutCollection(14 workouts" in r
    assert "2026-01-05" in r
    assert "2026-01-26" in r


def test_workout_collection_repr_empty(empty_workouts: WorkoutCollection):
    assert repr(empty_workouts) == "WorkoutCollection(empty)"


#
# Filtering with where()
#


def test_where_returns_workout_collection(workouts: WorkoutCollection):
    filtered = workouts.where(lambda w: True)
    assert isinstance(filtered, WorkoutCollection)


def test_where_filters_by_predicate(workouts: WorkoutCollection):
    high_power = workouts.where(lambda w: w.power.mean > 250)
    assert len(high_power) > 0
    assert len(high_power) < len(workouts)
    assert all(w.power.mean > 250 for w in high_power)


def test_where_preserves_order(workouts: WorkoutCollection):
    filtered = workouts.where(lambda w: True)
    for orig, filt in zip(workouts, filtered):
        assert orig is filt


def test_where_empty_result(workouts: WorkoutCollection):
    empty = workouts.where(lambda w: w.power.mean < 0)
    assert isinstance(empty, WorkoutCollection)
    assert len(empty) == 0


def test_where_all_match(workouts: WorkoutCollection):
    all_workouts = workouts.where(lambda w: w.duration > timedelta(0))
    assert len(all_workouts) == len(workouts)


def test_where_has_metric_accessors(workouts: WorkoutCollection):
    filtered = workouts.where(lambda w: w.power.mean > 250)
    assert isinstance(filtered.power, MetricAccessor)
    assert len(filtered.power.mean) == len(filtered)


def test_where_chained(workouts: WorkoutCollection):
    result = workouts.where(lambda w: w.power.mean > 150).where(
        lambda w: w.heartrate.mean > 100
    )
    assert isinstance(result, WorkoutCollection)
    assert all(w.power.mean > 150 and w.heartrate.mean > 100 for w in result)


#
# Finding with closest_to()
#


def test_closest_to_exact_match(workouts: WorkoutCollection, workout: Workout):
    found = workouts.closest_to(workout.start_time)
    assert found is workout


def test_closest_to_string_timestamp(workouts: WorkoutCollection, workout: Workout):
    found = workouts.closest_to(workout.start_time.isoformat())
    assert found is workout


def test_closest_to_between_workouts(workouts: WorkoutCollection):
    first = workouts[0]
    second = workouts[1]
    midpoint = first.start_time + (second.start_time - first.start_time) / 2
    found = workouts.closest_to(midpoint)
    assert found in (first, second)


def test_closest_to_before_all(workouts: WorkoutCollection, workout: Workout):
    before = workout.start_time - timedelta(days=365)
    found = workouts.closest_to(before)
    assert found is workout


def test_closest_to_after_all(workouts: WorkoutCollection):
    last = workouts[-1]
    after = last.start_time + timedelta(days=365)
    found = workouts.closest_to(after)
    assert found is last


def test_closest_to_empty_collection(empty_workouts: WorkoutCollection):
    assert empty_workouts.closest_to(datetime.now(timezone.utc)) is None


def test_closest_to_max_distance_within(workouts: WorkoutCollection, workout: Workout):
    near = workout.start_time + timedelta(hours=1)
    found = workouts.closest_to(near, max_distance=timedelta(hours=2))
    assert found is workout


def test_closest_to_max_distance_exceeded(
    workouts: WorkoutCollection, workout: Workout
):
    far = workout.start_time - timedelta(days=365)
    found = workouts.closest_to(far, max_distance=timedelta(days=1))
    assert found is None


def test_closest_to_naive_datetime(workouts: WorkoutCollection, workout: Workout):
    naive = workout.start_time.replace(tzinfo=None)
    found = workouts.closest_to(naive)
    assert found is workout


#
# DataFrame Exports
#


def test_workout_to_pandas(workout: Workout):
    import pandas as pd

    df = workout.to_pandas()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(workout.timestamps)
    assert list(df.columns) == [
        "time_ms",
        "power",
        "heartrate",
        "cadence",
        "distance",
        "calories",
    ]
    np.testing.assert_array_equal(df["power"].values, workout.power.ts)


def test_workout_to_polars(workout: Workout):
    import polars as pl

    df = workout.to_polars()

    assert isinstance(df, pl.DataFrame)
    assert len(df) == len(workout.timestamps)
    assert df.columns == [
        "time_ms",
        "power",
        "heartrate",
        "cadence",
        "distance",
        "calories",
    ]
    np.testing.assert_array_equal(df["power"].to_numpy(), workout.power.ts)


def test_collection_to_pandas(workouts: WorkoutCollection):
    import pandas as pd

    df = workouts.to_pandas()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(workouts)
    assert "start_time" in df.columns
    assert "power_mean" in df.columns
    assert "zone_1" in df.columns
    np.testing.assert_array_equal(df["power_mean"].values, workouts.power.mean)


def test_collection_to_polars(workouts: WorkoutCollection):
    import polars as pl

    df = workouts.to_polars()

    assert isinstance(df, pl.DataFrame)
    assert len(df) == len(workouts)
    assert "start_time" in df.columns
    assert "power_mean" in df.columns
    assert "zone_1" in df.columns
    np.testing.assert_array_equal(df["power_mean"].to_numpy(), workouts.power.mean)


def test_collection_to_dict(workouts: WorkoutCollection):
    d = workouts.to_dict()

    assert isinstance(d, dict)
    assert all(isinstance(v, np.ndarray) for v in d.values())
    assert "start_time" in d
    assert "power_mean" in d
    assert "zone_5" in d
    assert len(d["power_mean"]) == len(workouts)


#
# Markdown Exports
#


def test_workout_to_markdown(workout: Workout):
    md = workout.to_markdown()

    assert isinstance(md, str)
    assert "## Workout:" in md
    assert "### Summary" in md
    assert "### Power Zones" in md
    assert "### Time Series" in md
    assert "Power (W)" in md


def test_workout_to_markdown_custom_interval(workout: Workout):
    md_default = workout.to_markdown()
    md_10s = workout.to_markdown(sample_interval=10)

    # More rows with smaller interval
    default_rows = [line for line in md_default.split("\n") if line.startswith("|")]
    rows_10s = [line for line in md_10s.split("\n") if line.startswith("|")]
    assert len(rows_10s) > len(default_rows)


def test_collection_to_markdown(workouts: WorkoutCollection):
    md = workouts.to_markdown()

    assert isinstance(md, str)
    assert "| Start |" in md
    assert "| Power |" in md
    # Header + separator + 14 data rows = 16 lines starting with |
    table_rows = [line for line in md.split("\n") if line.startswith("|")]
    assert len(table_rows) == 16


def test_empty_collection_to_markdown(empty_workouts: WorkoutCollection):
    md = empty_workouts.to_markdown()

    assert md == "No workouts."


#
# SQLite Export
#


def test_to_sqlite(data: BodyBikeExport, tmp_path: Path):
    db_path = data.to_sqlite(tmp_path / "workouts.db")

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT * FROM workouts").fetchall()
    assert len(rows) == 14

    first = con.execute(
        "SELECT start_time, duration, power_mean FROM workouts WHERE id = 1"
    ).fetchone()
    assert first[0] == data.workouts[0].start_time.isoformat()
    assert first[1] == data.workouts[0].duration.total_seconds()
    assert first[2] == pytest.approx(data.workouts[0].power.mean)
    con.close()


def test_to_sqlite_timeseries(data: BodyBikeExport, tmp_path: Path):
    db_path = data.to_sqlite(tmp_path / "workouts.db")
    workout = data.workouts[0]

    con = sqlite3.connect(db_path)
    count = con.execute(
        "SELECT COUNT(*) FROM timeseries WHERE workout_id = 1"
    ).fetchone()[0]
    assert count == len(workout.timestamps)

    row = con.execute(
        "SELECT power FROM timeseries WHERE workout_id = 1 AND timestamp = ?",
        (int(workout.timestamps[100]),),
    ).fetchone()
    assert row[0] == pytest.approx(float(workout.power.ts[100]))
    con.close()


def test_to_sqlite_schema(data: BodyBikeExport, tmp_path: Path):
    db_path = data.to_sqlite(tmp_path / "workouts.db")

    con = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"workouts", "timeseries"} <= tables

    workout_cols = [
        row[1] for row in con.execute("PRAGMA table_info(workouts)").fetchall()
    ]
    assert "power_mean" in workout_cols
    assert "heartrate_mean" in workout_cols
    assert "distance" in workout_cols
    assert "zone_1" in workout_cols

    ts_cols = [
        row[1] for row in con.execute("PRAGMA table_info(timeseries)").fetchall()
    ]
    assert "workout_id" in ts_cols
    assert "timestamp" in ts_cols
    assert "speed" in ts_cols
    con.close()


def test_to_sqlite_overwrites(data: BodyBikeExport, tmp_path: Path):
    db_path = tmp_path / "workouts.db"
    data.to_sqlite(db_path)
    data.to_sqlite(db_path)

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    assert count == 14
    con.close()
