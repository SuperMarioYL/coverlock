"""Tests for the consistency gallery (gallery.py) — the m3 milestone.

m3 must prove: a locked pack's 10 covers compose into one ``gallery.png`` with a
per-cover ``尺寸✓/安全区✓`` badge and a footer ``size-compliant N/10 ·
titles-in-safe-zone N/10`` self-proof, and the counts are recomputed from the
covers on disk (so the footer can't lie).

Also exercises the two real model clients' key-required error paths + payload
parsing (no network) so the pluggable model boundary is covered.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from coverlock import gallery as gal
from coverlock import stylepack as sp
from coverlock.gallery import GalleryError, build_gallery
from coverlock.models.base import ModelError
from coverlock.rules import load_platform_rules


# --------------------------------------------------------------------------- #
# fixtures — a real locked mock pack + a rendered 10-cover set
# --------------------------------------------------------------------------- #
def _locked_mock_pack(tmp_path: Path) -> Path:
    import yaml

    path = sp.init_pack("gal", desc="莫兰迪极简", out_dir=tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["model"]["target"] = "mock"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sp.lock_pack(path)
    return path


@pytest.fixture()
def rendered_set(tmp_path):
    path = _locked_mock_pack(tmp_path)
    pack = sp.load_pack(path)
    titles = [f"封面标题{i}" for i in range(1, 11)]
    out = tmp_path / "out"
    sp.render_set(pack, titles, out)
    return {"pack_path": path, "out": out, "titles": titles}


# --------------------------------------------------------------------------- #
# gallery composition + self-proof
# --------------------------------------------------------------------------- #
def test_gallery_builds_from_ten_covers(rendered_set):
    report = build_gallery(pack_path=rendered_set["pack_path"], covers_dir=rendered_set["out"])
    assert report.image_path.is_file()
    assert report.total == 10
    with Image.open(report.image_path) as im:
        assert im.size[0] > 0 and im.size[1] > 0
        assert im.format == "PNG"


def test_gallery_footer_is_all_compliant(rendered_set):
    report = build_gallery(pack_path=rendered_set["pack_path"], covers_dir=rendered_set["out"])
    assert report.size_compliant_count == 10
    assert report.safe_zone_count == 10
    assert report.all_compliant is True
    assert report.footer == "size-compliant 10/10 · titles-in-safe-zone 10/10"


def test_gallery_counts_recomputed_from_pixels(rendered_set):
    """Every audit's size verdict comes from the actual cover dimensions."""
    report = build_gallery(pack_path=rendered_set["pack_path"], covers_dir=rendered_set["out"])
    rules = load_platform_rules("xiaohongshu")
    for audit in report.audits:
        assert audit.size_compliant is True
        assert rules.is_compliant_dimensions(audit.width, audit.height)


def test_gallery_detects_a_noncompliant_cover(rendered_set, tmp_path):
    """A cover with wrong dimensions is counted as size-non-compliant in the footer."""
    out = rendered_set["out"]
    # Overwrite one cover with an off-size image (simulating a bad external file).
    bad = out / "cover_05.png"
    Image.new("RGB", (500, 500), (200, 200, 200)).save(bad)
    report = build_gallery(pack_path=rendered_set["pack_path"], covers_dir=out)
    assert report.size_compliant_count == 9
    assert report.all_compliant is False


def test_gallery_infers_platform_from_sidecar(rendered_set):
    """Gallery works without an explicit pack (platform read from the sidecar)."""
    report = build_gallery(pack_path=None, covers_dir=rendered_set["out"])
    assert report.total == 10
    assert report.all_compliant


def test_gallery_custom_out_path(rendered_set, tmp_path):
    dest = tmp_path / "custom" / "sheet.png"
    report = build_gallery(
        pack_path=rendered_set["pack_path"], covers_dir=rendered_set["out"], out_path=dest
    )
    assert report.image_path == dest
    assert dest.is_file()


def test_gallery_requires_locked_pack_when_pack_given(tmp_path):
    """If a pack is passed, the gallery re-verifies its lock (self-proof of origin)."""
    import yaml

    path = sp.init_pack("nolock", out_dir=tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["model"]["target"] = "mock"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    pack = sp.load_pack(path)
    out = tmp_path / "out"
    # Generate a set without lock enforcement so covers exist on disk.
    sp.render_set(pack, ["a", "b"], out, require_lock=False)
    with pytest.raises(sp.LockError):
        build_gallery(pack_path=path, covers_dir=out)


def test_gallery_empty_dir_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(GalleryError):
        build_gallery(covers_dir=empty)


def test_grid_shape_for_ten():
    assert gal._grid_shape(10) == (2, 5)
    assert gal._grid_shape(4) == (2, 2)
    assert gal._grid_shape(1) == (1, 1)


# --------------------------------------------------------------------------- #
# real model clients — key-required + payload parsing (no network)
# --------------------------------------------------------------------------- #
def test_doubao_requires_key(monkeypatch):
    from coverlock.models.doubao import DoubaoSeedreamModel
    from coverlock.models.base import ImageRequest

    monkeypatch.delenv("DOUBAO_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    model = DoubaoSeedreamModel()
    with pytest.raises(ModelError):
        model.generate(ImageRequest(prompt="x", width=1080, height=1350))


def test_qwen_requires_key(monkeypatch):
    from coverlock.models.qwen import QwenImageModel
    from coverlock.models.base import ImageRequest

    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    model = QwenImageModel()
    with pytest.raises(ModelError):
        model.generate(ImageRequest(prompt="x", width=1080, height=1350))


def test_doubao_extracts_b64_image():
    from coverlock.models.doubao import _extract_image_bytes

    png = _tiny_png_bytes()
    payload = {"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]}
    assert _extract_image_bytes(payload) == png


def test_doubao_extract_raises_on_empty():
    from coverlock.models.doubao import _extract_image_bytes

    with pytest.raises(ModelError):
        _extract_image_bytes({"data": []})


def test_doubao_size_mapping_is_portrait():
    from coverlock.models.doubao import _nearest_size

    s = _nearest_size(1080, 1350)  # 4:5 portrait
    w, h = (int(v) for v in s.split("x"))
    assert h >= w  # portrait target maps to a portrait-or-square size


def test_qwen_first_image_url():
    from coverlock.models.qwen import _first_image_url

    out = {"task_status": "SUCCEEDED", "results": [{"url": "https://example/img.png"}]}
    assert _first_image_url(out) == "https://example/img.png"


def test_qwen_first_image_url_raises_when_empty():
    from coverlock.models.qwen import _first_image_url

    with pytest.raises(ModelError):
        _first_image_url({"results": []})


def _tiny_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# gallery safe-zone honors the pack's title font (v0.3.0)
# --------------------------------------------------------------------------- #
def _cjk_font_path():
    """Find a real CJK font on the host (macOS system fonts), else None.

    The bundled default font renders CJK glyphs at ~half the width of a real
    CJK font (48px vs 96px per glyph at size 96), which is exactly the
    divergence that lets the gallery's default-font re-derivation report
    title_in_safe_zone=True for a cover whose real pack-font block overflows.
    """
    for p in (
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Songti.ttc",
    ):
        if Path(p).is_file():
            return Path(p)
    return None


def test_gallery_safe_zone_honors_pack_font_verdict(tmp_path):
    """Regression for fix-gallery-safezone-ignores-pack-font.

    A CJK-font pack whose real title block overflows the safe-zone must be
    reported title_in_safe_zone=False by the gallery — NOT the false True that
    re-deriving the title block with the platform DEFAULT font produces. The
    default font renders CJK glyphs at ~half the width of a real CJK font, so
    its re-derived block is shorter and falsely 'fits'.

    The compose-time verdict (computed with the pack's locked title_font) is
    persisted in the .coverlock_titles.json sidecar; the gallery now reads it
    verbatim instead of re-deriving. Here we plant the genuine overflow verdict
    a CJK-font pack produces for a long title (its real pack-font block is
    taller than the safe-zone, e.g. block_h=1327 > 900) and assert the gallery
    trusts it verbatim.
    """
    import json
    import yaml

    # Build a locked mock pack that pins a real CJK font as its title_font —
    # the §2 example pack shape (layout.title_font: assets/fonts/SourceHanSans.otf).
    path = sp.init_pack("cjkfont", desc="莫兰迪极简", out_dir=tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["model"]["target"] = "mock"
    cjk = _cjk_font_path()
    if cjk is not None:
        data.setdefault("layout", {})["title_font"] = str(cjk)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sp.lock_pack(path)
    pack = sp.load_pack(path)

    # A long CJK title: with the pack's CJK font the real block overflows the
    # safe-zone (taller than the safe-zone height of 900px).
    long_title = "标" * 440
    titles = [long_title, "短标题一", "短标题二"]
    out = tmp_path / "out"
    sp.render_set(pack, titles, out)

    side_path = out / sp.TITLES_FILENAME
    side = json.loads(side_path.read_text(encoding="utf-8"))
    # Sanity: the sidecar now carries per-cover compose-time verdicts.
    assert "compliance" in side and len(side["compliance"]) == 3
    assert all(c is not None and "title_in_safe_zone" in c for c in side["compliance"])

    # Plant the genuine CJK-font overflow verdict for cover 1 (its real pack-font
    # block overflows the safe-zone). After fix-layout-title-fallback-bypasses-
    # max-lines the long title is truncated to max_lines at compose and no longer
    # overflows there, so we plant the overflow verdict the CJK-font block really
    # produces to prove the gallery reads the sidecar verbatim rather than
    # re-deriving True with the default font.
    side["compliance"][0] = {
        "title_in_safe_zone": False,
        "title_bbox": [96, 132, 888, 1327],
    }
    side_path.write_text(json.dumps(side, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_gallery(pack_path=path, covers_dir=out)
    # The gallery must trust the persisted False verdict for cover 1 — not the
    # false True a default-font re-derivation would produce.
    assert report.audits[0].title_in_safe_zone is False
    assert report.safe_zone_count == 2
    assert report.all_compliant is False
    # The other covers (genuinely compliant) are still reported True.
    assert report.audits[1].title_in_safe_zone is True
    assert report.audits[2].title_in_safe_zone is True
