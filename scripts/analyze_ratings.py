#!/usr/bin/env python3
"""Validate blind ratings and report pair-level preference/sign-test statistics."""

import argparse
import json
from pathlib import Path

from autodj.config.settings import load_settings
from autodj.services.evaluation_tools import analyze_ratings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ratings", type=Path, required=True)
    parser.add_argument("--codebook", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_ratings(
        args.ratings,
        args.codebook,
        minimum_listeners=load_settings().evaluation.minimum_listeners,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
