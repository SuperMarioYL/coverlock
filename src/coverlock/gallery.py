"""Consistency gallery — the self-proving screenshot artifact (m3).

:func:`build_gallery` takes a locked pack's rendered cover set and composes a
single ``gallery.png``:

* an N-up grid of the covers (default up to 10, in a tidy row×col layout),
* a per-cover corner badge stamping ``4:5 ✓`` and ``安全区 ✓`` (size + safe-zone),
* a footer line ``size-compliant N/N · titles-in-safe-zone N/N`` — the machine
  self-proof that the whole locked set is compliant.

That image is the strongest shareable hook: at a glance it shows ten covers that
obviously came from one account, each provably compliant. The compliance numbers
are recomputed here from the covers on disk + the platform rules, so the footer
can never lie about a set it didn't actually check.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from .rules import PlatformRules, Rect, RuleError, SizeSpec, load_platform_rules_cached
from .compose import ComposeError, layout_title
from . import stylepack as _sp

__all__ = [
    "GalleryError",
    "CoverAudit",
    "GalleryReport",
    "audit_cover",
    "build_gallery",
]

# Chrome colours (Morandi-neutral so the gallery reads as one calm sheet).
_BG = (244, 241, 236)
_CARD_BG = (255, 255, 255)
_BADGE_OK_BG = (58, 122, 92)
_BADGE_BAD_BG = (176, 74, 60)
_BADGE_TEXT = (248, 246, 242)
_FOOTER_TEXT = (58, 58, 58)
_ZONE_STROKE = (184, 92, 56)


class GalleryError(ValueError):
    """Raised when a gallery cannot be built (no covers, bad dimensions…)."""


@dataclass(frozen=True)
class CoverAudit:
    """The recomputed compliance verdict for one cover on disk."""

    path: Path
    width: int
    height: int
    size_name: Optional[str]
    size_compliant: bool
    # Safe-zone compliance is re-derived in audit_cover from the sidecar title
    # + the platform rules (re-running layout_title), so the footer reflects
    # the actual geometry — never a hardcoded pass.
    title_in_safe_zone: bool

    @property
    def fully_compliant(self) -> bool:
        return self.size_compliant and self.title_in_safe_zone


@dataclass(frozen=True)
class GalleryReport:
    """The gallery's self-proof: per-cover audits + rolled-up counts."""

    audits: tuple[CoverAudit, ...]
    size_compliant_count: int
    safe_zone_count: int
    total: int
    image_path: Path

    @property
    def footer(self) -> str:
        return (
            f"size-compliant {self.size_compliant_count}/{self.total} · "
            f"titles-in-safe-zone {self.safe_zone_count}/{self.total}"
        )

    @property
    def all_compliant(self) -> bool:
        return (
            self.total > 0
            and self.size_compliant_count == self.total
            and self.safe_zone_count == self.total
        )


def _matching_size(rules: PlatformRules, width: int, height: int) -> Optional[SizeSpec]:
    for name in rules.size_names():
        s = rules.size(name)
        if s.matches_dimensions(width, height):
            return s
    return None


def _recompute_safe_zone(
    rules: PlatformRules,
    title: Optional[str],
    size_name: Optional[str],
    width: int,
    height: int,
) -> bool:
    """Re-derive whether ``title``'s layout fits the safe zone, honestly.

    Mirrors compose.py's geometry: re-run ``layout_title`` for the sidecar
    title at the sidecar size and test the safe-zone. The verdict is trusted
    only when the cover on disk IS that named size (a real CoverLock cover);
    a foreign-sized or sidecar-less cover cannot be proven compliant and
    reports ``False`` — so the gallery footer can never lie about a set it
    didn't actually check.
    """
    if not title or not size_name:
        return False
    try:
        size = rules.size(size_name)
    except RuleError:
        return False
    # The cover on disk must actually be the named size, else the title the
    # sidecar describes was never drawn here → cannot be safe-zone-compliant.
    if (width, height) != (size.width, size.height):
        return False
    area = rules.title_area(size)
    try:
        layout = layout_title(title, area, defaults=rules.title_defaults)
    except ComposeError:
        return False
    return size.safe_zone.contains(layout.block)


def audit_cover(
    path: Path,
    rules: PlatformRules,
    *,
    title: Optional[str] = None,
    size_name: Optional[str] = None,
) -> CoverAudit:
    """Recompute a cover's compliance from its pixels + the platform rules.

    Size compliance is derived from the cover's pixel dimensions. Safe-zone
    compliance is re-derived by re-running the title layout for the sidecar
    title at the sidecar size — but only when the cover on disk actually IS
    that named size (a real CoverLock cover). A foreign-sized or sidecar-less
    cover cannot be proven safe-zone-compliant, so it reports ``False``: the
    footer can never claim a safe-zone pass it did not actually check.
    """
    with Image.open(path) as im:
        w, h = im.size
    size = _matching_size(rules, w, h)
    title_in_safe_zone = _recompute_safe_zone(rules, title, size_name, w, h)
    return CoverAudit(
        path=path,
        width=w,
        height=h,
        size_name=size.name if size else None,
        size_compliant=size is not None,
        title_in_safe_zone=title_in_safe_zone,
    )


def _discover_covers(covers_dir: Path) -> list[Path]:
    covers = sorted(covers_dir.glob("cover_*.png"))
    if not covers:
        raise GalleryError(
            f"no covers found in {covers_dir} (expected cover_01.png …); run `coverlock gen` first"
        )
    return covers


def _grid_shape(n: int) -> tuple[int, int]:
    """Choose (rows, cols) for ``n`` covers, favouring a 5-wide sheet for 10."""
    if n <= 0:
        raise GalleryError("cannot build a gallery from zero covers")
    if n <= 3:
        return 1, n
    if n == 4:
        return 2, 2
    if n <= 6:
        return 2, 3
    if n <= 8:
        return 2, 4
    if n <= 10:
        return 2, 5
    cols = 5
    rows = (n + cols - 1) // cols
    return rows, cols


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    ok: bool,
    font: ImageFont.FreeTypeFont,
) -> int:
    """Draw a small rounded compliance badge; return its width."""
    tw, th = _text_size(draw, text, font)
    pad_x, pad_y = 12, 6
    w, h = tw + 2 * pad_x, th + 2 * pad_y
    bg = _BADGE_OK_BG if ok else _BADGE_BAD_BG
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=bg)
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=_BADGE_TEXT)
    return w


def build_gallery(
    pack_path: Optional[str | Path] = None,
    covers_dir: str | Path = "out",
    *,
    out_path: Optional[str | Path] = None,
    max_covers: int = 10,
    thumb_width: int = 360,
) -> GalleryReport:
    """Compose ``gallery.png`` from a rendered cover set + write it to disk.

    Args:
        pack_path: the locked pack (used only to resolve the platform rule table
            and to re-verify the lock; may be ``None`` to infer from the sidecar).
        covers_dir: directory holding ``cover_NN.png`` (as written by ``gen``).
        out_path: where to write the gallery (default ``<covers_dir>/gallery.png``).
        max_covers: cap the number of covers placed (the thesis artifact is 10).
        thumb_width: per-cover thumbnail width in the grid.

    Returns:
        A :class:`GalleryReport` whose ``footer`` is the compliance self-proof.
    """
    covers_dir = Path(covers_dir)
    cover_paths = _discover_covers(covers_dir)[:max_covers]

    platform = "xiaohongshu"
    titles: Optional[list[str]] = None
    size_name: Optional[str] = None
    # Prefer the sidecar (records platform + per-cover titles + the size), so
    # the safe-zone verdict can be re-derived per cover instead of hardcoded.
    try:
        side = _sp.read_sidecar(covers_dir)
        platform = str(side.get("platform") or platform)
        side_titles = side.get("titles") or []
        if side_titles:
            titles = [str(t) for t in side_titles]
        size_name = side.get("size_name")
    except _sp.StylePackError:
        side = None
    if pack_path is not None:
        pack = _sp.load_pack(pack_path)
        _sp.verify_lock(pack)  # a gallery must self-prove it came from a locked pack
        platform = pack.platform

    rules = load_platform_rules_cached(platform)
    audits = [
        audit_cover(
            p,
            rules,
            title=titles[i] if titles and i < len(titles) else None,
            size_name=size_name,
        )
        for i, p in enumerate(cover_paths)
    ]

    report_image = _compose_grid(cover_paths, audits, thumb_width=thumb_width)
    dest = Path(out_path) if out_path else covers_dir / "gallery.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    report_image.save(dest)

    size_ok = sum(a.size_compliant for a in audits)
    zone_ok = sum(a.title_in_safe_zone for a in audits)
    return GalleryReport(
        audits=tuple(audits),
        size_compliant_count=size_ok,
        safe_zone_count=zone_ok,
        total=len(audits),
        image_path=dest,
    )


def _compose_grid(
    cover_paths: Sequence[Path],
    audits: Sequence[CoverAudit],
    *,
    thumb_width: int,
) -> Image.Image:
    n = len(cover_paths)
    rows, cols = _grid_shape(n)

    # Uniform thumbnail cells (use the first cover's aspect for the cell height).
    with Image.open(cover_paths[0]) as first:
        fw, fh = first.size
    aspect = fh / fw if fw else 1.25
    thumb_h = int(round(thumb_width * aspect))

    gutter = 24
    margin = 40
    header_h = 96
    footer_h = 88

    grid_w = cols * thumb_width + (cols - 1) * gutter
    grid_h = rows * thumb_h + (rows - 1) * gutter
    canvas_w = grid_w + 2 * margin
    canvas_h = header_h + grid_h + footer_h + 2 * margin

    canvas = Image.new("RGB", (canvas_w, canvas_h), _BG)
    draw = ImageDraw.Draw(canvas)

    title_font = _load_font(34)
    badge_font = _load_font(18)
    footer_font = _load_font(30)

    # Header.
    draw.text((margin, margin), "CoverLock · consistency gallery", font=title_font, fill=_FOOTER_TEXT)

    top = margin + header_h
    for i, (cover_path, audit) in enumerate(zip(cover_paths, audits)):
        r, c = divmod(i, cols)
        x = margin + c * (thumb_width + gutter)
        y = top + r * (thumb_h + gutter)

        # Card backdrop.
        draw.rounded_rectangle((x - 6, y - 6, x + thumb_width + 6, y + thumb_h + 6), radius=14, fill=_CARD_BG)

        with Image.open(cover_path) as im:
            thumb = im.convert("RGB").resize((thumb_width, thumb_h), Image.LANCZOS)
        canvas.paste(thumb, (x, y))

        # Compliance badges, bottom-right of each thumbnail.
        size_label = f"{audit.size_name or '?'} ✓" if audit.size_compliant else "size ✗"
        zone_label = "安全区 ✓" if audit.title_in_safe_zone else "安全区 ✗"
        bw2 = _text_size(draw, zone_label, badge_font)[0] + 24
        by = y + thumb_h - 40
        _draw_badge(draw, x + thumb_width - bw2 - 10, by, zone_label, audit.title_in_safe_zone, badge_font)
        bw1 = _text_size(draw, size_label, badge_font)[0] + 24
        _draw_badge(draw, x + thumb_width - bw2 - bw1 - 20, by, size_label, audit.size_compliant, badge_font)

    # Footer self-proof.
    size_ok = sum(a.size_compliant for a in audits)
    zone_ok = sum(a.title_in_safe_zone for a in audits)
    footer = f"size-compliant {size_ok}/{n} · titles-in-safe-zone {zone_ok}/{n}"
    fy = canvas_h - margin - footer_h + 20
    draw.text((margin, fy), footer, font=footer_font, fill=_FOOTER_TEXT)

    return canvas
