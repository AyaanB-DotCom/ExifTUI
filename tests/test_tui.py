from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_image, needs_exiftool
from textual.widgets import DataTable, Input, Static

from exiftui import render
from exiftui.app import ExifTUI
from exiftui.core import report
from exiftui.core.scanner import OUTPUT_DIR_NAME
from exiftui.models import Artifact, FileResult, Tag, Verdict
from exiftui.screens import ConfirmScrub, HelpScreen, PathPicker, ResultsScreen

pytestmark = needs_exiftool


def text_of(app: ExifTUI, selector: str) -> str:
    return str(app.query_one(selector, Static).render())


async def wait_idle(pilot, app, limit: float = 30) -> None:
    for _ in range(int(limit / 0.2)):
        await pilot.pause(0.2)
        if not app.running:
            return
    raise AssertionError("batch did not finish")


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    make_image(tmp_path / "a.jpg")
    make_image(tmp_path / "sub" / "b.png")
    return tmp_path


async def test_boots_with_empty_state_and_labelled_footer():
    app = ExifTUI(exiftool_version="13.55")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.theme == "necroterra"
        assert "No images loaded" in text_of(app, "#empty")
        keys = {k for k, ab in app.active_bindings.items() if ab.binding.show}
        assert {"a", "d", "i", "space", "s", "v", "r", "question_mark", "q"} <= keys


async def test_letter_keys_are_inert_while_typing_a_path():
    app = ExifTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("a")
        assert isinstance(app.screen, PathPicker)
        await pilot.press(*"sqvird?")  # every one of these is a global shortcut
        assert isinstance(app.screen, PathPicker)
        assert app.screen.query_one("#path", Input).value == "sqvird?"
        await pilot.press("escape")
        assert not isinstance(app.screen, PathPicker)


async def test_shortcuts_disabled_under_dialogs():
    app = ExifTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("s")  # must not open the scrub dialog on top of help
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        assert len(app.screen_stack) == 1


async def test_add_folder_via_picker_and_full_scrub_flow(folder):
    app = ExifTUI()
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("d")
        await pilot.press(*str(folder))
        await pilot.press("enter")
        await pilot.pause(1.0)
        assert [a.display for a in app.artifacts] == ["a.jpg", "sub/b.png"]
        await pilot.press("i")
        await pilot.pause(1.5)
        assert "EMBEDDED METADATA" in text_of(app, "#inspect-body")
        assert "LOCATION" in text_of(app, "#inspect-body")
        await pilot.press("s")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConfirmScrub)
        await pilot.press("enter")
        await wait_idle(pilot, app)
        await pilot.pause(0.5)
        assert isinstance(app.screen, ResultsScreen)
        assert {a.result.verdict for a in app.artifacts} == {Verdict.CLEAN}
        assert (folder / OUTPUT_DIR_NAME / "sub" / "b.png").is_file()
        # export both report formats; they must not contain tag values
        await pilot.press("j")
        await pilot.press("t")
        await pilot.pause(0.3)
        out = folder / OUTPUT_DIR_NAME
        js = next(out.glob("exiftui-report-*.json"))
        data = json.loads(js.read_text())
        assert data["totals"]["CLEAN"] == 2 and data["verdict"] == "ALL VERIFIED CLEAN"
        blob = js.read_text() + next(out.glob("exiftui-report-*.txt")).read_text()
        for secret in ("Jane Doe", "SN12345", "EditorX", "48.85"):
            assert secret not in blob
        await pilot.press("escape")
        assert len(app.screen_stack) == 1


async def test_in_place_needs_explicit_checkbox(folder):
    app = ExifTUI(initial_paths=[folder / "a.jpg"])
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(1.0)
        before = (folder / "a.jpg").read_bytes()
        await pilot.press("s")
        await pilot.pause(0.3)
        await pilot.press("escape")  # cancel: nothing may change
        await pilot.pause(0.3)
        assert (folder / "a.jpg").read_bytes() == before
        await pilot.press("s")
        await pilot.pause(0.3)
        await pilot.press("enter")  # default button: copy mode
        await wait_idle(pilot, app)
        assert (folder / "a.jpg").read_bytes() == before
        assert (folder / "a-clean.jpg").exists()


async def test_verify_unscrubbed_file_reports_partial(folder):
    app = ExifTUI(initial_paths=[folder / "a.jpg"])
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(1.0)
        await pilot.press("v")
        await pilot.pause(2.0)
        assert app.artifacts[0].result.verdict is Verdict.PARTIAL
        assert "PARTIAL" in text_of(app, "#inspect-body")


async def test_narrow_terminal_swaps_panels(folder):
    app = ExifTUI(initial_paths=[folder / "a.jpg"])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(1.0)
        assert app.has_class("compact") and not app.query_one("#inspect").display
        await pilot.press("i")
        await pilot.pause(1.5)
        assert app.has_class("view-inspect")
        assert app.query_one("#inspect").display and not app.query_one("#artifacts").display
        await pilot.press("escape")
        assert app.query_one("#artifacts").display


async def test_cancel_stops_batch_and_keeps_originals(tmp_path):
    n = 40  # enough that a cancel issued after the first result always lands mid-batch
    for i in range(n):
        make_image(tmp_path / f"{i}.jpg")
    app = ExifTUI(initial_paths=[tmp_path])
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(2.0)
        await pilot.press("s")
        await pilot.pause(0.3)
        await pilot.press("enter")
        for _ in range(100):  # wait for the first result, then cancel at once
            await pilot.pause(0.05)
            if any(a.result for a in app.artifacts):
                break
        await pilot.press("c")
        await wait_idle(pilot, app)
        done = [a for a in app.artifacts if a.result]
        assert 1 <= len(done) < n
        assert not list(tmp_path.rglob(".exiftui-*"))
        assert len(list((tmp_path / OUTPUT_DIR_NAME).glob("*.jpg"))) == len(done)


async def test_toggle_select_and_remove(folder):
    app = ExifTUI(initial_paths=[folder])
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(1.0)
        await pilot.press("space")
        assert app.artifacts[0].selected is False
        await pilot.press("x")
        assert len(app.artifacts) == 1
        assert app.query_one("#table", DataTable).row_count == 1
        assert (folder / "a.jpg").exists()  # removing from the list never touches the file


def test_report_text_matches_spec_shape():
    a = Artifact(Path("/x/p.jpg"), None, 1)
    a.result = FileResult(Verdict.PARTIAL, remaining={"Location": ["EXIF:GPS:GPSLatitude"]})
    b = Artifact(Path("/x/q.jpg"), None, 1)
    b.result = FileResult(Verdict.CLEAN)
    txt = report.render_text([a, b])
    assert "EXIFTUI // PURGE REPORT" in txt and "VERDICT: REVIEW REQUIRED" in txt
    assert "remaining: Location (1)" in txt


def test_inspection_hides_composite_duplicates_unless_raw():
    tags = [
        Tag("EXIF", "GPS", "GPSLatitude", "1"),
        Tag("Composite", "Composite", "GPSLatitude", "1"),
        Tag("Composite", "Composite", "ImageSize", "4x4"),
    ]
    a = Artifact(Path("/x/p.jpg"), None, 1)
    assert str(render.inspection(a.path.name, a.size, tags, raw=False)).count("GPSLatitude") == 1
    assert str(render.inspection(a.path.name, a.size, tags, raw=True)).count("GPSLatitude") == 2
