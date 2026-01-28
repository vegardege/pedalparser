import bisect
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum, StrEnum
from os import PathLike
from typing import IO, TYPE_CHECKING, Any, Callable, TypeVar, overload
from zipfile import ZipFile

import numpy as np

if TYPE_CHECKING:
    import pandas as pd  # type: ignore[import-not-found]
    import polars as pl  # type: ignore[import-not-found]


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


class MetricAccessor:
    """Proxy for accessing a metric across all workouts in a collection.

    Provides the same attribute interface as Metric, but returns numpy arrays
    containing values from all workouts in the collection.

    Example:
        >>> collection.power.mean      # np.ndarray of mean power per workout
        >>> collection.power.max       # np.ndarray of max power per workout
        >>> workout.power.mean         # float for single workout
    """

    __slots__ = ("_collection", "_metric")

    def __init__(self, collection: "WorkoutCollection", metric: str):
        self._collection = collection
        self._metric = metric

    @property
    def value(self) -> np.ndarray:
        return np.array(
            [getattr(w, self._metric).value for w in self._collection],
            dtype=np.float64,
        )

    @property
    def max(self) -> np.ndarray:
        return np.array(
            [getattr(w, self._metric).max for w in self._collection],
            dtype=np.float64,
        )

    @property
    def min(self) -> np.ndarray:
        return np.array(
            [getattr(w, self._metric).min for w in self._collection],
            dtype=np.float64,
        )

    @property
    def mean(self) -> np.ndarray:
        return np.array(
            [getattr(w, self._metric).mean for w in self._collection],
            dtype=np.float64,
        )

    @property
    def sum(self) -> np.ndarray:
        return np.array(
            [getattr(w, self._metric).sum for w in self._collection],
            dtype=np.float64,
        )


@dataclass(frozen=True, slots=True)
class Workout:
    # Exact time the workout was started, plus start and end offsets in ms
    start_date: datetime
    start_time: int
    end_time: int

    @property
    def duration(self) -> timedelta:
        """Workout duration."""
        return timedelta(milliseconds=self.end_time - self.start_time)

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

    def to_pandas(self) -> "pd.DataFrame":
        """Convert time series to a pandas DataFrame.

        Returns:
            DataFrame with columns: time_ms, power, heartrate, cadence,
            distance, calories.

        Raises:
            ImportError: If pandas is not installed.
        """
        try:
            import pandas as pd  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError("pandas must be installed to run to_pandas().") from None

        return pd.DataFrame(
            {
                "time_ms": self.time_ms,
                "power": self.power.ts,
                "heartrate": self.heartrate.ts,
                "cadence": self.cadence.ts,
                "distance": self.distance.ts,
                "calories": self.calories.ts,
            }
        )

    def to_polars(self) -> "pl.DataFrame":
        """Convert time series to a polars DataFrame.

        Returns:
            DataFrame with columns: time_ms, power, heartrate, cadence,
            distance, calories.

        Raises:
            ImportError: If polars is not installed.
        """
        try:
            import polars as pl  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError("polars must be installed to run to_polars().") from None

        return pl.DataFrame(
            {
                "time_ms": self.time_ms,
                "power": self.power.ts,
                "heartrate": self.heartrate.ts,
                "cadence": self.cadence.ts,
                "distance": self.distance.ts,
                "calories": self.calories.ts,
            }
        )


class WorkoutCollection(Sequence[Workout]):
    """Immutable, indexable collection of workouts sorted by start_date."""

    __slots__ = ("_workouts",)

    def __init__(self, workouts: Iterable[Workout]):
        self._workouts: tuple[Workout, ...] = tuple(workouts)

    @overload
    def __getitem__(self, index: int) -> Workout: ...

    @overload
    def __getitem__(self, index: slice) -> "WorkoutCollection": ...

    def __getitem__(self, index: int | slice) -> "Workout | WorkoutCollection":
        if isinstance(index, slice):
            return WorkoutCollection(self._workouts[index])
        return self._workouts[index]

    def __len__(self) -> int:
        return len(self._workouts)

    @property
    def power(self) -> MetricAccessor:
        return MetricAccessor(self, "power")

    @property
    def heartrate(self) -> MetricAccessor:
        return MetricAccessor(self, "heartrate")

    @property
    def cadence(self) -> MetricAccessor:
        return MetricAccessor(self, "cadence")

    @property
    def distance(self) -> MetricAccessor:
        return MetricAccessor(self, "distance")

    @property
    def calories(self) -> MetricAccessor:
        return MetricAccessor(self, "calories")

    @property
    def start_dates(self) -> np.ndarray:
        """Start dates as numpy datetime64[ms] array (UTC)."""
        timestamps_ms = [int(w.start_date.timestamp() * 1000) for w in self]
        return np.array(timestamps_ms, dtype="datetime64[ms]")

    @property
    def durations(self) -> np.ndarray:
        """Workout durations as numpy timedelta64[ms] array."""
        ms = [w.end_time - w.start_time for w in self]
        return np.array(ms, dtype="timedelta64[ms]")

    def where(self, predicate: Callable[[Workout], bool]) -> "WorkoutCollection":
        """Filter workouts by predicate. Returns a new collection."""
        return WorkoutCollection(w for w in self if predicate(w))

    def closest_to(
        self,
        timestamp: datetime | str,
        max_distance: timedelta | None = None,
    ) -> Workout | None:
        """Find the workout closest to the given timestamp.

        Args:
            timestamp: Target time as datetime or ISO format string.
            max_distance: Maximum allowed distance from target. If the closest
                workout is further away, returns None.

        Returns:
            The workout with start_date closest to timestamp, or None if the
            collection is empty or no workout is within max_distance.
        """
        if not self._workouts:
            return None

        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        # Ensure timestamp is timezone-aware (assume UTC if naive)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        # Binary search for insertion point
        timestamps = [w.start_date for w in self._workouts]
        idx = bisect.bisect_left(timestamps, timestamp)

        # Check neighbors to find closest
        candidates = []
        if idx > 0:
            candidates.append(self._workouts[idx - 1])
        if idx < len(self._workouts):
            candidates.append(self._workouts[idx])

        closest = min(candidates, key=lambda w: abs(w.start_date - timestamp))

        if max_distance is not None:
            if abs(closest.start_date - timestamp) > max_distance:
                return None

        return closest

    def to_pandas(self) -> "pd.DataFrame":
        """Convert collection to a pandas DataFrame with aggregate metrics.

        Returns:
            DataFrame with one row per workout. Columns include start_date,
            duration, and mean/max/min/sum for each metric.

        Raises:
            ImportError: If pandas is not installed.
        """
        try:
            import pandas as pd  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError("pandas must be installed to run to_pandas().") from None

        return pd.DataFrame(self.to_dict())

    def to_polars(self) -> "pl.DataFrame":
        """Convert collection to a polars DataFrame with aggregate metrics.

        Returns:
            DataFrame with one row per workout. Columns include start_date,
            duration, and mean/max/min/sum for each metric.

        Raises:
            ImportError: If polars is not installed.
        """
        try:
            import polars as pl  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError("polars must be installed to run to_polars().") from None

        return pl.DataFrame(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Build dict representation for DataFrame export."""
        data: dict[str, Any] = {
            "start_date": self.start_dates,
            "duration": self.durations,
        }

        for name in ("power", "heartrate", "cadence", "distance", "calories"):
            accessor = getattr(self, name)
            data[f"{name}_max"] = accessor.max
            data[f"{name}_min"] = accessor.min
            data[f"{name}_mean"] = accessor.mean
            data[f"{name}_sum"] = accessor.sum

        for i in range(5):
            data[f"zone_{i + 1}"] = [float(w.power_zones[i]) for w in self]

        return data


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
