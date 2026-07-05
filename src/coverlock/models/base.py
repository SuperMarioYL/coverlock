"""The image-model boundary.

CoverLock's owned value is entirely offline (rules / compose / stylepack /
gallery). An image model is the *pluggable periphery*: it takes a fully-rendered
prompt and returns the raw bytes of a **text-free main visual**. It never sees the
platform rules, the safe-zone, or the title — those belong to ``compose.py``.

This module defines the narrow contract every model client honours:

* :class:`ImageRequest` — the immutable request (prompt + aspect + pinned params).
* :class:`ImageModel` — a runtime-checkable protocol: ``generate(req) -> bytes``.
* :class:`ModelError` — raised on any provider/transport failure.

Keeping the surface this small means a model API can be swapped, re-priced, or go
offline without touching a single line of the compliance core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

__all__ = ["ImageRequest", "ImageModel", "ModelError"]


class ModelError(RuntimeError):
    """Raised when an image model fails to produce a visual (transport, auth, quota…)."""


@dataclass(frozen=True)
class ImageRequest:
    """An immutable request for one text-free main visual.

    Attributes:
        prompt: the fully-composed prompt (scaffold + injected topic/title).
        width: target pixel width of the main visual.
        height: target pixel height of the main visual.
        seed: optional deterministic seed; a pinned seed keeps a pack reproducible.
        params: extra provider-specific knobs (guidance, model id, …).
    """

    prompt: str
    width: int
    height: int
    seed: int | None = None
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.prompt or not self.prompt.strip():
            raise ModelError("ImageRequest.prompt must be a non-empty string")
        if self.width <= 0 or self.height <= 0:
            raise ModelError(
                f"ImageRequest dimensions must be positive, got {self.width}x{self.height}"
            )


@runtime_checkable
class ImageModel(Protocol):
    """A pluggable image model: prompt -> text-free main-visual bytes.

    Implementations MUST:
      * return raw image bytes (PNG or JPEG) sized at least ``req.width`` x
        ``req.height`` (compose.py resizes/crops to the exact compliant size);
      * be deterministic for a fixed ``(prompt, seed)`` when the provider supports
        pinned seeds (so a locked style-pack reproduces);
      * raise :class:`ModelError` — never a bare provider exception — on failure.
    """

    #: Stable identifier used by the registry and style-packs (e.g. "doubao-seedream").
    name: str

    def generate(self, request: ImageRequest) -> bytes:
        """Produce raw image bytes for ``request`` or raise :class:`ModelError`."""
        ...
