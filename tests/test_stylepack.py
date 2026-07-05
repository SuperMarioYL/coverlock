"""Tests for the style-pack primitive (stylepack.py) — the m2 milestone.

The three invariants m2 must prove:

1. A pack can be scaffolded, schema-validated, and hash-locked; the lock is a
   sha256 over the *style* fields only (model + scaffold + palette + layout +
   platform), independent of key ordering / comments / the id.
2. After lock, ANY edit to a locked field is DETECTED (verify_lock raises).
3. ``regen --index N`` re-renders exactly one cover using the SAME locked pack;
   every other cover file is left byte-for-byte identical (style preserved), and
   the single re-rendered cover changes with the new title.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from coverlock import stylepack as sp
from coverlock.stylepack import (
    LockError,
    StylePack,
    StylePackError,
    compute_sha,
    init_pack,
    load_pack,
    lock_pack,
    regen_one,
    render_set,
    verify_lock,
    with_model_override,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _mock_locked_pack(tmp_path: Path, pack_id: str = "p") -> Path:
    """init a pack, retarget it at the offline mock model, then lock it."""
    path = init_pack(pack_id, desc="莫兰迪极简大留白", out_dir=tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["model"]["target"] = "mock"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    lock_pack(path)
    return path


# --------------------------------------------------------------------------- #
# init + load + schema validation
# --------------------------------------------------------------------------- #
def test_init_writes_unlocked_draft(tmp_path):
    path = init_pack("mypack", desc="极简杂志风", out_dir=tmp_path)
    assert path == tmp_path / "mypack.yaml"
    pack = load_pack(path)
    assert isinstance(pack, StylePack)
    assert pack.id == "mypack"
    assert pack.locked_sha is None
    assert pack.is_locked is False
    # The description is threaded into the system prompt.
    assert "极简杂志风" in pack.system_prompt


def test_init_refuses_overwrite(tmp_path):
    init_pack("dup", out_dir=tmp_path)
    with pytest.raises(StylePackError):
        init_pack("dup", out_dir=tmp_path)


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(StylePackError):
        load_pack(tmp_path / "nope.yaml")


def test_load_rejects_missing_id(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("model: {target: mock}\n", encoding="utf-8")
    with pytest.raises(StylePackError):
        load_pack(p)


def test_load_rejects_missing_model_target(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("id: x\nmodel: {params: {}}\n", encoding="utf-8")
    with pytest.raises(StylePackError):
        load_pack(p)


def test_load_rejects_unknown_template_placeholder(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "id: x\nmodel: {target: mock}\n"
        "prompt_scaffold: {per_cover_template: '{topic} {unknown_var}'}\n",
        encoding="utf-8",
    )
    with pytest.raises(StylePackError):
        load_pack(p)


def test_shipped_example_pack_loads():
    path = sp.example_pack_path()
    assert path is not None and path.is_file()
    pack = load_pack(path)
    assert pack.id == "example"
    assert pack.model_target in {"doubao-seedream", "qwen-image", "mock"}
    assert pack.palette  # non-empty locked palette


# --------------------------------------------------------------------------- #
# canonical hashing
# --------------------------------------------------------------------------- #
def test_sha_ignores_key_order_and_id(tmp_path):
    a = {
        "id": "a",
        "platform": "xiaohongshu",
        "model": {"target": "mock", "params": {"aspect": "4:5", "guidance": 6.5}},
        "prompt_scaffold": {"system": "s", "per_cover_template": "{topic}"},
        "palette": ["#111111", "#222222"],
        "layout": {"title_style": {"color": "#333333", "align": "center-top"}},
    }
    # Same style, different id + reordered params + a locked_sha present.
    b = {
        "locked_sha": "irrelevant",
        "layout": {"title_style": {"align": "center-top", "color": "#333333"}},
        "palette": ["#111111", "#222222"],
        "prompt_scaffold": {"per_cover_template": "{topic}", "system": "s"},
        "model": {"params": {"guidance": 6.5, "aspect": "4:5"}, "target": "mock"},
        "platform": "xiaohongshu",
        "id": "DIFFERENT",
    }
    assert compute_sha(a) == compute_sha(b)


def test_sha_changes_when_style_field_changes():
    base = {
        "id": "a",
        "platform": "xiaohongshu",
        "model": {"target": "mock"},
        "prompt_scaffold": {"system": "s", "per_cover_template": "{topic}"},
        "palette": ["#111111"],
        "layout": {"title_style": {"color": "#333333"}},
    }
    changed = {**base, "palette": ["#999999"]}
    assert compute_sha(base) != compute_sha(changed)


# --------------------------------------------------------------------------- #
# lock / verify
# --------------------------------------------------------------------------- #
def test_lock_writes_sha_and_verifies(tmp_path):
    path = _mock_locked_pack(tmp_path)
    pack = load_pack(path)
    assert pack.is_locked
    assert len(pack.locked_sha) == 64  # sha256 hex
    verify_lock(pack)  # must not raise


def test_lock_is_idempotent(tmp_path):
    path = _mock_locked_pack(tmp_path)
    first = load_pack(path).locked_sha
    second = lock_pack(path)  # re-lock unchanged pack
    assert first == second


def test_verify_lock_rejects_unlocked(tmp_path):
    path = init_pack("draft", out_dir=tmp_path)
    pack = load_pack(path)
    with pytest.raises(LockError):
        verify_lock(pack)


def test_edit_after_lock_is_detected(tmp_path):
    path = _mock_locked_pack(tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # Tamper with a locked field WITHOUT re-locking.
    data["palette"] = ["#000000"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tampered = load_pack(path)
    assert tampered.locked_sha is not None  # stale sha still present
    with pytest.raises(LockError):
        verify_lock(tampered)


def test_relock_adopts_new_style(tmp_path):
    path = _mock_locked_pack(tmp_path)
    original = load_pack(path).locked_sha
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["palette"] = ["#000000", "#ffffff"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    new_sha = lock_pack(path)  # explicit re-lock
    assert new_sha != original
    verify_lock(load_pack(path))  # now valid again


# --------------------------------------------------------------------------- #
# prompt assembly + model override
# --------------------------------------------------------------------------- #
def test_prompt_injects_only_title(tmp_path):
    path = _mock_locked_pack(tmp_path)
    pack = load_pack(path)
    p1 = pack.prompt_for("春日穿搭")
    p2 = pack.prompt_for("秋日穿搭")
    assert "春日穿搭" in p1 and "秋日穿搭" in p2
    # Everything except the injected title is identical across covers.
    assert p1.replace("春日穿搭", "X") == p2.replace("秋日穿搭", "X")


def test_with_model_override_keeps_locked_sha_but_changes_target(tmp_path):
    path = _mock_locked_pack(tmp_path, "p")
    pack = load_pack(path)
    over = with_model_override(pack, "doubao-seedream")
    assert over.model_target == "doubao-seedream"
    assert pack.model_target == "mock"
    # Overriding the model changes the identity, so verify against the OLD sha fails.
    with pytest.raises(LockError):
        verify_lock(over)


# --------------------------------------------------------------------------- #
# render_set + regen (the core m2 in-the-loop guarantee)
# --------------------------------------------------------------------------- #
def test_render_set_requires_lock(tmp_path):
    path = init_pack("unlocked", out_dir=tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["model"]["target"] = "mock"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    pack = load_pack(path)  # never locked
    with pytest.raises(LockError):
        render_set(pack, ["标题一", "标题二"], tmp_path / "out")


def test_render_set_writes_covers_and_sidecar(tmp_path):
    path = _mock_locked_pack(tmp_path)
    pack = load_pack(path)
    titles = [f"第{i}篇分享" for i in range(1, 6)]
    written = render_set(pack, titles, tmp_path / "out")
    assert len(written) == 5
    assert all(p.is_file() for p in written)
    side = sp.read_sidecar(tmp_path / "out")
    assert side["titles"] == titles
    assert side["locked_sha"] == pack.locked_sha


def test_render_set_is_deterministic_for_locked_pack(tmp_path):
    """A locked pack reproduces byte-identical covers across two gen runs."""
    path = _mock_locked_pack(tmp_path)
    pack = load_pack(path)
    titles = ["一", "二", "三"]
    a = render_set(pack, titles, tmp_path / "a")
    b = render_set(pack, titles, tmp_path / "b")
    for pa, pb in zip(a, b):
        assert pa.read_bytes() == pb.read_bytes()


def test_regen_changes_only_the_target_cover(tmp_path):
    path = _mock_locked_pack(tmp_path)
    pack = load_pack(path)
    titles = [f"标题{i}" for i in range(1, 11)]
    out = tmp_path / "out"
    render_set(pack, titles, out)

    before = {p.name: _sha_file(p) for p in sorted(out.glob("cover_*.png"))}
    dest = regen_one(path, index=3, title="全新的第三个标题", out_dir=out)
    assert dest.name == "cover_03.png"

    after = {p.name: _sha_file(p) for p in sorted(out.glob("cover_*.png"))}
    changed = [n for n, h in before.items() if after[n] != h]
    assert changed == ["cover_03.png"], f"regen touched more than one cover: {changed}"

    # The sidecar records the new title for that slot only.
    side = sp.read_sidecar(out)
    assert side["titles"][2] == "全新的第三个标题"
    assert side["titles"][0] == "标题1"


def test_regen_reflects_new_title(tmp_path):
    path = _mock_locked_pack(tmp_path)
    pack = load_pack(path)
    titles = ["原标题一", "原标题二", "原标题三"]
    out = tmp_path / "out"
    render_set(pack, titles, out)
    original = _sha_file(out / "cover_02.png")
    regen_one(path, index=2, title="完全不同的新标题", out_dir=out)
    assert _sha_file(out / "cover_02.png") != original


def test_regen_rejects_out_of_range_index(tmp_path):
    path = _mock_locked_pack(tmp_path)
    pack = load_pack(path)
    out = tmp_path / "out"
    render_set(pack, ["a", "b"], out)
    with pytest.raises(StylePackError):
        regen_one(path, index=9, title="x", out_dir=out)


def test_regen_requires_locked_pack(tmp_path):
    path = init_pack("nolock", out_dir=tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["model"]["target"] = "mock"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # No render/lock; regen must refuse an unlocked pack.
    with pytest.raises(LockError):
        regen_one(path, index=1, title="x", out_dir=tmp_path / "out")
