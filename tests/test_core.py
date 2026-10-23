from __future__ import annotations

import hashlib
import os
import stat
import threading
import time
from pathlib import Path

import pytest
from conftest import KNOWN_META, make_image, needs_exiftool, write_meta
from PIL import Image

from exiftui.core import exiftool
from exiftui.core.batch import run_batch
from exiftui.core.classify import categorize, is_embedded_metadata, privacy_flag
from exiftui.core.sanitizer import Options, sanitize
from exiftui.core.scanner import OUTPUT_DIR_NAME, scan_file, scan_folder
from exiftui.core.verifier import verify_file
from exiftui.models import Artifact, Category, Tag, Verdict

pytestmark = needs_exiftool


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pixels(p: Path) -> bytes:
    with Image.open(p) as im:
        return im.convert("RGB").tobytes()


def art(p: Path, root: Path | None = None) -> Artifact:
    return Artifact(p, root, p.stat().st_size)


# --- reading ---------------------------------------------------------------------------------

def test_inspect_reads_known_metadata(jpg):
    tags = exiftool.inspect(jpg)
    by = {t.name: t for t in tags}
    assert by["Make"].value == "Canon"
    assert by["SerialNumber"].value == "12345" or by["SerialNumber"].value == "SN12345"
    assert any(t.name == "GPSLatitude" for t in tags)
    assert any(t.group0 == "XMP" and t.name == "Creator" for t in tags)


def test_inspect_is_read_only(jpg):
    before = sha(jpg)
    exiftool.inspect(jpg)
    assert sha(jpg) == before
    assert [p.name for p in jpg.parent.iterdir()] == ["photo.jpg"]


def test_duplicate_tags_from_different_groups_are_kept(jpg):
    write_meta(jpg, "-XMP-exif:GPSLatitude=48.85", "-XMP-exif:GPSLongitude=2.35")
    names = [t.qualified for t in exiftool.inspect(jpg) if t.name == "GPSLatitude"]
    assert len(set(names)) >= 2  # EXIF:GPS and XMP-exif, plus Composite


def test_privacy_flags_are_narrow():
    lat = Tag("EXIF", "GPS", "GPSLatitude", "1")
    ver = Tag("EXIF", "GPS", "GPSVersionID", "2.3.0.0")
    ser = Tag("EXIF", "ExifIFD", "SerialNumber", "x")
    exp = Tag("EXIF", "ExifIFD", "ExposureTime", "1/100")
    assert privacy_flag(lat) == "LOCATION"
    assert privacy_flag(ver) is None
    assert privacy_flag(ser) == "SERIAL"
    assert privacy_flag(exp) is None and categorize(exp) is not Category.TIME


# --- scrubbing -------------------------------------------------------------------------------

def test_scrub_each_format_is_clean_and_preserves_original(any_image):
    original = sha(any_image)
    px = pixels(any_image)
    r = sanitize(art(any_image))
    assert r.verdict is Verdict.CLEAN, r.remaining
    assert sha(any_image) == original
    assert r.output == any_image.with_name(f"{any_image.stem}-clean{any_image.suffix}")
    assert pixels(r.output) == px  # not re-encoded
    assert r.before_count and r.before_count >= 8


def test_scrub_removes_specific_categories(jpg):
    out = sanitize(art(jpg)).output
    names = {t.name for t in exiftool.inspect(out)}
    for gone in ("GPSLatitude", "Make", "Model", "SerialNumber", "Artist", "Software",
                 "DateTimeOriginal", "Creator", "Description", "Comment"):
        assert gone not in names


def test_orientation_is_kept(jpg):
    out = sanitize(art(jpg)).output
    assert any(t.name == "Orientation" for t in exiftool.inspect(out))


def test_heic(heic):
    original = sha(heic)
    r = sanitize(art(heic))
    assert r.verdict is Verdict.CLEAN, (r.remaining, r.error)
    assert sha(heic) == original
    names = {t.name for t in exiftool.inspect(r.output)}
    assert "Make" not in names and "GPSLatitude" not in names


def test_xmp_only_metadata_removed(tmp_path):
    p = make_image(tmp_path / "x.jpg", meta=False)
    write_meta(p, "-XMP-dc:Creator=Someone", "-XMP-dc:Rights=Mine")
    assert verify_file(p).verdict is Verdict.PARTIAL
    assert sanitize(art(p)).verdict is Verdict.CLEAN


def test_no_temp_or_backup_files_left(jpg):
    sanitize(art(jpg))
    assert sorted(p.name for p in jpg.parent.iterdir()) == ["photo-clean.jpg", "photo.jpg"]


def test_collision_never_overwrites(jpg):
    first = sanitize(art(jpg)).output
    first_hash = sha(first)
    second = sanitize(art(jpg)).output
    third = sanitize(art(jpg)).output
    assert {first.name, second.name, third.name} == {
        "photo-clean.jpg", "photo-clean-2.jpg", "photo-clean-3.jpg"}
    assert sha(first) == first_hash


def test_pre_existing_output_is_not_clobbered(jpg):
    victim = jpg.with_name("photo-clean.jpg")
    victim.write_bytes(b"precious")
    out = sanitize(art(jpg)).output
    assert victim.read_bytes() == b"precious" and out.name == "photo-clean-2.jpg"


@pytest.mark.parametrize("name", ["my photo (1).jpg", "-leading-hyphen.jpg", "日本語 фото.jpg",
                                  "semi;colon&amp$(echo).jpg", "pipe|.jpg"])
def test_awkward_file_names(tmp_path, name):
    p = make_image(tmp_path / name)
    r = sanitize(art(p))
    assert r.verdict is Verdict.CLEAN and r.output.exists()
    assert r.output.name == p.stem + "-clean.jpg"


def test_in_place_replaces_only_after_confirmation_option(jpg):
    r = sanitize(art(jpg), Options(in_place=True))
    assert r.verdict is Verdict.CLEAN and r.in_place and r.output == jpg
    assert verify_file(jpg).verdict is Verdict.CLEAN
    assert [p.name for p in jpg.parent.iterdir()] == ["photo.jpg"]  # no _original backups


# --- verification ----------------------------------------------------------------------------

def test_verify_flags_unscrubbed_file_with_categories(jpg):
    r = verify_file(jpg)
    assert r.verdict is Verdict.PARTIAL
    assert {"Location", "Device & serials", "Author & rights"} <= set(r.remaining)
    assert r.reasons


def test_verify_does_not_trust_a_scrub(jpg):
    out = sanitize(art(jpg)).output
    assert verify_file(out).verdict is Verdict.CLEAN
    write_meta(out, "-Artist=Leaked")  # metadata re-added after the "successful" scrub
    r = verify_file(out)
    assert r.verdict is Verdict.PARTIAL and "Author & rights" in r.remaining


def test_verify_reports_no_values(jpg):
    r = verify_file(jpg)
    blob = repr(r)
    for secret in ("Jane Doe", "EditorX", "SN12345", "48.85", "private description"):
        assert secret not in blob


def test_structural_tags_do_not_cause_partial(any_image):
    out = sanitize(art(any_image)).output
    tags = exiftool.inspect(out)
    assert tags and not [t for t in tags if is_embedded_metadata(t)]


# --- bad inputs ------------------------------------------------------------------------------

def test_corrupt_files_fail_without_output(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(os.urandom(2048))
    r = sanitize(art(bad))
    assert r.verdict in (Verdict.FAILED, Verdict.UNSUPPORTED) and r.output is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bad.jpg"]


def test_truncated_jpeg_fails(tmp_path, jpg):
    big = make_image(tmp_path / "big.jpg", size=(400, 400))
    data = big.read_bytes()
    big.write_bytes(data[: len(data) // 2])
    r = sanitize(art(big))
    assert r.verdict is Verdict.FAILED
    assert not (tmp_path / "big-clean.jpg").exists()


def test_wrong_extension_uses_real_type(tmp_path):
    p = tmp_path / "actually-gif.jpg"
    Image.new("RGB", (8, 8)).save(p, format="GIF")
    assert sanitize(art(p)).verdict is Verdict.UNSUPPORTED


def test_known_unsupported_extension_is_flagged_by_scanner(tmp_path):
    raw = tmp_path / "shot.cr2"
    raw.write_bytes(b"x")
    a = scan_file(raw)
    assert a and a.unsupported_reason
    assert sanitize(a).verdict is Verdict.UNSUPPORTED
    assert sorted(p.name for p in tmp_path.iterdir()) == ["shot.cr2"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_unwritable_destination_fails_cleanly(tmp_path):
    d = tmp_path / "ro"
    p = make_image(d / "a.jpg")
    d.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        r = sanitize(art(p))
    finally:
        d.chmod(stat.S_IRWXU)
    assert r.verdict is Verdict.FAILED and r.output is None
    assert [x.name for x in d.iterdir()] == ["a.jpg"]


# --- ExifTool availability / process control -------------------------------------------------

def test_missing_exiftool(monkeypatch):
    monkeypatch.setenv("EXIFTUI_EXIFTOOL", "/nonexistent/exiftool")
    with pytest.raises(exiftool.ExifToolMissing):
        exiftool.check()
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("EXIFTUI_EXIFTOOL")
    with pytest.raises(exiftool.ExifToolMissing):
        exiftool.check()


def test_run_is_cancellable_and_kills_process(tmp_path, monkeypatch):
    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nsleep 30\n")
    slow.chmod(0o755)
    monkeypatch.setenv("EXIFTUI_EXIFTOOL", str(slow))
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(exiftool.Cancelled):
        exiftool.run(["-ver"], cancel=cancel)
    assert time.monotonic() - t0 < 5


def test_run_times_out(tmp_path, monkeypatch):
    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nsleep 30\n")
    slow.chmod(0o755)
    monkeypatch.setenv("EXIFTUI_EXIFTOOL", str(slow))
    with pytest.raises(exiftool.ExifToolError, match="timed out"):
        exiftool.run(["-ver"], timeout=0.5)


# --- scanning and batches --------------------------------------------------------------------

def build_tree(root: Path) -> None:
    make_image(root / "a.jpg")
    make_image(root / "sub dir" / "b.png")
    make_image(root / "sub dir" / "deeper" / "ü.webp")
    (root / "notes.txt").write_text("hi")
    (root / "raw.nef").write_bytes(b"x")


def test_scan_recursive_vs_flat(tmp_path):
    build_tree(tmp_path)
    flat = scan_folder(tmp_path, recursive=False)
    deep = scan_folder(tmp_path, recursive=True)
    assert [a.display for a in flat.artifacts if not a.unsupported_reason] == ["a.jpg"]
    assert len([a for a in deep.artifacts if not a.unsupported_reason]) == 3
    assert [a for a in deep.artifacts if a.unsupported_reason][0].path.name == "raw.nef"
    assert deep.ignored_other == 1


def test_scan_skips_symlinks_and_output_dirs(tmp_path):
    outside = tmp_path / "outside"
    make_image(outside / "secret.jpg")
    root = tmp_path / "root"
    make_image(root / "a.jpg")
    (root / "link.jpg").symlink_to(outside / "secret.jpg")
    (root / "linkdir").symlink_to(outside, target_is_directory=True)
    make_image(root / OUTPUT_DIR_NAME / "old.jpg")
    make_image(root / "a-clean.jpg")
    res = scan_folder(root)
    assert [a.display for a in res.artifacts] == ["a.jpg"]
    assert res.skipped_symlinks == 2 and res.skipped_previous_output == 1


def test_scan_refuses_output_folder(tmp_path):
    out = tmp_path / OUTPUT_DIR_NAME
    make_image(out / "a.jpg")
    res = scan_folder(out)
    assert not res.artifacts and res.errors


def test_batch_folder_preserves_structure_and_originals(tmp_path):
    build_tree(tmp_path)
    arts = scan_folder(tmp_path).artifacts
    before = {a.path: sha(a.path) for a in arts}
    results: dict[str, object] = {}
    run_batch(arts, Options(), threading.Event(),
              on_result=lambda a, r: results.__setitem__(a.display, r))
    clean = tmp_path / OUTPUT_DIR_NAME
    assert (clean / "a.jpg").is_file()
    assert (clean / "sub dir" / "b.png").is_file()
    assert (clean / "sub dir" / "deeper" / "ü.webp").is_file()
    assert results["raw.nef"].verdict is Verdict.UNSUPPORTED
    assert all(results[k].verdict is Verdict.CLEAN for k in results if k != "raw.nef")
    assert {a.path: sha(a.path) for a in arts} == before
    assert not list(tmp_path.rglob(".exiftui-*"))
    # A second run must not re-process the output folder, and must not overwrite it.
    again = scan_folder(tmp_path).artifacts
    assert all(OUTPUT_DIR_NAME not in a.path.parts for a in again)
    run_batch(again, Options(), threading.Event())
    assert (clean / "a-2.jpg").is_file() and (clean / "a.jpg").is_file()


def test_batch_cancel_before_start_does_nothing(tmp_path):
    build_tree(tmp_path)
    arts = scan_folder(tmp_path).artifacts
    cancel = threading.Event()
    cancel.set()
    seen = []
    run_batch(arts, Options(), cancel, on_result=lambda a, r: seen.append(r))
    assert seen and all(r is None for r in seen)
    assert not (tmp_path / OUTPUT_DIR_NAME).exists()


def test_batch_cancel_midway_leaves_no_partials(tmp_path):
    for i in range(8):
        make_image(tmp_path / f"{i}.jpg")
    arts = scan_folder(tmp_path).artifacts
    cancel = threading.Event()
    results: list = []

    def on_result(a, r):
        results.append(r)
        cancel.set()

    run_batch(arts, Options(), cancel, on_result=on_result, workers=1)
    done = [r for r in results if r is not None]
    assert 1 <= len(done) < 8
    outs = list((tmp_path / OUTPUT_DIR_NAME).glob("*.jpg"))
    assert len(outs) == len(done)
    assert not list(tmp_path.rglob(".exiftui-*"))
    assert all(verify_file(o).verdict is Verdict.CLEAN for o in outs)


def test_cancel_during_exiftool_cleans_temp(tmp_path, monkeypatch):
    p = make_image(tmp_path / "a.jpg")
    real = exiftool.find_exiftool()
    wrapper = tmp_path / "wrap"
    # Passes -json calls straight through, stalls on the write call.
    script = f'#!/bin/sh\ncase "$*" in *-all=*) sleep 30;; *) exec "{real}" "$@";; esac\n'
    wrapper.write_text(script)
    wrapper.chmod(0o755)
    monkeypatch.setenv("EXIFTUI_EXIFTOOL", str(wrapper))
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    with pytest.raises(exiftool.Cancelled):
        sanitize(art(p), cancel=cancel)
    assert [x.name for x in tmp_path.iterdir() if x.name != "wrap"] == ["a.jpg"]


def test_known_meta_list_is_sane():
    assert len(KNOWN_META) > 5
