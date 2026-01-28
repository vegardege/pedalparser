import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from os import PathLike
from typing import IO, Any, Callable, TypeVar, overload
from zipfile import ZipFile

import numpy as np

T = TypeVar("T")


class InvalidBodyBikeExport(Exception):
    """Exception raised if a BodyBike archive could not be parsed.

    This may be because the provided file was not a ZIP archive with the
    expected files, or because one of the files contained unexpected JSON
    keys or values.
    """

    pass


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class MedalLevel(IntEnum):
    NONE = 0
    BRONZE = 1
    SILVER = 2
    GOLD = 3


class Unit(IntEnum):
    METRIC = 0
    IMPERIAL = 1


class TrainingLevel(IntEnum):
    HOURS_1_3 = 0
    HOURS_3_5 = 1
    HOURS_5_8 = 2
    HOURS_8_PLUS = 3


@dataclass(frozen=True, slots=True)
class AppInfo:
    version: str


@dataclass(frozen=True, slots=True)
class MetricRanges:
    # Ranges per metric. The meaning of each int is unclear, as they can't be
    # seen or modified directly in the app. Presumably related to the gauges
    # shown while cycling, e.g. min and max values. Replace with a dataclass
    # if we ever find reliable information about each value's meaning.
    power: tuple[int, int, int, int]
    cadence: tuple[int, int, int, int]
    heartrate: tuple[int, int, int, int]
    calories: tuple[int, int, int, int]
    distance: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    # Theme name, selectable from a hard coded list in the app. Not an enum
    # because themes are likely to change over time.
    theme_name: str

    # These ranges can not be changed in my version of the app. Meaning is not
    # clear, but assumed to be related to the gauges you see while cycling,
    # e.g. min/max and default values.
    ranges: MetricRanges

    # Toggles whether the BodyBike app scans for ANT+ devices. Not set by user.
    ant_plus_enabled: bool


@dataclass(frozen=True, slots=True)
class LevelSystem:
    # User level (number of permanent medals earned)
    level: int

    # Medals earned this week
    medal_level: MedalLevel

    # Indices showing which challenges are required to earn the three medals
    # this week. One tuple per medal, three indices for the three challenges.
    # I have not reverse engineered what each index means, and assume this may
    # change over time anyway, so use the numbers at your own risk.
    challenges: tuple[tuple[int, int, int], ...]

    # Medal count (in total for the user)
    bronze: int
    silver: int
    gold: int

    # Medal streaks (number of consecutive weeks with each medal)
    bronze_weeks: int
    silver_weeks: int
    gold_weeks: int

    # Week number of the exported archive
    period: int


@dataclass(frozen=True, slots=True)
class UserSettings:
    # Name is "BodyBike" in my archive, and I don't think it can be changed
    name: str

    # User provided information, used for HR/FTP calculations
    gender: Gender
    date_of_birth: datetime
    weight: int
    height: int
    training_level: TrainingLevel

    # User defined values or `None` for app estimation based on above fields
    heartrate_max: int | None
    ftp: int | None

    # User can choose metric or imperial. Values are stored in metric either
    # way, the setting is just used to toggle which is displayed in the app.
    unit: Unit

    # User progression, including medals earned and weekly challenges
    level_system: LevelSystem

    # Presumably ID/address of a paired heart rate monitor. I am not using
    # this, reach out if you know more about how it works.
    default_hr_sensor: str


@dataclass(frozen=True, slots=True)
class Metric:
    # Aggregated values from the workout, as calculated by the app. Note that
    # these are not identical to metrics derived from the time series (e.g.
    # `ts.mean()`). I'm not sure why, but assume these are the most accurate.
    value: float
    max: float
    min: float
    mean: float
    sum: float

    # Per second data. Time axis is given as `time_ms` on the parent object.
    ts: np.ndarray


@dataclass(frozen=True, slots=True)
class Workout:
    # Exact time the workout was started, plus start and end offsets in ms
    start_date: datetime
    start_time: int
    end_time: int

    # Shared time axis for all metrics
    time_ms: np.ndarray

    # Metrics aggregates and time series per second
    heartrate: Metric
    cadence: Metric
    power: Metric
    distance: Metric
    calories: Metric

    # How much time was spent in each power zone (1-5)
    power_zones: tuple[float, float, float, float, float]

    # These are always set to 1 and 0 respectively in my exports, not sure what
    # they actually mean. Improve documentations once we understand it better.
    power_zones_count: int
    total: int


class WorkoutCollection(Sequence[Workout]):
    def __init__(self, workouts: list[Workout]):
        self._workouts = workouts

    @overload
    def __getitem__(self, index: int) -> Workout: ...

    @overload
    def __getitem__(self, index: slice) -> list[Workout]: ...

    def __getitem__(self, index: int | slice) -> Workout | list[Workout]:
        return self._workouts[index]

    def __len__(self) -> int:
        return len(self._workouts)


@dataclass(frozen=True, slots=True)
class BodyBikeExport:
    app_info: AppInfo
    app_settings: ApplicationSettings
    user_settings: UserSettings
    workouts: WorkoutCollection


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
    return AppInfo(version=data["version"])


def _load_app_settings(data: Any) -> ApplicationSettings:
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

    workouts.sort(key=lambda w: w.start_date)
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
    start_time: int, aggregate: dict[str, Any], samples: list[Any]
) -> Workout:
    """Build a Workout object from aggregate stats and time series samples."""
    time_ms = np.array([s["startTime"] for s in samples], dtype=np.int64)

    return Workout(
        start_date=datetime.fromtimestamp(start_time / 1000, tz=timezone.utc),
        start_time=aggregate["startTime"],
        end_time=aggregate["endTime"],
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
