"""Phase 5 T-32 — `pit-market` CLI tests."""
from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pit_market.cli import app

runner = CliRunner()


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    """A temporary workspace with config/ copied from the project."""
    proj_config = Path(__file__).resolve().parents[2] / "config"
    if not proj_config.is_dir():
        pytest.skip(f"config dir not found: {proj_config}")
    ws = tmp_path / "ws"
    (ws / "config").mkdir(parents=True)
    for f in proj_config.glob("*.yaml"):
        shutil.copy2(f, ws / "config" / f.name)
    schemas_src = proj_config / "schemas"
    if schemas_src.is_dir():
        shutil.copytree(schemas_src, ws / "config" / "schemas")
    yield ws


def test_root_help_lists_nine_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    expected = {
        "init", "refresh", "pit", "analyze", "report",
        "export", "healthcheck", "backfill", "backtest",
    }
    for cmd in expected:
        assert cmd in result.stdout, f"missing command: {cmd}"


def test_pit_subcommand_help() -> None:
    result = runner.invoke(app, ["pit", "--help"])
    assert result.exit_code == 0
    assert "build" in result.stdout
    assert "replay" in result.stdout


def test_init_creates_workspace(tmp_path: Path) -> None:
    target = tmp_path / "new_ws"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0
    assert (target / "config").is_dir()
    assert (target / "data" / "raw").is_dir()
    assert (target / "data" / "gold" / "pit_panels").is_dir()
    assert (target / ".env").is_file()
    assert (target / ".gitignore").is_file()


def test_init_copies_config_from_source(tmp_path: Path) -> None:
    src = tmp_path / "src_cfg"
    src.mkdir()
    (src / "instruments.yaml").write_text("instruments: []\n", encoding="utf-8")
    target = tmp_path / "ws"
    result = runner.invoke(app, ["init", str(target), "--from", str(src)])
    assert result.exit_code == 0
    assert (target / "config" / "instruments.yaml").is_file()


def test_pit_build_writes_manifest(workspace: Path) -> None:
    result = runner.invoke(app, [
        "pit", "build",
        "--decision-time", "2024-01-31T18:05:00Z",
        "--universe", "SPY,QQQ",
        "--config", str(workspace / "config"),
        "--data", str(workspace / "data"),
    ])
    assert result.exit_code == 0, result.stdout
    panels = list((workspace / "data" / "gold" / "pit_panels").glob("*manifest.json"))
    assert len(panels) == 1
    manifest = json.loads(panels[0].read_text(encoding="utf-8"))
    assert manifest["universe"] == ["SPY", "QQQ"]
    assert manifest["decision_clock"] == "1805_ET"
    assert "registry_hash" in manifest


def test_pit_build_rejects_unknown_symbol(workspace: Path) -> None:
    result = runner.invoke(app, [
        "pit", "build",
        "--decision-time", "2024-01-31T18:05:00Z",
        "--universe", "SPY,BOGUS_XYZ",
        "--config", str(workspace / "config"),
        "--data", str(workspace / "data"),
    ])
    assert result.exit_code == 2
    assert "BOGUS_XYZ" in result.stdout or "BOGUS_XYZ" in (result.stderr or "")


def test_pit_replay_round_trip(workspace: Path) -> None:
    build = runner.invoke(app, [
        "pit", "build",
        "--decision-time", "2024-02-29T18:05:00Z",
        "--universe", "SPY",
        "--config", str(workspace / "config"),
        "--data", str(workspace / "data"),
    ])
    assert build.exit_code == 0
    manifest_path = next((workspace / "data" / "gold" / "pit_panels").glob("*manifest.json"))
    panel_id = json.loads(manifest_path.read_text(encoding="utf-8"))["panel_id"]
    replay = runner.invoke(app, [
        "pit", "replay",
        "--panel-id", panel_id,
        "--data", str(workspace / "data"),
    ])
    assert replay.exit_code == 0
    assert "replay" in replay.stdout


def test_healthcheck_runs_with_real_config(workspace: Path) -> None:
    result = runner.invoke(app, [
        "healthcheck",
        "--config", str(workspace / "config"),
        "--data", str(workspace / "data"),
    ])
    assert result.exit_code == 0
    for src in ("yfinance", "fred_alfred", "cftc_cot", "finra_regsho"):
        assert src in result.stdout


def test_backfill_plans_date_range(workspace: Path) -> None:
    result = runner.invoke(app, [
        "backfill",
        "--feature-group", "equity_close",
        "--start", "2024-01-02",
        "--end", "2024-01-31",
        "--config", str(workspace / "config"),
    ])
    assert result.exit_code == 0
    assert "equity_close" in result.stdout
    assert "days=30" in result.stdout


def test_backfill_rejects_inverted_range(workspace: Path) -> None:
    result = runner.invoke(app, [
        "backfill",
        "--feature-group", "equity_close",
        "--start", "2024-12-31",
        "--end", "2024-01-01",
        "--config", str(workspace / "config"),
    ])
    assert result.exit_code == 2


def test_export_writes_index(workspace: Path) -> None:
    runner.invoke(app, [
        "pit", "build",
        "--decision-time", "2024-03-15T18:05:00Z",
        "--universe", "GLD",
        "--config", str(workspace / "config"),
        "--data", str(workspace / "data"),
    ])
    panel_id = next(
        json.loads(p.read_text(encoding="utf-8"))["panel_id"]
        for p in (workspace / "data" / "gold" / "pit_panels").glob("*manifest.json")
    )
    out = workspace / "export.json"
    result = runner.invoke(app, [
        "export",
        "--panel-id", panel_id,
        "--format", "json",
        "--output", str(out),
        "--data", str(workspace / "data"),
    ])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["panel_id"] == panel_id


def test_export_rejects_bad_format(workspace: Path) -> None:
    result = runner.invoke(app, [
        "export", "--panel-id", "x", "--format", "xml",
        "--config", str(workspace / "config"),
        "--data", str(workspace / "data"),
    ])
    assert result.exit_code == 2


def test_report_build_writes_frozen(workspace: Path) -> None:
    runner.invoke(app, [
        "pit", "build",
        "--decision-time", "2024-04-01T18:05:00Z",
        "--universe", "SPY",
        "--config", str(workspace / "config"),
        "--data", str(workspace / "data"),
    ])
    panel_id = next(
        json.loads(p.read_text(encoding="utf-8"))["panel_id"]
        for p in (workspace / "data" / "gold" / "pit_panels").glob("*manifest.json")
    )
    result = runner.invoke(app, [
        "report", "build",
        "--panel-id", panel_id,
        "--title", "Test Report",
        "--data", str(workspace / "data"),
    ])
    assert result.exit_code == 0
    rpts = list((workspace / "data" / "gold" / "reports").glob("*.json"))
    assert len(rpts) == 1
    rpt = json.loads(rpts[0].read_text(encoding="utf-8"))
    assert rpt["frozen"] is True
    assert rpt["panel_id"] == panel_id


def test_refresh_dry_run(workspace: Path) -> None:
    result = runner.invoke(app, [
        "refresh",
        "--config", str(workspace / "config"),
        "--date", "2024-01-31",
        "--dry-run",
    ])
    assert result.exit_code == 0
    for src in ("yfinance", "fred_alfred", "cftc_cot", "finra_regsho"):
        assert src in result.stdout


def test_backtest_run(workspace: Path, tmp_path: Path) -> None:
    """backtest run on synthetic CSVs writes a manifest."""
    import numpy as np
    import pandas as pd
    dates = pd.bdate_range("2022-01-03", periods=600)
    pd.DataFrame(
        {"f1": np.random.default_rng(0).normal(0, 1, 600),
         "f2": np.random.default_rng(1).normal(0, 1, 600)},
        index=dates,
    ).to_csv(workspace / "features.csv")
    pd.DataFrame(
        {"fwd_return_1d": np.random.default_rng(2).normal(0, 1, 600)},
        index=dates,
    ).to_csv(workspace / "target.csv")
    out = tmp_path / "bt"
    result = runner.invoke(app, [
        "backtest", "run",
        "--features", str(workspace / "features.csv"),
        "--target", str(workspace / "target.csv"),
        "--feature-cols", "f1,f2",
        "--train", "200", "--test", "30", "--step", "30",
        "--output", str(out),
    ])
    assert result.exit_code == 0, result.stdout
    files = list(out.glob("wf-*_summary.json"))
    assert len(files) == 1
    import json
    s = json.loads(files[0].read_text(encoding="utf-8"))
    assert s["folds"] >= 1
    assert "ic_mean" in s
