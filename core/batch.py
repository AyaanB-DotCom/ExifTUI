"""Bounded-concurrency batch runner. Pure Python threads; the TUI drives it from a worker."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from exiftui.core import exiftool
from exiftui.core.sanitizer import Options, sanitize
from exiftui.models import Artifact, FileResult, Verdict

MAX_WORKERS = 4  # each worker is one short-lived exiftool process


def run_batch(
    artifacts: Sequence[Artifact],
    opts: Options,
    cancel: threading.Event,
    on_start: Callable[[Artifact], None] = lambda a: None,
    on_result: Callable[[Artifact, FileResult | None], None] = lambda a, r: None,
    workers: int | None = None,
) -> None:
    """Scrub every artifact. `on_result` gets None for files skipped or cut short by cancel."""
    n = workers or min(MAX_WORKERS, os.cpu_count() or 2)

    def job(a: Artifact) -> None:
        if cancel.is_set():
            on_result(a, None)
            return
        on_start(a)
        try:
            on_result(a, sanitize(a, opts, cancel))
        except exiftool.Cancelled:
            on_result(a, None)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
            err = f"internal error ({type(exc).__name__})"
            on_result(a, FileResult(verdict=Verdict.FAILED, error=err))

    with ThreadPoolExecutor(max_workers=n) as pool:
        for f in [pool.submit(job, a) for a in artifacts]:
            f.result()
