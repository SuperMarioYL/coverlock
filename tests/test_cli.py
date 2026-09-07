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


# --------------------------------------------------------------------------- #
# packless `gen` writes a sidecar so the gallery self-proves honestly (v0.6.0)
# --------------------------------------------------------------------------- #
def test_packless_gen_writes_sidecar_for_gallery(tmp_path):
    """Regression for fix-packless-gen-skips-sidecar.

    The packless ``gen --model mock`` path (m1 demo) used to render each cover
    via ``compose_cover`` (which computes a real ``title_in_safe_zone``) and
    even echo ``done · titles-in-safe-zone N/N``, but write NO sidecar, so
    ``gallery``'s no-sidecar fallback (``_recompute_safe_zone`` returning
    ``False`` for a missing title) reported a definitive ``0/N`` for covers
    ``gen`` just verified as compliant — the footer lied, contradicting the
    gallery module docstring ("the footer can never lie about a set it didn't
    actually check") and the README's "install → gallery … 跑通全链路 …
    size-compliant 10/10 · titles-in-safe-zone 10/10" promise. Now the
    packless path writes a sidecar (null pack provenance, carrying the CLI
    ``platform``) so the gallery recovers the real verdicts and self-proves
    honestly end to end.
    """
    from typer.testing import CliRunner

    from coverlock.gallery import build_gallery

    titles = tmp_path / "t.txt"
    titles.write_text("\n".join(f"第{i}篇分享" for i in range(1, 6)), encoding="utf-8")
    out = tmp_path / "out"

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.app,
        ["gen", "--model", "mock", "--titles", str(titles), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output

    # The packless path now persists a sidecar the gallery can read back.
    side = sp.read_sidecar(out)
    assert side["platform"] == "xiaohongshu"
    assert side["size_name"] == "4:5"
    assert side["titles"] == [f"第{i}篇分享" for i in range(1, 6)]
    # No pack ⇒ null pack provenance (the gallery needs only platform/size/titles).
    assert side["pack_id"] is None
    assert side["locked_sha"] is None
    assert "compliance" in side
    assert len(side["compliance"]) == 5
    assert all(c["title_in_safe_zone"] is True for c in side["compliance"])

    # The gallery now self-proves honestly for the mock demo set (5/5, not 0/5).
    report = build_gallery(pack_path=None, covers_dir=out)
    assert report.total == 5
    assert report.size_compliant_count == 5
    assert report.safe_zone_count == 5
    assert report.all_compliant


def test_packless_gallery_reports_honest_footer_via_cli(tmp_path):
    """The full ``gen --model mock`` → ``gallery`` CLI chain self-proves 5/5.

    End-to-end regression (via the CLI, not just the library): the documented
    zero-key offline chain now ends with a ``size-compliant 5/5 ·
    titles-in-safe-zone 5/5`` footer and exit 0, instead of the previous
    ``0/5`` + ``warning: not every cover is fully compliant.`` + exit 1.
    """
    from typer.testing import CliRunner

    titles = tmp_path / "t.txt"
    titles.write_text("\n".join(f"第{i}篇分享" for i in range(1, 4)), encoding="utf-8")
    out = tmp_path / "out"

    runner = CliRunner()
    g = runner.invoke(
        cli_mod.app,
        ["gen", "--model", "mock", "--titles", str(titles), "--out", str(out)],
    )
    assert g.exit_code == 0, g.output
    gal = runner.invoke(cli_mod.app, ["gallery", "--out", str(out)])
    assert gal.exit_code == 0, gal.output
    assert "size-compliant 3/3" in gal.output
    assert "titles-in-safe-zone 3/3" in gal.output
