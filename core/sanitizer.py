"""Non-destructive scrubbing: ExifTool writes to a private temp file, we verify it, then move it
into place without ever overwriting an existing file (unless in-place mode was confirmed)."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from exiftui.core import exiftool
from exiftui.core.classify import is_embedded_metadata
from exiftui.core.formats import policy_for
from exiftui.core.scanner import OUTPUT_DIR_NAME
from exiftui.core.verifier import NOTE_PIXELS, dimensions, file_type, judge
from exiftui.models import Artifact, FileResult, Verdict


@dataclass(frozen=True)
class Options:
    in_place: bool = False


def planned_output(a: Artifact) -> Path:
    """Where a scrubbed copy of `a` should go (before collision handling)."""
    if a.root is not None:
        out_root = a.root / OUTPUT_DIR_NAME
        dest = out_root / a.path.relative_to(a.root)
        if os.path.commonpath([out_root, dest]) != str(out_root):  # defence in depth
            raise ValueError("output path escapes the output folder")
        return dest
    return a.path.with_name(f"{a.path.stem}-clean{a.path.suffix}")


def _unique_link(tmp: Path, dest: Path) -> Path:
    """Move `tmp` to `dest` (or dest-2, dest-3, ...) atomically, never replacing a file."""
    n = 1
    while True:
        cand = dest if n == 1 else dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
        try:
            os.link(tmp, cand)
            return cand
        except FileExistsError:
            n += 1
        except OSError:
            # Filesystem without hard links (e.g. exFAT): exclusive-create a copy instead.
            try:
                with open(tmp, "rb") as src, open(cand, "xb") as dst:
                    shutil.copyfileobj(src, dst)
                return cand
            except FileExistsError:
                n += 1
            except OSError:
                cand.unlink(missing_ok=True)
                raise


def _fail(msg: str) -> FileResult:
    return FileResult(Verdict.FAILED, error=msg[:200])


def sanitize(
    a: Artifact, opts: Options = Options(), cancel: threading.Event | None = None  # noqa: B008
) -> FileResult:
    """Scrub one artifact. Raises exiftool.Cancelled if cancelled; otherwise returns a result."""
    if a.unsupported_reason:
        return FileResult(Verdict.UNSUPPORTED, reasons=[a.unsupported_reason])
    src = a.path
    tmpdir: str | None = None
    try:
        try:
            before = exiftool.inspect(src, cancel=cancel)
        except exiftool.ExifToolError as exc:
            return _fail(str(exc))
        pre = judge(before)  # type / corruption check on the source
        if pre.verdict in (Verdict.UNSUPPORTED, Verdict.FAILED):
            pre.mode = "scrub"
            return pre
        ftype = file_type(before) or ""
        policy = policy_for(ftype)
        if policy is None:  # judge() already rejects these; kept so the contract is local
            return FileResult(Verdict.UNSUPPORTED, reasons=[f"No safe policy for {ftype}"])
        src_dims = dimensions(before)
        before_count = sum(1 for t in before if is_embedded_metadata(t))

        planned = src if opts.in_place else planned_output(a)
        dest_dir = planned.parent
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            tmpdir = tempfile.mkdtemp(prefix=".exiftui-", dir=dest_dir)
        except OSError as exc:
            return _fail(f"cannot write to output folder: {exc.strerror or type(exc).__name__}")
        tmp = Path(tmpdir) / f"out{src.suffix}"

        res = exiftool.run([*policy.args, "-o", str(tmp), str(src)], cancel=cancel)
        if res.returncode != 0 or not tmp.exists():
            return _fail(exiftool.first_line(res.stderr) or "exiftool did not write an output")
        errs = [ln for ln in res.stderr.splitlines() if ln.startswith("Error")]
        if errs:
            return _fail(errs[0])

        after = exiftool.inspect(tmp, cancel=cancel)
        verdict = judge(after, tmp)
        if verdict.verdict is Verdict.FAILED:
            return _fail(f"output failed verification: {verdict.error}")
        if src_dims is not None and dimensions(after) != src_dims:
            return _fail("output dimensions differ from the source")
        verdict.mode = "scrub"
        verdict.before_count = before_count

        if opts.in_place:
            if verdict.verdict is not Verdict.CLEAN:
                verdict.notes.append("Original left untouched: in-place needs a CLEAN result.")
                return verdict
            shutil.copymode(src, tmp)
            os.replace(tmp, src)
            verdict.output, verdict.in_place = src, True
        else:
            shutil.copymode(src, tmp)
            verdict.output = _unique_link(tmp, planned)
        return verdict
    except exiftool.Cancelled:
        raise
    except exiftool.ExifToolError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(f"file error: {exc.strerror or type(exc).__name__}")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


__all__ = ["NOTE_PIXELS", "Options", "planned_output", "sanitize"]
