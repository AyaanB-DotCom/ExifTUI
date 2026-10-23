# ExifTUI

*Image metadata removal, without memorizing commands.*

<img width="3456" height="2200" alt="Screenshot 2026-10-22 at 9 07 25 PM-clean" src="https://github.com/user-attachments/assets/4973ef8d-7d9d-413a-a11d-b642a771f64e" />


ExifTUI is a terminal interface for [ExifTool](https://exiftool.org). You pick images or a
folder, look at what metadata they carry, write cleaned copies, and then the program re-reads
each copy and tells you what, if anything, is still embedded. It is Python and
[Textual](https://textual.textualize.io) only: no Node, no browser, no network access.

The default look is a deliberate 1995 occult-utility pastiche (theme name: NECROTERRA): rust
and mustard plates, parchment text boxes, near-black ground. Three alternative schemes ship
with it.

> No screenshots are included yet. I have only captured them in a headless test harness, and
> I would rather add real terminal recordings later than ship something that is not the real
> thing.

## Why

ExifTool can remove nearly any metadata, but `exiftool -all= -tagsFromFile @ -icc_profile
-orientation -o out.jpg in.jpg` is not something most people remember, and "it exited with
code 0" is not proof the output is clean. ExifTUI wraps the right invocation per format and
treats verification as a separate step that does not trust the scrub.

## Features

- Add files or whole folders (recursive or flat). Paths can be typed, pasted, or dragged into
  the terminal.
- Read-only inspection, grouped into categories (location, device and serials, author and
  rights, timestamps, software and edit history, comments, embedded previews, other), with
  narrow privacy markers for GPS coordinates and serial numbers. `T` shows raw
  `Group:Tag` names; duplicate tags from different groups are kept.
- Non-destructive scrubbing: `photo-clean.jpg` beside single files, `ExifTUI-clean/` with the
  folder structure preserved for folders. Existing files are never overwritten (`-2`, `-3`
  suffixes). Output is written to a private temp file, verified, then moved into place.
- Optional in-place mode, off by default, behind an explicit checkbox in the confirm dialog.
  It only replaces a file when the result verifies CLEAN.
- Batch processing in worker threads with at most 4 concurrent ExifTool processes, live
  progress, per-file status and cancellation. The UI does not block.
- Before/after comparison: after a scrub, `I` shows a diff of the original against the output:
  removed tags (with the original values), anything still embedded, structural tags that were
  kept, and tags the writer added. `B` cycles original, output and comparison. Filesystem
  fields are ignored in the diff because they always differ. After an in-place scrub there is
  no original left, so only the output is shown.
- Four colour schemes, switchable at any time with `P` or at startup with `--theme`:
  `necroterra` (default), `oxide` (verdigris on green-black), `lampblack` (amber phosphor) and
  `parchment` (a light theme). The choice is not saved between sessions.
- Verification that works on any file, including ones ExifTUI did not clean.
- A purge report (CLI-style summary plus per-file table), exportable as JSON or plain text.
  Reports contain file names, verdicts and tag *names*, never tag values.

## Requirements and installation

- Python 3.11 or newer
- ExifTool 12.40 or newer (older versions had a file-name command-execution flaw, so ExifTUI
  refuses them)
- macOS (primary) or Linux

Install ExifTool first:

```bash
brew install exiftool                      # macOS (Homebrew)
sudo apt install libimage-exiftool-perl    # Debian / Ubuntu
sudo dnf install perl-Image-ExifTool       # Fedora / RHEL
sudo pacman -S perl-image-exiftool         # Arch
```

Then install ExifTUI with any of:

```bash
pipx install .             # from a checkout
uv tool install .
python -m venv .venv && .venv/bin/pip install .
```

Optionally add Pillow (`pip install ".[verify]"`) so the verifier fully decodes JPEG, PNG,
WebP and TIFF outputs as an extra readability check. Without it, readability is judged from
ExifTool's report only.

ExifTUI never installs anything for you. If ExifTool is missing it prints the commands above
and exits with code 3.

## Usage

```bash
exiftui                      # start empty
exiftui photo.jpg ~/Pictures # start with paths loaded
exiftui --theme oxide        # necroterra | oxide | lampblack | parchment
exiftui --help
exiftui --version
```

Exit codes: `0` ok, `2` usage (including no interactive terminal), `3` ExifTool missing or too
old, `4` a given path does not exist.

| Key | Action |
| --- | --- |
| `A` | add image files |
| `D` | add a folder (checkbox for subfolders) |
| `I` / `Enter` | inspect the highlighted file (after a scrub: before/after comparison) |
| `B` | cycle original / output / compare for the inspected file |
| `P` | next colour theme |
| `Space` | select / deselect |
| `S` | scrub selected files (confirm dialog first) |
| `V` | verify the highlighted file (its output if it has one) |
| `R` | results; `J` / `T` there export JSON / text |
| `C` | cancel a running job |
| `X` | remove from the list (never touches the file) |
| `T` | raw tag names on/off |
| `Tab` | swap panels on terminals narrower than 100 columns |
| `?` / `Esc` / `Q` | help / back / quit |

Single-letter shortcuts are disabled while a dialog is open, so typing a path cannot trigger
them. The layout works at 80×24; below 100 columns it shows one panel at a time.

## Supported formats

| Format | Status |
| --- | --- |
| JPEG, PNG, WebP | supported |
| HEIC / HEIF, TIFF | supported, but validated only on small synthetic files (see limits) |
| RAW (DNG, CR2, CR3, NEF, ARW, ORF, RW2, RAF, PEF), PSD, GIF, BMP, AVIF, JPEG 2000 | shown as restricted; never modified |
| Video, PDF | not in this release |

The format is decided from file *content*, not the extension. A GIF named `.jpg` is reported
UNSUPPORTED.

## What scrubbing does

ExifTool runs with `-all=` and then restores only the colour profile and the Orientation
flag, so images still display correctly. Pixel data is not re-encoded. TIFF additionally gets
explicit deletes for IFD0 tags (Make, Model, Software, Artist, Copyright, ...) because
`-all=` leaves those in TIFF files. Filesystem timestamps and file names are not altered, and
the output file gets new filesystem timestamps.

`-all=` is not assumed to be sufficient everywhere, which is why verification exists.

## How verification works

After writing, ExifTUI runs ExifTool again on the output, in read-only JSON mode with
duplicates enabled, and classifies every tag:

- **Structural** (image dimensions, compression, PNG header chunks, WebP flags, the colour
  profile, rotation flag, container tags): not counted.
- **Embedded metadata** (everything in EXIF, XMP, IPTC, Photoshop, MakerNotes, JPEG comments,
  PNG text chunks, previews, identifiers and timestamps in HEIC containers, and any unknown
  group): counted.

Verdicts:

- **CLEAN**: no removable embedded metadata detected by these checks.
- **PARTIAL**: some remains; the report lists categories and tag names.
- **UNSUPPORTED**: the format is not handled.
- **FAILED**: the write failed, ExifTool reported an error or truncation, the image
  dimensions changed, or (with Pillow) the image did not decode. Nothing is delivered for
  FAILED files.

The tests include re-adding a tag to a "successfully scrubbed" file and confirming the
verdict flips to PARTIAL.

## Security and privacy limits

- No network access, telemetry, accounts, or elevated privileges. ExifTool is invoked with
  argument lists, never a shell, and with absolute paths so names like `-x.jpg` or `a|.jpg`
  are not parsed as options.
- Symlinks found during folder scans are skipped. Output folders (`ExifTUI-clean`) and earlier
  `*-clean` outputs are skipped when scanning.
- Inspected values live in memory for the current view only. Reports omit values.
- Temp files are created in a private `0700` directory next to the destination and removed on
  success, failure and cancellation.
- **No tool can guarantee that unknown or proprietary identifiers are gone.** CLEAN means "none
  detected by ExifTool's view of the file", not "provably none".
- Pixels are untouched: faces, visible text, addresses and watermarks stay. So do file names
  and filesystem timestamps.
- Trailer data and unrecognised container tags that ExifTool does not report cannot be
  verified. In HEIC, unknown QuickTime tags are not counted as metadata (a documented
  simplification in `core/classify.py`).
- Each file costs three short ExifTool processes (inspect, write, verify). Large batches are
  fine but not fast; a `-stay_open` session would be the upgrade path.

## Testing status

Last full run on macOS (Apple Silicon), Python 3.12, ExifTool 13.55, Textual 8.2.8:
`pytest` 69 passed in 89s (engine, interface, theme, comparison and classifier tests), `ruff check` clean.
The interface tests drive Textual's headless pilot, not a real terminal. Separately, a
pseudo-terminal run at 80×24 (`exiftui --theme necroterra`, pressing `P`, opening and closing
help, then `Q`) exited with code 0; an earlier non-editable install into a fresh venv without
Pillow did the same before the theme and comparison features were added. Not tested:
Linux, Intel Macs, other ExifTool or Textual versions, HEIC files from real phones, TIFFs from
real cameras or scanners, terminals other than a headless Textual driver and one
pseudo-terminal launch.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check exiftui tests
```

Layout:

```
exiftui/
  cli.py          entry point, exit codes, ExifTool guidance
  app.py          main screen, key handling, workers
  screens.py      path picker, confirm, help, results
  render.py       Rich text builders, incl. the before/after diff (testable without a terminal)
  themes.py       the four palettes; each field becomes a $nt-* variable in theme.tcss
  theme.tcss      layout and styling shared by every theme
  models.py       dataclasses and enums
  core/           exiftool.py  scanner.py  sanitizer.py  verifier.py
                  classify.py  formats.py  batch.py  report.py
tests/            real-ExifTool integration tests and Textual pilot tests
```

The core has no Textual dependency. Tests build real images with Pillow, inject known
metadata with ExifTool, and inspect actual output; HEIC fixtures are generated with macOS
`sips` and skipped elsewhere.

## Contributing

Issues and pull requests are welcome. Please keep changes small, add a test that fails
without the change, keep `ruff check` clean, and do not add network access, telemetry, or
JavaScript tooling. New format support needs real sample files and a verification test, not
just a policy entry.

## License

MIT. See [LICENSE](LICENSE).
