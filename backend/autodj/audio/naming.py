"""Deriving a track's title and artist.

Embedded tags win when they exist. Filenames are treated as a source path first and a naming
hint second: real libraries contain names like ``Drake - Nice For What (Lyrics).mp3`` and
``Bad Bunny, Drake - MIA (Official Video).mp3``, so the fallback cleans obvious upload noise and
only splits an artist off when a spaced dash makes that unambiguous.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

MAX_FIELD_LENGTH = 500

_ARTIST_TAG_KEYS = ("artist", "album_artist", "albumartist", "performer", "author")
_TITLE_TAG_KEYS = ("title", "track")

# Values that carry no information, seen in the wild from taggers and download tools.
_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "-",
        "--",
        "?",
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "unknown artist",
        "unknown album",
        "untitled",
        "track",
        "audio track",
        "various",
        "various artists",
    }
)

# Bracketed segments matching these are upload noise, not part of the title. Anything else,
# including "(feat. X)", "(Radio Edit)" or "(Remastered 2011)", is kept.
_NOISE_SEGMENT = re.compile(
    r"""^(
        (official\s+)?((music|lyrics?)\s+)?(video|audio|visuali[sz]er)
        | lyrics?
        | with\s+lyrics
        | lyrics?\s+video
        | official
        | audio
        | video
        | hd | hq | uhd | \d{3,4}p | 4k
        | full\s+(song|album|version)
        | free\s+download
        | download
        | explicit
        | clean
        | cc
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

_BRACKETED = re.compile(r"[(\[{]([^()\[\]{}]*)[)\]}]")
_LEADING_TRACK_NUMBER = re.compile(r"^\s*\d{1,3}\s*[.)\-_]\s+")
_SPACED_DASH = re.compile(r"\s+[-\u2013\u2014]\s+")
_TRAILING_TOPIC = re.compile(r"\s*[-\u2013\u2014]\s*topic\s*$", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
# Trailing periods are left alone: they belong to names like "HUMBLE." and "Fred again..".
_EDGE_JUNK = re.compile(r"^[\s\-_.,;:|]+|[\s\-_,;:|]+$")


class MetadataSource(StrEnum):
    """Where a track's title and artist came from."""

    TAGS = "tags"
    FILENAME = "filename"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class TrackNaming:
    title: str
    artist: str | None
    source: MetadataSource


def _normalize_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value.replace("_", " ")).strip()


def _truncate(value: str) -> str:
    return value if len(value) <= MAX_FIELD_LENGTH else value[:MAX_FIELD_LENGTH].rstrip()


def _clean_tag_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _normalize_whitespace(value)
    if cleaned.lower() in _PLACEHOLDER_VALUES:
        return None
    return _truncate(cleaned)


def _first_tag(tags: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _clean_tag_value(tags.get(key))
        if value is not None:
            return value
    return None


def _strip_noise_segments(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = _normalize_whitespace(match.group(1))
        return "" if _NOISE_SEGMENT.match(inner) else match.group(0)

    return _BRACKETED.sub(replace, value)


def clean_filename_stem(stem: str) -> str:
    """Turn a filename stem into a human-readable string without guessing structure."""
    value = _normalize_whitespace(stem)
    value = _TRAILING_TOPIC.sub("", value)
    value = _strip_noise_segments(value)
    value = _LEADING_TRACK_NUMBER.sub("", value)
    value = _EDGE_JUNK.sub("", value)
    return _truncate(_normalize_whitespace(value))


def naming_from_filename(stem: str) -> TrackNaming:
    """Best-effort naming from a filename stem.

    An artist is only claimed when the cleaned stem contains a spaced dash with content on both
    sides, which covers ``Artist - Title`` and ``Artist A, Artist B - Title`` without imposing
    that shape on names that do not have it.
    """
    cleaned = clean_filename_stem(stem)
    if not cleaned:
        # Nothing survived cleaning (e.g. a stem of only punctuation): keep the raw stem so the
        # track is still identifiable in the library.
        return TrackNaming(
            title=_truncate(stem.strip()) or stem, artist=None, source=MetadataSource.FILENAME
        )

    parts = _SPACED_DASH.split(cleaned, maxsplit=1)
    if len(parts) == 2:
        artist_candidate = _EDGE_JUNK.sub("", parts[0]).strip()
        title_candidate = _EDGE_JUNK.sub("", parts[1]).strip()
        if artist_candidate and title_candidate:
            return TrackNaming(
                title=_truncate(title_candidate),
                artist=_truncate(artist_candidate),
                source=MetadataSource.FILENAME,
            )

    return TrackNaming(title=cleaned, artist=None, source=MetadataSource.FILENAME)


def resolve_naming(tags: Mapping[str, str], stem: str) -> TrackNaming:
    """Prefer embedded tags; fall back to the filename only for what the tags do not provide."""
    tag_title = _first_tag(tags, _TITLE_TAG_KEYS)
    tag_artist = _first_tag(tags, _ARTIST_TAG_KEYS)

    if tag_title is not None:
        return TrackNaming(title=tag_title, artist=tag_artist, source=MetadataSource.TAGS)

    derived = naming_from_filename(stem)
    if tag_artist is not None:
        return TrackNaming(title=derived.title, artist=tag_artist, source=MetadataSource.MIXED)
    return derived
