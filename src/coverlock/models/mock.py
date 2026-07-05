"""Offline, deterministic image model — the zero-key demo backbone.

``MockModel`` is what makes ``pip install coverlock`` → ``coverlock gallery`` run
end to end with **no API key and no network**. It synthesises a text-free main
visual entirely with Pillow: a smooth diagonal gradient plus a single centred
subject shape, its colours derived deterministically from a hash of
``(prompt, seed)``. Same prompt + seed ⇒ byte-identical output, which is exactly
what a locked style-pack needs to prove consistency.

It is NOT a real generator — it just gives the compliance/compose/gallery layers
real bytes to work on so the whole pipeline is demonstrable offline.
"""

from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageChops, ImageDraw

from .base import ImageModel, ImageRequest, ModelError

__all__ = ["MockModel"]


def _digest(prompt: str, seed: int | None) -> bytes:
    h = hashlib.sha256()
    h.update(prompt.encode("utf-8"))
    h.update(b"\x00")
    h.update(str(seed if seed is not None else "unseeded").encode("utf-8"))
    return h.digest()


def _hues_from_digest(d: bytes) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Derive three muted RGB colours (background pair + subject) from the digest."""
    def chan(i: int, lo: int, hi: int) -> int:
        return lo + (d[i] % max(1, (hi - lo + 1)))

    # Two low-saturation background tones (Morandi-ish) + a warmer subject tone.
    bg_a = (chan(0, 205, 240), chan(1, 200, 235), chan(2, 190, 225))
    bg_b = (chan(3, 150, 190), chan(4, 150, 190), chan(5, 155, 195))
    subject = (chan(6, 120, 190), chan(7, 80, 140), chan(8, 60, 120))
    return bg_a, bg_b, subject


def _channel_ramp(size: int, lo: int, hi: int, *, horizontal: bool) -> Image.Image:
    """A single-channel linear ramp ``lo``→``hi`` across ``size`` px, tiled to 2-D.

    Built once per axis at native resolution using ``Image.linear_gradient``
    (C-implemented) so there is no Python per-pixel loop.
    """
    # linear_gradient("L") is a 256x256 ramp 0->255 top-to-bottom. Take one column,
    # remap 0..255 to lo..hi, resize to the axis length, then broadcast.
    base = Image.linear_gradient("L").resize((1, size))  # size x 1 column, 0->255
    if lo != 0 or hi != 255:
        span = hi - lo
        base = base.point(lambda v: lo + (v * span) // 255)
    if horizontal:
        base = base.transpose(Image.Transpose.ROTATE_90)  # now 1 x size row
        return base.resize((size, 1))
    return base


def _diagonal_gradient(
    w: int,
    h: int,
    a: tuple[int, int, int],
    b: tuple[int, int, int],
) -> Image.Image:
    """RGB diagonal gradient: top-left ≈ ``a``, bottom-right ≈ ``b``.

    Composed as the average of a horizontal ramp and a vertical ramp per channel.
    Fully vectorised (no Python per-pixel work) and deterministic.
    """
    channels = []
    for lo, hi in zip(a, b):
        horiz = _channel_ramp(w, lo, hi, horizontal=True).resize((w, h))
        vert = _channel_ramp(h, lo, hi, horizontal=False).resize((w, h))
        # Average the two ramps → a smooth diagonal ramp.
        channels.append(Image.blend(horiz, vert, 0.5))
    return Image.merge("RGB", channels)


class MockModel:
    """A deterministic, offline :class:`ImageModel` implementation."""

    name = "mock"

    def generate(self, request: ImageRequest) -> bytes:
        if not isinstance(request, ImageRequest):  # defensive: registry passes real requests
            raise ModelError("MockModel.generate expects an ImageRequest")

        w, h = request.width, request.height
        d = _digest(request.prompt, request.seed)
        bg_a, bg_b, subject = _hues_from_digest(d)

        # Diagonal gradient bg_a -> bg_b. Rendered vectorised: a per-channel
        # linear ramp (top-left = bg_a, bottom-right = bg_b) composed from a
        # horizontal and a vertical ramp, then averaged. Deterministic and fast
        # (no Python per-pixel loop — the old loop cost ~1s per 1080x1350 cover).
        img = _diagonal_gradient(w, h, bg_a, bg_b)

        # A single centred subject (a soft rounded square, radius from the digest)
        # so every mock cover reads as "one subject, centred, lots of whitespace".
        draw = ImageDraw.Draw(img)
        short = min(w, h)
        frac = 0.30 + (d[9] % 12) / 100.0  # 0.30 .. 0.41 of the short side
        size = int(short * frac)
        cx, cy = w // 2, int(h * 0.46)
        radius = int(size * (0.12 + (d[10] % 20) / 100.0))
        box = (cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2)
        draw.rounded_rectangle(box, radius=radius, fill=subject)

        # A faint accent ring to give the composition a second focal element.
        ring_r = int(size * 0.72)
        ring = (
            min(255, subject[0] + 30),
            min(255, subject[1] + 30),
            min(255, subject[2] + 30),
        )
        draw.ellipse(
            (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
            outline=ring,
            width=max(2, short // 240),
        )

        # A subtle vignette so the corners stay quiet (helps the title read later).
        img = self._apply_vignette(img, d)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _apply_vignette(img: Image.Image, d: bytes) -> Image.Image:
        """Darken the corners with a radial vignette. Returns the vignetted image.

        Vectorised via a precomputed radial mask multiplied into the image — the
        old version looped in pure Python over every pixel (~1s per 1080x1350
        cover) which dominated the whole test suite's runtime.
        """
        w, h = img.size
        strength = 0.12 + (d[11] % 8) / 100.0

        # radial_gradient("L"): 0 (white) at centre → 255 (black) at the edge on a
        # 256x256 canvas. Resize to the cover, scale by `strength`, invert, and use
        # it as a per-pixel multiplier so the centre stays bright and corners dim.
        radial = Image.radial_gradient("L").resize((w, h))
        # darken factor per pixel = 255 - strength * radial  (centre≈255, edge dimmer)
        darken = radial.point(lambda v: 255 - int(strength * v))
        mult = Image.merge("RGB", (darken, darken, darken))
        return ImageChops.multiply(img, mult)


# Static type-check aid: assert MockModel satisfies the protocol at import time in
# tests, not here (avoids import-time overhead). See tests/test_compose.py.
_MODEL_CHECK: ImageModel = MockModel()  # noqa: F841  (instance is cheap, catches drift early)
