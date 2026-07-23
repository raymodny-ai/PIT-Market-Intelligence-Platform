-- 001_init_schema.sql (T-37)
-- Initial schema: panels, data_registry, replay_snapshots, backtest_runs
-- All tables use CREATE TABLE IF NOT EXISTS for idempotent re-runs.

CREATE TABLE IF NOT EXISTS panels (
    panel_id    VARCHAR PRIMARY KEY,
    panel_type  VARCHAR NOT NULL DEFAULT 'manifest',   -- 'manifest' | 'real'
    asset_class VARCHAR,
    symbols     VARCHAR[],                              -- list of canonical_symbols
    source      VARCHAR,                                -- 'yahoo' | 'polygon' | 'auto'
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    panel_hash  VARCHAR NOT NULL,
    manifest_json JSON
);

CREATE TABLE IF NOT EXISTS data_registry (
    symbol          VARCHAR NOT NULL,
    source          VARCHAR NOT NULL DEFAULT 'yahoo',
    freq            VARCHAR NOT NULL DEFAULT '1d',      -- '1d' | '1h' | '1m'
    last_fetched_at TIMESTAMP,
    row_count       INTEGER DEFAULT 0,
    quality_flags_json JSON,
    PRIMARY KEY (symbol, source, freq)
);

CREATE TABLE IF NOT EXISTS replay_snapshots (
    snapshot_id   VARCHAR PRIMARY KEY,
    panel_id      VARCHAR NOT NULL,
    as_of_date    DATE NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    snapshot_hash VARCHAR NOT NULL,
    FOREIGN KEY (panel_id) REFERENCES panels(panel_id)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id      VARCHAR PRIMARY KEY,
    strategy    VARCHAR NOT NULL,
    panel_id    VARCHAR,
    params_json JSON,
    result_json JSON,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status      VARCHAR NOT NULL DEFAULT 'queued'       -- queued | running | completed | failed
);
