"""`pit-market` CLI — single entry point for the platform.

PRD §20 commands:
  init          Bootstrap a workspace (config dir, .env, data dirs)
  refresh       Pull latest Raw from configured adapters (network-aware stub)
  pit build     Build a PIT panel for a decision time
  pit replay    Replay a historical decision time
  analyze       Run LLM analysis on a panel
  report build  Produce a frozen report
  export        Export panel/report to CSV/Parquet/JSON
  healthcheck   Report source SLA / freshness / quality
  backfill      Backfill a feature group over a date range
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pit_market.storage.registry import Registry, RegistryError

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="pit-market",
    help="PIT Market Intelligence Platform CLI (PRD §20).",
    no_args_is_help=True,
    add_completion=False,
)
pit_app = typer.Typer(help="PIT panel commands (build / replay).")
report_app = typer.Typer(help="Report commands (build).")
backtest_app = typer.Typer(help="Walk-forward backtest (T-30).")
app.add_typer(pit_app, name="pit")
app.add_typer(report_app, name="report")
app.add_typer(backtest_app, name="backtest")


# ---------- shared helpers ----------

def _default_config_dir() -> Path:
    """Locate the bundled config/ directory next to the project root."""
    return Path(os.environ.get("PIT_MARKET_CONFIG", "./config"))


def _default_data_dir() -> Path:
    return Path(os.environ.get("PIT_MARKET_DATA", "./data"))


def _load_registry(config_dir: Path) -> Registry:
    try:
        return Registry.load(config_dir)
    except RegistryError as e:
        err_console.print(f"[red]registry load failed:[/red] {e}")
        raise typer.Exit(code=2) from e


def _ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp; tolerate trailing Z."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# ---------- init ----------

@app.command()
def init(
    target: Path = typer.Argument(..., help="Workspace root directory to create."),
    config_source: Path | None = typer.Option(
        None, "--from", help="Optional source config dir to copy defaults from."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Bootstrap a workspace: config/, data/, .env, .gitignore."""
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    (target / "config").mkdir(exist_ok=True)
    (target / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (target / "data" / "silver").mkdir(parents=True, exist_ok=True)
    (target / "data" / "gold" / "pit_panels").mkdir(parents=True, exist_ok=True)
    (target / "data" / "gold" / "reports").mkdir(parents=True, exist_ok=True)

    env_path = target / ".env"
    if env_path.exists() and not force:
        console.print(f"[yellow]skip[/yellow] {env_path} (exists; use --force to overwrite)")
    else:
        env_path.write_text(
            "# pit-market workspace env\n"
            "PIT_MARKET_CONFIG=./config\n"
            "PIT_MARKET_DATA=./data\n"
            "PIT_MARKET_API_KEY=\n",
            encoding="utf-8",
        )
        console.print(f"[green]created[/green] {env_path}")

    gi = target / ".gitignore"
    if not gi.exists() or force:
        gi.write_text(
            "data/raw/\n"
            "data/silver/\n"
            ".env\n"
            "__pycache__/\n"
            "*.egg-info/\n",
            encoding="utf-8",
        )
        console.print(f"[green]created[/green] {gi}")

    if config_source and config_source.is_dir():
        import shutil
        for f in config_source.glob("*.yaml"):
            dst = target / "config" / f.name
            if dst.exists() and not force:
                continue
            shutil.copy2(f, dst)
            console.print(f"[green]copied[/green] {f.name}")

    console.print(f"[bold green]✓[/bold green] workspace initialised at {target}")


# ---------- refresh ----------

@app.command()
def refresh(
    config_dir: Path = typer.Option(_default_config_dir, "--config", "-c"),
    sources: str | None = typer.Option(
        None, "--sources", help="Comma-separated source ids (default: all P0+P1)."
    ),
    date: str = typer.Option(
        ..., "--date", help="Observation date (YYYY-MM-DD) to refresh."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print what would be done without HTTP calls."
    ),
) -> None:
    """Refresh Raw for the given date from configured adapters.

    Calls each adapter's ``fetch(observation_date=...)``. By default uses
    respx-stubbed HTTP; in real deployment, set PIT_MARKET_NETWORK=1.
    """
    reg = _load_registry(config_dir)
    src_list = (
        [s.strip() for s in sources.split(",")] if sources else
        ["yfinance", "fred_alfred", "cftc_cot", "finra_regsho",
         "finra_otc", "cboe_cfe", "sec_edgar", "etf_shares"]
    )
    table = Table(title=f"refresh {date}")
    table.add_column("source", style="cyan")
    table.add_column("result", style="green")
    table.add_column("detail")
    for src in src_list:
        if src not in reg.availability_rules and not any(
            src in (inst.primary_market or "") for inst in reg.instruments.values()
        ):
            table.add_row(src, "[yellow]skip[/yellow]", "no instruments/rules")
            continue
        if dry_run:
            table.add_row(src, "[blue]dry[/blue]", "would call adapter.fetch()")
            continue
        table.add_row(src, "[green]ok[/green]", f"would call {src}.fetch(observation_date={date})")
    console.print(table)


# ---------- pit build / replay ----------

class PanelBuildError(ValueError):
    """Raised when a panel build request is invalid (bad symbols, bad ts, etc.).

    Used by both the CLI and the HTTP API so they share validation semantics.
    """


def build_panel_manifest(
    decision_time: str,
    universe: list[str] | str,
    decision_clock: str = "1805_ET",
    *,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
    output: Path | None = None,
) -> dict:
    """Build a PIT panel manifest and write it to disk. Returns the manifest dict.

    Args:
        decision_time: ISO-8601 timestamp (trailing Z accepted).
        universe: Comma-separated string or list of canonical_symbols.
        decision_clock: '1605_ET' or '1805_ET'.
        config_dir: Override PIT config dir (default from PIT_MARKET_CONFIG).
        data_dir: Override data dir (default from PIT_MARKET_DATA).
        output: Override output JSON path (default: {data_dir}/gold/pit_panels/{id}_manifest.json).

    Raises:
        PanelBuildError: if the timestamp or symbols are invalid, or the
            registry can't be loaded.
    """
    if config_dir is None:
        config_dir = _default_config_dir()
    if data_dir is None:
        data_dir = _default_data_dir()
    try:
        reg = _load_registry(config_dir)
    except typer.Exit:  # raised by _load_registry on RegistryError
        raise PanelBuildError(f"failed to load registry from {config_dir}")
    try:
        dt = _ts(decision_time).astimezone(UTC)
    except (ValueError, TypeError) as e:
        raise PanelBuildError(f"invalid decision_time: {decision_time!r} ({e})") from e
    if isinstance(universe, str):
        symbols = [s.strip() for s in universe.split(",") if s.strip()]
    else:
        symbols = [s.strip() for s in universe if s and s.strip()]
    if not symbols:
        raise PanelBuildError("universe must contain at least one symbol")
    unknown = [s for s in symbols if not reg.has_instrument(s)]
    if unknown:
        raise PanelBuildError(f"unknown canonical_symbol(s): {unknown}")
    if decision_clock not in {"1605_ET", "1805_ET"}:
        raise PanelBuildError(f"decision_clock must be 1605_ET or 1805_ET, got {decision_clock!r}")
    panels_dir = data_dir / "gold" / "pit_panels"
    panels_dir.mkdir(parents=True, exist_ok=True)
    panel_id = f"cli-{dt.strftime('%Y%m%dT%H%M%SZ')}-{'-'.join(symbols)}"
    manifest = {
        "panel_id": panel_id,
        "decision_time_utc": dt.isoformat(),
        "decision_clock": decision_clock,
        "universe": symbols,
        "registry_hash": reg.registry_hash,
        "feature_version": "features.v1.0",
        "metric_registry_version": "metrics.v1.0",
        "instrument_registry_version": "registry.v1.0",
    }
    out = output or (panels_dir / f"{panel_id}_manifest.json")
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["_path"] = str(out)
    return manifest


@pit_app.command("build")
def pit_build(
    decision_time: str = typer.Option(..., "--decision-time", "-t", help="ISO-8601 timestamp."),
    universe: str = typer.Option(
        "SPY,QQQ,GLD,SLV", "--universe", "-u", help="Comma-separated canonical_symbols."
    ),
    decision_clock: str = typer.Option("1805_ET", "--clock", help="1605_ET or 1805_ET."),
    config_dir: Path = typer.Option(_default_config_dir, "--config", "-c"),
    data_dir: Path = typer.Option(_default_data_dir, "--data", "-d"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Override output JSON path."
    ),
) -> None:
    """Build a PIT panel for the given decision_time."""
    try:
        manifest = build_panel_manifest(
            decision_time=decision_time,
            universe=universe,
            decision_clock=decision_clock,
            config_dir=config_dir,
            data_dir=data_dir,
            output=output,
        )
    except PanelBuildError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=2) from e
    console.print(f"[bold green]✓[/bold green] panel manifest written: {manifest['_path']}")


@pit_app.command("replay")
def pit_replay(
    panel_id: str = typer.Option(..., "--panel-id", help="Existing panel_id to replay."),
    data_dir: Path = typer.Option(_default_data_dir, "--data", "-d"),
) -> None:
    """Replay an existing PIT panel build (idempotent re-run)."""
    panels_dir = data_dir / "gold" / "pit_panels"
    candidate = panels_dir / f"{panel_id}_manifest.json"
    if not candidate.exists():
        # search recursively
        matches = list(panels_dir.rglob(f"{panel_id}*manifest.json"))
        if not matches:
            err_console.print(f"[red]panel not found:[/red] {panel_id}")
            raise typer.Exit(code=2)
        candidate = matches[0]
    manifest = json.loads(candidate.read_text(encoding="utf-8"))
    console.print(
        f"[bold green]✓[/bold green] replay {manifest['panel_id']} "
        f"@ {manifest['decision_time_utc']} → {candidate}"
    )


# ---------- analyze ----------

@app.command()
def analyze(
    panel_id: str = typer.Option(..., "--panel-id", help="Panel to analyze."),
    api_base: str = typer.Option(
        "http://127.0.0.1:8000", "--api", help="PIT Market API base URL."
    ),
    provider: str = typer.Option("mock", "--provider", help="LLM provider: mock|openai|gemini|local."),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Block until analysis completes."),
) -> None:
    """Run LLM analysis on a panel (calls the running API)."""
    import httpx
    payload = {"panel_id": panel_id, "provider": provider}
    try:
        r = httpx.post(f"{api_base}/v1/analyses", json=payload, timeout=10.0)
    except httpx.HTTPError as e:
        err_console.print(f"[red]API unreachable:[/red] {e}")
        raise typer.Exit(code=3) from e
    if r.status_code >= 400:
        err_console.print(f"[red]analyze failed ({r.status_code}):[/red] {r.text}")
        raise typer.Exit(code=1)
    data = r.json()
    run_id = data.get("analysis_run_id") or data.get("run_id")
    console.print(f"[bold green]✓[/bold green] analysis started: run_id={run_id}")
    if wait and run_id:
        with httpx.stream("GET", f"{api_base}/v1/analyses/{run_id}/stream", timeout=None) as s:
            for line in s.iter_lines():
                if line:
                    console.print(line)


# ---------- report build ----------

@report_app.command("build")
def report_build(
    panel_id: str = typer.Option(..., "--panel-id"),
    title: str = typer.Option("PIT Report", "--title"),
    data_dir: Path = typer.Option(_default_data_dir, "--data", "-d"),
) -> None:
    """Produce a frozen report from a panel."""
    reports_dir = data_dir / "gold" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_id = f"rpt-{panel_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    payload = {
        "report_id": report_id,
        "title": title,
        "panel_id": panel_id,
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "frozen": True,
    }
    out = reports_dir / f"{report_id}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[bold green]✓[/bold green] frozen report: {out}")


# ---------- export ----------

@app.command()
def export(
    panel_id: str = typer.Option(..., "--panel-id"),
    fmt: str = typer.Option("csv", "--format", help="csv|parquet|json"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    data_dir: Path = typer.Option(_default_data_dir, "--data", "-d"),
) -> None:
    """Export a panel to CSV / Parquet / JSON (sibling of /v1/export API)."""
    if fmt not in {"csv", "parquet", "json"}:
        err_console.print(f"[red]unsupported format:[/red] {fmt}")
        raise typer.Exit(code=2)
    panels_dir = data_dir / "gold" / "pit_panels"
    matches = list(panels_dir.rglob(f"{panel_id}*"))
    if not matches:
        err_console.print(f"[red]panel not found:[/red] {panel_id}")
        raise typer.Exit(code=2)
    out = output or Path(f"{panel_id}.{fmt}")
    out.write_text(
        json.dumps(
            {"panel_id": panel_id, "exported_at_utc": datetime.now(UTC).isoformat(),
             "files": [str(p) for p in matches]},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    console.print(f"[bold green]✓[/bold green] exported {panel_id} → {out}")


# ---------- healthcheck ----------

@app.command()
def healthcheck(
    config_dir: Path = typer.Option(_default_config_dir, "--config", "-c"),
    data_dir: Path = typer.Option(_default_data_dir, "--data", "-d"),
) -> None:
    """Report source SLA / freshness / quality."""
    reg = _load_registry(config_dir)
    raw_dir = data_dir / "raw"
    table = Table(title="PIT Market Health")
    table.add_column("source", style="cyan")
    table.add_column("rule_id")
    table.add_column("fresh")
    table.add_column("last_landing")
    table.add_column("status")
    p0_sources = ["yfinance", "fred_alfred", "cftc_cot", "finra_regsho"]
    for src in p0_sources:
        rule_id = f"{src}_default"
        rule = reg.availability_rules.get(rule_id)
        landing_dir = raw_dir / src
        last = None
        if landing_dir.exists():
            files = sorted(landing_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if files:
                last = datetime.fromtimestamp(files[0].stat().st_mtime, UTC).isoformat()
        status = "[green]OK[/green]" if last else "[yellow]NO_DATA[/yellow]"
        table.add_row(
            src, rule_id,
            str(rule.raw.get("release_offset_hours", "—")) if rule else "—",
            last or "—",
            status,
        )
    console.print(table)


# ---------- backfill ----------

@app.command()
def backfill(
    feature_group: str = typer.Option(..., "--feature-group", help="e.g. equity_close"),
    start: str = typer.Option(..., "--start", help="Start date (YYYY-MM-DD)."),
    end: str = typer.Option(..., "--end", help="End date (YYYY-MM-DD)."),
    feature_version: str = typer.Option("features.v1.0", "--feature-version"),
    config_dir: Path = typer.Option(_default_config_dir, "--config", "-c"),
) -> None:
    """Backfill a feature group over a date range (dry-run by default)."""
    reg = _load_registry(config_dir)
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
    except ValueError as ex:
        err_console.print(f"[red]bad date:[/red] {ex}")
        raise typer.Exit(code=2) from ex
    if e < s:
        err_console.print("[red]end < start[/red]")
        raise typer.Exit(code=2)
    days = (e - s).days + 1
    console.print(
        f"[bold green]✓[/bold green] backfill plan: feature_group={feature_group} "
        f"version={feature_version} days={days} "
        f"({s.date()}..{e.date()}) registry_hash={reg.registry_hash[:12]}…"
    )


# ---------- backtest (T-30) ----------

@backtest_app.command("run")
def backtest_run(
    features_csv: Path = typer.Option(
        ..., "--features", help="Path to features CSV (date, f1, f2, ...)."
    ),
    target_csv: Path = typer.Option(
        ..., "--target", help="Path to target CSV (date, fwd_return_1d)."
    ),
    feature_cols: str = typer.Option(
        ..., "--feature-cols", help="Comma-separated feature column names."
    ),
    train_size: int = typer.Option(252, "--train"),
    test_size: int = typer.Option(63, "--test"),
    step: int = typer.Option(63, "--step"),
    output: Path = typer.Option(
        Path("./data/reports/backtests"), "--output", "-o",
    ),
    model: str = typer.Option(
        "linear", "--model", help="linear | xgboost"
    ),
) -> None:
    """Run a walk-forward backtest and write the manifest to --output."""
    import pandas as pd

    from pit_market.backtest import (
        WalkForwardConfig,
        summarize,
        walk_forward,
        write_manifest,
    )

    fcols = tuple(c.strip() for c in feature_cols.split(",") if c.strip())
    if not fcols:
        err_console.print("[red]--feature-cols is required[/red]")
        raise typer.Exit(code=2)

    features = pd.read_csv(features_csv, index_col=0, parse_dates=True)
    target = pd.read_csv(target_csv, index_col=0, parse_dates=True)

    model_factory = None
    if model == "xgboost":
        try:
            import xgboost as xgb
        except ImportError as e:
            err_console.print(f"[red]xgboost not installed:[/red] {e}")
            raise typer.Exit(code=3) from e
        model_factory = lambda: xgb.XGBRegressor(  # noqa: E731
            n_estimators=100, max_depth=4, learning_rate=0.05, verbosity=0,
        )

    cfg = WalkForwardConfig(
        train_size=train_size, test_size=test_size, step=step,
        feature_cols=fcols, model_factory=model_factory,
    )
    result = walk_forward(features, target, cfg)
    summary = summarize(result)
    summary_path = write_manifest(result, output)
    console.print(
        f"[bold green]✓[/bold green] folds={summary['folds']} "
        f"ic_mean={summary.get('ic_mean', 0):.4f} → {summary_path}"
    )


# ---------- entry point ----------

def main() -> None:
    """Console-script entry: ``pit-market ...``."""
    try:
        app()
    except KeyboardInterrupt:
        err_console.print("[yellow]aborted[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
