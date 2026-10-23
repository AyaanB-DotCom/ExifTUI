"""Which formats ExifTUI will touch, and how."""

from __future__ import annotations

from dataclasses import dataclass

# Decided from ExifTool's content-based FileTypeExtension, not from the file name.
SUPPORTED_TYPES = {"jpg", "png", "webp", "heic", "heif", "tif"}

SCAN_EXTENSIONS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff",
}

UNSUPPORTED_EXTENSIONS = {
    ".gif": "GIF is not covered in this release",
    ".bmp": "BMP carries almost no metadata and is not covered",
    ".avif": "AVIF is not covered in this release",
    ".jp2": "JPEG 2000 is not covered in this release",
    ".psd": "PSD is a layered editing format; metadata removal could damage it",
    ".dng": "RAW format: removal may break raw processing, so it is not attempted",
    ".cr2": "RAW format: removal may break raw processing, so it is not attempted",
    ".cr3": "RAW format: removal may break raw processing, so it is not attempted",
    ".nef": "RAW format: removal may break raw processing, so it is not attempted",
    ".arw": "RAW format: removal may break raw processing, so it is not attempted",
    ".orf": "RAW format: removal may break raw processing, so it is not attempted",
    ".rw2": "RAW format: removal may break raw processing, so it is not attempted",
    ".raf": "RAW format: removal may break raw processing, so it is not attempted",
    ".pef": "RAW format: removal may break raw processing, so it is not attempted",
}

# Args appended after the common policy, per true file type.
# TIFF keeps IFD0 tags through "-all=" ("Can't delete IFD0 from TIFF"), so name them.
TIFF_EXTRA_DELETES = [
    "-Make=", "-Model=", "-Software=", "-Artist=", "-Copyright=", "-ImageDescription=",
    "-DateTime=", "-HostComputer=", "-DocumentName=", "-PageName=",
    "-XPAuthor=", "-XPComment=", "-XPKeywords=", "-XPSubject=", "-XPTitle=",
]
# ExifTool emits this minor warning for the above even though it did its job.
EXPECTED_WARNINGS = {"tif": "Can't delete IFD0 from TIFF"}


@dataclass(frozen=True)
class Policy:
    args: list[str]
    expected_warning: str | None = None


def policy_for(file_type_ext: str) -> Policy | None:
    """Scrub arguments for a content-detected type, or None if unsupported."""
    if file_type_ext not in SUPPORTED_TYPES:
        return None
    # Delete everything removable, then put back only what keeps the image usable:
    # the colour profile and the rotation flag. Pixel data is never re-encoded.
    extra = TIFF_EXTRA_DELETES if file_type_ext == "tif" else []
    args = ["-all=", *extra, "-tagsFromFile", "@", "-icc_profile", "-orientation"]
    return Policy(args, EXPECTED_WARNINGS.get(file_type_ext))
