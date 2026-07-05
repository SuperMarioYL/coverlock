"""Tests for the compose core (compose.py) — the m1 compliance guarantee.

The two hard invariants this milestone must prove:

1. Every rendered cover is EXACTLY a named platform size (size-compliant).
2. The rendered title's bounding box lies FULLY inside the safe-zone
   (overflow is shrunk/wrapped, never clipped).
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from coverlock.compose import (
    ComposeError,
    ComposedCover,
    compose_cover,
    fit_image_to_size,
    layout_title,
)
from coverlock.models import ImageModel, ImageRequest, get_model
from coverlock.models.mock import MockModel
from coverlock.rules import Rect, load_platform_rules


@pytest.fixture(scope="module")
def rules():
    return load_platform_rules("xiaohongshu")


@pytest.fixture(scope="module")
def mock_model():
    return MockModel()


def _visual(model: MockModel, prompt: str, w: int, h: int, seed=None) -> bytes:
    return model.generate(ImageRequest(prompt=prompt, width=w, height=h, seed=seed))


# --- mock model + protocol -------------------------------------------------- #
def test_mock_model_satisfies_protocol():
    assert isinstance(MockModel(), ImageModel)


def test_registry_returns_mock():
    m = get_model("mock")
    assert m.name == "mock"


def test_mock_output_is_valid_png_of_requested_size(mock_model):
    raw = _visual(mock_model, "test subject", 400, 500, seed=1)
    img = Image.open(io.BytesIO(raw))
    assert img.format == "PNG"
    assert img.size == (400, 500)


def test_mock_is_deterministic(mock_model):
    a = _visual(mock_model, "same prompt", 300, 300, seed=7)
    b = _visual(mock_model, "same prompt", 300, 300, seed=7)
    assert a == b  # byte-identical => a locked pack reproduces


def test_mock_differs_on_prompt(mock_model):
    a = _visual(mock_model, "prompt one", 300, 300, seed=7)
    b = _visual(mock_model, "prompt two", 300, 300, seed=7)
    assert a != b


# --- size enforcement ------------------------------------------------------- #
def test_fit_image_forces_exact_size(rules):
    size = rules.size("4:5")
    src = Image.new("RGB", (640, 480), (200, 200, 200))  # wrong aspect + size
    out = fit_image_to_size(src, size)
    assert out.size == (size.width, size.height) == (1080, 1350)


def test_fit_image_from_tall_source(rules):
    size = rules.size("3:4")
    src = Image.new("RGB", (100, 2000), (10, 10, 10))
    out = fit_image_to_size(src, size)
    assert out.size == (size.width, size.height)


# --- the compliance guarantee ---------------------------------------------- #
@pytest.mark.parametrize("size_name", ["4:5", "3:4"])
def test_cover_is_size_compliant(rules, mock_model, size_name):
    size = rules.size(size_name)
    visual = _visual(mock_model, "morandi minimal", size.width, size.height, seed=3)
    cover = compose_cover(visual, "旅行日记", rules, size_name=size_name)
    assert cover.image.size == (size.width, size.height)
    assert cover.report.size_compliant is True
    assert cover.report.width == size.width
    assert cover.report.height == size.height


@pytest.mark.parametrize("size_name", ["4:5", "3:4"])
def test_title_bbox_inside_safe_zone(rules, mock_model, size_name):
    size = rules.size(size_name)
    visual = _visual(mock_model, "morandi minimal", size.width, size.height, seed=4)
    cover = compose_cover(visual, "极简穿搭分享", rules, size_name=size_name)
    bx, by, bw, bh = cover.report.title_bbox
    box = Rect(bx, by, bw, bh)
    assert size.safe_zone.contains(box), "title escaped the safe-zone"
    assert cover.report.title_in_safe_zone is True
    assert cover.report.fully_compliant is True


TITLES = [
    "旅行",
    "极简穿搭日常分享",
    "A very long English cover title that absolutely must wrap across lines to fit",
    "十个字都很长的中文标题需要自动换行才能塞进安全区不被裁切",
    "Mixed 中英文 title with 数字 2026 and punctuation!",
]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("size_name", ["4:5", "3:4"])
def test_every_title_stays_in_safe_zone(rules, mock_model, title, size_name):
    size = rules.size(size_name)
    visual = _visual(mock_model, "bg", size.width, size.height, seed=9)
    cover = compose_cover(visual, title, rules, size_name=size_name)
    bx, by, bw, bh = cover.report.title_bbox
    box = Rect(bx, by, bw, bh)
    assert size.safe_zone.contains(box), f"'{title}' escaped safe-zone at {size_name}"
    assert cover.report.size_compliant
    assert cover.report.title_in_safe_zone


def test_long_title_shrinks_font(rules, mock_model):
    """A long title must produce a smaller font than a short one (shrink-to-fit)."""
    size = rules.size("4:5")
    visual = _visual(mock_model, "bg", size.width, size.height, seed=2)
    short = compose_cover(visual, "旅行", rules, size_name="4:5")
    longt = compose_cover(
        visual,
        "A very long English cover title that absolutely must wrap across lines to fit",
        rules,
        size_name="4:5",
    )
    assert longt.report.font_size_pt <= short.report.font_size_pt
    assert longt.report.line_count >= 1


def test_long_title_wraps_multiple_lines(rules, mock_model):
    size = rules.size("4:5")
    visual = _visual(mock_model, "bg", size.width, size.height, seed=2)
    cover = compose_cover(
        visual,
        "十个字都很长的中文标题需要自动换行才能塞进安全区不被裁切完整",
        rules,
        size_name="4:5",
    )
    assert cover.report.line_count >= 2
    # Still fully inside the safe-zone.
    bx, by, bw, bh = cover.report.title_bbox
    assert size.safe_zone.contains(Rect(bx, by, bw, bh))


# --- layout_title unit behaviour ------------------------------------------- #
def test_layout_title_fits_area(rules):
    size = rules.size("4:5")
    area = rules.title_area(size)
    layout = layout_title("测试标题", area, defaults=rules.title_defaults)
    assert layout.block.width <= area.width
    assert layout.block.height <= area.height
    assert area.contains(layout.block)


def test_layout_title_empty_rejected(rules):
    size = rules.size("4:5")
    area = rules.title_area(size)
    with pytest.raises(ComposeError):
        layout_title("   ", area, defaults=rules.title_defaults)


def test_compose_accepts_pil_image(rules):
    size = rules.size("4:5")
    src = Image.new("RGB", (500, 500), (220, 210, 200))
    cover = compose_cover(src, "标题", rules, size_name="4:5")
    assert isinstance(cover, ComposedCover)
    assert cover.report.size_compliant


def test_compose_rejects_bad_visual_type(rules):
    with pytest.raises(ComposeError):
        compose_cover(12345, "标题", rules, size_name="4:5")  # type: ignore[arg-type]


def test_composed_cover_save_roundtrip(rules, mock_model, tmp_path):
    size = rules.size("4:5")
    visual = _visual(mock_model, "bg", size.width, size.height, seed=1)
    cover = compose_cover(visual, "保存测试", rules, size_name="4:5")
    dest = cover.save(tmp_path / "sub" / "cover_01.png")
    assert dest.is_file()
    reloaded = Image.open(dest)
    assert reloaded.size == (size.width, size.height)


def test_default_size_used_when_unspecified(rules, mock_model):
    size = rules.size()  # default
    visual = _visual(mock_model, "bg", size.width, size.height, seed=1)
    cover = compose_cover(visual, "默认尺寸", rules)  # no size_name
    assert cover.image.size == (size.width, size.height)


def test_title_color_hex_applied(rules, mock_model):
    size = rules.size("4:5")
    visual = _visual(mock_model, "bg", size.width, size.height, seed=1)
    cover = compose_cover(visual, "颜色", rules, size_name="4:5", title_color="#B85C38")
    assert cover.report.fully_compliant
