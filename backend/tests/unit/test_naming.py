"""Filename and tag resolution.

Cases mirror what a real download-built library looks like: upload noise in brackets, multiple
artists separated by commas, apostrophes, no separator at all, and names long enough to worry
about.
"""

from __future__ import annotations

import pytest

from autodj.audio.naming import (
    MAX_FIELD_LENGTH,
    MetadataSource,
    clean_filename_stem,
    naming_from_filename,
    resolve_naming,
)


@pytest.mark.parametrize(
    ("stem", "expected_artist", "expected_title"),
    [
        ("Drake - Nice For What (Lyrics)", "Drake", "Nice For What"),
        ("Bad Bunny, Drake - MIA (Official Video)", "Bad Bunny, Drake", "MIA"),
        ("Kendrick Lamar - HUMBLE. [Official Audio]", "Kendrick Lamar", "HUMBLE."),
        ("Rihanna - Don't Stop The Music (Lyric Video)", "Rihanna", "Don't Stop The Music"),
        ("Fisher - Losing It (Extended Mix)", "Fisher", "Losing It (Extended Mix)"),
        ("Duke Dumont - Ocean Drive (feat. Nobody)", "Duke Dumont", "Ocean Drive (feat. Nobody)"),
        ("ODESZA – Say My Name", "ODESZA", "Say My Name"),
        ("Disclosure — Latch", "Disclosure", "Latch"),
        ("03 - Fred again.. - Delilah", "Fred again..", "Delilah"),
        ("07. Peggy Gou - It Makes You Forget", "Peggy Gou", "It Makes You Forget"),
        ("Bicep_-_Glue", "Bicep", "Glue"),
        ("Jamie xx - Gosh (HQ) [1080p]", "Jamie xx", "Gosh"),
    ],
)
def test_artist_and_title_from_messy_filenames(
    stem: str, expected_artist: str, expected_title: str
) -> None:
    naming = naming_from_filename(stem)

    assert naming.artist == expected_artist
    assert naming.title == expected_title
    assert naming.source is MetadataSource.FILENAME


@pytest.mark.parametrize(
    "stem",
    [
        "some_random_track_name",
        "Untitled Session 4",
        "mix2019final",
        "track-without-spaced-dash",
        "Someone feat. Another - -",
    ],
)
def test_no_artist_is_invented_without_a_clear_separator(stem: str) -> None:
    naming = naming_from_filename(stem)

    assert naming.artist is None
    assert naming.title


def test_punctuation_and_unicode_survive() -> None:
    naming = naming_from_filename("Sigur Rós - Hoppípolla (Official Audio)")

    assert naming.artist == "Sigur Rós"
    assert naming.title == "Hoppípolla"


def test_commas_parentheses_and_apostrophes_are_kept_when_meaningful() -> None:
    naming = naming_from_filename("Tiësto, Ava Max - The Motto (Don't Stop) [Official Video]")

    assert naming.artist == "Tiësto, Ava Max"
    assert naming.title == "The Motto (Don't Stop)"


def test_long_names_are_truncated_not_rejected() -> None:
    stem = "Artist Name - " + "Extremely Long Title " * 40

    naming = naming_from_filename(stem)

    assert naming.artist == "Artist Name"
    assert len(naming.title) <= MAX_FIELD_LENGTH
    assert naming.title.startswith("Extremely Long Title")


def test_stem_of_only_punctuation_still_yields_a_title() -> None:
    naming = naming_from_filename("---")

    assert naming.title == "---"
    assert naming.artist is None


def test_noise_only_brackets_are_removed_but_real_ones_stay() -> None:
    assert clean_filename_stem("Track (Official Video)") == "Track"
    assert clean_filename_stem("Track [Lyrics]") == "Track"
    assert clean_filename_stem("Track (Radio Edit)") == "Track (Radio Edit)"
    assert clean_filename_stem("Track (Remastered 2011)") == "Track (Remastered 2011)"


def test_youtube_topic_channels_are_cleaned() -> None:
    naming = naming_from_filename("Aphex Twin - Windowlicker - Topic")

    assert naming.artist == "Aphex Twin"
    assert naming.title == "Windowlicker"


def test_tags_win_over_the_filename() -> None:
    naming = resolve_naming(
        {"title": "Nice For What", "artist": "Drake"},
        "Drake - Nice For What (Lyrics) 320kbps AUDIO",
    )

    assert naming.title == "Nice For What"
    assert naming.artist == "Drake"
    assert naming.source is MetadataSource.TAGS


def test_tag_artist_combines_with_filename_title() -> None:
    naming = resolve_naming({"artist": "Peggy Gou"}, "It Makes You Forget (Official Audio)")

    assert naming.artist == "Peggy Gou"
    assert naming.title == "It Makes You Forget"
    assert naming.source is MetadataSource.MIXED


def test_placeholder_tags_are_ignored() -> None:
    naming = resolve_naming(
        {"title": "  ", "artist": "Unknown Artist"}, "Bicep - Glue (Official Video)"
    )

    assert naming.artist == "Bicep"
    assert naming.title == "Glue"
    assert naming.source is MetadataSource.FILENAME


def test_alternative_tag_keys_are_honoured() -> None:
    naming = resolve_naming({"title": "Latch", "album_artist": "Disclosure"}, "whatever")

    assert naming.artist == "Disclosure"
    assert naming.title == "Latch"


def test_tag_values_are_truncated() -> None:
    naming = resolve_naming({"title": "x" * (MAX_FIELD_LENGTH + 50)}, "stem")

    assert len(naming.title) == MAX_FIELD_LENGTH
