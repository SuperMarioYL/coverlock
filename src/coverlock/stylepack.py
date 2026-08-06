"""The account-level style-pack primitive — load, validate, hash-lock, regen.

A **style-pack** is CoverLock's core data model: a lockable, reusable YAML asset
that fixes one account's whole visual language (which model, the prompt scaffold,
the palette, the title layout, the platform). It is what makes covers converge to
the same look across posts instead of drifting per one-off prompt.

The lifecycle this module owns:

* :func:`init_pack`   — scaffold a draft ``<id>.yaml`` from a free-text style desc.
* :func:`load_pack`   — parse + schema-validate a pack into a :class:`StylePack`.
* :func:`lock_pack`   — canonicalise the locked fields, sha256 them, write
  ``locked_sha`` back into the file. The style is frozen from that point.
* :func:`verify_lock` — recompute the sha and compare, so any post-lock edit to a
  locked field is *detected* (the m2 done-criterion).
* :func:`render_set` — render a whole compliant cover set from a (locked) pack.
* :func:`regen_one`   — re-render exactly ONE cover with a new title, keeping the
  same pack (same model+scaffold+palette+layout) so the rest of the set is
  untouched byte-for-byte.

The hash is computed over a **canonical projection** of the locked fields only
(``model``, ``prompt_scaffold``, ``palette``, ``layout``, ``platform``) — never
over ``id``, ``locked_sha``, comments, or key ordering — so re-serialising a pack
never changes its identity, but changing any *style* field does.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import yaml

from .compose import ComposedCover, compose_cover
from .models import ImageRequest, get_model
from .rules import PlatformRules, load_platform_rules_cached

__all__ = [
    "StylePack",
    "StylePackError",
    "LockError",
    "load_pack",
    "init_pack",
    "lock_pack",
    "verify_lock",
    "render_set",
    "render_cover",
    "regen_one",
    "verify_lock",
    "is_lock_valid",
    "with_model_override",
    "write_sidecar",
    "read_sidecar",
    "report_to_compliance",
    "example_pack_path",
    "canonical_bytes",
    "compute_sha",
    "LOCKED_FIELDS",
    "TITLES_FILENAME",
]

# The fields that constitute the *identity* of a pack's style. The sha256 lock is
# computed over exactly these (canonicalised). ``id``/``locked_sha`` are excluded
# so renaming or re-locking never changes the frozen style hash.
LOCKED_FIELDS: tuple[str, ...] = ("model", "prompt_scaffold", "palette", "layout", "platform")

# When `gen` writes a cover set it also drops the titles beside the covers, so
# `regen --index N` and `gallery` know each cover's title without re-passing them.
TITLES_FILENAME = ".coverlock_titles.json"


class StylePackError(ValueError):
    """Raised when a style-pack is missing required fields or is malformed."""


class LockError(StylePackError):
    """Raised when a lock check fails (missing lock, or a locked field changed)."""


# --------------------------------------------------------------------------- #
# The validated in-memory pack
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StylePack:
    """A validated, in-memory style-pack.

    ``raw`` keeps the original mapping (so a round-trip preserves any extra keys
    a future version adds); the typed accessors expose the fields the pipeline
    needs. ``locked_sha`` is ``None`` for an unlocked draft.
    """

    id: str
    platform: str
    model_target: str
    model_params: Mapping[str, Any]
    system_prompt: str
    per_cover_template: str
    palette: tuple[str, ...]
    title_color: Optional[str]
    title_align: Optional[str]
    title_max_pt: Optional[int]
    font_path: Optional[str]
    locked_sha: Optional[str]
    source_path: Optional[Path] = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    # -- prompt assembly ---------------------------------------------------- #
    def prompt_for(self, title: str) -> str:
        """Compose the full model prompt for ``title`` from the locked scaffold.

        The title is the ONLY per-cover variable; the system line and palette are
        fixed by the pack, which is what keeps a set visually consistent.
        """
        palette_hint = "、".join(self.palette) if self.palette else "低饱和莫兰迪配色"
        per_cover = self.per_cover_template.format(topic=title, palette_hint=palette_hint)
        return f"{self.system_prompt}. {per_cover}"

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_sha)

    def canonical(self) -> "dict[str, Any]":
        """The canonical projection of the locked fields (basis for the sha)."""
        return _canonical_projection(self.raw)


# --------------------------------------------------------------------------- #
# Canonicalisation + hashing
# --------------------------------------------------------------------------- #
def _canonical_value(value: Any) -> Any:
    """Recursively normalise a value so the sha is stable across serialisations.

    Mappings become sorted-key dicts, sequences keep order, scalars pass through.
    This makes the hash independent of YAML key ordering / comments / quoting.
    """
    if isinstance(value, Mapping):
        return {str(k): _canonical_value(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(v) for v in value]
    return value


def _canonical_projection(data: Mapping[str, Any]) -> "dict[str, Any]":
    """Project a pack mapping down to just the locked fields, canonicalised."""
    return {k: _canonical_value(data.get(k)) for k in LOCKED_FIELDS}


def canonical_bytes(data: Mapping[str, Any]) -> bytes:
    """Deterministic byte-serialisation of a pack's locked fields."""
    projection = _canonical_projection(data)
    return json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_sha(data: Mapping[str, Any]) -> str:
    """The sha256 (hex) over a pack's canonical locked-field projection."""
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


# --------------------------------------------------------------------------- #
# Parsing / validation
# --------------------------------------------------------------------------- #
def _as_mapping(value: Any, ctx: str) -> "dict[str, Any]":
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise StylePackError(f"{ctx}: expected a mapping, got {type(value).__name__}")
    return dict(value)


def _pack_from_dict(data: Mapping[str, Any], source: Optional[Path]) -> StylePack:
    if not isinstance(data, Mapping):
        raise StylePackError("style-pack: top-level document must be a mapping")

    pack_id = data.get("id")
    if not pack_id or not str(pack_id).strip():
        raise StylePackError("style-pack: missing required non-empty 'id'")

    model = _as_mapping(data.get("model"), "model")
    target = model.get("target")
    if not target or not str(target).strip():
        raise StylePackError("style-pack: 'model.target' is required (e.g. doubao-seedream)")
    params = _as_mapping(model.get("params"), "model.params")

    scaffold = _as_mapping(data.get("prompt_scaffold"), "prompt_scaffold")
    system = str(
        scaffold.get("system", "极简杂志风、莫兰迪低饱和、大留白、单一主体居中，画面不含任何文字")
    )
    template = str(scaffold.get("per_cover_template", "{topic} 主视觉，{palette_hint}，不含文字"))
    _validate_template(template)

    raw_palette = data.get("palette") or []
    if not isinstance(raw_palette, (list, tuple)):
        raise StylePackError("style-pack: 'palette' must be a list of hex colours")
    palette = tuple(str(c) for c in raw_palette)

    layout = _as_mapping(data.get("layout"), "layout")
    title_style = _as_mapping(layout.get("title_style"), "layout.title_style")
    title_color = title_style.get("color")
    title_align = title_style.get("align")
    size_pt = title_style.get("size_pt")
    font_path = layout.get("title_font")

    platform = str(data.get("platform", "xiaohongshu"))

    locked_sha = data.get("locked_sha")
    locked_sha = str(locked_sha) if locked_sha else None

    return StylePack(
        id=str(pack_id),
        platform=platform,
        model_target=str(target),
        model_params=params,
        system_prompt=system,
        per_cover_template=template,
        palette=palette,
        title_color=str(title_color) if title_color else None,
        title_align=str(title_align) if title_align else None,
        title_max_pt=int(size_pt) if isinstance(size_pt, (int, float)) else None,
        font_path=str(font_path) if font_path else None,
        locked_sha=locked_sha,
        source_path=Path(source) if source else None,
        raw=dict(data),
    )


def _validate_template(template: str) -> None:
    """Ensure the per-cover template only references the allowed placeholders."""
    import string

    allowed = {"topic", "palette_hint"}
    try:
        fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
    except ValueError as exc:
        raise StylePackError(f"prompt_scaffold.per_cover_template is not a valid format string: {exc}") from exc
    unknown = fields - allowed
    if unknown:
        raise StylePackError(
            f"prompt_scaffold.per_cover_template references unknown placeholder(s) {sorted(unknown)}; "
            f"only {sorted(allowed)} are injected per cover"
        )


def load_pack(path: str | Path) -> StylePack:
    """Load and schema-validate a style-pack YAML into a :class:`StylePack`.

    Raises:
        StylePackError: if the file is missing or structurally invalid.
    """
    p = Path(path)
    if not p.is_file():
        raise StylePackError(f"style-pack file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise StylePackError(f"style-pack {p} is not valid YAML: {exc}") from exc
    return _pack_from_dict(data or {}, source=p)


def with_model_override(pack: StylePack, model_target: str) -> StylePack:
    """Return a copy of ``pack`` whose model target is ``model_target``.

    Handy for a CLI ``--model mock`` override on a real (doubao-targeted) pack so
    the whole loop demos offline. This does NOT change the locked identity: the
    override is applied to the in-memory pack only, never written back to disk, so
    the on-disk lock still describes the account's real style.
    """
    raw = dict(pack.raw)
    model = dict(raw.get("model") or {})
    model["target"] = model_target
    raw["model"] = model
    return _pack_from_dict(raw, source=pack.source_path)


# --------------------------------------------------------------------------- #
# init — scaffold a draft
# --------------------------------------------------------------------------- #
def _draft_dict(pack_id: str, desc: str) -> "dict[str, Any]":
    system = desc.strip() or "极简杂志风、莫兰迪低饱和、大留白、单一主体居中，画面不含任何文字"
    return {
        "id": pack_id,
        "model": {
            "target": "doubao-seedream",
            "params": {"aspect": "4:5", "seed_strategy": "pinned", "guidance": 6.5},
        },
        "prompt_scaffold": {
            "system": system,
            "per_cover_template": "{topic} 主视觉，{palette_hint}，构图留白居中，不含文字",
        },
        "palette": ["#E8E2D9", "#3A3A3A", "#B85C38"],
        "layout": {
            "title_box_ref": "safe_zone",
            "title_style": {
                "size_pt": 88,
                "weight": "heavy",
                "color": "#3A3A3A",
                "align": "center-top",
            },
        },
        "platform": "xiaohongshu",
    }


_DRAFT_HEADER = (
    "# CoverLock style-pack (draft — run `coverlock lock` to freeze the style).\n"
    "#\n"
    "# A style-pack fixes one account's whole visual language. The title/topic is\n"
    "# the ONLY per-cover variable; everything else stays fixed so every cover\n"
    "# across posts converges to the same look. `locked_sha` is written by\n"
    "# `coverlock lock` and, once present, any edit to a style field is detected.\n"
)


def init_pack(pack_id: str, desc: str = "", out_dir: str | Path = ".") -> Path:
    """Scaffold ``<pack_id>.yaml`` (an *unlocked* draft) from a style description.

    Returns the written path. Refuses to overwrite an existing file.
    """
    pack_id = pack_id.strip()
    if not pack_id:
        raise StylePackError("init: pack id must be non-empty")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{pack_id}.yaml"
    if dest.exists():
        raise StylePackError(f"init: refusing to overwrite existing {dest}")
    body = yaml.safe_dump(
        _draft_dict(pack_id, desc),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    dest.write_text(_DRAFT_HEADER + body, encoding="utf-8")
    return dest


# --------------------------------------------------------------------------- #
# lock / verify
# --------------------------------------------------------------------------- #
def lock_pack(pack_path: str | Path) -> str:
    """Validate + hash-lock a style-pack in place, writing ``locked_sha``.

    Idempotent: re-locking an unchanged pack yields the same sha. If the pack was
    already locked but a style field has since changed, the sha updates to the new
    value (an explicit re-lock is how you intentionally evolve a style).

    Returns the sha256 written.
    """
    p = Path(pack_path)
    pack = load_pack(p)  # validates schema
    sha = compute_sha(pack.raw)

    # Re-serialise from the ORIGINAL text so we preserve comments/formatting and
    # only insert-or-replace the locked_sha line, rather than dumping a new file.
    original = p.read_text(encoding="utf-8")
    data = yaml.safe_load(original) or {}
    if not isinstance(data, dict):
        raise StylePackError(f"style-pack {p} is not a YAML mapping")
    data["locked_sha"] = sha

    body = yaml.safe_dump(
        _reorder_with_lock(data),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    p.write_text(body, encoding="utf-8")
    return sha


def _reorder_with_lock(data: Mapping[str, Any]) -> "dict[str, Any]":
    """Put ``id`` then ``locked_sha`` first for readability, keep the rest in order."""
    ordered: dict[str, Any] = {}
    if "id" in data:
        ordered["id"] = data["id"]
    if "locked_sha" in data:
        ordered["locked_sha"] = data["locked_sha"]
    for k, v in data.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def verify_lock(pack: StylePack) -> None:
    """Assert a pack is locked AND its recorded sha matches its current fields.

    Raises:
        LockError: if the pack has no ``locked_sha`` (never locked) or if a locked
            field has been edited since the lock (recorded sha != recomputed sha).
    """
    if not pack.locked_sha:
        raise LockError(
            f"style-pack {pack.id!r} is not locked; run `coverlock lock` before gen/regen "
            f"so the style is frozen and reproducible"
        )
    current = compute_sha(pack.raw)
    if current != pack.locked_sha:
        raise LockError(
            f"style-pack {pack.id!r} was edited after lock: recorded sha "
            f"{pack.locked_sha[:12]}… but current fields hash to {current[:12]}…. "
            f"Re-run `coverlock lock` to intentionally adopt the new style."
        )


def is_lock_valid(pack: StylePack) -> bool:
    """Non-raising variant of :func:`verify_lock`."""
    try:
        verify_lock(pack)
        return True
    except LockError:
        return False


# --------------------------------------------------------------------------- #
# Rendering a set from a (locked) pack
# --------------------------------------------------------------------------- #
def _seed_for(pack: StylePack, index: int) -> Optional[int]:
    """Derive a per-cover seed when the pack pins seeds (keeps output reproducible)."""
    strategy = str(pack.model_params.get("seed_strategy", "")).lower()
    if strategy != "pinned":
        return None
    base = pack.model_params.get("seed")
    if isinstance(base, int):
        return base + index
    # Derive a stable base seed from the locked identity so a locked pack always
    # reproduces the same set even without an explicit seed in the YAML.
    digest = hashlib.sha256((pack.locked_sha or pack.id).encode("utf-8")).digest()
    base_seed = int.from_bytes(digest[:4], "big")
    return base_seed + index


def render_cover(
    pack: StylePack,
    title: str,
    index: int,
    rules: PlatformRules,
    size_name: Optional[str] = None,
) -> ComposedCover:
    """Render one compliant cover for ``title`` using the pack's locked style."""
    size = rules.size(size_name)
    model = get_model(pack.model_target)
    prompt = pack.prompt_for(title)
    req = ImageRequest(
        prompt=prompt,
        width=size.width,
        height=size.height,
        seed=_seed_for(pack, index),
    )
    main_visual = model.generate(req)
    return compose_cover(
        main_visual,
        title,
        rules,
        size_name=size.name,
        font_path=pack.font_path,
        title_color=pack.title_color,
        title_max_pt=pack.title_max_pt,
        title_align=pack.title_align,
    )


def render_set(
    pack: StylePack,
    titles: Sequence[str],
    out_dir: str | Path,
    *,
    size_name: Optional[str] = None,
    require_lock: bool = True,
) -> "list[Path]":
    """Render a whole cover set from a locked pack and persist it to ``out_dir``.

    Writes ``cover_01.png`` … plus a sidecar ``.coverlock_titles.json`` recording
    the pack path, size, and each cover's title so ``regen`` / ``gallery`` can
    reconstruct the set without re-passing arguments.

    Args:
        require_lock: when True (default) the pack MUST be locked and unmodified.
    """
    if require_lock:
        verify_lock(pack)
    rules = load_platform_rules_cached(pack.platform)
    size = rules.size(size_name)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    compliance: list[dict[str, Any]] = []
    for i, title in enumerate(titles, start=1):
        cover = render_cover(pack, title, i, rules, size_name=size.name)
        dest = out / f"cover_{i:02d}.png"
        cover.save(dest)
        written.append(dest)
        compliance.append(report_to_compliance(cover.report))

    _write_sidecar(out, pack, list(titles), size.name, compliance=compliance)
    return written


def _sidecar_path(out_dir: str | Path) -> Path:
    return Path(out_dir) / TITLES_FILENAME


def report_to_compliance(report: Any) -> "dict[str, Any]":
    """Project a :class:`~coverlock.compose.ComplianceReport` into the sidecar.

    Persists the compose-time safe-zone verdict + the real title bbox verbatim,
    so ``gallery.audit_cover`` can read them back instead of re-deriving the
    title block with the platform DEFAULT font (which diverges from the pack's
    locked title_font / align / size_pt that ``compose_cover`` actually drew —
    a divergence that let the footer claim title_in_safe_zone=True for a cover
    whose real pack-font block overflowed). Reading the verdict verbatim means
    the gallery can never report a safe-zone pass it did not actually check.
    """
    return {
        "title_in_safe_zone": bool(report.title_in_safe_zone),
        "title_bbox": [int(v) for v in report.title_bbox],
    }


def _write_sidecar(
    out_dir: Path,
    pack: StylePack,
    titles: list[str],
    size_name: str,
    *,
    compliance: "list[dict[str, Any] | None] | None" = None,
) -> None:
    payload = {
        "pack_id": pack.id,
        "pack_path": str(pack.source_path) if pack.source_path else None,
        "locked_sha": pack.locked_sha,
        "platform": pack.platform,
        "size_name": size_name,
        "titles": titles,
    }
    if compliance is not None:
        payload["compliance"] = compliance
    _sidecar_path(out_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_sidecar(
    out_dir: str | Path,
    pack: StylePack,
    titles: Sequence[str],
    size_name: str,
    *,
    compliance: "Sequence[dict[str, Any] | None] | None" = None,
) -> None:
    """Public wrapper: record the cover-set sidecar (pack id, size, per-cover
    titles, and per-cover compose-time compliance verdicts)."""
    _write_sidecar(
        Path(out_dir), pack, list(titles), size_name,
        compliance=list(compliance) if compliance is not None else None,
    )


def read_sidecar(out_dir: str | Path) -> "dict[str, Any]":
    """Read the cover-set sidecar written by :func:`render_set`.

    Raises:
        StylePackError: if no sidecar exists (the set was never generated here).
    """
    sp = _sidecar_path(out_dir)
    if not sp.is_file():
        raise StylePackError(
            f"no cover set found in {out_dir} (missing {TITLES_FILENAME}); "
            f"run `coverlock gen` first"
        )
    return json.loads(sp.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# regen — re-render exactly one cover, keep the rest intact
# --------------------------------------------------------------------------- #
def regen_one(
    pack_path: str | Path,
    index: int,
    title: str,
    out_dir: str | Path = "out",
    *,
    size_name: Optional[str] = None,
) -> Path:
    """Re-render exactly cover ``index`` (1-based) with a new title.

    Uses the SAME locked pack, so the regenerated cover inherits the identical
    model + scaffold + palette + layout. Every OTHER cover file is left untouched
    byte-for-byte — this is the in-the-loop control the milestone requires.

    Returns the path of the single re-rendered cover.

    Raises:
        LockError: if the pack is unlocked or has been edited since lock.
        StylePackError: if there is no generated set, or ``index`` is out of range.
    """
    pack = load_pack(pack_path)
    verify_lock(pack)

    out = Path(out_dir)
    side = read_sidecar(out)
    titles: list[str] = list(side.get("titles") or [])
    if not titles:
        raise StylePackError(f"cover set in {out} records no titles")
    if index < 1 or index > len(titles):
        raise StylePackError(
            f"index {index} out of range 1..{len(titles)} for the set in {out}"
        )

    resolved_size = size_name or side.get("size_name")
    rules = load_platform_rules_cached(pack.platform)

    cover = render_cover(pack, title, index, rules, size_name=resolved_size)
    dest = out / f"cover_{index:02d}.png"
    cover.save(dest)

    # Update just this title in the sidecar; leave every other cover file alone.
    titles[index - 1] = title
    # Refresh this cover's persisted compose-time safe-zone verdict too, so the
    # gallery footer for the set still reflects the real (re)drawn block — a
    # regen with a new title may flip the verdict, and the sidecar is the gallery's
    # source of truth (it must not re-derive with the platform default font).
    existing_compliance: list[Any] = list(side.get("compliance") or [])
    if len(existing_compliance) < len(titles):
        existing_compliance += [None] * (len(titles) - len(existing_compliance))
    elif len(existing_compliance) > len(titles):
        existing_compliance = existing_compliance[: len(titles)]
    existing_compliance[index - 1] = report_to_compliance(cover.report)
    _write_sidecar(out, pack, titles, resolved_size or rules.default_aspect, compliance=existing_compliance)
    return dest


# --------------------------------------------------------------------------- #
# Shipped example
# --------------------------------------------------------------------------- #
def example_pack_path() -> Optional[Path]:
    """Path to the shipped example style-pack, if present (packaged or repo copy)."""
    packaged = Path(__file__).resolve().parent / "assets" / "stylepacks" / "example.yaml"
    if packaged.is_file():
        return packaged
    repo = Path(__file__).resolve().parents[2] / "assets" / "stylepacks" / "example.yaml"
    return repo if repo.is_file() else None
