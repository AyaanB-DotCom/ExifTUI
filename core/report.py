"""Session report. Contains file names, verdicts and tag *names* only, never tag values."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from exiftui import __version__
from exiftui.models import Artifact, Verdict

DISCLAIMER = (
    "Verification covers embedded metadata that ExifTool can read. No tool can guarantee removal "
    "of unknown or proprietary fields. Pixels, file names and filesystem timestamps are untouched."
)


def counts(artifacts: Iterable[Artifact]) -> Counter[str]:
    c: Counter[str] = Counter()
    for a in artifacts:
        if a.result:
            c[a.result.verdict.value] += 1
    return c


def verdict_line(c: Counter[str]) -> str:
    total = sum(c.values())
    if total == 0:
        return "NOTHING PROCESSED"
    return "ALL VERIFIED CLEAN" if c["CLEAN"] == total else "REVIEW REQUIRED"


def output_location(artifacts: Iterable[Artifact]) -> str:
    dirs = {str(a.result.output.parent) for a in artifacts if a.result and a.result.output}
    if not dirs:
        return "(no output written)"
    return next(iter(dirs)) if len(dirs) == 1 else f"{len(dirs)} folders"


def render_text(artifacts: list[Artifact], width: int = 38) -> str:
    done = [a for a in artifacts if a.result]
    c = counts(done)
    rule = "─" * width
    rows = [
        "EXIFTUI // PURGE REPORT", rule,
        f"ARTIFACTS PROCESSED  {len(done):>{width - 21}}",
        f"VERIFIED CLEAN       {c['CLEAN']:>{width - 21}}",
        f"PARTIAL              {c['PARTIAL']:>{width - 21}}",
        f"UNSUPPORTED          {c['UNSUPPORTED']:>{width - 21}}",
        f"FAILED               {c['FAILED']:>{width - 21}}",
        rule, f"VERDICT: {verdict_line(c)}", "",
        f"OUTPUT: {output_location(done)}", "",
    ]
    for a in done:
        r = a.result
        assert r is not None
        rows.append(f"{r.verdict.value:<11} {a.display}")
        for cat, names in r.remaining.items():
            rows.append(f"    remaining: {cat} ({len(names)})")
        for reason in r.reasons if r.verdict is not Verdict.PARTIAL else []:
            rows.append(f"    {reason}")
        if r.error:
            rows.append(f"    error: {r.error}")
        for note in r.notes:
            if "left untouched" in note:
                rows.append(f"    {note}")
    rows += ["", DISCLAIMER]
    return "\n".join(rows) + "\n"


def render_json(artifacts: list[Artifact]) -> str:
    done = [a for a in artifacts if a.result]
    c = counts(done)
    files = []
    for a in done:
        r = a.result
        assert r is not None
        files.append({
            "file": a.display,
            "mode": r.mode,
            "verdict": r.verdict.value,
            "output": str(r.output) if r.output else None,
            "in_place": r.in_place,
            "remaining": r.remaining,  # category -> qualified tag names (no values)
            "reasons": r.reasons,
            "error": r.error,
        })
    doc = {
        "tool": "exiftui",
        "version": __version__,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "totals": {k: c[k] for k in ("CLEAN", "PARTIAL", "UNSUPPORTED", "FAILED")}
        | {"processed": len(done)},
        "verdict": verdict_line(c),
        "output": output_location(done),
        "disclaimer": DISCLAIMER,
        "files": files,
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def export(artifacts: list[Artifact], fmt: str, directory: Path) -> Path:
    """Write the report without overwriting anything. Returns the path written."""
    text = render_json(artifacts) if fmt == "json" else render_text(artifacts)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ext = "json" if fmt == "json" else "txt"
    n = 0
    while True:
        suffix = f"-{n}" if n else ""
        path = directory / f"exiftui-report-{stamp}{suffix}.{ext}"
        try:
            with open(path, "x", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except FileExistsError:
            n += 1
