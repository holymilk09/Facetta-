"""Provider-neutral exceptions shared by legacy and canonical image paths."""

from __future__ import annotations


class RenderUnavailable(Exception):
    """A required image or vision provider is unavailable."""
