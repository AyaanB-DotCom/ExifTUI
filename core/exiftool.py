"""Thin, safe wrapper around the ExifTool binary.

Every call uses an argument list (never a shell). File paths are always passed as absolute
paths so a name like ``-evil.jpg`` can never be read as an option.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from exiftui.models import Tag

# ExifTool 12.38 fixed a flaw where file names ending in "|" were executed as commands.
MIN_VERSION = (12, 40)

# Applied to every call: decode file names as UTF-8 (macOS/Linux), never read stdin.
BASE_ARGS = ["-charset", "filename=utf8"]

_DUP_SUFFIX = re.compile(r" \((\d+)\)$")


class ExifToolError(Exception):
    """ExifTool failed or produced unusable output."""


class ExifToolMissing(ExifToolError):
    """ExifTool is not installed, or is too old to use safely."""


class Cancelled(Exception):
    """The operation was cancelled by the user."""


@dataclass
class RunResult:
    returncode: int
    stdout: bytes
    stderr: str


def find_exiftool() -> str | None:
    return os.environ.get("EXIFTUI_EXIFTOOL") or shutil.which("exiftool")


def version() -> tuple[int, ...]:
    """Return ExifTool's version as a tuple, or raise ExifToolMissing."""
    exe = find_exiftool()
    if not exe:
        raise ExifToolMissing("exiftool was not found on PATH")
    try:
        out = subprocess.run(
            [exe, "-ver"], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL
        ).stdout.strip()
        return tuple(int(p) for p in out.split("."))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ExifToolMissing(f"could not run exiftool ({type(exc).__name__})") from exc


def check() -> str:
    """Verify ExifTool is usable. Returns its version string or raises ExifToolMissing."""
    ver = version()
    if ver < MIN_VERSION:
        need = ".".join(map(str, MIN_VERSION))
        raise ExifToolMissing(f"exiftool {'.'.join(map(str, ver))} is too old (need >= {need})")
    return ".".join(map(str, ver))


def run(
    args: list[str], *, timeout: float = 120, cancel: threading.Event | None = None
) -> RunResult:
    """Run exiftool. Kills the process on timeout or when `cancel` is set."""
    exe = find_exiftool()
    if not exe:
        raise ExifToolMissing("exiftool was not found on PATH")
    try:
        proc = subprocess.Popen(
            [exe, *BASE_ARGS, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # lets us kill the whole process group on cancel
        )
    except OSError as exc:
        raise ExifToolError(f"could not start exiftool ({type(exc).__name__})") from exc
    deadline = time.monotonic() + timeout
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            return RunResult(proc.returncode, out, err.decode("utf-8", "replace"))
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                _kill(proc)
                raise Cancelled from None
            if time.monotonic() > deadline:
                _kill(proc)
                raise ExifToolError(f"exiftool timed out after {timeout:.0f}s") from None


def _kill(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()
    proc.communicate()


def first_line(text: str, limit: int = 200) -> str:
    """Short, single-line error text. Used so diagnostics stay small."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line[:limit]


def _flatten(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(_flatten(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def parse_tags(stdout: bytes) -> list[Tag]:
    """Turn `exiftool -json -G0:1 -a` output into Tag objects."""
    try:
        data = json.loads(stdout.decode("utf-8", "replace"))
        record = data[0]
    except (ValueError, IndexError, TypeError) as exc:
        raise ExifToolError("exiftool returned no readable metadata record") from exc
    tags: list[Tag] = []
    for key, value in record.items():
        if key == "SourceFile":
            continue
        dup = 0
        if m := _DUP_SUFFIX.search(key):
            dup = int(m.group(1))
            key = key[: m.start()]
        parts = key.split(":")
        if len(parts) == 1:
            g0 = g1 = "Unknown"
            name = parts[0]
        elif len(parts) == 2:
            g0 = g1 = parts[0]
            name = parts[1]
        else:
            g0, g1, name = parts[0], parts[1], ":".join(parts[2:])
        tags.append(Tag(g0, g1, name, _flatten(value), dup))
    return tags


def inspect(path: Path, *, cancel: threading.Event | None = None) -> list[Tag]:
    """Read-only metadata dump. Duplicate tags from different groups are all kept (-a)."""
    res = run(["-json", "-G0:1", "-a", "-u", str(path.resolve())], cancel=cancel)
    if not res.stdout.strip():
        raise ExifToolError(first_line(res.stderr) or "exiftool produced no output")
    return parse_tags(res.stdout)
