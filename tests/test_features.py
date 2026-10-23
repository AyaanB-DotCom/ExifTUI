"""Themes and the before/after comparison."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import make_image, needs_exiftool, write_meta
from textual.widgets import Static

from exiftui import render, themes
from exiftui.app import ExifTUI
from exiftui.cli import build_parser
from exiftui.core import exiftool
from exiftui.core.sanitizer import Options, sanitize
from exiftui.models import Artifact, FileResult, Verdict


def panel_text(app: ExifTUI) -> str:
    return str(app.query_one("#inspect-body", Static).render())


async def scrub_all(pilot, app) -> None:
    await pilot.press("s")
    await pilot.pause(0.4)
    await pilot.press("enter")
    for _ in range(150):
        await pilot.pause(0.2)
        if not app.running:
            break
    await pilot.pause(0.6)
    await pilot.press("escape")  # leave the auto-opened results screen
    await pilot.pause(0.3)


# --- themes ----------------------------------------------------------------------------------

def test_every_palette_is_complete_and_valid():
    assert set(themes.THEMES) == {"necroterra", "oxide", "lampblack", "parchment"}
    for p in themes.THEMES.values():
        vars_ = p.css_variables
        assert "nt-ground" in vars_ and "nt-box-bg" in vars_
        assert all(re.fullmatch(r"#[0-9a-f]{6}", v) for v in vars_.values()), p.name
        p.textual_theme()  # constructs without error


def test_stylesheet_only_uses_defined_variables():
    css = (Path(themes.__file__).parent / "theme.tcss").read_text()
    used = set(re.findall(r"\$(nt-[a-z-]+)", css))
    assert used <= set(themes.NECROTERRA.css_variables), used - set(themes.NECROTERRA.css_variables)


def test_cli_theme_flag():
    assert build_parser().parse_args(["--theme", "oxide"]).theme == "oxide"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--theme", "neon-green"])


@needs_exiftool
async def test_p_cycles_through_all_themes_and_back(tmp_path):
    make_image(tmp_path / "a.jpg")
    app = ExifTUI(initial_paths=[tmp_path / "a.jpg"])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(1.0)
        seen = [app.theme]
        for _ in range(len(themes.THEMES)):
            await pilot.press("p")
            await pilot.pause(0.2)
            seen.append(app.theme)
            assert themes.current().name.lower() == app.theme
        assert seen[0] == seen[-1] == "necroterra"
        assert set(seen) == set(themes.THEMES)
        # text built by render.py follows the theme too
        await pilot.press("p")
        assert themes.current().name == "OXIDE"
        done = Artifact(tmp_path / "x.jpg")
        done.result = FileResult(Verdict.CLEAN)
        assert render.state_text(done).style == themes.OXIDE.ok
    themes.set_current("necroterra")


@needs_exiftool
async def test_start_theme_and_light_theme_footer_is_legible(tmp_path):
    app = ExifTUI(theme="parchment")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        assert app.theme == "parchment"
        assert "PARCHMENT" in str(app.query_one("#inspect-body", Static).render())
        await pilot.press("p")  # wraps to the first theme
        assert app.theme == "necroterra"
    themes.set_current("necroterra")


# --- comparison ------------------------------------------------------------------------------

@needs_exiftool
def test_compare_tags_on_real_files(jpg):
    out = sanitize(Artifact(jpg, None, 1)).output
    d = render.compare_tags(exiftool.inspect(jpg), exiftool.inspect(out))
    removed = {t.name for t in d["removed"]}
    assert {"GPSLatitude", "Make", "SerialNumber", "Artist", "Software"} <= removed
    assert d["still"] == []
    assert "Orientation" in {t.name for t in d["kept"]}


@needs_exiftool
def test_compare_flags_metadata_still_present(jpg):
    out = sanitize(Artifact(jpg, None, 1)).output
    write_meta(out, "-Artist=Leaked")
    d = render.compare_tags(exiftool.inspect(jpg), exiftool.inspect(out))
    assert [t.name for t, _ in d["still"]] == ["Artist"]
    txt = str(render.comparison("x", exiftool.inspect(jpg), exiftool.inspect(out), False))
    assert "STILL EMBEDDED 1" in txt and "▲" in txt


@needs_exiftool
def test_compare_ignores_filesystem_fields(jpg):
    out = sanitize(Artifact(jpg, None, 1)).output
    d = render.compare_tags(exiftool.inspect(jpg), exiftool.inspect(out))
    every = d["removed"] + d["kept"] + d["added"]
    assert not [t for t in every if t.group1 == "System"]


@needs_exiftool
async def test_inspect_after_scrub_shows_before_after_and_b_cycles(tmp_path):
    make_image(tmp_path / "a.jpg")
    app = ExifTUI(initial_paths=[tmp_path / "a.jpg"])
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(1.0)
        await pilot.press("b")  # nothing scrubbed yet
        assert "Nothing to compare" in str(app.query_one("#activity", Static).render())
        await scrub_all(pilot, app)
        await pilot.press("i")
        await pilot.pause(2.0)
        txt = panel_text(app)
        assert "COMPARE" in app.query_one("#inspect").border_title
        assert "REMOVED" in txt and "Canon" in txt and "GPSLatitude" in txt
        assert "STILL EMBEDDED 0" in txt and "CLEAN" in txt
        await pilot.press("b")  # cycle order: original -> output -> compare -> original
        assert "ORIGINAL" in app.query_one("#inspect").border_title
        assert "Canon" in panel_text(app)
        await pilot.press("b")
        assert "OUTPUT" in app.query_one("#inspect").border_title
        assert "Canon" not in panel_text(app)
        assert "No removable embedded metadata" in panel_text(app)
        await pilot.press("b")
        assert "COMPARE" in app.query_one("#inspect").border_title
        # a theme change while viewing must not lose the view
        await pilot.press("p")
        assert "COMPARE" in app.query_one("#inspect").border_title
    themes.set_current("necroterra")


@needs_exiftool
async def test_inspect_after_in_place_has_no_comparison(tmp_path):
    p = make_image(tmp_path / "a.jpg")
    app = ExifTUI(initial_paths=[p])
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause(1.0)
        a = app.artifacts[0]
        a.result = sanitize(a, Options(in_place=True))
        assert a.result.verdict is Verdict.CLEAN and a.result.in_place
        await pilot.press("i")
        await pilot.pause(2.0)
        assert "nothing to" in panel_text(app) and "compare" in panel_text(app)
        await pilot.press("b")
        assert "Nothing to compare" in str(app.query_one("#activity", Static).render())


def test_package_has_no_js_tooling():
    root = Path(__file__).parent.parent
    for name in ("package.json", "node_modules", "package-lock.json"):
        assert not (root / name).exists()
    out = subprocess.run([sys.executable, "-m", "pip", "show", "exiftui"], capture_output=True,
                         text=True).stdout
    assert "Requires: textual" in out
