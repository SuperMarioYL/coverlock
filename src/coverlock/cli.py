"""CoverLock command-line interface (typer).

Commands (the whole `init → lock → gen → regen → gallery` loop):

* ``coverlock init``    — scaffold a style-pack draft from a style description.
* ``coverlock lock``    — validate + hash-lock a style-pack, freezing the style.
* ``coverlock gen``     — render a compliant cover set from a titles file.
* ``coverlock regen``   — re-render exactly one cover, keeping the rest intact.
* ``coverlock gallery`` — build the 10-cover consistency gallery + self-proof.
* ``coverlock models``  — list available image models.
* ``coverlock rules``   — show the loaded platform rule table.

Every command runs fully offline with ``--model mock`` (no key, no network), so
``init → lock → gen → gallery`` is demonstrable end to end out of the box.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .compose import compose_cover
from .models import ImageRequest, available_models, get_model
from .rules import load_platform_rules_cached

app = typer.Typer(
    name="coverlock",
    help="Lock an account-level cover style-pack; render size-compliant, "
    "safe-zone-aware vertical cover sets for Xiaohongshu.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"coverlock {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """CoverLock — consistent, compliant Xiaohongshu cover sets from a locked style-pack."""


def _read_titles(path: Path) -> list[str]:
    if not path.is_file():
        raise typer.BadParameter(f"titles file not found: {path}")
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    titles = [ln for ln in lines if ln and not ln.startswith("#")]
    if not titles:
        raise typer.BadParameter(f"titles file {path} has no usable lines")
    return titles


def _echo_cover_line(dest: Path, rep) -> None:
    mark = "✓" if rep.fully_compliant else "✗"
    typer.echo(
        f"  [{mark}] {dest.name}  {rep.width}x{rep.height}  "
        f"size={'✓' if rep.size_compliant else '✗'} "
        f"safe-zone={'✓' if rep.title_in_safe_zone else '✗'}"
    )


@app.command()
def gen(
    titles: Path = typer.Option(..., "--titles", "-t", help="Text file, one cover title per line."),
    pack: Optional[Path] = typer.Option(None, "--pack", "-p", help="Style-pack YAML (a locked pack keeps the set consistent)."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override the image model (e.g. mock, doubao, qwen)."),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Output directory for cover_NN.png."),
    platform: str = typer.Option("xiaohongshu", "--platform", help="Platform rule table (used when no pack is given)."),
    size: Optional[str] = typer.Option(None, "--size", help="Named size to enforce (default: platform default)."),
    seed: Optional[int] = typer.Option(None, "--seed", help="Base seed for reproducible main visuals (packless mode)."),
    require_lock: bool = typer.Option(
        True, "--require-lock/--no-require-lock",
        help="When a pack is given, require it to be locked and unmodified (default: on).",
    ),
) -> None:
    """Render a size-compliant, safe-zone-aware cover for each title.

    With ``--pack``, the covers are rendered from the *locked* style-pack (same
    model + scaffold + palette + layout for every cover) and a sidecar is written
    so ``regen`` / ``gallery`` can reconstruct the set. Without a pack it runs the
    packless m1 path (handy for a one-off ``--model mock`` demo).
    """
    title_list = _read_titles(titles)

    if pack is not None:
        _gen_from_pack(pack, title_list, out, model=model, size=size, require_lock=require_lock)
        return

    # -- packless path (no style-pack; a quick offline demo) ---------------- #
    rules = load_platform_rules_cached(platform)
    size_spec = rules.size(size)
    model_name = model or "mock"
    try:
        image_model = get_model(model_name)
    except Exception as exc:  # ModelError
        raise typer.BadParameter(str(exc))

    out.mkdir(parents=True, exist_ok=True)
    size_ok = zone_ok = 0
    typer.echo(
        f"coverlock gen · model={model_name} · size={size_spec.name} "
        f"({size_spec.width}x{size_spec.height}) · {len(title_list)} title(s)"
    )
    for i, title in enumerate(title_list, start=1):
        prompt = f"极简杂志风、莫兰迪低饱和、大留白、单一主体居中，画面不含任何文字. {title} 主视觉，低饱和莫兰迪配色，不含文字"
        req = ImageRequest(
            prompt=prompt,
            width=size_spec.width,
            height=size_spec.height,
            seed=(seed + i) if seed is not None else None,
        )
        main_visual = image_model.generate(req)
        cover = compose_cover(main_visual, title, rules, size_name=size_spec.name)
        dest = out / f"cover_{i:02d}.png"
        cover.save(dest)
        rep = cover.report
        size_ok += int(rep.size_compliant)
        zone_ok += int(rep.title_in_safe_zone)
        _echo_cover_line(dest, rep)

    n = len(title_list)
    typer.echo(f"done · size-compliant {size_ok}/{n} · titles-in-safe-zone {zone_ok}/{n} · out={out}")
    if size_ok != n or zone_ok != n:
        raise typer.Exit(code=1)


def _gen_from_pack(
    pack: Path,
    title_list: list[str],
    out: Path,
    *,
    model: Optional[str],
    size: Optional[str],
    require_lock: bool,
) -> None:
    """Render a cover set from a (locked) style-pack via the stylepack module."""
    from . import stylepack

    try:
        sp = stylepack.load_pack(pack)
    except stylepack.StylePackError as exc:
        raise typer.BadParameter(str(exc))

    if model:
        # Allow overriding the pack's model on the CLI (e.g. --model mock offline).
        # The override is in-memory only; the on-disk lock is unaffected.
        sp = stylepack.with_model_override(sp, model)

    if require_lock and not model:
        try:
            stylepack.verify_lock(sp)
        except stylepack.LockError as exc:
            raise typer.BadParameter(str(exc))

    rules = load_platform_rules_cached(sp.platform)
    size_spec = rules.size(size)
    typer.echo(
        f"coverlock gen · pack={sp.id} "
        f"({'locked' if sp.is_locked else 'UNLOCKED'}) · model={sp.model_target} · "
        f"size={size_spec.name} ({size_spec.width}x{size_spec.height}) · {len(title_list)} title(s)"
    )

    out.mkdir(parents=True, exist_ok=True)
    size_ok = zone_ok = 0
    for i, title in enumerate(title_list, start=1):
        try:
            cover = stylepack.render_cover(sp, title, i, rules, size_name=size_spec.name)
        except Exception as exc:  # ModelError etc.
            raise typer.BadParameter(str(exc))
        dest = out / f"cover_{i:02d}.png"
        cover.save(dest)
        rep = cover.report
        size_ok += int(rep.size_compliant)
        zone_ok += int(rep.title_in_safe_zone)
        _echo_cover_line(dest, rep)

    # Persist the sidecar so `regen` / `gallery` can reconstruct this exact set.
    stylepack.write_sidecar(out, sp, list(title_list), size_spec.name)

    n = len(title_list)
    typer.echo(f"done · size-compliant {size_ok}/{n} · titles-in-safe-zone {zone_ok}/{n} · out={out}")
    if size_ok != n or zone_ok != n:
        raise typer.Exit(code=1)


@app.command()
def models() -> None:
    """List the image models CoverLock can drive."""
    for name in available_models():
        suffix = "  (offline, no key)" if name == "mock" else "  (needs API key)"
        typer.echo(f"{name}{suffix}")


@app.command()
def rules(
    platform: str = typer.Option("xiaohongshu", "--platform", help="Platform rule table to show."),
) -> None:
    """Print the loaded platform rule table (sizes + safe-zones)."""
    r = load_platform_rules_cached(platform)
    typer.echo(f"platform: {r.platform} ({r.display_name}) · default={r.default_aspect}")
    for name in r.size_names():
        s = r.size(name)
        sz = s.safe_zone
        typer.echo(
            f"  {name}: {s.width}x{s.height}  safe_zone=({sz.x},{sz.y},{sz.width},{sz.height})"
        )


# --------------------------------------------------------------------------- #
# Style-pack lifecycle commands (m2 / m3).
# --------------------------------------------------------------------------- #
@app.command()
def init(
    pack_id: str = typer.Argument(..., help="Style-pack id (also the output filename stem)."),
    desc: str = typer.Option("", "--desc", "-d", help="Free-text account style description."),
    out: Path = typer.Option(Path("."), "--out", "-o", help="Directory to write <pack_id>.yaml into."),
) -> None:
    """Scaffold a new style-pack draft from a style description."""
    from . import stylepack

    try:
        dest = stylepack.init_pack(pack_id=pack_id, desc=desc, out_dir=out)
    except stylepack.StylePackError as exc:
        raise typer.BadParameter(str(exc))
    typer.echo(f"created style-pack draft: {dest}")
    typer.echo(f"next: edit it, then `coverlock lock {dest}` to freeze the style.")


@app.command()
def lock(
    pack: Path = typer.Argument(..., help="Path to the style-pack YAML to lock."),
) -> None:
    """Validate + hash-lock a style-pack, freezing its style."""
    from . import stylepack

    try:
        sha = stylepack.lock_pack(pack)
    except stylepack.StylePackError as exc:
        raise typer.BadParameter(str(exc))
    typer.echo(f"locked {pack}")
    typer.echo(f"locked_sha: {sha}")
    typer.echo("the style is now frozen; any edit to a locked field will be detected.")


@app.command()
def regen(
    pack: Path = typer.Option(..., "--pack", "-p", help="Locked style-pack YAML."),
    index: int = typer.Option(..., "--index", "-i", help="1-based index of the cover to re-render."),
    title: str = typer.Option(..., "--title", help="New title for that single cover."),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Cover output directory (from `gen`)."),
) -> None:
    """Re-render exactly one cover, keeping the rest of the locked set intact."""
    from . import stylepack

    try:
        dest = stylepack.regen_one(pack_path=pack, index=index, title=title, out_dir=out)
    except stylepack.StylePackError as exc:
        raise typer.BadParameter(str(exc))
    typer.echo(f"regenerated cover {index:02d} → {dest} (same locked pack; other covers untouched)")


@app.command()
def gallery(
    pack: Optional[Path] = typer.Option(None, "--pack", "-p", help="Locked style-pack YAML (optional; inferred from the set otherwise)."),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Directory holding cover_NN.png."),
    image: Optional[Path] = typer.Option(None, "--image", help="Where to write the gallery (default: <out>/gallery.png)."),
) -> None:
    """Compose the 10-cover consistency gallery with the compliance self-proof."""
    from . import gallery as gallery_mod
    from . import stylepack

    try:
        report = gallery_mod.build_gallery(pack_path=pack, covers_dir=out, out_path=image)
    except (gallery_mod.GalleryError, stylepack.StylePackError) as exc:
        raise typer.BadParameter(str(exc))
    typer.echo(f"gallery → {report.image_path}")
    typer.echo(report.footer)
    if not report.all_compliant:
        typer.echo("warning: not every cover is fully compliant.", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
