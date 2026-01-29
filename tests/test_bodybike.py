import json
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


def test_workout_collection_length(data: BodyBikeExport):
    assert len(data.workouts) == 14


def test_workout_collection_indexing(data: BodyBikeExport):
    first = data.workouts[0]
    last = data.workouts[-1]
    assert isinstance(first, Workout)
    assert isinstance(last, Workout)
    assert first.start_time < last.start_time


def test_workout_collection_iteration(data: BodyBikeExport):
    workouts = list(data.workouts)
    assert len(workouts) == 14
    assert all(isinstance(w, Workout) for w in workouts)


def test_workout_collection_contains(data: BodyBikeExport):
    first = data.workouts[0]
    assert first in data.workouts


def test_workout_collection_slicing(data: BodyBikeExport):
    first_three = data.workouts[:3]
    assert isinstance(first_three, WorkoutCollection)
    assert len(first_three) == 3
    assert first_three[0] is data.workouts[0]


def test_workouts_sorted_by_date(data: BodyBikeExport):
    dates = [w.start_time for w in data.workouts]
    assert dates == sorted(dates)


def test_workout_start_time(data: BodyBikeExport):
    first = data.workouts[0]
    expected = datetime.fromtimestamp(1767608564932 / 1000, tz=timezone.utc)
    assert first.start_time == expected


def test_workout_duration(data: BodyBikeExport):
    first = data.workouts[0]
    assert first.duration == timedelta(milliseconds=3601001)
    assert first.duration > timedelta(hours=1)


def test_workout_time_ms_array(data: BodyBikeExport):
    first = data.workouts[0]
    assert isinstance(first.time_ms, np.ndarray)
    assert first.time_ms.dtype == np.int64
    assert len(first.time_ms) == 3601
    assert first.time_ms[0] == 0


def test_workout_power_zones(data: BodyBikeExport):
    first = data.workouts[0]
    assert len(first.power_zones) == 5
    assert first.power_zones[1] == pytest.approx(0.7253540683143571)


def test_metric_aggregate_values(data: BodyBikeExport):
    power = data.workouts[0].power
    assert isinstance(power, Metric)
    assert power.mean == pytest.approx(196.98515095043686)
    assert power.max == 284


def test_metric_time_series(data: BodyBikeExport):
    power = data.workouts[0].power
    assert isinstance(power.ts, np.ndarray)
    assert power.ts.dtype == np.float64
    assert len(power.ts) == 3601
    assert power.ts[0] == 0  # First sample power value


def test_all_metrics_present(data: BodyBikeExport):
    first = data.workouts[0]
    for metric in [
        first.heartrate,
        first.cadence,
        first.power,
        first.distance,
        first.calories,
    ]:
        assert isinstance(metric, Metric)
        assert isinstance(metric.ts, np.ndarray)
        assert len(metric.ts) == len(first.time_ms)


def test_metric_accessor_returns_accessor(data: BodyBikeExport):
    assert isinstance(data.workouts.power, MetricAccessor)
    assert isinstance(data.workouts.heartrate, MetricAccessor)
    assert isinstance(data.workouts.cadence, MetricAccessor)
    assert isinstance(data.workouts.distance, MetricAccessor)
    assert isinstance(data.workouts.calories, MetricAccessor)


def test_metric_accessor_mean_returns_array(data: BodyBikeExport):
    means = data.workouts.power.mean
    assert isinstance(means, np.ndarray)
    assert means.dtype == np.float64
    assert len(means) == len(data.workouts)


def test_metric_accessor_values_match_individual_workouts(data: BodyBikeExport):
    # Collection-level access should match iterating over individual workouts
    expected_means = np.array([w.power.mean for w in data.workouts])
    expected_maxes = np.array([w.power.max for w in data.workouts])
    expected_mins = np.array([w.power.min for w in data.workouts])
    expected_sums = np.array([w.power.sum for w in data.workouts])

    np.testing.assert_array_equal(data.workouts.power.mean, expected_means)
    np.testing.assert_array_equal(data.workouts.power.max, expected_maxes)
    np.testing.assert_array_equal(data.workouts.power.min, expected_mins)
    np.testing.assert_array_equal(data.workouts.power.sum, expected_sums)


def test_metric_accessor_all_metrics(data: BodyBikeExport):
    # Verify all metric accessors work
    for accessor in [
        data.workouts.power,
        data.workouts.heartrate,
        data.workouts.cadence,
        data.workouts.distance,
        data.workouts.calories,
    ]:
        assert len(accessor.mean) == len(data.workouts)
        assert len(accessor.max) == len(data.workouts)
        assert len(accessor.min) == len(data.workouts)
        assert len(accessor.sum) == len(data.workouts)


def test_sliced_collection_has_metric_accessors(data: BodyBikeExport):
    sliced = data.workouts[:5]
    assert len(sliced.power.mean) == 5
    np.testing.assert_array_equal(
        sliced.power.mean,
        data.workouts.power.mean[:5],
    )


def test_start_times_property(data: BodyBikeExport):
    dates = data.workouts.start_times
    assert isinstance(dates, np.ndarray)
    assert dates.dtype == np.dtype("datetime64[ms]")
    assert len(dates) == len(data.workouts)
    # Should be sorted (oldest first)
    assert np.all(dates[:-1] <= dates[1:])


def test_where_returns_workout_collection(data: BodyBikeExport):
    filtered = data.workouts.where(lambda w: True)
    assert isinstance(filtered, WorkoutCollection)


def test_where_filters_by_predicate(data: BodyBikeExport):
    # Filter to workouts with mean power > 250
    high_power = data.workouts.where(lambda w: w.power.mean > 250)
    assert len(high_power) > 0
    assert len(high_power) < len(data.workouts)
    assert all(w.power.mean > 250 for w in high_power)


def test_where_preserves_order(data: BodyBikeExport):
    filtered = data.workouts.where(lambda w: True)
    for orig, filt in zip(data.workouts, filtered):
        assert orig is filt


def test_where_empty_result(data: BodyBikeExport):
    # No workout has negative power
    empty = data.workouts.where(lambda w: w.power.mean < 0)
    assert isinstance(empty, WorkoutCollection)
    assert len(empty) == 0


def test_where_all_match(data: BodyBikeExport):
    # All workouts have positive duration
    all_workouts = data.workouts.where(lambda w: w.duration > timedelta(0))
    assert len(all_workouts) == len(data.workouts)


def test_where_has_metric_accessors(data: BodyBikeExport):
    filtered = data.workouts.where(lambda w: w.power.mean > 250)
    assert isinstance(filtered.power, MetricAccessor)
    assert len(filtered.power.mean) == len(filtered)


def test_where_chained(data: BodyBikeExport):
    # Chain multiple where calls
    result = data.workouts.where(lambda w: w.power.mean > 150).where(
        lambda w: w.heartrate.mean > 100
    )
    assert isinstance(result, WorkoutCollection)
    assert all(w.power.mean > 150 and w.heartrate.mean > 100 for w in result)


def test_closest_to_exact_match(data: BodyBikeExport):
    # Search for exact timestamp of first workout
    first = data.workouts[0]
    found = data.workouts.closest_to(first.start_time)
    assert found is first


def test_closest_to_string_timestamp(data: BodyBikeExport):
    first = data.workouts[0]
    found = data.workouts.closest_to(first.start_time.isoformat())
    assert found is first


def test_closest_to_between_workouts(data: BodyBikeExport):
    # Search for time between first and second workout
    first = data.workouts[0]
    second = data.workouts[1]
    midpoint = first.start_time + (second.start_time - first.start_time) / 2

    # Should return whichever is closer
    found = data.workouts.closest_to(midpoint)
    assert found in (first, second)


def test_closest_to_before_all(data: BodyBikeExport):
    # Search for time before all workouts
    first = data.workouts[0]
    before = first.start_time - timedelta(days=365)
    found = data.workouts.closest_to(before)
    assert found is first


def test_closest_to_after_all(data: BodyBikeExport):
    # Search for time after all workouts
    last = data.workouts[-1]
    after = last.start_time + timedelta(days=365)
    found = data.workouts.closest_to(after)
    assert found is last


def test_closest_to_empty_collection(data: BodyBikeExport):
    empty = data.workouts.where(lambda w: False)
    assert empty.closest_to(datetime.now(timezone.utc)) is None


def test_closest_to_max_distance_within(data: BodyBikeExport):
    first = data.workouts[0]
    near = first.start_time + timedelta(hours=1)
    found = data.workouts.closest_to(near, max_distance=timedelta(hours=2))
    assert found is first


def test_closest_to_max_distance_exceeded(data: BodyBikeExport):
    first = data.workouts[0]
    far = first.start_time - timedelta(days=365)
    found = data.workouts.closest_to(far, max_distance=timedelta(days=1))
    assert found is None


def test_closest_to_naive_datetime(data: BodyBikeExport):
    # Naive datetime should be treated as UTC
    first = data.workouts[0]
    naive = first.start_time.replace(tzinfo=None)
    found = data.workouts.closest_to(naive)
    assert found is first
