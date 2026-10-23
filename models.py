"""Plain data types shared by the engine and the TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Verdict(Enum):
    CLEAN = "CLEAN"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


class Category(Enum):
    GPS = "Location"
    DEVICE = "Device & serials"
    AUTHOR = "Author & rights"
    TIME = "Embedded timestamps"
    SOFTWARE = "Software & edit history"
    TEXT = "Comments & descriptions"
    THUMB = "Embedded previews"
    COLOR = "Colour profile"
    OTHER = "Other metadata"
    STRUCT = "Image structure"
    FILESYSTEM = "Filesystem (not embedded)"


@dataclass(frozen=True)
class Tag:
    """One ExifTool tag. `group0`/`group1` are ExifTool's family 0 and 1 groups."""

    group0: str
    group1: str
    name: str
    value: str
    dup: int = 0  # >0 when ExifTool reported the same group:name more than once

    @property
    def qualified(self) -> str:
        base = f"{self.group0}:{self.group1}:{self.name}" if self.group1 != self.group0 else (
            f"{self.group0}:{self.name}"
        )
        return f"{base} ({self.dup})" if self.dup else base


@dataclass
class FileResult:
    """Outcome for one file. Never holds tag *values*, only names and counts."""

    verdict: Verdict
    output: Path | None = None
    in_place: bool = False
    mode: str = "scrub"  # "scrub" | "verify"
    before_count: int | None = None  # embedded tags found in the source
    remaining: dict[str, list[str]] = field(default_factory=dict)  # category -> tag names
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class Artifact:
    path: Path
    root: Path | None = None  # folder it was found in, if added via a folder scan
    size: int = 0
    selected: bool = True
    state: str = "queued"  # queued | working | done
    unsupported_reason: str | None = None  # set by the scanner for known-unsupported formats
    result: FileResult | None = None

    @property
    def ext(self) -> str:
        return self.path.suffix.lstrip(".").upper()

    @property
    def display(self) -> str:
        if self.root is not None:
            return str(self.path.relative_to(self.root))
        return self.path.name
