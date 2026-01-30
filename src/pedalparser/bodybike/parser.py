import json
import os
from datetime import datetime, timedelta, timezone
from os import PathLike
from typing import IO, Any, Callable, TypeVar
from zipfile import ZipFile

import numpy as np

from .models import (
    AppInfo,
    ApplicationSettings,
    BodyBikeExport,
    Gender,
    InvalidBodyBikeExport,
    LevelSystem,
    MedalLevel,
    Metric,
    MetricRanges,
    TrainingLevel,
    Unit,
    UserSettings,
    Workout,
    WorkoutCollection,
)

T = TypeVar("T")


def load(path: str | PathLike[str] | IO[bytes]) -> BodyBikeExport:
    """Load an exported BodyBike archive.

    The file must be exported from your BodyBike app, and the file must be
    moved manually to your computer. Call this function with the path to get
    an object representation of the file content.

    Args:
        path: Path to the exported BodyBike archive.

    Returns:
        A BodyBikeExport object holding all information in the archive.

    Raises:
        InvalidBodyBikeExport: The file is not a valid BodyBike export archive.
    """
    with ZipFile(path, "r") as zf:
        # Meta data is loaded directly to the appropriate data classes
        app_info = _parse(zf, "appInfo", _load_app_info)
        app_settings = _parse(zf, "applicationSettings", _load_app_settings)
        user_settings = _parse(zf, "userSettings", _load_user_settings)

        # For workouts, we load meta data first, then merge with the workout
        # specific data later to avoid having to incrementally build the
        # data classes. The first line just reads the raw JSON data.
        aggregated_data = _parse(zf, "workoutHistory", lambda x: x)
        workouts = _load_workouts(zf, aggregated_data)

    return BodyBikeExport(
        app_info=app_info,
        app_settings=app_settings,
        user_settings=user_settings,
        workouts=workouts,
    )


def _parse(zf: ZipFile, name: str, loader: Callable[[Any], T]) -> T:
    """Load a JSON file from the zip and parse it with the given loader."""
    try:
        with zf.open(os.path.join("files", name)) as f:
            data = json.load(f)
    except KeyError:
        raise InvalidBodyBikeExport(f"Missing required file: '{name}'")
    except json.JSONDecodeError as e:
        raise InvalidBodyBikeExport(f"Invalid JSON file: '{name}': {e}")

    try:
        return loader(data)
    except KeyError as e:
        raise InvalidBodyBikeExport(f"Missing field {e} in '{name}'")
    except (ValueError, TypeError) as e:
        raise InvalidBodyBikeExport(f"Invalid data in '{name}': {e}")


def _load_app_info(data: Any) -> AppInfo:
    """App info is as of now a single value on JSON format"""
    return AppInfo(version=data["version"])


def _load_app_settings(data: Any) -> ApplicationSettings:
    """Theme is the only application setting open to normal users"""
    ranges = data["ranges"]
    return ApplicationSettings(
        theme_name=data["themeName"],
        ranges=MetricRanges(
            power=tuple(ranges["power"]),
            cadence=tuple(ranges["cadence"]),
            heartrate=tuple(ranges["heartrate"]),
            calories=tuple(ranges["calories"]),
            distance=tuple(ranges["distance"]),
        ),
        ant_plus_enabled=data["antPlusEnabled"],
    )


def _load_level_system(data: Any) -> LevelSystem:
    """The level system tracks weekly and overall progress"""
    return LevelSystem(
        level=data["level"],
        medal_level=MedalLevel(data["medalLevel"]),
        challenges=tuple(tuple(c) for c in data["challenges"]),
        bronze=data["bronze"],
        silver=data["silver"],
        gold=data["gold"],
        bronze_weeks=data["bronzeWeeks"],
        silver_weeks=data["silverWeeks"],
        gold_weeks=data["goldWeeks"],
        period=data["period"],
    )


def _load_user_settings(data: Any) -> UserSettings:
    """User settings are configurable by the app user"""
    return UserSettings(
        name=data["name"],
        gender=Gender(data["gender"]),
        date_of_birth=datetime.fromisoformat(
            data["dateOfBirth"].replace("Z", "+00:00")
        ),
        weight=data["weight"],
        height=data["height"],
        training_level=TrainingLevel(data["trainingLevel"]),
        heartrate_max=data["heartrateMax"] or None,
        ftp=data["ftp"] or None,
        unit=Unit(data["unit"]),
        level_system=_load_level_system(data["levelSystem"]),
        default_hr_sensor=data["defaultHRSensor"],
    )


def _load_workouts(zf: ZipFile, aggregated_data: list[Any]) -> WorkoutCollection:
    """Load workouts by merging aggregated per-workout data with per-second
    time series files."""
    # Index history by timestamp (milliseconds) for reliable matching
    aggregates = {
        row["sessionBin"]["startDate"]: row["sessionBin"] for row in aggregated_data
    }

    workout_prefix = "files/workout/"
    matched_timestamps: set[int] = set()
    workouts: list[Workout] = []

    for name in zf.namelist():
        if not name.startswith(workout_prefix):
            continue
        filename = name.removeprefix(workout_prefix)
        if not filename:
            continue

        start_time = _parse_workout_filename(filename)
        aggregate = aggregates.get(start_time)
        if aggregate is None:
            raise InvalidBodyBikeExport(
                f"Workout file '{filename}' has no matching history entry"
            )
        matched_timestamps.add(start_time)

        try:
            with zf.open(name) as f:
                samples = json.load(f)
        except json.JSONDecodeError as e:
            raise InvalidBodyBikeExport(f"Invalid JSON in workout '{filename}': {e}")

        workouts.append(_build_workout(start_time, aggregate, samples))

    # Check for history entries without workout files
    if orphaned := set(aggregates.keys()) - matched_timestamps:
        raise InvalidBodyBikeExport(
            f"History entries without workout files: {len(orphaned)} orphaned"
        )

    workouts.sort(key=lambda w: w.start_time)
    return WorkoutCollection(workouts)


def _parse_workout_filename(name: str) -> int:
    """Parse workout filename to milliseconds since epoch.

    Filenames are formatted as 'YYYYMMDDTHHMMSSmmm[Z]', e.g. '20260128T094740403Z'.
    """
    name = name.rstrip("Z")
    dt = datetime.strptime(name[:15], "%Y%m%dT%H%M%S").replace(
        microsecond=int(name[15:18]) * 1000,
        tzinfo=timezone.utc,
    )
    return int(dt.timestamp() * 1000)


def _build_workout(
    start_timestamp_ms: int, aggregate: dict[str, Any], samples: list[Any]
) -> Workout:
    """Build a Workout object from aggregate stats and time series samples."""
    time_ms = np.array([s["startTime"] for s in samples], dtype=np.int64)
    duration_ms = aggregate["endTime"] - aggregate["startTime"]

    return Workout(
        start_time=datetime.fromtimestamp(start_timestamp_ms / 1000, tz=timezone.utc),
        duration=timedelta(milliseconds=duration_ms),
        time_ms=time_ms,
        heartrate=_build_metric(aggregate["heartrate"], samples, "heartrate"),
        cadence=_build_metric(aggregate["cadence"], samples, "cadence"),
        power=_build_metric(aggregate["power"], samples, "power"),
        distance=_build_metric(aggregate["distance"], samples, "distance"),
        calories=_build_metric(aggregate["calories"], samples, "calories"),
        power_zones=tuple(aggregate["powerZones"]),
        power_zones_count=aggregate["powerZonesCount"],
        total=aggregate["total"],
    )


def _build_metric(aggregate: dict[str, Any], samples: list[Any], key: str) -> Metric:
    """Build a Metric object from aggregate stats and time series samples."""
    return Metric(
        value=aggregate["value"],
        max=aggregate["max"],
        min=aggregate["min"],
        mean=aggregate["mean"],
        sum=aggregate["sum"],
        ts=np.array([s[key]["value"] for s in samples], dtype=np.float64),
    )
