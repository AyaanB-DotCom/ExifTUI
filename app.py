"""The ExifTUI application: dashboard, workers and key handling."""

from __future__ import annotations

import contextlib
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Footer, ProgressBar, Static

from exiftui import __version__, render, themes
from exiftui.core import exiftool, report
from exiftui.core.batch import run_batch
from exiftui.core.sanitizer import Options
from exiftui.core.scanner import OUTPUT_DIR_NAME, scan_file, scan_folder
from exiftui.core.verifier import verify_file
from exiftui.models import Artifact, FileResult, Tag, Verdict
from exiftui.screens import ConfirmScrub, HelpScreen, PathPicker, ResultsScreen

COMPACT_BELOW = 100  # columns; narrower terminals show one panel at a time
MAIN_ACTIONS = {
    "add_files", "add_folder", "inspect", "toggle", "scrub", "verify", "results", "help",
    "raw", "remove", "cancel", "switch_panel", "view", "theme",
}


@dataclass
class Shown:
    """What the inspection panel is currently showing. Values live in memory only."""

    artifact: Artifact
    original: list[Tag] | None
    output: list[Tag] | None
    view: str  # "original" | "output" | "compare"


class ExifTUI(App[None]):
    CSS_PATH = "theme.tcss"
    TITLE = "ExifTUI"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("a", "add_files", "Add"),
        Binding("d", "add_folder", "Folder"),
        Binding("i", "inspect", "Inspect"),
        Binding("space", "toggle", "Select"),
        Binding("s", "scrub", "Scrub"),
        Binding("v", "verify", "Verify"),
        Binding("r", "results", "Results"),
        Binding("p", "theme", "Theme"),
        Binding("c", "cancel", "Cancel"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
        Binding("b", "view", "Before/after", show=False),
        Binding("t", "raw", "Raw tags", show=False),
        Binding("x", "remove", "Remove", show=False),
        Binding("tab", "switch_panel", "Panel", show=False, priority=True),
        Binding("escape", "back", "Back", show=False),
    ]

    def __init__(
        self,
        initial_paths: list[Path] | None = None,
        exiftool_version: str = "",
        theme: str = themes.DEFAULT,
    ) -> None:
        super().__init__()
        for palette in themes.THEMES.values():
            self.register_theme(palette.textual_theme())
        themes.set_current(theme)
        self.theme = theme  # before the stylesheet loads, so $nt-* variables resolve
        self.initial_paths = initial_paths or []
        self.exiftool_version = exiftool_version
        self.artifacts: list[Artifact] = []
        self._by_path: dict[str, Artifact] = {}
        self._cancel = threading.Event()
        self.running = False
        self._phase = "READY"
        self._shown: Shown | None = None
        self._raw = False
        self._panel_fn = render.intro
        self._last_say: tuple[str, bool] = ("Ready.", False)

    # ---------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(id="brand")
            yield Static(id="topstate")
        with Horizontal(id="body"):
            with Vertical(id="artifacts", classes="panel"):
                yield Static(self._empty_text(), id="empty")
                yield DataTable(id="table", cursor_type="row", zebra_stripes=False)
            with VerticalScroll(id="inspect", classes="panel"):
                yield Static(render.intro(), id="inspect-body")
        with Vertical(id="status"):
            yield Static("Ready.", id="activity")
            yield ProgressBar(total=1, show_eta=False, id="bar")
        yield Footer(compact=True)

    @staticmethod
    def _empty_text() -> Text:
        p = themes.current()
        chip = f"bold {p.key_fg} on {p.key_bg}"
        t = Text()
        t.append("No images loaded.\n\n", style=f"bold {p.fg}")
        t.append(" A ", style=chip)
        t.append(" add images   ")
        t.append(" D ", style=chip)
        t.append(" add a folder\n\n")
        t.append("Paths can also be given on the command line:\n  exiftui photo.jpg ~/Pictures\n",
                 style=p.dim)
        return t

    def on_mount(self) -> None:
        self.query_one("#artifacts").border_title = " ARTIFACTS "
        self.query_one("#inspect").border_title = " INSPECTION "
        self.query_one("#status").border_title = " STATUS "
        table = self.query_one("#table", DataTable)
        table.display = False
        table.focus()
        self._apply_layout(self.size.width)
        self._rebuild_table()
        self._refresh_topbar()
        self.query_one("#bar", ProgressBar).update(total=1, progress=0)
        if self.initial_paths:
            self._add_paths(self.initial_paths, recursive=True)

    def on_resize(self, event: events.Resize) -> None:
        self._apply_layout(event.size.width)
        self.call_after_refresh(self._rebuild_table)

    def _apply_layout(self, width: int) -> None:
        compact = width < COMPACT_BELOW
        self.set_class(compact, "compact")
        if not compact:
            self.remove_class("view-inspect")
        self.refresh_bindings()

    @property
    def _compact(self) -> bool:
        return self.has_class("compact")

    # ---------------------------------------------------------------- state helpers
    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in MAIN_ACTIONS:
            if len(self.screen_stack) > 1:
                return False  # a dialog or the results screen is on top
            if action == "cancel":
                return bool(self.running)
            if action == "switch_panel":
                return self._compact
        return True

    def _say(self, text: str, error: bool = False) -> None:
        p = themes.current()
        self._last_say = (text, error)
        self.query_one("#activity", Static).update(
            Text(("✖ " if error else "") + text, style=f"bold {p.box_bad if error else p.box_fg}")
        )

    def _set_phase(self, phase: str) -> None:
        self._phase = phase
        self._refresh_topbar()

    def _refresh_topbar(self) -> None:
        p = themes.current()
        brand = Text()
        brand.append(" EXIF ", style=f"bold {p.plate_fg}")
        brand.append(" TUI ", style=f"bold {p.plate_tag_fg} on {p.plate_tag_bg}")
        brand.append(f" v{__version__}", style=p.plate_fg)
        self.query_one("#brand", Static).update(brand)
        c = report.counts(self.artifacts)
        st = Text(justify="right")
        if self.artifacts:
            st.append("● ", style=p.plate_ok)
            st.append(f"{c['CLEAN']}  ")
            st.append("▲ ", style=p.plate_warn)
            st.append(f"{c['PARTIAL']}  ")
            st.append("✖ ", style=p.plate_bad)
            st.append(f"{c['FAILED']}   ")
        st.append(f"{self._phase}", style=f"bold {p.plate_fg}")
        if self.exiftool_version and self.size.width >= 90:
            st.append(f"  exiftool {self.exiftool_version}", style=p.plate_fg)
        self.query_one("#topstate", Static).update(st)

    # ---------------------------------------------------------------- themes
    def action_theme(self) -> None:
        names = list(themes.THEMES)
        nxt = names[(names.index(themes.current().name.lower()) + 1) % len(names)]
        self._apply_theme(nxt)
        p = themes.current()
        self._say(f"Theme {p.name}: {p.blurb}")

    def _apply_theme(self, name: str) -> None:
        themes.set_current(name)
        self.theme = name
        self.query_one("#empty", Static).update(self._empty_text())
        self._rebuild_table()
        self._refresh_topbar()
        self._refresh_panel()
        self._say(*self._last_say)

    # ---------------------------------------------------------------- table
    def _name_width(self) -> int:
        w = self.query_one("#artifacts").size.width or 40
        return max(10, w - 4 - (3 + 5 + 7 + 13) - 2 * 5 - 1)

    def _row_cells(self, a: Artifact, nw: int) -> list[object]:
        return [
            Text("[x]" if a.selected else "[ ]",
                 style=themes.current().warn if a.selected else themes.current().dim),
            Text(render.tail(a.display, nw)),
            Text(a.ext[:4], style=themes.current().cyan),
            Text(render.human_size(a.size), justify="right"),
            render.state_text(a),
        ]

    def _rebuild_table(self) -> None:
        table = self.query_one("#table", DataTable)
        keep = table.cursor_row if table.row_count else 0
        nw = self._name_width()
        table.clear(columns=True)
        table.add_column("", width=3, key="sel")
        table.add_column("NAME", width=nw, key="name")
        table.add_column("TYPE", width=5, key="type")
        table.add_column("SIZE", width=7, key="size")
        table.add_column("STATUS", width=13, key="state")
        for a in self.artifacts:
            table.add_row(*self._row_cells(a, nw), key=str(a.path))
        has = bool(self.artifacts)
        table.display = has
        self.query_one("#empty").display = not has
        if has:
            table.move_cursor(row=min(keep, len(self.artifacts) - 1))

    def _update_row(self, a: Artifact) -> None:
        table = self.query_one("#table", DataTable)
        cells = self._row_cells(a, self._name_width())
        for col, val in zip(("sel", "name", "type", "size", "state"), cells, strict=True):
            table.update_cell(str(a.path), col, val)

    def _current(self) -> Artifact | None:
        table = self.query_one("#table", DataTable)
        if not self.artifacts or not table.row_count:
            return None
        try:
            key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value
        except Exception:  # noqa: BLE001 - empty or mid-rebuild table
            return None
        return self._by_path.get(key or "")

    def _selected(self) -> list[Artifact]:
        return [a for a in self.artifacts if a.selected and a.state != "working"]

    # ---------------------------------------------------------------- adding
    def action_add_files(self) -> None:
        self.push_screen(PathPicker("files"), self._picked)

    def action_add_folder(self) -> None:
        self.push_screen(PathPicker("dir"), self._picked)

    def _picked(self, value: tuple[list[Path], bool] | None) -> None:
        if value:
            self._add_paths(*value)

    def _add_paths(self, paths: list[Path], recursive: bool) -> None:
        self._say("Scanning…")
        self._scan_worker(paths, recursive)

    @work(thread=True, exclusive=True, group="scan")
    def _scan_worker(self, paths: list[Path], recursive: bool) -> None:
        found: list[Artifact] = []
        notes: list[str] = []
        for p in paths:
            try:
                if p.expanduser().is_dir():
                    res = scan_folder(p.expanduser(), recursive=recursive)
                    found += res.artifacts
                    for label, n in (("symlinks", res.skipped_symlinks),
                                     ("earlier outputs", res.skipped_previous_output),
                                     ("non-image files", res.ignored_other)):
                        if n:
                            notes.append(f"{n} {label} skipped")
                    notes += res.errors
                else:
                    a = scan_file(p)
                    if a:
                        found.append(a)
                    else:
                        notes.append(f"not a file: {p.name}")
            except OSError as exc:
                notes.append(f"{p.name}: {exc.strerror or 'unreadable'}")
        self._ui(self._merge, found, notes)

    def _merge(self, found: list[Artifact], notes: list[str]) -> None:
        added = 0
        for a in found:
            if str(a.path) not in self._by_path:
                self._by_path[str(a.path)] = a
                self.artifacts.append(a)
                added += 1
        self._rebuild_table()
        self._refresh_topbar()
        msg = f"Added {added} image(s)." + ("  " + "; ".join(notes) if notes else "")
        self._say(msg, error=added == 0 and bool(notes))
        self.query_one("#table", DataTable).focus()

    # ---------------------------------------------------------------- selection
    def action_toggle(self) -> None:
        if a := self._current():
            a.selected = not a.selected
            self._update_row(a)

    def action_remove(self) -> None:
        a = self._current()
        if a and not self.running:
            self.artifacts.remove(a)
            del self._by_path[str(a.path)]
            self._rebuild_table()
            self._refresh_topbar()
            self._say(f"Removed {a.path.name} from the list (file untouched).")

    # ---------------------------------------------------------------- inspect
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_inspect()

    def action_inspect(self) -> None:
        a = self._current()
        if a is None:
            self._say("Nothing to inspect. Press A or D to add images.", error=True)
            return
        self._say(f"Inspecting {a.path.name}…")
        self._inspect_worker(a)

    @work(thread=True, exclusive=True, group="inspect")
    def _inspect_worker(self, a: Artifact) -> None:
        """Read the original and, if the file was scrubbed to a new copy, the output too."""
        r = a.result
        out_path = r.output if r and r.output else None
        original = output = None
        errors: list[str] = []
        if not (r and r.in_place):
            try:
                original = exiftool.inspect(a.path)
            except exiftool.ExifToolError as exc:
                errors.append(str(exc))
        if out_path:
            try:
                output = exiftool.inspect(out_path)
            except exiftool.ExifToolError as exc:
                errors.append(str(exc))
        if original is None and output is None:
            self._ui(self._say, f"Inspect failed: {errors[0] if errors else 'unreadable'}", True)
            return
        self._ui(self._show_tags, a, original, output)

    def _show_tags(self, a: Artifact, original: list[Tag] | None, output: list[Tag] | None) -> None:
        if original is not None and output is not None:
            view = "compare"
        else:
            view = "output" if output is not None else "original"
        self._shown = Shown(a, original, output, view)
        self._set_panel(self._inspection_text)
        what = {"compare": "before and after", "output": "output", "original": "original"}[view]
        self._say(f"Inspected {a.path.name}: {what} (read-only).")
        if self._compact:
            self.add_class("view-inspect")
            self.query_one("#inspect").focus()

    def _available_views(self) -> list[str]:
        s = self._shown
        if s is None:
            return []
        views = []
        if s.original is not None:
            views.append("original")
        if s.output is not None:
            views.append("output")
        if s.original is not None and s.output is not None:
            views.append("compare")
        return views

    def action_view(self) -> None:
        views = self._available_views()
        if len(views) < 2 or self._shown is None:
            self._say("Nothing to compare yet: scrub a file, then press I on it.", error=True)
            return
        self._shown.view = views[(views.index(self._shown.view) + 1) % len(views)]
        self._refresh_panel()
        self._say(f"View: {self._shown.view}.")

    def _inspection_text(self) -> Text:
        s = self._shown
        assert s is not None
        p = themes.current()
        width = self.query_one("#inspect").size.width - 4
        views = self._available_views()
        header = Text()
        if len(views) > 1:
            header.append_text(render.view_bar(s.view, views))
        a, r = s.artifact, s.artifact.result
        if r and r.in_place:
            header.append("In-place scrub: the original was replaced, so there is nothing to "
                          "compare.\n\n", style=p.dim)
        if s.view == "compare":
            assert s.original is not None and s.output is not None
            return render.comparison(
                f"{a.path.name}  →  {r.output.name if r and r.output else ''}",
                s.original, s.output, self._raw, width, header, r.verdict if r else None,
            )
        if s.view == "output" and r and r.output:
            try:
                size = r.output.stat().st_size
            except OSError:
                size = 0
            assert s.output is not None
            return render.inspection(r.output.name, size, s.output, self._raw, width, header)
        assert s.original is not None
        return render.inspection(a.path.name, a.size, s.original, self._raw, width, header)

    def _set_panel(self, fn) -> None:  # type: ignore[no-untyped-def]
        self._panel_fn = fn
        self._refresh_panel()

    def _refresh_panel(self) -> None:
        self.query_one("#inspect-body", Static).update(self._panel_fn())
        view = self._shown.view.upper() if self._shown else ""
        title = f" INSPECTION · {view} " if view else " INSPECTION "
        self.query_one("#inspect").border_title = title

    def action_raw(self) -> None:
        self._raw = not self._raw
        self._refresh_panel()
        self._say("Raw tag names " + ("on." if self._raw else "off."))

    def action_switch_panel(self) -> None:
        if not self._compact:
            return
        self.toggle_class("view-inspect")
        target = "#inspect" if self.has_class("view-inspect") else "#table"
        self.query_one(target).focus()

    def action_back(self) -> None:
        if self._compact and self.has_class("view-inspect"):
            self.remove_class("view-inspect")
            self.query_one("#table", DataTable).focus()

    # ---------------------------------------------------------------- scrub
    def action_scrub(self) -> None:
        if self.running:
            return
        sel = self._selected()
        if not sel:
            self._say("Nothing selected. Add images (A / D) and select them (Space).", error=True)
            return
        restricted = sum(1 for a in sel if a.unsupported_reason)
        self.push_screen(
            ConfirmScrub(len(sel), restricted, self._destinations(sel)),
            lambda in_place: self._start_scrub(sel, in_place),
        )

    @staticmethod
    def _destinations(sel: list[Artifact]) -> str:
        roots = {a.root for a in sel if a.root}
        parts = [render.tail(f"{r}/{OUTPUT_DIR_NAME}/", 62) for r in sorted(roots, key=str)[:2]]
        if len(roots) > 2:
            parts.append(f"… {len(roots) - 2} more folders")
        if any(a.root is None for a in sel):
            parts.append("name-clean.ext beside each single file")
        return "\n        ".join(parts)

    def _start_scrub(self, sel: list[Artifact], in_place: bool | None) -> None:
        if in_place is None:
            self._say("Scrub cancelled before starting.")
            return
        for a in sel:
            a.result, a.state = None, "queued"
            self._update_row(a)
        self._cancel = threading.Event()
        self.running = True
        self.refresh_bindings()
        self._set_phase("WORKING")
        self.query_one("#bar", ProgressBar).update(total=len(sel), progress=0)
        self._say(f"Scrubbing {len(sel)} file(s)…")
        self._scrub_worker(sel, Options(in_place=in_place), self._cancel)

    @work(thread=True, exclusive=True, group="batch")
    def _scrub_worker(self, sel: list[Artifact], opts: Options, cancel: threading.Event) -> None:
        run_batch(
            sel, opts, cancel,
            on_start=lambda a: self._ui(self._mark_working, a),
            on_result=lambda a, r: self._ui(self._finish_one, a, r),
        )
        self._ui(self._batch_done, sel, cancel.is_set())

    def _ui(self, fn, *args) -> None:  # type: ignore[no-untyped-def]
        """Run on the UI thread; silently drop updates if the app is already shutting down."""
        with contextlib.suppress(Exception):
            self.call_from_thread(fn, *args)

    def _mark_working(self, a: Artifact) -> None:
        a.state = "working"
        self._update_row(a)

    def _finish_one(self, a: Artifact, r: FileResult | None) -> None:
        a.state = "done" if r else "queued"
        a.result = r
        self._update_row(a)
        bar = self.query_one("#bar", ProgressBar)
        bar.advance(1)
        done = int(bar.progress or 0)
        c = report.counts(self.artifacts)
        self._say(f"{done}/{int(bar.total or 0)}  clean {c['CLEAN']} · partial {c['PARTIAL']}"
                  f" · unsupported {c['UNSUPPORTED']} · failed {c['FAILED']}")
        self._refresh_topbar()

    def _batch_done(self, sel: list[Artifact], cancelled: bool) -> None:
        self.running = False
        self.refresh_bindings()
        c: Counter[str] = report.counts(sel)
        if cancelled:
            self._set_phase("CANCELLED")
            self._say(f"Cancelled. {sum(c.values())} file(s) finished, the rest were not touched.")
        else:
            self._set_phase("DONE")
            self._say(f"Done: {c['CLEAN']} clean, {c['PARTIAL']} partial, "
                      f"{c['UNSUPPORTED']} unsupported, {c['FAILED']} failed.",
                      error=c["FAILED"] > 0)
            self.action_results()

    def action_cancel(self) -> None:
        if self.running:
            self._cancel.set()
            self._say("Cancelling… in-flight files are finished or discarded safely.")

    # ---------------------------------------------------------------- verify
    def action_verify(self) -> None:
        a = self._current()
        if a is None:
            self._say("Nothing to verify. Add images first.", error=True)
            return
        target = a.result.output if a.result and a.result.output else a.path
        self._say(f"Verifying {target.name}…")
        self._verify_worker(a, target)

    @work(thread=True, exclusive=True, group="verify")
    def _verify_worker(self, a: Artifact, target: Path) -> None:
        res = verify_file(target)
        self._ui(self._show_verification, a, target, res)

    def _show_verification(self, a: Artifact, target: Path, res: FileResult) -> None:
        old = a.result
        if old is not None and old.output == target:  # keep scrub details, refresh the verdict
            old.verdict, old.remaining, old.reasons = res.verdict, res.remaining, res.reasons
            old.error, old.notes = res.error, res.notes
        else:
            a.result = res
        a.state = "done"
        self._update_row(a)
        self._refresh_topbar()
        self._shown = None
        self._set_panel(lambda: render.verification(target.name, res))
        self._say(f"Verified {target.name}: {res.verdict.value}.",
                  error=res.verdict is Verdict.FAILED)
        if self._compact:
            self.add_class("view-inspect")

    # ---------------------------------------------------------------- misc screens
    def action_results(self) -> None:
        if not any(a.result for a in self.artifacts):
            self._say("No results yet. Scrub or verify something first.", error=True)
            return
        outs = [a.result.output for a in self.artifacts if a.result and a.result.output]
        export_dir = outs[0].parent if outs else Path.cwd()
        self.push_screen(ResultsScreen(self.artifacts, export_dir))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_quit(self) -> None:  # type: ignore[override]
        self._cancel.set()
        self.exit()
