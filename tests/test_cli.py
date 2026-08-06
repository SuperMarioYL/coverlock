"""Tests for the CoverLock CLI (cli.py) — lock enforcement under --model.

Regression for fix-gen-model-flag-bypasses-lock-check: a pack tampered after
lock must STILL be detected when --model is passed, because verify_lock now
runs on the ORIGINAL pack right after load_pack (before the in-memory model
override is applied) — guarded only by `if require_lock:`, not by the old
`if require_lock and not model:` which exempted verification entirely whenever
--model was supplied.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from coverlock import cli as cli_mod
from coverlock import stylepack as sp


def _locked_mock_pack(tmp_path: Path) -> Path:
    """init a mock pack, retarget it at the offline mock model, then lock it."""
    path = sp.init_pack("p", desc="莫兰迪极简大留白", out_dir=tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["model"]["target"] = "mock"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sp.lock_pack(path)
    return path


def _tamper(path: Path) -> None:
    """Edit a locked field (palette) WITHOUT re-locking."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["palette"] = ["#000000"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_gen_model_override_still_verifies_tampered_pack(tmp_path):
    """A tampered pack + --model must still fail lock verification.

    Regression for fix-gen-model-flag-bypasses-lock-check: _gen_from_pack used
    to guard the lock check with `if require_lock and not model:`, so passing
    --model skipped verify_lock entirely — including on the original on-disk
    pack — and a pack tampered after lock was used silently (the stale
    locked_sha then propagated end-to-end via the sidecar). Now verify_lock
    runs on the ORIGINAL pack right after load_pack, before with_model_override.
    """
    import typer

    path = _locked_mock_pack(tmp_path)
    _tamper(path)
    out = tmp_path / "out"
    with pytest.raises(typer.BadParameter):
        cli_mod._gen_from_pack(
            path,
            ["标题一", "标题二"],
            out,
            model="mock",
            size=None,
            require_lock=True,
        )
    # Nothing should have been rendered when the lock check fails up-front.
    assert not (out / "cover_01.png").exists()


def test_gen_model_override_on_locked_pack_succeeds(tmp_path):
    """Sanity: a genuinely-locked pack + --model mock still renders.

    The fix must NOT break the offline --model demo path: a real (locked,
    untampered) pack passes verify_lock, the in-memory override is applied,
    and covers are generated with the mock model.
    """
    path = _locked_mock_pack(tmp_path)
    out = tmp_path / "out"
    cli_mod._gen_from_pack(
        path,
        ["标题一"],
        out,
        model="mock",
        size=None,
        require_lock=True,
    )
    assert (out / "cover_01.png").is_file()
    side = sp.read_sidecar(out)
    assert side["titles"] == ["标题一"]
    # The sidecar carries the persisted compose-time safe-zone verdicts.
    assert "compliance" in side and side["compliance"][0]["title_in_safe_zone"] is True


def test_gen_without_model_detects_tampered_pack(tmp_path):
    """The plain (no --model) path still catches a tampered pack (unchanged)."""
    import typer

    path = _locked_mock_pack(tmp_path)
    _tamper(path)
    out = tmp_path / "out"
    with pytest.raises(typer.BadParameter):
        cli_mod._gen_from_pack(
            path,
            ["标题一"],
            out,
            model=None,
            size=None,
            require_lock=True,
        )
