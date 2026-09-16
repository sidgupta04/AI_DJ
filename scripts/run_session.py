"""Pre-render a complete DJ set from an already-analyzed seed track."""

import argparse
import json

from autodj.config.settings import load_settings
from autodj.services.sessions import open_session_service


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-id", type=int, required=True)
    parser.add_argument("--length", type=int)
    args = parser.parse_args()
    service, engine = open_session_service(load_settings())
    try:
        result = service.create(args.track_id, args.length)
        print(json.dumps(result, indent=2))
        if result["audio_url"]:
            print(f"WAV: {service.audio_path(result['id'])}")
        return 1 if result["status"] == "FAILED" else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
