"""Fixtures build real images carrying known metadata, then tests inspect real ExifTool output."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HAVE_EXIFTOOL = shutil.which("exiftool") is not None
needs_exiftool = pytest.mark.skipif(not HAVE_EXIFTOOL, reason="exiftool not installed")

KNOWN_META = [
    "-GPSLatitude=48.85", "-GPSLatitudeRef=N", "-GPSLongitude=2.35", "-GPSLongitudeRef=E",
    "-Make=Canon", "-Model=EOS R5", "-SerialNumber=SN12345", "-Artist=Jane Doe",
    "-Orientation#=6", "-Software=EditorX", "-DateTimeOriginal=2020:01:01 10:00:00",
    "-XMP-dc:Creator=Jane", "-XMP-dc:Description=private description", "-Comment=hello",
]


def write_meta(path: Path, *args: str) -> None:
    subprocess.run(
        ["exiftool", "-overwrite_original", "-q", "-m", *args, str(path)],
        check=True, capture_output=True,
    )


def make_image(path: Path, meta: bool = True, size: tuple[int, int] = (64, 48)) -> Path:
    from PIL import Image

    img = Image.new("RGB", size)
    img.putdata([(x * 4 % 256, y * 5 % 256, (x + y) % 256) for y in range(size[1])
                 for x in range(size[0])])
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    if meta:
        write_meta(path, *KNOWN_META)
    return path


@pytest.fixture
def jpg(tmp_path: Path) -> Path:
    return make_image(tmp_path / "photo.jpg")


@pytest.fixture(params=["jpg", "png", "webp", "tif"])
def any_image(request, tmp_path: Path) -> Path:
    return make_image(tmp_path / f"sample.{request.param}")


@pytest.fixture
def heic(tmp_path: Path) -> Path:
    if sys.platform != "darwin" or not shutil.which("sips"):
        pytest.skip("HEIC fixtures are generated with macOS sips")
    src = make_image(tmp_path / "src.jpg")
    out = tmp_path / "sample.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(src), "--out", str(out)],
                   check=True, capture_output=True)
    write_meta(out, *KNOWN_META)
    return out
