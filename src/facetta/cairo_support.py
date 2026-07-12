"""Load CairoSVG reliably from Homebrew-backed macOS Python runtimes.

Conda and other non-Homebrew Python builds do not always search Homebrew's
library directory, even when ``cairo`` itself is installed.  Keep that
platform concern in one place so drawing services do not each carry their own
loader workaround.
"""

from __future__ import annotations

import importlib
import os
import sys
from ctypes.util import find_library
from pathlib import Path
from types import ModuleType

MACOS_CAIRO_DIRS = (Path("/opt/homebrew/lib"), Path("/usr/local/lib"))


def _ensure_macos_cairo_search_path() -> None:
    if sys.platform != "darwin" or find_library("cairo") is not None:
        return

    existing = [
        value
        for value in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "").split(
            os.pathsep
        )
        if value
    ]
    discovered = [
        str(directory)
        for directory in MACOS_CAIRO_DIRS
        if (directory / "libcairo.2.dylib").is_file()
        and str(directory) not in existing
    ]
    if discovered:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = os.pathsep.join(
            [*discovered, *existing]
        )


def load_cairosvg() -> ModuleType:
    """Return CairoSVG after preparing the macOS dynamic-library search path."""

    _ensure_macos_cairo_search_path()
    return importlib.import_module("cairosvg")
