"""Classifier regressions that need no ExifTool. Tags below were reported on a real macOS
screenshot whose scrubbed copy was wrongly marked PARTIAL."""

from exiftui.core.classify import is_embedded_metadata
from exiftui.models import Tag


def test_png_colour_and_decode_hints_are_structural():
    for g1, name in [
        ("PNG", "ProfileName"), ("PNG", "AppleDataOffsets"),
        ("PNG-cICP", "ColorPrimaries"), ("PNG-cICP", "TransferCharacteristics"),
        ("PNG-cICP", "MatrixCoefficients"), ("PNG-cICP", "VideoFullRangeFlag"),
    ]:
        assert not is_embedded_metadata(Tag("PNG", g1, name, "x")), name


def test_png_real_metadata_is_still_flagged():
    for g0, g1, name in [
        ("PNG", "PNG", "Comment"), ("PNG", "PNG", "Software"), ("PNG", "PNG", "ModifyDate"),
        ("XMP", "XMP-x", "XMPToolkit"), ("EXIF", "ExifIFD", "UserComment"),
        ("EXIF", "IFD0", "Make"),
    ]:
        assert is_embedded_metadata(Tag(g0, g1, name, "x")), name


def test_exif_dimensions_are_structural():
    assert not is_embedded_metadata(Tag("EXIF", "ExifIFD", "ExifImageWidth", "3456"))
