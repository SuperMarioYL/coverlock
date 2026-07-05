"""Tests for the platform rule table loader (rules.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from coverlock.rules import (
    PlatformRules,
    Rect,
    RuleError,
    SizeSpec,
    available_platforms,
    load_platform_rules,
    load_platform_rules_cached,
    rules_dir,
)


def test_shipped_xiaohongshu_rules_load():
    r = load_platform_rules("xiaohongshu")
    assert isinstance(r, PlatformRules)
    assert r.platform == "xiaohongshu"
    assert r.default_aspect in r.sizes
    assert set(r.size_names()) >= {"4:5", "3:4"}


def test_default_size_matches_default_aspect():
    r = load_platform_rules("xiaohongshu")
    default = r.size()  # no name -> default
    assert default.name == r.default_aspect


def test_size_dimensions_match_declared_aspect():
    r = load_platform_rules("xiaohongshu")
    for name in r.size_names():
        s = r.size(name)
        aw, ah = s.aspect_pair
        # width * ah == height * aw  <=>  width/height == aw/ah
        assert s.width * ah == s.height * aw, f"{name} dimensions don't match aspect"


def test_4x5_exact_dimensions():
    r = load_platform_rules("xiaohongshu")
    s = r.size("4:5")
    assert (s.width, s.height) == (1080, 1350)


def test_safe_zone_inside_canvas_for_every_size():
    r = load_platform_rules("xiaohongshu")
    for name in r.size_names():
        s = r.size(name)
        canvas = Rect(0, 0, s.width, s.height)
        assert canvas.contains(s.safe_zone), f"{name} safe-zone escapes canvas"


def test_is_compliant_dimensions():
    r = load_platform_rules("xiaohongshu")
    assert r.is_compliant_dimensions(1080, 1350) is True
    assert r.is_compliant_dimensions(1080, 1440) is True
    assert r.is_compliant_dimensions(1000, 1000) is False


def test_title_area_is_safe_zone_inset():
    r = load_platform_rules("xiaohongshu")
    s = r.size("4:5")
    area = r.title_area(s)
    pad = r.title_defaults.inner_padding
    assert area.x == s.safe_zone.x + pad
    assert area.width == s.safe_zone.width - 2 * pad
    # The title area is strictly inside the safe-zone.
    assert s.safe_zone.contains(area)


def test_unknown_size_raises():
    r = load_platform_rules("xiaohongshu")
    with pytest.raises(RuleError):
        r.size("16:9")


def test_unknown_platform_raises():
    with pytest.raises(RuleError):
        load_platform_rules("no_such_platform")


def test_available_platforms_lists_xiaohongshu():
    assert "xiaohongshu" in available_platforms()


def test_rules_dir_exists():
    assert rules_dir().is_dir()


def test_cached_loader_returns_equivalent():
    a = load_platform_rules_cached("xiaohongshu")
    b = load_platform_rules_cached("xiaohongshu")
    assert a is b  # cached
    assert a.size("4:5").width == 1080


# --- Rect geometry ---------------------------------------------------------- #
def test_rect_contains_and_edges():
    outer = Rect(0, 0, 100, 100)
    inner = Rect(10, 10, 80, 80)
    assert outer.contains(inner)
    edge = Rect(0, 0, 100, 100)  # touching edges counts as contained
    assert outer.contains(edge)
    escaping = Rect(10, 10, 100, 80)
    assert not outer.contains(escaping)


def test_rect_inset():
    r = Rect(0, 0, 100, 100)
    i = r.inset(10)
    assert i.as_tuple() == (10, 10, 80, 80)


def test_rect_inset_collapse_raises():
    r = Rect(0, 0, 20, 20)
    with pytest.raises(RuleError):
        r.inset(15)


def test_rect_rejects_nonpositive():
    with pytest.raises(RuleError):
        Rect(0, 0, 0, 10)


# --- Validation of malformed rule files ------------------------------------- #
def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "custom.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_dimensions_not_matching_aspect_rejected(tmp_path):
    p = _write(
        tmp_path,
        """
        platform: custom
        default_aspect: "4:5"
        sizes:
          "4:5":
            aspect: "4:5"
            width: 1000
            height: 1000
            safe_zone: {x: 10, y: 10, width: 100, height: 100}
        """,
    )
    with pytest.raises(RuleError):
        load_platform_rules(rules_path=p)


def test_safe_zone_escaping_canvas_rejected(tmp_path):
    p = _write(
        tmp_path,
        """
        platform: custom
        default_aspect: "4:5"
        sizes:
          "4:5":
            aspect: "4:5"
            width: 1080
            height: 1350
            safe_zone: {x: 10, y: 10, width: 2000, height: 100}
        """,
    )
    with pytest.raises(RuleError):
        load_platform_rules(rules_path=p)


def test_default_aspect_not_in_sizes_rejected(tmp_path):
    p = _write(
        tmp_path,
        """
        platform: custom
        default_aspect: "9:16"
        sizes:
          "4:5":
            aspect: "4:5"
            width: 1080
            height: 1350
            safe_zone: {x: 10, y: 10, width: 100, height: 100}
        """,
    )
    with pytest.raises(RuleError):
        load_platform_rules(rules_path=p)


def test_missing_sizes_rejected(tmp_path):
    p = _write(
        tmp_path,
        """
        platform: custom
        default_aspect: "4:5"
        """,
    )
    with pytest.raises(RuleError):
        load_platform_rules(rules_path=p)


def test_sizespec_direct_validation():
    # A well-formed SizeSpec constructs fine.
    ss = SizeSpec("4:5", "4:5", 1080, 1350, Rect(96, 132, 888, 900))
    assert ss.matches_dimensions(1080, 1350)
    assert not ss.matches_dimensions(1080, 1351)
