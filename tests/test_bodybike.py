import json
from io import BytesIO
from pathlib import Path
from zipfile import BadZipfile, ZipFile

import pytest

from pedalparser.bodybike import (
    BodyBikeExport,
    Gender,
    InvalidBodyBikeExport,
    MedalLevel,
    Unit,
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
