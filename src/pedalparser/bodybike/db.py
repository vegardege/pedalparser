from __future__ import annotations

import sqlite3
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pedalparser.bodybike.models import BodyBikeExport

SCHEMA = """\
CREATE TABLE workouts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time      TEXT NOT NULL,
    duration        REAL NOT NULL,
    power_min       REAL,
    power_mean      REAL,
    power_max       REAL,
    heartrate_min   REAL,
    heartrate_mean  REAL,
    heartrate_max   REAL,
    cadence_min     REAL,
    cadence_mean    REAL,
    cadence_max     REAL,
    speed_min       REAL,
    speed_mean      REAL,
    speed_max       REAL,
    distance        REAL,
    calories        REAL,
    zone_1          REAL,
    zone_2          REAL,
    zone_3          REAL,
    zone_4          REAL,
    zone_5          REAL
);

CREATE TABLE timeseries (
    workout_id  INTEGER NOT NULL
                    REFERENCES workouts(id),
    timestamp   INTEGER NOT NULL,
    power       REAL,
    heartrate   REAL,
    cadence     REAL,
    speed       REAL,
    calories    REAL,
    PRIMARY KEY (workout_id, timestamp)
);
"""


def write_sqlite(export: BodyBikeExport, path: str | PathLike[str]) -> Path:
    p = Path(path)
    p.unlink(missing_ok=True)

    con = sqlite3.connect(p)
    try:
        con.executescript(SCHEMA)

        for workout in export.workouts:
            cur = con.execute(
                """
                INSERT INTO workouts (
                    start_time, duration,
                    power_min, power_mean, power_max,
                    heartrate_min, heartrate_mean, heartrate_max,
                    cadence_min, cadence_mean, cadence_max,
                    speed_min, speed_mean, speed_max,
                    distance, calories,
                    zone_1, zone_2, zone_3, zone_4, zone_5
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workout.start_time.isoformat(),
                    workout.duration.total_seconds(),
                    workout.power.min,
                    workout.power.mean,
                    workout.power.max,
                    workout.heartrate.min,
                    workout.heartrate.mean,
                    workout.heartrate.max,
                    workout.cadence.min,
                    workout.cadence.mean,
                    workout.cadence.max,
                    workout.distance.min,
                    workout.distance.mean,
                    workout.distance.max,
                    workout.distance.sum,
                    workout.calories.sum,
                    *workout.power_zones,
                ),
            )

            workout_id = cur.lastrowid
            con.executemany(
                """
                INSERT INTO timeseries
                    (workout_id, timestamp, power, heartrate, cadence, speed, calories)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        workout_id,
                        int(workout.timestamps[i]),
                        float(workout.power.ts[i]),
                        float(workout.heartrate.ts[i]),
                        float(workout.cadence.ts[i]),
                        float(workout.distance.ts[i]),
                        float(workout.calories.ts[i]),
                    )
                    for i in range(len(workout.timestamps))
                ),
            )

        con.commit()
    finally:
        con.close()

    return p.resolve()
