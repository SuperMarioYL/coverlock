"""Platform rule tables — cover geometry + title safe-zones (config-driven).

The rules live in editable YAML (``assets/rules/<platform>.yaml``), NOT in code.
That is the product's moat: if the platform shifts its cover sizes or safe-zone,
only the YAML changes — ``compose.py`` keeps working untouched.

This module loads that YAML into small, validated value objects:

* :class:`Rect` — an axis-aligned rectangle (x, y, width, height), top-left origin.
* :class:`SizeSpec` — one named cover size: its aspect, pixel dimensions, and the
  title safe-zone rectangle.
* :class:`TitleDefaults` — platform-sane title typography fallbacks.
* :class:`PlatformRules` — the whole table for one platform, with helpers to look
  up a size by name and to test whether a title box fits its safe-zone.

Everything here is pure/offline and has zero dependency on any image model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

__all__ = [
    "Rect",
    "SizeSpec",
    "TitleDefaults",
    "PlatformRules",
    "RuleError",
    "rules_dir",
    "load_platform_rules",
    "available_platforms",
]


class RuleError(ValueError):
    """Raised when a platform rule file is missing or structurally invalid."""


# Directory holding the shipped rule YAML files. In the source tree this is
# ``<repo>/assets/rules``; in an installed wheel the files are force-included at
# ``coverlock/assets/rules`` (see pyproject). We resolve the packaged copy first
# and fall back to the repo-root copy so tests run from a checkout too.
def rules_dir() -> Path:
    """Return the directory that holds ``<platform>.yaml`` rule files."""
    packaged = Path(__file__).resolve().parent / "assets" / "rules"
    if packaged.is_dir():
        return packaged
    repo_root = Path(__file__).resolve().parents[2] / "assets" / "rules"
    return repo_root


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in canvas pixels, top-left origin (+x right, +y down)."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise RuleError(f"rectangle must have positive size, got {self!r}")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    def inset(self, pad: int) -> "Rect":
        """Return this rectangle shrunk by ``pad`` px on every side."""
        if pad < 0:
            raise RuleError("inset padding must be non-negative")
        new_w = self.width - 2 * pad
        new_h = self.height - 2 * pad
        if new_w <= 0 or new_h <= 0:
            raise RuleError(
                f"inset of {pad}px collapses rectangle {self!r}"
            )
        return Rect(self.x + pad, self.y + pad, new_w, new_h)

    def contains(self, other: "Rect") -> bool:
        """True iff ``other`` is fully inside this rectangle (edges may touch)."""
        return (
            other.left >= self.left
            and other.top >= self.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def contains_box(self, x: float, y: float, width: float, height: float) -> bool:
        """True iff the box (x, y, width, height) is fully inside this rectangle."""
        return (
            x >= self.left
            and y >= self.top
            and x + width <= self.right
            and y + height <= self.bottom
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


def _parse_aspect(aspect: str) -> tuple[int, int]:
    """Parse an ``"W:H"`` aspect string into a ``(w, h)`` integer pair."""
    try:
        w_str, h_str = str(aspect).split(":")
        w, h = int(w_str), int(h_str)
    except (ValueError, AttributeError) as exc:
        raise RuleError(f"invalid aspect string: {aspect!r}") from exc
    if w <= 0 or h <= 0:
        raise RuleError(f"aspect components must be positive: {aspect!r}")
    return w, h


@dataclass(frozen=True)
class SizeSpec:
    """One named cover size: enforced pixel dimensions + title safe-zone."""

    name: str
    aspect: str
    width: int
    height: int
    safe_zone: Rect

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise RuleError(f"size {self.name!r} must have positive dimensions")
        # The declared pixel dimensions must actually match the declared aspect,
        # otherwise "size-compliant" would be meaningless.
        aw, ah = _parse_aspect(self.aspect)
        if self.width * ah != self.height * aw:
            raise RuleError(
                f"size {self.name!r}: {self.width}x{self.height} does not match "
                f"aspect {self.aspect!r}"
            )
        canvas = Rect(0, 0, self.width, self.height)
        if not canvas.contains(self.safe_zone):
            raise RuleError(
                f"size {self.name!r}: safe_zone {self.safe_zone.as_tuple()} "
                f"escapes the {self.width}x{self.height} canvas"
            )

    @property
    def aspect_pair(self) -> tuple[int, int]:
        return _parse_aspect(self.aspect)

    def matches_dimensions(self, width: int, height: int) -> bool:
        """True iff (width, height) is exactly this size's canvas dimensions."""
        return width == self.width and height == self.height


@dataclass(frozen=True)
class TitleDefaults:
    """Platform-sane title typography fallbacks (a style-pack may override these)."""

    max_size_pt: int = 96
    min_size_pt: int = 40
    line_spacing: float = 1.12
    inner_padding: int = 24
    align: str = "center-top"

    def __post_init__(self) -> None:
        if self.min_size_pt <= 0 or self.max_size_pt <= 0:
            raise RuleError("title size bounds must be positive")
        if self.min_size_pt > self.max_size_pt:
            raise RuleError(
                f"min_size_pt ({self.min_size_pt}) exceeds max_size_pt ({self.max_size_pt})"
            )
        if self.line_spacing <= 0:
            raise RuleError("line_spacing must be positive")
        if self.inner_padding < 0:
            raise RuleError("inner_padding must be non-negative")


@dataclass(frozen=True)
class PlatformRules:
    """The full rule table for one platform."""

    platform: str
    display_name: str
    default_aspect: str
    sizes: Mapping[str, SizeSpec]
    title_defaults: TitleDefaults

    def size(self, name: str | None = None) -> SizeSpec:
        """Look up a size by name, or the platform default when ``name`` is None."""
        key = name or self.default_aspect
        try:
            return self.sizes[key]
        except KeyError as exc:
            raise RuleError(
                f"platform {self.platform!r} has no size {key!r}; "
                f"available: {sorted(self.sizes)}"
            ) from exc

    def size_names(self) -> list[str]:
        return sorted(self.sizes)

    def is_compliant_dimensions(self, width: int, height: int) -> bool:
        """True iff (width, height) exactly matches one named size."""
        return any(s.matches_dimensions(width, height) for s in self.sizes.values())

    def title_area(self, size: SizeSpec) -> Rect:
        """The rectangle a title may occupy: safe-zone inset by the inner padding."""
        return size.safe_zone.inset(self.title_defaults.inner_padding)


def _require(mapping: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in mapping:
        raise RuleError(f"{ctx}: missing required key {key!r}")
    return mapping[key]


def _rect_from(raw: Mapping[str, Any], ctx: str) -> Rect:
    if not isinstance(raw, Mapping):
        raise RuleError(f"{ctx}: expected a mapping for a rectangle, got {type(raw).__name__}")
    return Rect(
        x=int(_require(raw, "x", ctx)),
        y=int(_require(raw, "y", ctx)),
        width=int(_require(raw, "width", ctx)),
        height=int(_require(raw, "height", ctx)),
    )


def _platform_rules_from_dict(data: Mapping[str, Any], source: str) -> PlatformRules:
    if not isinstance(data, Mapping):
        raise RuleError(f"{source}: top-level document must be a mapping")

    platform = str(_require(data, "platform", source))
    display_name = str(data.get("display_name", platform))
    default_aspect = str(_require(data, "default_aspect", source))

    raw_sizes = _require(data, "sizes", source)
    if not isinstance(raw_sizes, Mapping) or not raw_sizes:
        raise RuleError(f"{source}: 'sizes' must be a non-empty mapping")

    sizes: dict[str, SizeSpec] = {}
    for name, raw in raw_sizes.items():
        ctx = f"{source}:sizes.{name}"
        if not isinstance(raw, Mapping):
            raise RuleError(f"{ctx}: each size must be a mapping")
        sizes[str(name)] = SizeSpec(
            name=str(name),
            aspect=str(_require(raw, "aspect", ctx)),
            width=int(_require(raw, "width", ctx)),
            height=int(_require(raw, "height", ctx)),
            safe_zone=_rect_from(_require(raw, "safe_zone", ctx), f"{ctx}.safe_zone"),
        )

    if default_aspect not in sizes:
        raise RuleError(
            f"{source}: default_aspect {default_aspect!r} is not among sizes "
            f"{sorted(sizes)}"
        )

    raw_defaults = data.get("title_defaults") or {}
    if not isinstance(raw_defaults, Mapping):
        raise RuleError(f"{source}: 'title_defaults' must be a mapping")
    title_defaults = TitleDefaults(
        max_size_pt=int(raw_defaults.get("max_size_pt", 96)),
        min_size_pt=int(raw_defaults.get("min_size_pt", 40)),
        line_spacing=float(raw_defaults.get("line_spacing", 1.12)),
        inner_padding=int(raw_defaults.get("inner_padding", 24)),
        align=str(raw_defaults.get("align", "center-top")),
    )

    return PlatformRules(
        platform=platform,
        display_name=display_name,
        default_aspect=default_aspect,
        sizes=sizes,
        title_defaults=title_defaults,
    )


def load_platform_rules(platform: str = "xiaohongshu", *, rules_path: Path | None = None) -> PlatformRules:
    """Load and validate the rule table for ``platform``.

    Args:
        platform: platform key; selects ``<platform>.yaml`` from :func:`rules_dir`.
        rules_path: explicit YAML path override (used by tests / custom platforms).

    Raises:
        RuleError: if the file is missing or structurally invalid.
    """
    path = Path(rules_path) if rules_path is not None else rules_dir() / f"{platform}.yaml"
    if not path.is_file():
        raise RuleError(
            f"no rule file for platform {platform!r} at {path} "
            f"(available: {available_platforms()})"
        )
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return _platform_rules_from_dict(data, source=path.name)


@lru_cache(maxsize=None)
def _cached_platform_rules(platform: str, rules_dir_str: str) -> PlatformRules:
    return load_platform_rules(platform, rules_path=Path(rules_dir_str) / f"{platform}.yaml")


def load_platform_rules_cached(platform: str = "xiaohongshu") -> PlatformRules:
    """Cached variant for hot paths (``gen`` loops). Keyed on the rules directory."""
    return _cached_platform_rules(platform, str(rules_dir()))


def available_platforms() -> list[str]:
    """List platform keys with a shipped rule file."""
    d = rules_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))
