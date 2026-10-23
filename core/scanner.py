"""Find images to process without following symlinks or entering output folders."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from exiftui.core.formats import SCAN_EXTENSIONS, UNSUPPORTED_EXTENSIONS
from exiftui.models import Artifact

OUTPUT_DIR_NAME = "ExifTUI-clean"
_PREVIOUS_OUTPUT = re.compile(r"-clean(-\d+)?$")


@dataclass
class ScanResult:
    artifacts: list[Artifact] = field(default_factory=list)
    skipped_symlinks: int = 0
    skipped_previous_output: int = 0
    ignored_other: int = 0
    errors: list[str] = field(default_factory=list)


def _artifact_for(path: Path, root: Path | None, size: int) -> Artifact | None:
    ext = path.suffix.lower()
    if ext in SCAN_EXTENSIONS:
        return Artifact(path, root, size)
    if ext in UNSUPPORTED_EXTENSIONS:
        return Artifact(path, root, size, unsupported_reason=UNSUPPORTED_EXTENSIONS[ext])
    return None


def scan_folder(root: Path, *, recursive: bool = True) -> ScanResult:
    """List images under `root`. Symlinks (files and directories) are skipped."""
    res = ScanResult()
    root = root.resolve()
    if root.name == OUTPUT_DIR_NAME:
        res.errors.append(f"{root.name} is an ExifTUI output folder; pick its parent instead")
        return res
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            res.errors.append(f"{current.name}: {exc.strerror or 'cannot read folder'}")
            continue
        subdirs: list[Path] = []
        for e in entries:
            if e.name.startswith((".", "._")):
                continue
            if e.is_symlink():
                res.skipped_symlinks += 1
            elif e.is_dir(follow_symlinks=False):
                if recursive and e.name != OUTPUT_DIR_NAME:
                    subdirs.append(Path(e.path))
            elif e.is_file(follow_symlinks=False):
                p = Path(e.path)
                if _PREVIOUS_OUTPUT.search(p.stem):
                    res.skipped_previous_output += 1
                elif a := _artifact_for(p, root, e.stat(follow_symlinks=False).st_size):
                    res.artifacts.append(a)
                else:
                    res.ignored_other += 1
        stack.extend(reversed(subdirs))
    return res


def scan_file(path: Path) -> Artifact | None:
    """An explicitly chosen file. Symlinks are resolved because the user named them."""
    real = path.expanduser().resolve()
    if not real.is_file():
        return None
    return _artifact_for(real, None, real.stat().st_size)
