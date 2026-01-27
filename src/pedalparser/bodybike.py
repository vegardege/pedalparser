import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from os import PathLike
from typing import IO, Any, Callable, TypeVar
from zipfile import ZipFile

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
class BodyBikeExport:
    app_info: AppInfo
    app_settings: ApplicationSettings
    user_settings: UserSettings


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
        app_info = _parse(zf, "appInfo", _load_app_info)
        app_settings = _parse(zf, "applicationSettings", _load_app_settings)
        user_settings = _parse(zf, "userSettings", _load_user_settings)

    return BodyBikeExport(
        app_info=app_info,
        app_settings=app_settings,
        user_settings=user_settings,
    )


def _parse(zf: ZipFile, name: str, loader: Callable[[dict[str, Any]], T]) -> T:
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


def _load_app_info(data: dict[str, Any]) -> AppInfo:
    return AppInfo(version=data["version"])


def _load_app_settings(data: dict[str, Any]) -> ApplicationSettings:
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


def _load_level_system(data: dict[str, Any]) -> LevelSystem:
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


def _load_user_settings(data: dict[str, Any]) -> UserSettings:
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
