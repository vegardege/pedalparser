"""Body Bike export parser.

Load exports from the Body Bike app and access workout data.

Example:
    >>> from pedalparser import bodybike
    >>> export = bodybike.load("backup.zip")
    >>> print(export.workouts[-1].power.mean)
"""

from .models import (
    AppInfo,
    ApplicationSettings,
    BodyBikeExport,
    Gender,
    InvalidBodyBikeExport,
    LevelSystem,
    MedalLevel,
    Metric,
    MetricAccessor,
    MetricRanges,
    TrainingLevel,
    Unit,
    UserSettings,
    Workout,
    WorkoutCollection,
)
from .parser import load

__all__ = [
    # Main entry point
    "load",
    # Export container
    "BodyBikeExport",
    # Workout types
    "Workout",
    "WorkoutCollection",
    "Metric",
    "MetricAccessor",
    # Settings types
    "AppInfo",
    "ApplicationSettings",
    "MetricRanges",
    "UserSettings",
    "LevelSystem",
    # Enums
    "Gender",
    "MedalLevel",
    "Unit",
    "TrainingLevel",
    # Exceptions
    "InvalidBodyBikeExport",
]
