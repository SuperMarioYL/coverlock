"""CoverLock — account-level cover style-pack tooling for Xiaohongshu.

CoverLock turns "an account's visual language" into a lockable, reusable
``style-pack`` asset. Once a pack is hash-locked, ``gen`` / ``regen`` reuse the
same model + prompt scaffold + palette + layout so every cover across posts
converges to the same look — always size-compliant (4:5 / 3:4) and with the
title always placed inside the platform safe-zone.

This package is the offline core (rules / compose / stylepack / gallery) plus a
pluggable image-model registry. The offline value does not depend on any single
model provider; models only produce the text-free main visual.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.3.0"
