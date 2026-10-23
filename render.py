"""Rich text builders for the TUI. Pure functions, so they can be tested without a terminal.

Colours are read from the active palette at call time, so a theme switch only needs a re-render.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from rich.text import Text

from exiftui.core.classify import categorize, is_embedded_metadata, privacy_flag
from exiftui.core.report import output_location, verdict_line
from exiftui.core.verifier import dimensions, file_type
from exiftui.models import Artifact, Category, FileResult, Tag, Verdict
from exiftui.themes import Palette, current

VERDICT_GLYPH = {
    Verdict.CLEAN: "■", Verdict.PARTIAL: "▲", Verdict.UNSUPPORTED: "◇", Verdict.FAILED: "✖",
}

EMBEDDED_ORDER = [
    Category.GPS, Category.DEVICE, Category.AUTHOR, Category.TIME, Category.SOFTWARE,
    Category.TEXT, Category.THUMB, Category.OTHER,
]
INTRINSIC_ORDER = [Category.COLOR, Category.STRUCT, Category.FILESYSTEM]

ACTIONS = [
    ("A", "Add images", "pick one or more image files"),
    ("D", "Add folder", "scan a folder, optionally recursively"),
    ("I", "Inspect", "metadata of the highlighted file; after a scrub, before vs after"),
    ("S", "Scrub", "write cleaned copies; originals stay untouched"),
    ("V", "Verify", "re-read the output and report what is left"),
    ("R", "Results", "session report, exportable as JSON or text"),
]


def verdict_color(v: Verdict, p: Palette) -> str:
    return {Verdict.CLEAN: p.ok, Verdict.PARTIAL: p.warn, Verdict.UNSUPPORTED: p.lav,
            Verdict.FAILED: p.bad}[v]


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def tail(s: str, n: int) -> str:
    """Keep the end of a name so extensions stay visible."""
    return s if len(s) <= n else "…" + s[-(n - 1):]


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "K", "M", "G"):
        if size < 1024 or unit == "G":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{n}B"


def state_text(a: Artifact) -> Text:
    p = current()
    if a.result:
        v = a.result.verdict
        return Text(f"{VERDICT_GLYPH[v]} {v.value}", style=verdict_color(v, p))
    if a.state == "working":
        return Text("… WORKING", style=p.warn)
    if a.unsupported_reason:
        return Text("◇ RESTRICTED", style=p.lav)
    return Text("· queued", style=p.dim)


def intro() -> Text:
    p = current()
    t = Text()
    t.append("Remove embedded metadata from images.\n", style=f"bold {p.bright}")
    t.append(
        "GPS, EXIF, IPTC, XMP, camera serials, comments and edit history are stripped from "
        "JPEG, PNG, WebP, HEIC and TIFF. Originals are never touched unless you confirm "
        "in-place mode. Every output is re-read and verified before it is called clean.\n\n",
        style=p.fg,
    )
    for key, name, desc in ACTIONS:
        t.append(f" {key} ", style=f"bold {p.key_fg} on {p.key_bg}")
        t.append(f" {name:<11}", style=f"bold {p.fg}")
        t.append(f"{desc}\n", style=p.dim)
    t.append("\nPixels, file names and filesystem timestamps are not changed.\n", style=p.dim)
    t.append(f"Theme: {p.name} (press P to change)\n", style=p.dim)
    return t


def _group_by_category(tags: Iterable[Tag], raw: bool) -> dict[Category, list[Tag]]:
    out: dict[Category, list[Tag]] = {}
    for tg in tags:
        if tg.group0 == "Composite" and not raw:
            continue  # derived duplicates of tags shown elsewhere
        out.setdefault(categorize(tg), []).append(tg)
    return out


def view_bar(view: str, available: list[str]) -> Text:
    """One line showing which view is active and that B cycles them."""
    p = current()
    t = Text()
    t.append("VIEW ", style=p.dim)
    for i, v in enumerate(available):
        if i:
            t.append(" · ", style=p.dim)
        t.append(v.upper(), style=f"bold {p.key_fg} on {p.key_bg}" if v == view else p.dim)
    if len(available) > 1:
        t.append("   B to switch", style=p.dim)
    t.append("\n\n")
    return t


def inspection(
    name: str, size: int, tags: list[Tag], raw: bool, width: int = 60, header: Text | None = None
) -> Text:
    p = current()
    t = Text()
    if header is not None:
        t.append_text(header)
    dims = dimensions(tags)
    t.append(f"{name}\n", style=f"bold {p.bright}")
    t.append(
        f"{(file_type(tags) or '?').upper()}"
        + (f"  {dims[0]}×{dims[1]}" if dims else "")
        + f"  {human_size(size)}\n",
        style=p.dim,
    )
    embedded = [x for x in tags if is_embedded_metadata(x)]
    flags = Counter(f for x in tags if (f := privacy_flag(x)))
    t.append(f"EMBEDDED METADATA  {len(embedded)} tags", style=f"bold {p.warn}")
    if flags:
        t.append("   ")
        for fname, n in flags.items():
            t.append(f"▲ {fname} ×{n} ", style=f"bold {p.bad}")
    t.append("\n\n")
    if not embedded:
        t.append("No removable embedded metadata found.\n\n", style=p.ok)
    groups = _group_by_category(tags, raw)
    for cat in EMBEDDED_ORDER + INTRINSIC_ORDER:
        items = groups.get(cat)
        if not items:
            continue
        intrinsic = cat in INTRINSIC_ORDER
        t.append(f"── {cat.value.upper()} ", style=f"bold {p.cyan if intrinsic else p.edge}")
        t.append(f"({len(items)})\n", style=p.dim)
        for tg in items:
            flag = privacy_flag(tg)
            label = tg.qualified if raw else tg.name + (f" ({tg.dup})" if tg.dup else "")
            t.append("  ")
            t.append(clip(label, 30).ljust(32 if raw else 18), style=p.dim if intrinsic else p.fg)
            t.append(" ")
            t.append(clip(tg.value.replace("\n", " "), max(20, width - 34)), style=p.bright)
            if flag:
                t.append(f"  ▲ {flag}", style=f"bold {p.bad}")
            t.append("\n")
        t.append("\n")
    t.append("Intrinsic and filesystem rows are not embedded metadata and are not removed.\n",
             style=p.dim)
    return t


def _key(t: Tag) -> tuple[str, str, str, int]:
    return (t.group0, t.group1, t.name, t.dup)


def compare_tags(before: list[Tag], after: list[Tag], raw: bool = False) -> dict[str, list]:
    """Diff two tag lists into removed / still / changed / kept / added. Filesystem is ignored."""

    def usable(t: Tag) -> bool:
        if t.group0 == "ExifTool" or t.group1 == "System":
            return False
        return raw or t.group0 != "Composite"

    b = {_key(t): t for t in before if usable(t)}
    a = {_key(t): t for t in after if usable(t)}
    out: dict[str, list] = {"removed": [], "still": [], "kept": [], "added": [], "changed": []}
    for k, tb in b.items():
        ta = a.get(k)
        if ta is None:
            out["removed"].append(tb)
        elif is_embedded_metadata(ta):
            out["still"].append((tb, ta))
        elif tb.value != ta.value:
            out["changed"].append((tb, ta))
        else:
            out["kept"].append(ta)
    out["added"] = [ta for k, ta in a.items() if k not in b]
    return out


def comparison(
    name: str, before: list[Tag], after: list[Tag], raw: bool, width: int = 60,
    header: Text | None = None, verdict: Verdict | None = None,
) -> Text:
    p = current()
    d = compare_tags(before, after, raw)
    t = Text()
    if header is not None:
        t.append_text(header)
    t.append(f"{name}\n", style=f"bold {p.bright}")
    t.append(f"REMOVED {len(d['removed'])}", style=f"bold {p.bad}")
    t.append("  ·  ", style=p.dim)
    t.append(f"STILL EMBEDDED {len(d['still'])}", style=f"bold {p.warn}" if d["still"] else p.dim)
    t.append("  ·  ", style=p.dim)
    t.append(f"KEPT {len(d['kept']) + len(d['changed'])}", style=p.dim)
    t.append("  ·  ", style=p.dim)
    t.append(f"ADDED {len(d['added'])}\n", style=p.cyan if d["added"] else p.dim)
    if verdict is not None:
        t.append(f"{VERDICT_GLYPH[verdict]} verification: {verdict.value}\n",
                 style=f"bold {verdict_color(verdict, p)}")
    t.append("\n")

    rows: dict[Category, list[tuple[str, Tag, str]]] = {}

    def add(mark: str, tag: Tag, extra: str = "") -> None:
        rows.setdefault(categorize(tag), []).append((mark, tag, extra))

    for tg in d["removed"]:
        add("−", tg)
    for tb, _ in d["still"]:
        add("▲", tb)
    for tb, ta in d["changed"]:
        add("~", tb, f" → {clip(ta.value, 24)}")
    for tg in d["kept"]:
        add("=", tg)
    for tg in d["added"]:
        add("+", tg)

    styles = {"−": p.bad, "▲": p.warn, "~": p.cyan, "=": p.dim, "+": p.cyan}
    for cat in EMBEDDED_ORDER + INTRINSIC_ORDER:
        items = rows.get(cat)
        if not items:
            continue
        intrinsic = cat in INTRINSIC_ORDER
        t.append(f"── {cat.value.upper()} ", style=f"bold {p.cyan if intrinsic else p.edge}")
        t.append(f"({len(items)})\n", style=p.dim)
        for mark, tg, extra in items:
            label = tg.qualified if raw else tg.name + (f" ({tg.dup})" if tg.dup else "")
            st = styles[mark]
            t.append(f" {mark} ", style=f"bold {st}")
            t.append(clip(label, 30).ljust(32 if raw else 18),
                     style=p.dim if mark == "=" else p.fg)
            t.append(" ")
            t.append(clip(tg.value.replace("\n", " "), max(16, width - 38)) + extra, style=st)
            t.append("\n")
        t.append("\n")
    t.append("− removed   ▲ still embedded   = kept (structural)   + added by the writer\n",
             style=p.dim)
    t.append("Removed values are the original file's. Filesystem fields are ignored here.\n",
             style=p.dim)
    return t


def verification(name: str, r: FileResult) -> Text:
    p = current()
    t = Text()
    t.append(f"VERIFY  {name}\n", style=f"bold {p.bright}")
    t.append(f"{VERDICT_GLYPH[r.verdict]} {r.verdict.value}\n\n",
             style=f"bold {verdict_color(r.verdict, p)}")
    if r.error:
        t.append(f"{r.error}\n\n", style=p.bad)
    for line in r.reasons:
        t.append(f"• {line}\n", style=p.fg)
    for cat, names in r.remaining.items():
        t.append(f"\n── {cat.upper()} ({len(names)})\n", style=f"bold {p.edge}")
        for n in names[:25]:
            t.append(f"  {n}\n", style=p.fg)
        if len(names) > 25:
            t.append(f"  … {len(names) - 25} more\n", style=p.dim)
    if r.verdict is Verdict.CLEAN:
        t.append("No removable embedded metadata detected by the supported checks.\n", style=p.ok)
    t.append("\n")
    for n in r.notes:
        t.append(f"{n}\n", style=p.dim)
    t.append("No tool can guarantee that unknown or proprietary fields are gone.\n", style=p.dim)
    return t


def purge_summary(artifacts: list[Artifact], c: Counter[str], width: int = 40) -> Text:
    p = current()
    done = [a for a in artifacts if a.result]
    rule = "─" * width
    t = Text()

    def row(label: str, n: int, style: str) -> None:
        t.append(f"{label:<{width - 5}}", style=style)
        t.append(f"{n:>5}\n", style=f"bold {style}")

    t.append("EXIFTUI // PURGE REPORT\n", style=f"bold {p.box_accent}")
    t.append(rule + "\n", style=p.box_fg)
    row("ARTIFACTS PROCESSED", len(done), p.box_fg)
    row("VERIFIED CLEAN", c["CLEAN"], p.box_ok)
    row("PARTIAL", c["PARTIAL"], p.box_warn)
    row("UNSUPPORTED", c["UNSUPPORTED"], p.box_lav)
    row("FAILED", c["FAILED"], p.box_bad)
    t.append(rule + "\n", style=p.box_fg)
    t.append(f"VERDICT: {verdict_line(c)}\n", style=f"bold {p.box_fg}")
    t.append(f"OUTPUT: {clip(output_location(done), width - 8)}", style=p.box_fg)
    return t


def result_detail(a: Artifact) -> Text:
    p = current()
    t = Text()
    r = a.result
    if r is None:
        return Text("Not processed.", style=p.dim)
    t.append(f"{a.display}\n", style=f"bold {p.bright}")
    if r.output:
        t.append(f"→ {r.output}\n", style=p.dim)
    if r.error:
        t.append(f"error: {r.error}\n", style=p.bad)
    for line in r.reasons:
        t.append(f"• {line}\n", style=p.fg)
    for cat, names in r.remaining.items():
        t.append(f"  {cat}: ", style=p.warn)
        t.append(clip(", ".join(names), 120) + "\n", style=p.dim)
    for n in r.notes:
        if "untouched" in n:
            t.append(f"{n}\n", style=p.warn)
    return t


HELP = """\
KEYS
  A      add image files        D      add a folder
  I      inspect (also Enter)   Space  select / deselect
  S      scrub selected         C      cancel a running job
  V      verify highlighted     R      results and export
  B      original / output /    P      next colour theme
         compare (after scrub)  T      raw tag names on/off
  X      remove from list       Tab    swap panels (narrow)
  ?      this help              Esc    close or go back
  Q      quit

SCRUBBING
  Writes a cleaned copy (photo-clean.jpg, or ExifTUI-clean/
  for folders) with ExifTool. The colour profile and rotation
  flag are kept so the image still displays correctly. Pixels
  are not re-encoded. Existing files are never overwritten.

BEFORE / AFTER
  After a scrub, I opens a comparison: removed tags (with the
  original values), anything still embedded, structural tags
  that were kept, and tags the writer added. B cycles the
  original, the output and the comparison.

VERIFYING
  The output is re-opened and inspected on its own. CLEAN: no
  removable embedded metadata detected. PARTIAL: some is left
  (listed by category). UNSUPPORTED: format not handled.
  FAILED: the write or the image check failed.

LIMITS
  No tool can promise that unknown or proprietary fields are
  gone. Pixels (faces, text, watermarks), file names and
  filesystem timestamps are not touched.
"""
