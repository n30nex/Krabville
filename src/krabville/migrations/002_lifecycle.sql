ALTER TABLE seasons ADD COLUMN completion_reason TEXT NOT NULL DEFAULT 'natural';

CREATE TABLE world_props (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    event_id INTEGER REFERENCES town_events(id) ON DELETE SET NULL,
    location TEXT NOT NULL,
    prop TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'present',
    created_tick INTEGER NOT NULL,
    removed_tick INTEGER
);

CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(season_id, tick)
);

CREATE UNIQUE INDEX idx_model_usage_job_attempt
    ON model_usage(job_id, attempt_number)
    WHERE job_id IS NOT NULL;
CREATE INDEX idx_snapshots_season_tick ON snapshots(season_id, tick DESC);
CREATE INDEX idx_props_season_status ON world_props(season_id, status);
