"""Decide what a tag *is* and whether it counts as removable embedded metadata.

The rule of thumb: whole metadata containers (EXIF, XMP, IPTC, MakerNotes, ...) count, minus a
small allowlist of structural tags. Mixed containers (PNG, RIFF/WebP, QuickTime/HEIC) are
structural by default and only count when the tag is a recognisable identifier or timestamp.
"""

from __future__ import annotations

import re

from exiftui.models import Category, Tag


def _names(text: str) -> frozenset[str]:
    return frozenset(text.split())


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


_THUMB = _rx(r"^(thumbnail|preview|jpgfrom|otherimage|mpimage|mpf|mpentry)")
_PLACE = _rx(
    r"^(city|state|country|location|sublocation|sub-location|province-state|"
    r"country-primarylocation|primarylocation|worldregion|geotag|areainformation)"
)
_GPS_PRIVATE = _rx(
    r"(latitude|longitude|position|altitude|destlat|destlong|imgdirection|areainformation|"
    r"processingmethod|speed|track|dest)"
)
_DEVICE = _rx(
    r"(serial|^make$|^model$|lens|cameramodel|cameramake|deviceman|devicemodel|^owner|"
    r"hostcomputer|uniquecamera|cameraid|firmware|imageuniqueid|^machine|cameralabel)"
)
_SERIAL = _rx(r"(serial|imageuniqueid|^owner|cameraid)")
_SOFTWARE = _rx(
    r"(^software|creatortool|^history|derivedfrom|documentid|instanceid|originaldocumentid|"
    r"preservedfilename|processingsoftware|toolkit|^application|pantry|^versions|ingredients)"
)
_AUTHOR = _rx(
    r"(^artist|author|creator|copyright|rights|by-?line|^credit|^source$|photographer|"
    r"^contact|^writer|usageterms|^rightsowner|^licen)"
)
_TIME = _rx(
    r"(date|timecreated|creationtime|^subsec|offsettime|timezone|timestamp|^modifytime)"
)
_TEXT = _rx(
    r"(comment|description|caption|^title|keywords|^subject|^headline|^label|^rating|"
    r"instructions|^notes?$|abstract|^category|supplementalcategories|^special|^xp)"
)

PNG_STRUCT = _names(
    "ImageWidth ImageHeight BitDepth ColorType Compression Filter Interlace Gamma "
    "SRGBRendering WhitePoint PrimaryChromaticities PixelsPerUnitX PixelsPerUnitY "
    "PixelUnits Palette Transparency BackgroundColor SignificantBits AnimationFrames "
    "AnimationPlays ImageGamma "
    # colour signalling (iCCP name, cICP chunk) and Apple's iDOT parallel-decode hint:
    # all describe how to decode or display the pixels, not who or where.
    "ProfileName ColorPrimaries TransferCharacteristics MatrixCoefficients "
    "VideoFullRangeFlag AppleDataOffsets"
)
RIFF_STRUCT = _names(
    "ImageWidth ImageHeight VP8Version HorizontalScale VerticalScale WebP_Flags Duration "
    "FrameCount AnimationLoopCount BackgroundColor AnimationFrames AnimationPlays "
    "Encoding"
)
EXIF_STRUCT = _names(
    "Orientation YCbCrPositioning ImageWidth ImageHeight BitsPerSample Compression "
    "PhotometricInterpretation StripOffsets SamplesPerPixel RowsPerStrip StripByteCounts "
    "PlanarConfiguration XResolution YResolution ResolutionUnit TileWidth TileLength "
    "TileOffsets TileByteCounts Predictor ExtraSamples SampleFormat FillOrder ColorMap "
    "JPEGTables NewSubfileType SubfileType YCbCrCoefficients YCbCrSubSampling "
    "ReferenceBlackWhite InkSet NumberOfInks ExifImageWidth ExifImageHeight"
)
# JPEG COM segments and the stored IPTC digest are reported by ExifTool in the "File" group.
FILE_GROUP_METADATA = frozenset({"Comment", "CurrentIPTCDigest"})
ALWAYS_STRUCTURAL_GROUPS = frozenset({"ExifTool", "System", "Composite", "JFIF", "Adobe"})


def categorize(tag: Tag) -> Category:
    """Human-oriented category, used for display and for the verification report."""
    n = tag.name
    if tag.group1 == "System":
        return Category.FILESYSTEM
    if tag.group1.startswith("ICC") or n.lower() in {"icc_profile", "profiledescription"}:
        return Category.COLOR
    if _THUMB.search(n):
        return Category.THUMB
    if tag.group1 == "GPS" or n.startswith("GPS") or _PLACE.search(n):
        return Category.GPS
    if tag.group0 == "Photoshop" or _SOFTWARE.search(n):
        return Category.SOFTWARE
    if _DEVICE.search(n):
        return Category.DEVICE
    if _AUTHOR.search(n):
        return Category.AUTHOR
    if _TIME.search(n):
        return Category.TIME
    if _TEXT.search(n):
        return Category.TEXT
    if is_structural(tag) or tag.group0 in ALWAYS_STRUCTURAL_GROUPS:
        return Category.STRUCT
    return Category.OTHER


def privacy_flag(tag: Tag) -> str | None:
    """A narrow indicator for tags that identify a place or a specific device."""
    cat = categorize(tag)
    if cat is Category.GPS and (_GPS_PRIVATE.search(tag.name) or not tag.name.startswith("GPS")):
        return "LOCATION"
    if cat is Category.DEVICE and _SERIAL.search(tag.name):
        return "SERIAL"
    return None


def is_structural(tag: Tag) -> bool:
    """True for tags describing the image itself rather than who/where/when/with-what."""
    g0, n = tag.group0, tag.name
    if g0 in ALWAYS_STRUCTURAL_GROUPS or tag.group1 == "System":
        return True
    if g0 == "File":
        return n not in FILE_GROUP_METADATA
    if g0 == "PNG":
        return n in PNG_STRUCT
    if g0 == "RIFF":
        return n in RIFF_STRUCT
    if g0.startswith("ICC") or tag.group1.startswith("ICC"):
        return True  # colour data; ExifTUI keeps it deliberately
    if g0 == "EXIF":
        return n in EXIF_STRUCT
    return False


def is_embedded_metadata(tag: Tag) -> bool:
    """Does this tag count against a CLEAN verdict?"""
    if is_structural(tag):
        return False
    if tag.group0 in {"QuickTime", "Meta", "Track1"}:
        # ponytail: HEIC/MOV container tags are mostly structural; only identifiers and times
        # are flagged. Unknown QuickTime tags are not counted. Upgrade: an explicit allowlist.
        return categorize(tag) not in {Category.STRUCT, Category.OTHER, Category.COLOR}
    return True
