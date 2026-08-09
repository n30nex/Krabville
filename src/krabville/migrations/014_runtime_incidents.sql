PRAGMA foreign_keys = ON;

CREATE TABLE runtime_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    component TEXT NOT NULL,
    incident_key TEXT NOT NULL,
    error_class TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
    attempts INTEGER NOT NULL DEFAULT 1 CHECK(attempts > 0),
    first_at TEXT NOT NULL,
    last_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE(season_id,tick,component,incident_key)
);

CREATE INDEX idx_runtime_incidents_status
    ON runtime_incidents(season_id,status,last_at DESC);
