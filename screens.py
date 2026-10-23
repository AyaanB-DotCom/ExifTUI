"""Modal dialogs and the results screen."""

from __future__ import annotations

import shlex
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    DirectoryTree,
    Footer,
    Input,
    Label,
    Static,
)

from exiftui.core import report
from exiftui.core.formats import SCAN_EXTENSIONS
from exiftui.models import Artifact
from exiftui.render import HELP, clip, purge_summary, result_detail, state_text


class ImageTree(DirectoryTree):
    """Shows folders and image files only, hides dotfiles."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            p for p in paths
            if not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() in SCAN_EXTENSIONS)
        ]


class PathPicker(ModalScreen[tuple[list[Path], bool] | None]):
    """Add files or a folder. Accepts typed or pasted/dragged paths, or browse the tree."""

    BINDINGS = [Binding("escape", "cancel", "Close")]

    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode  # "files" | "dir"

    def compose(self) -> ComposeResult:
        files = self.mode == "files"
        with Vertical(classes="dialog"):
            yield Label("ADD IMAGES" if files else "ADD FOLDER", classes="dialog-title")
            yield Label(
                "Type, paste or drag a path (several are fine), then press Enter."
                if files else "Type, paste or drag a folder path, then press Enter.",
                classes="hint",
            )
            yield Input(placeholder="/path/to/photo.jpg" if files else "/path/to/folder", id="path")
            yield ImageTree(str(Path.home()), id="tree")
            if not files:
                yield Checkbox("Include subfolders", True, id="recursive")
            yield Label(
                "Tab: switch input / browser · Enter on a file adds it" if files
                else "Tab: switch input / browser · Enter on a folder picks it · → expands",
                classes="hint",
            )
            with Horizontal(classes="buttons"):
                yield Button("Add", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#path", Input).focus()
        if self.mode == "dir":
            self.query_one("#tree", ImageTree).auto_expand = False

    def _recursive(self) -> bool:
        return self.query_one("#recursive", Checkbox).value if self.mode == "dir" else False

    def _submit(self) -> None:
        raw = self.query_one("#path", Input).value.strip()
        if not raw:
            return
        try:
            parts = shlex.split(raw)  # handles quotes and "My\ Photos" from drag-and-drop
        except ValueError:
            parts = [raw]
        paths = [Path(p).expanduser() for p in parts]
        self.dismiss((paths, self._recursive()))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        if self.mode == "files":
            self.dismiss(([event.path], False))

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        event.stop()
        if self.mode == "dir":
            self.dismiss(([event.path], self._recursive()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScrub(ModalScreen[bool | None]):
    """Summary before writing anything. Returns in_place (bool) or None if cancelled."""

    BINDINGS = [Binding("escape", "cancel", "Close")]

    def __init__(self, total: int, restricted: int, destinations: str) -> None:
        super().__init__()
        self.total, self.restricted, self.destinations = total, restricted, destinations

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("START SCRUB", classes="dialog-title")
            body = Text()
            body.append(f"{self.total} file(s) selected", style="bold")
            if self.restricted:
                body.append(f", {self.restricted} of them restricted and will be skipped")
            body.append(".\n\nOutput: " + self.destinations + "\n")
            body.append("Originals are preserved. Existing files are never overwritten.\n")
            yield Static(body, id="confirm-body")
            yield Checkbox("Overwrite originals in place (no copy is kept)", False, id="inplace")
            yield Label(
                "In-place only replaces a file once its result verifies CLEAN.",
                classes="hint", id="inplace-hint",
            )
            with Horizontal(classes="buttons"):
                yield Button("Start", variant="primary", id="go")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#go", Button).focus()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        go = self.query_one("#go", Button)
        go.label = "OVERWRITE ORIGINALS" if event.value else "Start"
        go.variant = "error" if event.value else "primary"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "go":
            self.dismiss(self.query_one("#inplace", Checkbox).value)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,q", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("HELP · theme NECROTERRA", classes="dialog-title")
            with VerticalScroll(id="help-body"):
                yield Static(HELP)
            with Horizontal(classes="buttons"):
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ResultsScreen(Screen[None]):
    BINDINGS = [
        Binding("escape,r", "back", "Back"),
        Binding("j", "export('json')", "Export JSON"),
        Binding("t", "export('text')", "Export text"),
    ]

    def __init__(self, artifacts: list[Artifact], export_dir: Path) -> None:
        super().__init__()
        self.artifacts = [a for a in artifacts if a.result]
        self.export_dir = export_dir

    def compose(self) -> ComposeResult:
        c: Counter[str] = report.counts(self.artifacts)
        with Vertical(id="results"):
            yield Static(purge_summary(self.artifacts, c), id="purge")
            yield DataTable(id="results-table", cursor_type="row", zebra_stripes=False)
            yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_column("Status", width=13)
        table.add_column("File", width=max(20, self.app.size.width - 42))
        table.add_column("Left", width=6)
        for i, a in enumerate(self.artifacts):
            r = a.result
            assert r is not None
            left = sum(len(v) for v in r.remaining.values())
            table.add_row(
                state_text(a), clip(a.display, max(20, self.app.size.width - 42)),
                str(left) if left else "–", key=str(i),
            )
        self.query_one("#detail", Static).border_title = " DETAIL "
        self.query_one("#results-table", DataTable).border_title = " PER-FILE RESULTS "
        if self.artifacts:
            self._show(0)
        table.focus()

    def _show(self, index: int) -> None:
        self.query_one("#detail", Static).update(result_detail(self.artifacts[index]))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value is not None:
            self._show(int(event.row_key.value))

    def action_back(self) -> None:
        self.dismiss(None)

    def action_export(self, fmt: str) -> None:
        try:
            path = report.export(self.artifacts, fmt, self.export_dir)
        except OSError as exc:
            self.notify(f"Export failed: {exc.strerror or 'cannot write'}", severity="error")
            return
        self.notify(f"Report saved: {path}")


