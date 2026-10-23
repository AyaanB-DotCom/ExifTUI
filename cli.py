"""Command-line entry point: `exiftui [PATH ...]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from exiftui import __version__, themes
from exiftui.core import exiftool

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_EXIFTOOL = 3
EXIT_BAD_PATH = 4

INSTALL_HELP = """\
ExifTUI needs ExifTool (a separate program) to read and remove metadata.

  macOS (Homebrew):   brew install exiftool
  Debian / Ubuntu:    sudo apt install libimage-exiftool-perl
  Fedora / RHEL:      sudo dnf install perl-Image-ExifTool
  Arch Linux:         sudo pacman -S perl-image-exiftool
  Anything else:      https://exiftool.org/install.html

ExifTUI never installs software for you. Run `exiftui` again once ExifTool is on your PATH.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="exiftui",
        description="Image metadata removal, without memorizing commands. "
        "Inspect, scrub and verify image metadata in a terminal UI.",
        epilog="Originals are never modified unless you explicitly confirm in-place mode. "
        "Exit codes: 0 ok, 2 usage, 3 ExifTool missing or too old, 4 a given path does not exist.",
    )
    p.add_argument("paths", nargs="*", type=Path, metavar="PATH",
                   help="image files or folders to load on startup")
    p.add_argument(
        "--theme", choices=sorted(themes.THEMES), default=themes.DEFAULT,
        help="colour scheme (default: %(default)s); press P in the app to cycle",
    )
    p.add_argument("--version", action="version", version=f"exiftui {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        et_version = exiftool.check()
    except exiftool.ExifToolMissing as exc:
        print(f"exiftui: {exc}\n", file=sys.stderr)
        print(INSTALL_HELP, file=sys.stderr)
        return EXIT_NO_EXIFTOOL
    missing = [p for p in args.paths if not p.expanduser().exists()]
    if missing:
        for p in missing:
            print(f"exiftui: no such file or folder: {p}", file=sys.stderr)
        return EXIT_BAD_PATH
    if not sys.stdout.isatty():
        print("exiftui: needs an interactive terminal (stdout is not a TTY)", file=sys.stderr)
        return EXIT_USAGE

    from exiftui.app import ExifTUI  # imported late so --help/--version stay instant

    app = ExifTUI(
        initial_paths=[p.expanduser() for p in args.paths],
        exiftool_version=et_version,
        theme=args.theme,
    )
    app.run()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

