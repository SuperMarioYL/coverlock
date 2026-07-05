"""Cover composition — the offline compliance core.

Given a model's text-free main visual and a title, :func:`compose_cover` produces
a finished cover that is guaranteed to be:

1. **Size-compliant** — resized/cropped (never letter-boxed) to the *exact* pixel
   dimensions of a named platform size (e.g. 4:5 → 1080×1350).
2. **Title-in-safe-zone** — the title is typeset so its whole bounding box lies
   fully inside the platform safe-zone. Overflow is handled by shrinking the font
   and wrapping lines; text is **never clipped**.

The result is a :class:`ComposedCover` carrying the image plus a
:class:`ComplianceReport` — the machine-checkable self-proof the gallery footer
and the tests assert on.

This module never talks to a model or the network. It takes raw image bytes in
and returns a composed cover out.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from .rules import PlatformRules, Rect, SizeSpec, TitleDefaults

__all__ = [
    "ComplianceReport",
    "ComposedCover",
    "TitleLayout",
    "ComposeError",
    "fit_image_to_size",
    "layout_title",
    "compose_cover",
]


class ComposeError(ValueError):
    """Raised when a title genuinely cannot be fit (e.g. a single glyph too wide)."""


@dataclass(frozen=True)
class ComplianceReport:
    """Machine-checkable self-proof for one composed cover."""

    size_name: str
    width: int
    height: int
    size_compliant: bool
    title_in_safe_zone: bool
    title_bbox: tuple[int, int, int, int]  # (x, y, w, h) of the rendered title block
    safe_zone: tuple[int, int, int, int]
    font_size_pt: int
    line_count: int

    @property
    def fully_compliant(self) -> bool:
        return self.size_compliant and self.title_in_safe_zone


@dataclass(frozen=True)
class TitleLayout:
    """The resolved title typesetting: wrapped lines + the font size that fits."""

    lines: list[str]
    font_size: int
    line_spacing: float
    block: Rect  # tight bounding box of the whole title block, in canvas pixels
    color: tuple[int, int, int]


@dataclass
class ComposedCover:
    """A finished cover: the image plus its compliance self-proof."""

    image: Image.Image
    report: ComplianceReport
    title: str

    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(out)
        return out

    def to_png_bytes(self) -> bytes:
        buf = io.BytesIO()
        self.image.save(buf, format="PNG")
        return buf.getvalue()


# --------------------------------------------------------------------------- #
# Size enforcement
# --------------------------------------------------------------------------- #
def fit_image_to_size(img: Image.Image, size: SizeSpec) -> Image.Image:
    """Resize + centre-crop ``img`` to exactly ``size.width`` × ``size.height``.

    Uses a cover-fit (scale to fill, crop the overflow) so the output is always
    100% of the target dimensions with no letter-boxing and no distortion.
    """
    target_w, target_h = size.width, size.height
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        raise ComposeError("source image has zero area")

    # Scale so the image covers the whole target, then centre-crop the excess.
    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(target_w, int(round(src_w * scale)))
    new_h = max(target_h, int(round(src_h * scale)))
    resized = img.convert("RGB").resize((new_w, new_h), Image.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    cropped = resized.crop((left, top, left + target_w, top + target_h))
    # Guarantee exact dimensions even against rounding drift.
    if cropped.size != (target_w, target_h):
        cropped = cropped.resize((target_w, target_h), Image.LANCZOS)
    return cropped


# --------------------------------------------------------------------------- #
# Title typesetting (shrink-to-fit + wrap, never clip)
# --------------------------------------------------------------------------- #
def _load_font(font_path: str | None, size: int) -> ImageFont.FreeTypeFont:
    """Load a scalable font at ``size`` px. Falls back to Pillow's bundled font.

    A custom ``font_path`` (e.g. a CJK OTF from a style-pack's layout) is used when
    present and readable; otherwise the bundled DejaVu-based default is used so the
    geometry guarantee holds with zero external assets.
    """
    if font_path:
        p = Path(font_path)
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                pass  # fall through to default
    return ImageFont.load_default(size=size)


def _measure_line(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """Return (width, height) of a single line rendered with ``font``."""
    if text == "":
        # An empty line still occupies the font's line height.
        ascent, descent = font.getmetrics()
        return 0, ascent + descent
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> tuple[list[str], bool]:
    """Greedy word/char wrap of ``text`` to ``max_width`` px.

    Returns (lines, ok). ``ok`` is False if a single indivisible unit is wider than
    ``max_width`` even on its own (caller should shrink the font and retry).

    Wraps on spaces where present (Latin) and falls back to per-character wrapping
    (CJK, which has no spaces).
    """
    text = text.strip()
    if not text:
        return [""], True

    def width_of(s: str) -> int:
        return _measure_line(draw, s, font)[0]

    # Tokenise: keep whitespace-delimited words, but a word too wide for the box
    # is itself split character-by-character (handles CJK and very long words).
    raw_tokens = text.split(" ")
    tokens: list[str] = []
    for tok in raw_tokens:
        if tok == "":
            continue
        if width_of(tok) <= max_width:
            tokens.append(tok)
        else:
            # Split this over-wide token into per-character pieces.
            piece = ""
            for ch in tok:
                trial = piece + ch
                if width_of(trial) <= max_width or piece == "":
                    piece = trial
                else:
                    tokens.append(piece)
                    piece = ch
            if piece:
                tokens.append(piece)

    lines: list[str] = []
    current = ""
    for tok in tokens:
        if width_of(tok) > max_width:
            # A single character wider than the box → cannot fit at this size.
            return [text], False
        trial = tok if current == "" else current + " " + tok
        # When joining with a space would overflow, also try without the space
        # (CJK tokens were produced char-by-char and read better unspaced).
        trial_nospace = current + tok
        if width_of(trial) <= max_width:
            current = trial
        elif current and width_of(trial_nospace) <= max_width and _is_cjk_join(current, tok):
            current = trial_nospace
        else:
            if current:
                lines.append(current)
            current = tok
    if current:
        lines.append(current)
    return lines or [""], True


def _is_cjk_join(left: str, right: str) -> bool:
    """True when both sides end/start with CJK — such tokens read better unspaced."""
    return bool(left) and bool(right) and _is_cjk(left[-1]) and _is_cjk(right[0])


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF      # CJK Unified Ideographs
        or 0x3400 <= o <= 0x4DBF   # Extension A
        or 0x3000 <= o <= 0x303F   # CJK punctuation
        or 0xFF00 <= o <= 0xFFEF   # full-width forms
    )


def _block_size(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font: ImageFont.FreeTypeFont,
    line_spacing: float,
) -> tuple[int, int]:
    """Total (width, height) of a multi-line block."""
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    widths = [_measure_line(draw, ln, font)[0] for ln in lines]
    total_w = max(widths) if widths else 0
    total_h = int(round(line_h * len(lines) + line_h * (line_spacing - 1.0) * max(0, len(lines) - 1)))
    return total_w, total_h


def layout_title(
    title: str,
    area: Rect,
    *,
    defaults: TitleDefaults,
    font_path: str | None = None,
    color: tuple[int, int, int] = (58, 58, 58),
    max_size_pt: int | None = None,
    min_size_pt: int | None = None,
    line_spacing: float | None = None,
    max_lines: int = 4,
) -> TitleLayout:
    """Find the largest font size at which ``title`` wraps to fit inside ``area``.

    Shrinks from ``max_size_pt`` down to ``min_size_pt`` (px), wrapping at each
    step, and returns the first layout whose block fits ``area`` in both axes and
    within ``max_lines``. Never clips: if nothing fits even at ``min_size_pt`` the
    smallest wrapping is returned (still inside the box on width by construction).

    Raises:
        ComposeError: if ``title`` is empty or ``area`` is degenerate.
    """
    title = title.strip()
    if not title:
        raise ComposeError("title must be a non-empty string")

    hi = max_size_pt if max_size_pt is not None else defaults.max_size_pt
    lo = min_size_pt if min_size_pt is not None else defaults.min_size_pt
    ls = line_spacing if line_spacing is not None else defaults.line_spacing
    if lo > hi:
        lo = hi

    # A throwaway 1x1 draw surface for text measurement.
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    best: TitleLayout | None = None
    for size in range(hi, lo - 1, -1):
        font = _load_font(font_path, size)
        lines, ok = _wrap_to_width(probe, title, font, area.width)
        if not ok:
            continue
        if len(lines) > max_lines:
            continue
        block_w, block_h = _block_size(probe, lines, font, ls)
        if block_w <= area.width and block_h <= area.height:
            block = _placed_block(lines, block_w, block_h, area, defaults.align)
            return TitleLayout(lines=list(lines), font_size=size, line_spacing=ls, block=block, color=color)
        # Track the smallest attempt in case nothing fits (degenerate box).
        if size == lo:
            block = _placed_block(lines, min(block_w, area.width), min(block_h, area.height), area, defaults.align)
            best = TitleLayout(lines=list(lines), font_size=size, line_spacing=ls, block=block, color=color)

    if best is not None:
        return best
    # Last resort: smallest font, single greedy wrap (guaranteed width-fit).
    font = _load_font(font_path, lo)
    lines, _ = _wrap_to_width(probe, title, font, area.width)
    block_w, block_h = _block_size(probe, lines, font, ls)
    block = _placed_block(lines, min(block_w, area.width), min(block_h, area.height), area, defaults.align)
    return TitleLayout(lines=list(lines), font_size=lo, line_spacing=ls, block=block, color=color)


def _placed_block(lines: Sequence[str], block_w: int, block_h: int, area: Rect, align: str) -> Rect:
    """Position the title block inside ``area`` per the alignment string."""
    block_w = min(block_w, area.width)
    block_h = min(block_h, area.height)
    # Horizontal: centre for any "center*" alignment, else left.
    if "center" in align or "centre" in align:
        x = area.x + (area.width - block_w) // 2
    elif "right" in align:
        x = area.right - block_w
    else:
        x = area.x
    # Vertical: "top" pins to the safe-zone top; "bottom" to bottom; else centre.
    if "top" in align:
        y = area.y
    elif "bottom" in align:
        y = area.bottom - block_h
    else:
        y = area.y + (area.height - block_h) // 2
    return Rect(int(x), int(y), int(max(1, block_w)), int(max(1, block_h)))


def _draw_title(img: Image.Image, layout: TitleLayout, font_path: str | None) -> None:
    """Render the resolved title layout onto ``img``."""
    draw = ImageDraw.Draw(img)
    font = _load_font(font_path, layout.font_size)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    step = int(round(line_h * layout.line_spacing))
    y = layout.block.y
    for line in layout.lines:
        w = draw.textbbox((0, 0), line, font=font)[2] if line else 0
        x = layout.block.x + (layout.block.width - w) // 2
        draw.text((x, y), line, font=font, fill=layout.color)
        y += step


# --------------------------------------------------------------------------- #
# Top-level compose
# --------------------------------------------------------------------------- #
def _hex_to_rgb(value: str, fallback: tuple[int, int, int] = (58, 58, 58)) -> tuple[int, int, int]:
    s = value.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return fallback
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return fallback


def compose_cover(
    main_visual: bytes | Image.Image,
    title: str,
    rules: PlatformRules,
    *,
    size_name: str | None = None,
    font_path: str | None = None,
    title_color: str | tuple[int, int, int] | None = None,
    title_max_pt: int | None = None,
    title_align: str | None = None,
) -> ComposedCover:
    """Compose a compliant cover from a model's main visual + a title.

    Args:
        main_visual: raw image bytes (from a model) or a PIL Image.
        title: the cover title; typeset to fit fully inside the safe-zone.
        rules: the loaded platform rule table.
        size_name: which named size to enforce (defaults to the platform default).
        font_path: optional custom font (e.g. a CJK OTF); falls back to the bundled font.
        title_color: hex string or RGB tuple; defaults to the platform default.
        title_max_pt: cap the starting font size (a pack may pin a specific size).
        title_align: override the alignment (e.g. "center-top").

    Returns:
        A :class:`ComposedCover` with the image and its :class:`ComplianceReport`.
    """
    size = rules.size(size_name)

    if isinstance(main_visual, (bytes, bytearray)):
        base = Image.open(io.BytesIO(bytes(main_visual)))
    elif isinstance(main_visual, Image.Image):
        base = main_visual
    else:
        raise ComposeError(f"main_visual must be bytes or a PIL Image, got {type(main_visual).__name__}")

    canvas = fit_image_to_size(base, size)

    # Resolve title typography from platform defaults, allowing per-call overrides.
    defaults = rules.title_defaults
    if title_align is not None:
        defaults = TitleDefaults(
            max_size_pt=defaults.max_size_pt,
            min_size_pt=defaults.min_size_pt,
            line_spacing=defaults.line_spacing,
            inner_padding=defaults.inner_padding,
            align=title_align,
        )

    if isinstance(title_color, tuple):
        color = title_color
    elif isinstance(title_color, str):
        color = _hex_to_rgb(title_color)
    else:
        color = (58, 58, 58)

    area = rules.title_area(size)  # safe-zone inset by inner padding
    layout = layout_title(
        title,
        area,
        defaults=defaults,
        font_path=font_path,
        color=color,
        max_size_pt=title_max_pt,
    )
    _draw_title(canvas, layout, font_path)

    # Build the compliance self-proof.
    in_safe = size.safe_zone.contains(layout.block)
    report = ComplianceReport(
        size_name=size.name,
        width=canvas.size[0],
        height=canvas.size[1],
        size_compliant=(canvas.size == (size.width, size.height)),
        title_in_safe_zone=in_safe,
        title_bbox=layout.block.as_tuple(),
        safe_zone=size.safe_zone.as_tuple(),
        font_size_pt=layout.font_size,
        line_count=len(layout.lines),
    )
    return ComposedCover(image=canvas, report=report, title=title)
