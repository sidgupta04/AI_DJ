"""AutoDJ: automated music mixing engine."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("autodj")
except PackageNotFoundError:  # pragma: no cover - source tree without an install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
