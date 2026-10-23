"""Independent verification: re-read a file with ExifTool and judge what is left.

The verdict never depends on whether a scrub "succeeded". It depends only on what ExifTool
reports when it opens the file afterwards.
"""

from __future__ import annotations

import re
import threading
from collections import defaultdict
from pathlib import Path

from exiftui.core import exiftool
from exiftui.core.classify import categorize, is_embedded_metadata
from exiftui.core.formats import SUPPORTED_TYPES
from exiftui.models import FileResult, Tag, Verdict

_CORRUPT_WARNING = re.compile(r"truncated|corrupt|not a valid|invalid|unexpected end", re.I)
_DECODABLE = {"jpg", "png", "webp", "tif"}

NOTE_PIXELS = "Pixels, file name and filesystem timestamps are outside metadata verification."


def _tag(tags: list[Tag], group0: str, name: str) -> str | None:
    return next((t.value for t in tags if t.group0 == group0 and t.name == name), None)


def dimensions(tags: list[Tag]) -> tuple[int, int] | None:
    size = _tag(tags, "Composite", "ImageSize")
    if size and (m := re.fullmatch(r"(\d+)\D+(\d+)", size.strip())):
        return int(m.group(1)), int(m.group(2))
    return None


def file_type(tags: list[Tag]) -> str | None:
    return _tag(tags, "File", "FileTypeExtension")


def _decode_check(path: Path) -> str | None:
    """Full decode with Pillow when it is installed. Returns an error string or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            img.load()
    except Exception as exc:  # noqa: BLE001 - any decoder failure means "unreadable"
        return f"image did not decode ({type(exc).__name__})"
    return None


def judge(tags: list[Tag], path: Path | None = None) -> FileResult:
    """Turn a tag list into a FileResult. `path` enables the optional full-decode check."""
    notes = [NOTE_PIXELS]
    errors = [t.value for t in tags if t.name == "Error" and t.group0 == "ExifTool"]
    if errors:
        return FileResult(Verdict.FAILED, mode="verify", error=errors[0][:200], notes=notes)
    ftype = file_type(tags)
    if ftype not in SUPPORTED_TYPES:
        kind = _tag(tags, "File", "FileType") or "unknown"
        return FileResult(
            Verdict.UNSUPPORTED, mode="verify", notes=notes,
            reasons=[f"File type {kind} is not supported for scrubbing or verification."],
        )
    warnings = [t.value for t in tags if t.name == "Warning" and t.group0 == "ExifTool"]
    if bad := next((w for w in warnings if _CORRUPT_WARNING.search(w)), None):
        return FileResult(Verdict.FAILED, mode="verify", error=bad[:200], notes=notes)
    if dimensions(tags) is None:
        return FileResult(
            Verdict.FAILED, mode="verify", error="could not determine image dimensions",
            notes=notes,
        )
    if path is not None and ftype in _DECODABLE and (err := _decode_check(path)):
        return FileResult(Verdict.FAILED, mode="verify", error=err, notes=notes)

    remaining: dict[str, list[str]] = defaultdict(list)
    for t in tags:
        if is_embedded_metadata(t):
            remaining[categorize(t).value].append(t.qualified)
    if any(t.group0.startswith("ICC") for t in tags):
        notes.append("Colour profile retained on purpose (needed for correct colours).")
    if warnings:
        notes.append(f"ExifTool reported {len(warnings)} warning(s).")
    if not remaining:
        return FileResult(Verdict.CLEAN, mode="verify", notes=notes)
    reasons = [f"{cat}: {len(names)} tag(s) still embedded" for cat, names in remaining.items()]
    return FileResult(
        Verdict.PARTIAL, mode="verify", remaining=dict(remaining), reasons=reasons, notes=notes
    )


def verify_file(path: Path, *, cancel: threading.Event | None = None) -> FileResult:
    """Verify any file, whether or not ExifTUI produced it. Read-only."""
    try:
        tags = exiftool.inspect(path, cancel=cancel)
    except exiftool.Cancelled:
        raise
    except exiftool.ExifToolError as exc:
        return FileResult(Verdict.FAILED, mode="verify", error=str(exc)[:200])
    return judge(tags, path)
