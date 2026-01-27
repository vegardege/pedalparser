# BodyBike Export File Format

Based exports from the Body Bike app v2.3.4.

The export function produces a zip archive with JSON files as described below.

## File Overview

| File | Format | Description |
|------|--------|-------------|
| `appInfo` | JSON | App version info |
| `applicationSettings` | JSON | Display settings: theme, metric ranges, ANT+ toggle |
| `profileInstalled` | Binary | 24-byte file. Bytes 8-15 are a Unix timestamp in milliseconds (observed to match app update time). Other bytes unknown |
| `userSettings` | JSON | User profile: name, gender, DOB, weight, height, training level, achievements |
| `workoutHistory` | JSON | Summary array of all workout sessions with aggregated stats |
| `workout/` (directory) | JSON | Individual workout files with second-by-second data |

## File Details

### appInfo

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | App version |

### applicationSettings

| Field | Type | Description |
|-------|------|-------------|
| `themeName` | string | UI theme name |
| `ranges` | object | Gauge dial ranges per metric, four numbers per metric. Indices 1 and 3 are equal when unchanged from defaults. Not changeable from the app, so exact meaning is hard to derive. |
| `ranges.power` | number[] | Power range (watts) |
| `ranges.cadence` | number[] | Cadence range (RPM) |
| `ranges.heartrate` | number[] | Heart rate range (BPM) |
| `ranges.calories` | number[] | Calories range (kcal) |
| `ranges.distance` | number[] | Distance range (km) |
| `antPlusEnabled` | boolean | Whether ANT+ sensors are enabled |

### userSettings

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | `"BodyBike"` |
| `gender` | string | `"male"` or `"female"` |
| `dateOfBirth` | string | ISO 8601 timestamp |
| `weight` | number | Weight in kg |
| `height` | number | Height in cm |
| `trainingLevel` | number | Cardio sessions per week (0: 1–3h, 1: 3–5h, 2: 5–8h, 3: 8+h) |
| `heartrateMax` | number | Max heart rate in BPM (0 = auto-estimated by app) |
| `ftp` | number | Functional Threshold Power in watts (0 = auto-estimated by app) |
| `unit` | number | Display unit system (0: metric, 1: imperial). Note: values are always stored in metric (kg, cm, km), this setting only affects how they are displayed in the app. |
| `levelSystem` | object | Achievement/progression data |
| `levelSystem.level` | number | Number of achievements achieved |
| `levelSystem.period` | number | Current week number |
| `levelSystem.medalLevel` | number | Medal earned this week (0: none, 1: bronze, 2: silver, 3: gold) |
| `levelSystem.challenges` | number[][] | Weekly challenge indices per medal tier `[[bronze], [silver], [gold]]`, 3 challenges each, number is presumably an index. Reassigned weekly. |
| `levelSystem.bronze` | number | Total bronze medals earned |
| `levelSystem.silver` | number | Total silver medals earned |
| `levelSystem.gold` | number | Total gold medals earned |
| `levelSystem.bronzeWeeks` | number | Consecutive-week streak at bronze level |
| `levelSystem.silverWeeks` | number | Consecutive-week streak at silver level |
| `levelSystem.goldWeeks` | number | Consecutive-week streak at gold level |
| `defaultHRSensor` | string | Default heart rate sensor ID |

### workoutHistory

A JSON array of session summary objects.

| Field | Type | Description |
|-------|------|-------------|
| `startTime` | number | Session start in milliseconds (relative to session start) |
| `endTime` | number | Session end in milliseconds (relative to session start) |
| `startDate` | number | Absolute start time as Unix epoch milliseconds |
| `heartrate` | metric | Heart rate in BPM |
| `cadence` | metric | Cadence in RPM |
| `power` | metric | Power in watts |
| `distance` | metric | Speed in km/h (sum = total distance in km) |
| `calories` | metric | Calorie burn rate in kcal/h (sum = total kcal) |
| `powerZones` | number[] | Time distribution across 5 intensity zones (fractions summing to ~1.0): `[grey, blue, green, yellow, red]` |
| `powerZonesCount` | number | Always 1 |
| `total` | number | Always 0 |

Each **metric** object contains aggregated stats from all per-second readings:

| Field | Type | Description |
|-------|------|-------------|
| `value` | number | Last recorded value (from final second of workout) |
| `max` | number | Maximum value |
| `min` | number | Minimum value |
| `mean` | number | Average value |
| `sum` | number | Sum of all values (for distance/calories this is the total km/kcal) |
| `key` | string | Metric name (present on some fields) |

### workout/* (individual workout files)

Filenames use ISO 8601 compact timestamps (e.g., `20240510T114642190Z`), matching the session's `startDate`.

Each file is a JSON array of second-by-second data points:

| Field | Type | Description |
|-------|------|-------------|
| `startTime` | number | Milliseconds relative to session start |
| `endTime` | number | Milliseconds relative to session start |
| `heartrate.value` | number | Beats per minute (0 if no HR sensor) |
| `cadence.value` | number | RPM |
| `power.value` | number | Watts |
| `distance.value` | number | Instantaneous speed in km/h |
| `calories.value` | number | Instantaneous calorie burn rate in kcal/h |
